"""
OBSERVABILITY LAYER (Stage 8)

Assembles the complete execution trace for a single request.
Records stage-level metadata, latency, field mappings,
memory hits, and errors. Fully passive — never modifies payload.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.storage.models import (
    ObservabilityTrace,
    IngestionTrace,
    NormalizationTrace,
    RoutingTrace,
    CandidateScores,
    FieldMappingTrace,
    HealingTrace,
    MemoryUpdateTrace,
    MemoryHit,
    ErrorTrace,
    LatencyBreakdown,
    RoutingMode,
    MappingMode,
    MatchingMethod,
    ProcessingMode,
)


def _determine_processing_mode(
    mapping_trace_list: List[Dict[str, Any]],
    new_memory_entries: List[str],
    updated_memory_entries: List[str],
) -> ProcessingMode:
    """
    Determine if request was resolved via memory, heuristics, or mixed.
    NEW     → no memory used at all
    LEARNED → all successful mappings came from memory
    MIXED   → combination
    """
    memory_based = sum(
        1 for t in mapping_trace_list
        if t.get("matching_method") == MatchingMethod.MEMORY.value
    )
    total_mapped = sum(
        1 for t in mapping_trace_list
        if t.get("mapping_mode") != MappingMode.UNMAPPED.value
    )
    if total_mapped == 0 or memory_based == 0:
        return ProcessingMode.NEW
    if memory_based == total_mapped:
        return ProcessingMode.LEARNED
    return ProcessingMode.MIXED


def build_trace(
    *,
    request_id: str,
    ingestion_timestamp: str,
    # Stage data
    raw_payload_size: int,
    json_valid: bool,
    keys_normalized: List[str],
    flatten_operations: int,
    removed_fields: List[str],
    candidate_scores: Dict[str, float],
    selected_schema: str,
    routing_confidence: float,
    routing_mode: RoutingMode,
    routing_reason: str,
    mapping_trace_list: List[Dict[str, Any]],
    unmapped_fields: Dict[str, Any],
    coercions: List[str],
    schema_compliance: bool,
    validation_errors: List[str],
    new_memory_entries: List[str],
    updated_memory_entries: List[str],
    confidence_changes: List[str],
    frequency_updates: List[str],
    memory_hits: List[Dict[str, Any]],
    errors: List[Dict[str, Any]],
    # Latencies (ms)
    latency: Dict[str, float],
    debug: bool = False,
) -> ObservabilityTrace:
    """Assemble and return the full ObservabilityTrace for this request."""

    processing_mode = _determine_processing_mode(
        mapping_trace_list,
        new_memory_entries,
        updated_memory_entries,
    )

    # Build per-stage trace
    stages: Dict[str, Any] = {
        "ingestion": IngestionTrace(
            raw_payload_size=raw_payload_size,
            json_valid=json_valid,
            request_id=request_id,
        ).model_dump(),
        "normalization": NormalizationTrace(
            keys_normalized=keys_normalized,
            flatten_operations=flatten_operations,
            removed_fields=removed_fields,
        ).model_dump(),
        "routing": RoutingTrace(
            candidate_scores=CandidateScores(**{
                k: v for k, v in candidate_scores.items()
                if k in CandidateScores.model_fields
            }),
            selected_schema=selected_schema,
            decision_threshold=0.80 if routing_mode == RoutingMode.HARD else 0.60,
            routing_reason=routing_reason,
            routing_mode=routing_mode,
        ).model_dump(),
        "healing": HealingTrace(
            type_coercions=coercions,
            missing_fields_filled=[],
            unmapped_fields_captured=unmapped_fields,
            final_schema_compliance=schema_compliance,
        ).model_dump(),
        "memory_update": MemoryUpdateTrace(
            new_entries=new_memory_entries,
            updated_entries=updated_memory_entries,
            confidence_changes=confidence_changes,
            frequency_updates=frequency_updates,
        ).model_dump(),
    }

    # Build field mapping traces
    field_mappings: List[FieldMappingTrace] = []
    for t in mapping_trace_list:
        if not debug and t.get("mapping_mode") == MappingMode.UNMAPPED.value:
            continue  # Production mode: suppress unmapped noise
        ft = FieldMappingTrace(
            source_field=t["source_field"],
            canonical_field=t.get("canonical_field") or "_unmapped_",
            matching_method=MatchingMethod(t["matching_method"]),
            confidence=t["confidence"],
            mapping_mode=MappingMode(t["mapping_mode"]),
            schema_context=t["schema_context"],
            alternatives_considered=t.get("alternatives_considered", []) if debug else [],
        )
        field_mappings.append(ft)

    # Memory hits
    mem_hit_objects: List[MemoryHit] = [
        MemoryHit(**h) for h in memory_hits
    ]

    # Errors
    error_objects: List[ErrorTrace] = [
        ErrorTrace(**e) for e in errors
    ]
    if validation_errors:
        for ve in validation_errors:
            error_objects.append(ErrorTrace(
                error_type="validation_failure",
                stage="canonicalization",
                message=ve,
                recoverable=True,
                fallback_action="partial_output",
            ))

    return ObservabilityTrace(
        request_id=request_id,
        ingestion_timestamp=ingestion_timestamp,
        selected_schema=selected_schema,
        routing_confidence=routing_confidence,
        routing_mode=routing_mode,
        processing_mode=processing_mode,
        latency=LatencyBreakdown(**latency),
        stages=stages,
        field_mappings=field_mappings,
        unknown_fields=list(unmapped_fields.keys()),
        memory_hits=mem_hit_objects,
        errors=error_objects,
    )
