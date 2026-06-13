"""
HEALING ENGINE (Stage 5)

Applies resolved field mappings to construct canonical output:
  - Injects mapped values into canonical schema structure
  - Performs deterministic type coercion:
      * numeric strings → int / float
      * boolean normalization (true/false/1/0/yes/no)
      * timestamp normalization to ISO-8601 UTC
  - Sets missing fields to null
  - Preserves unmapped fields in unmapped_fields container
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as dateutil_parser


# ---------------------------------------------------------------------------
# Type coercion helpers
# ---------------------------------------------------------------------------

BOOL_TRUE  = {"true", "1", "yes", "on", "y"}
BOOL_FALSE = {"false", "0", "no", "off", "n"}

# Fields expected to hold numeric values per schema
NUMERIC_FIELDS = {"amount", "total_amount", "quantity", "price", "subtotal"}
BOOL_FIELDS    = {"active", "verified", "enabled", "is_active"}


def _try_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _try_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_boolean(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in BOOL_TRUE:
            return True
        if v in BOOL_FALSE:
            return False
    return None


def _normalize_timestamp(value: Any) -> Optional[str]:
    """Attempt to parse and normalize to ISO-8601 UTC string."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Treat as UNIX timestamp
        try:
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
            return dt.isoformat()
        except (OSError, OverflowError):
            return None
    if isinstance(value, str):
        try:
            dt = dateutil_parser.parse(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt.isoformat()
        except (ValueError, OverflowError):
            return None
    return None


def _coerce_value(
    canonical_field: str,
    value: Any,
) -> Tuple[Any, Optional[str]]:
    """
    Coerce a value based on the canonical field semantics.
    Returns (coerced_value, coercion_note | None).
    If coercion fails → returns (None, note) so caller can null the field.
    """
    if canonical_field == "timestamp":
        normalized = _normalize_timestamp(value)
        if normalized is None:
            return None, f"timestamp_coercion_failed: raw={value!r}"
        if str(value) != normalized:
            return normalized, f"timestamp: {value!r} → {normalized}"
        return normalized, None

    if canonical_field in NUMERIC_FIELDS:
        if isinstance(value, (int, float)):
            return value, None
        as_float = _try_float(value)
        if as_float is not None:
            coerced = int(as_float) if as_float == int(as_float) else as_float
            return coerced, f"numeric: {value!r} → {coerced}"
        # Coercion failure — null the field
        return None, f"numeric_coercion_failed: raw={value!r}"

    if canonical_field in BOOL_FIELDS:
        coerced = _normalize_boolean(value)
        if coerced is None:
            return None, f"bool_coercion_failed: raw={value!r}"
        if coerced != value:
            return coerced, f"bool: {value!r} → {coerced}"
        return coerced, None

    # Generic: try int/float for numeric-looking strings, else keep as-is
    if isinstance(value, str):
        as_int = _try_int(value)
        if as_int is not None and str(as_int) == value.strip():
            return as_int, f"numeric_string: {value!r} → {as_int}"
        as_float = _try_float(value)
        if as_float is not None:
            return as_float, f"numeric_string: {value!r} → {as_float}"

    return value, None


# ---------------------------------------------------------------------------
# Schema canonical template
# ---------------------------------------------------------------------------

SCHEMA_TEMPLATES: Dict[str, List[str]] = {
    "user_schema":    ["entity_id", "user_id", "email", "timestamp", "source_system"],
    "payment_schema": ["payment_id", "user_id", "amount", "currency", "status", "timestamp", "source_system"],
    "order_schema":   ["order_id", "user_id", "items", "total_amount", "status", "timestamp", "source_system"],
    "event_schema":   ["event_id", "user_id", "event_type", "properties", "timestamp", "source_system"],
    "unknown_schema": [],
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def heal(
    normalized_payload: Dict[str, Any],
    field_mapping_map: Dict[str, Any],
    unmapped_keys: List[str],
    schema_name: str,
    source_system: str,
) -> Tuple[Dict[str, Any], List[str], Dict[str, Any]]:
    """
    Apply mappings and produce canonical output.

    Returns:
        canonical_output  — dict matching the target schema
        coercions         — list of coercion event strings (for trace)
        unmapped_fields   — preserved unmapped key→value pairs
    """
    template_fields = SCHEMA_TEMPLATES.get(schema_name, [])
    canonical_output: Dict[str, Any] = {f: None for f in template_fields}
    coercions: List[str] = []
    unmapped_fields: Dict[str, Any] = {}

    # Apply mapped fields
    for source_field, mapping in field_mapping_map.items():
        canonical_field: str = mapping["canonical_field"]
        raw_value = normalized_payload.get(source_field)

        coerced_value, coercion_note = _coerce_value(canonical_field, raw_value)
        if coercion_note:
            coercions.append(f"{canonical_field}: {coercion_note}")

        if coerced_value is None and raw_value is not None:
            # Coercion failed — store raw in unmapped_fields
            unmapped_fields[source_field] = raw_value
        else:
            canonical_output[canonical_field] = coerced_value

    # Always set source_system
    if "source_system" in canonical_output:
        canonical_output["source_system"] = source_system

    # Collect unmapped fields
    for key in unmapped_keys:
        unmapped_fields[key] = normalized_payload.get(key)

    canonical_output["unmapped_fields"] = unmapped_fields

    return canonical_output, coercions, unmapped_fields
