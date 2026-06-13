"""
INGESTION GATEWAY — POST /ingest

Orchestrates the 8-stage deterministic transformation pipeline:
  1. Accept raw JSON
  2. Normalize keys + structure
  3. Detect schema (route)
  4. Match fields to schema
  5. Heal and transform
  6. Validate canonical compliance
  7. Update memory
  8. Generate observability trace
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.storage.db import get_db
from app.storage.models import IngestRequest, IngestResponse, SchemaName, RoutingMode
from app.core.normalize import normalize
from app.core.source_detector import detect_schema
from app.core.matcher import match_fields
from app.core.healer import heal
from app.core.canonicalizer import validate_and_enforce
from app.services.learning_service import (
    fetch_memory_for_schema,
    fetch_memory_for_all_schemas,
    update_memory,
)
from app.services.observability_service import build_trace

router = APIRouter()


@router.post(
    "/ingest",
    response_model=IngestResponse,
    summary="Ingest a raw JSON payload and transform it into a canonical schema",
    response_description="Canonical output + full observability trace",
)
async def ingest(request: IngestRequest) -> IngestResponse:
    pipeline_start = time.perf_counter()
    request_id = str(uuid.uuid4())
    ingestion_timestamp = datetime.now(tz=timezone.utc).isoformat()

    raw_payload = request.payload
    debug = request.debug

    errors: list = []
    memory_hits: list = []

    # ── Stage 1: Ingestion ───────────────────────────────────────────────────
    t0 = time.perf_counter()
    raw_payload_size = len(json.dumps(raw_payload))
    ingestion_ms = (time.perf_counter() - t0) * 1000

    # ── Stage 2: Normalization ───────────────────────────────────────────────
    t0 = time.perf_counter()
    normalized_payload, keys_normalized, flatten_ops, removed_fields = normalize(raw_payload)
    normalization_ms = (time.perf_counter() - t0) * 1000

    # ── Fetch memory (needed for routing + matching) ─────────────────────────
    with get_db() as conn:
        memory_partitions = fetch_memory_for_all_schemas(conn)

    # ── Stage 3: Schema Routing ──────────────────────────────────────────────
    t0 = time.perf_counter()
    selected_schema, routing_confidence, routing_mode, candidate_scores, routing_reason = detect_schema(
        normalized_payload, memory_partitions
    )
    routing_ms = (time.perf_counter() - t0) * 1000

    source_system = selected_schema.value.replace("_schema", "")

    # ── Stage 4: Field Matching ──────────────────────────────────────────────
    t0 = time.perf_counter()
    mapping_trace_list: list = []
    field_mapping_map: dict = {}
    unmapped_keys: list = []

    if selected_schema == SchemaName.UNKNOWN:
        # Skip field mapping for unknown schema
        unmapped_keys = list(normalized_payload.keys())
        mapping_trace_list = []
    else:
        with get_db() as conn:
            memory_entries = fetch_memory_for_schema(conn, selected_schema.value)

        # Track memory hits
        for entry in memory_entries:
            if entry["source_field"] in normalized_payload:
                memory_hits.append({
                    "source_field": entry["source_field"],
                    "schema_name": entry["schema_name"],
                    "matched_canonical_field": entry["canonical_field"],
                    "confidence": entry["confidence"],
                    "frequency": entry["frequency"],
                })

        field_mapping_map, mapping_trace_list, unmapped_keys = match_fields(
            normalized_payload,
            selected_schema,
            memory_entries,
        )
    mapping_ms = (time.perf_counter() - t0) * 1000

    # ── Stage 5: Healing ─────────────────────────────────────────────────────
    t0 = time.perf_counter()
    canonical_output, coercions, unmapped_fields_dict = heal(
        normalized_payload,
        field_mapping_map,
        unmapped_keys,
        selected_schema.value,
        source_system,
    )
    healing_ms = (time.perf_counter() - t0) * 1000

    # ── Stage 6: Canonical Validation ────────────────────────────────────────
    validated_output, is_valid, validation_errors = validate_and_enforce(
        canonical_output, selected_schema.value
    )
    if not is_valid:
        errors.append({
            "error_type": "validation_failure",
            "stage": "canonicalization",
            "message": "; ".join(validation_errors),
            "recoverable": True,
            "fallback_action": "partial_output_returned",
        })

    # ── Stage 7: Memory Update ───────────────────────────────────────────────
    t0 = time.perf_counter()
    new_entries: list = []
    updated_entries: list = []
    confidence_changes: list = []
    frequency_updates: list = []

    if selected_schema != SchemaName.UNKNOWN and field_mapping_map:
        with get_db() as conn:
            new_entries, updated_entries, confidence_changes, frequency_updates = update_memory(
                conn, selected_schema.value, field_mapping_map
            )
    memory_ms = (time.perf_counter() - t0) * 1000

    # ── Stage 8: Observability ───────────────────────────────────────────────
    total_ms = (time.perf_counter() - pipeline_start) * 1000

    trace = build_trace(
        request_id=request_id,
        ingestion_timestamp=ingestion_timestamp,
        raw_payload_size=raw_payload_size,
        json_valid=True,
        keys_normalized=keys_normalized,
        flatten_operations=flatten_ops,
        removed_fields=removed_fields,
        candidate_scores=candidate_scores,
        selected_schema=selected_schema.value,
        routing_confidence=routing_confidence,
        routing_mode=routing_mode,
        routing_reason=routing_reason,
        mapping_trace_list=mapping_trace_list,
        unmapped_fields=unmapped_fields_dict,
        coercions=coercions,
        schema_compliance=is_valid,
        validation_errors=validation_errors,
        new_memory_entries=new_entries,
        updated_memory_entries=updated_entries,
        confidence_changes=confidence_changes,
        frequency_updates=frequency_updates,
        memory_hits=memory_hits,
        errors=errors,
        latency={
            "ingestion_ms": round(ingestion_ms, 3),
            "normalization_ms": round(normalization_ms, 3),
            "routing_ms": round(routing_ms, 3),
            "mapping_ms": round(mapping_ms, 3),
            "healing_ms": round(healing_ms, 3),
            "memory_ms": round(memory_ms, 3),
            "total_ms": round(total_ms, 3),
        },
        debug=debug,
    )

    return IngestResponse(
        request_id=request_id,
        selected_schema=selected_schema.value,
        canonical_output=validated_output,
        trace=trace,
    )
