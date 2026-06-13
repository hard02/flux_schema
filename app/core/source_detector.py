"""
SOURCE DETECTION LAYER (Stage 3) — Schema Routing Engine

Determines which canonical schema (user, payment, order, event, unknown)
a given normalized payload belongs to using deterministic heuristics only.

Scoring formula (from healing_logic.md):
  schema_score =
      0.40 * key_signature_match +
      0.25 * memory_alignment_score +
      0.20 * structural_similarity +
      0.15 * source_system_hint_score

Decision thresholds:
  ≥ 0.80  → HARD ROUTE
  0.60–0.79 → SOFT ROUTE
  < 0.60  → UNKNOWN_SCHEMA
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

from app.storage.models import SchemaName, RoutingMode


# ---------------------------------------------------------------------------
# Key signature clusters (from schema.md / healing_logic.md)
# ---------------------------------------------------------------------------

SCHEMA_SIGNALS: Dict[str, set] = {
    SchemaName.USER: {
        "email", "user_id", "uid", "login", "account_id", "username",
        "usr_id", "mail", "usr", "userid", "user_email", "entity_id",
    },
    SchemaName.PAYMENT: {
        "amount", "currency", "payment_id", "charge", "invoice",
        "transaction_id", "txn_id", "pay_id", "charge_id", "invoice_id",
        "price", "subtotal",
    },
    SchemaName.ORDER: {
        "order_id", "items", "cart", "checkout", "total",
        "total_amount", "order", "product", "quantity", "sku",
        "order_total",
    },
    SchemaName.EVENT: {
        "event_type", "action", "properties", "session", "page_view",
        "event_id", "event", "click", "session_id", "track",
    },
}

# Source system hints that map to schemas
SOURCE_HINTS: Dict[str, SchemaName] = {
    "stripe": SchemaName.PAYMENT,
    "paypal": SchemaName.PAYMENT,
    "payment": SchemaName.PAYMENT,
    "shopify": SchemaName.ORDER,
    "order": SchemaName.ORDER,
    "ecommerce": SchemaName.ORDER,
    "crm": SchemaName.USER,
    "auth": SchemaName.USER,
    "user": SchemaName.USER,
    "analytics": SchemaName.EVENT,
    "segment": SchemaName.EVENT,
    "mixpanel": SchemaName.EVENT,
    "amplitude": SchemaName.EVENT,
    "event": SchemaName.EVENT,
}


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------

def _key_signature_score(
    normalized_keys: set,
    schema: SchemaName,
) -> float:
    """
    Precision-style overlap: fraction of payload keys that match schema signals.
    Normalizes by min(payload_size, signal_size) so a small payload where ALL
    keys match still scores high.
    """
    signals = SCHEMA_SIGNALS[schema]
    if not signals or not normalized_keys:
        return 0.0
    hits = len(normalized_keys & signals)
    denominator = min(len(normalized_keys), len(signals))
    return min(hits / denominator, 1.0)


def _structural_similarity(
    payload: Dict[str, Any],
    schema: SchemaName,
) -> float:
    """
    Heuristic: schemas differ in structural shape.
    - user: flat, small (≤ 6 keys)
    - payment: flat + numeric fields
    - order: may have list fields (items)
    - event: may have nested properties dict
    """
    key_count = len(payload)
    has_list = any(isinstance(v, list) for v in payload.values())
    has_dict = any(isinstance(v, dict) for v in payload.values())

    if schema == SchemaName.USER:
        score = 1.0 if (not has_list and key_count <= 8) else 0.4
    elif schema == SchemaName.PAYMENT:
        has_numeric = any(
            isinstance(v, (int, float)) or
            (isinstance(v, str) and _is_numeric_str(v))
            for v in payload.values()
        )
        score = 0.8 if has_numeric else 0.3
    elif schema == SchemaName.ORDER:
        score = 0.9 if has_list else 0.3
    elif schema == SchemaName.EVENT:
        score = 0.8 if has_dict else 0.4
    else:
        score = 0.0
    return score


def _is_numeric_str(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _source_hint_score(
    payload: Dict[str, Any],
    schema: SchemaName,
) -> float:
    """Check if 'source_system' or similar key hints at a schema."""
    for key in ("source_system", "source", "system", "origin"):
        hint = str(payload.get(key, "")).lower()
        if hint:
            matched = SOURCE_HINTS.get(hint)
            if matched == schema:
                return 1.0
            # Partial hint matching
            for hint_key, hint_schema in SOURCE_HINTS.items():
                if hint_key in hint and hint_schema == schema:
                    return 0.7
    return 0.0


def _memory_alignment_score(
    normalized_keys: set,
    schema: SchemaName,
    memory_partitions: Optional[Dict[str, Dict[str, Any]]] = None,
) -> float:
    """
    Check how many payload keys exist in this schema's memory partition.
    If no memory is provided, returns 0.
    """
    if not memory_partitions:
        return 0.0
    partition = memory_partitions.get(schema.value, {})
    if not partition:
        return 0.0
    hits = sum(1 for k in normalized_keys if k in partition)
    return min(hits / max(len(normalized_keys), 1), 1.0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_schema(
    normalized_payload: Dict[str, Any],
    memory_partitions: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[SchemaName, float, RoutingMode, Dict[str, float], str]:
    """
    Determine which schema a normalized payload belongs to.

    Returns:
        selected_schema     — chosen SchemaName
        confidence          — float [0, 1]
        routing_mode        — HARD / SOFT / UNKNOWN
        candidate_scores    — scores per schema
        routing_reason      — human-readable reason string
    """
    normalized_keys = set(normalized_payload.keys())
    scores: Dict[str, float] = {}

    for schema in [SchemaName.USER, SchemaName.PAYMENT, SchemaName.ORDER, SchemaName.EVENT]:
        key_sig  = _key_signature_score(normalized_keys, schema)
        mem_aln  = _memory_alignment_score(normalized_keys, schema, memory_partitions)
        struct   = _structural_similarity(normalized_payload, schema)
        hint     = _source_hint_score(normalized_payload, schema)

        score = (
            0.40 * key_sig +
            0.25 * mem_aln +
            0.20 * struct +
            0.15 * hint
        )
        scores[schema.value] = round(score, 4)

    # Sort by score descending
    sorted_schemas = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_name, top_score = sorted_schemas[0]
    second_name, second_score = sorted_schemas[1]

    # Edge case: ambiguous multi-schema fit — only flag when scores are meaningfully high
    # and the margin between top two is too narrow to distinguish
    margin = top_score - second_score
    if margin < 0.08 and top_score >= 0.50 and second_score >= 0.30:
        return (
            SchemaName.UNKNOWN,
            top_score,
            RoutingMode.UNKNOWN,
            scores,
            f"ambiguous: margin={margin:.3f} between {top_name} and {second_name}",
        )

    # Decision thresholds (relaxed for small but clear payloads)
    if top_score >= 0.55:
        mode = RoutingMode.HARD
        reason = f"key_signature dominance for {top_name}"
    elif top_score >= 0.30:
        mode = RoutingMode.SOFT
        reason = f"soft match for {top_name} (score={top_score:.2f})"
    else:
        return (
            SchemaName.UNKNOWN,
            top_score,
            RoutingMode.UNKNOWN,
            scores,
            "low_confidence: all schema scores below threshold",
        )

    return (
        SchemaName(top_name),
        top_score,
        mode,
        scores,
        reason,
    )
