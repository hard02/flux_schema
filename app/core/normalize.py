"""
INPUT NORMALIZATION LAYER (Stage 2)

Converts arbitrary JSON into a deterministic intermediate representation:
  - All keys → lowercase snake_case
  - Flatten nested objects to depth=1
  - Remove null / empty string values
  - Trim whitespace from string values
  - Preserve raw payload
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# Key normalization helpers
# ---------------------------------------------------------------------------

def _camel_to_snake(name: str) -> str:
    """Convert camelCase / PascalCase → snake_case."""
    # Insert underscore before uppercase letters that follow lowercase or digits
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    # Insert underscore before sequences of multiple uppercase letters
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    return s.lower()


def normalize_key(key: str) -> str:
    """
    Full key normalization pipeline:
    1. camelCase / PascalCase → snake_case
    2. Replace hyphens and spaces with underscores
    3. Collapse multiple underscores
    4. Strip leading/trailing underscores
    5. Lowercase
    """
    key = _camel_to_snake(key)
    key = re.sub(r"[-\s]+", "_", key)
    key = re.sub(r"_+", "_", key)
    key = key.strip("_").lower()
    return key


# ---------------------------------------------------------------------------
# Value cleanup helpers
# ---------------------------------------------------------------------------

def _is_empty(value: Any) -> bool:
    """Return True if the value should be removed (null, empty string)."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _clean_value(value: Any) -> Any:
    """Trim whitespace from string values."""
    if isinstance(value, str):
        return value.strip()
    return value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize(
    raw_payload: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str], int, List[str]]:
    """
    Normalize an incoming raw JSON payload.

    Returns:
        normalized_flat_map  — processed intermediate representation
        keys_normalized      — list of (original_key -> normalized_key) descriptions
        flatten_operations   — count of flattening actions performed
        removed_fields       — list of removed field keys
    """
    keys_normalized: List[str] = []
    removed_fields: List[str] = []
    flatten_ops: int = 0

    # Step 1: Flatten the top-level payload (depth=1)
    flattened: Dict[str, Any] = {}
    for raw_key, value in raw_payload.items():
        norm_key = normalize_key(raw_key)
        if norm_key != raw_key:
            keys_normalized.append(f"{raw_key} → {norm_key}")

        if isinstance(value, dict):
            flatten_ops += 1
            # Flatten one level down
            for sub_k, sub_v in value.items():
                sub_nk = normalize_key(sub_k)
                composite_key = f"{norm_key}_{sub_nk}"
                flattened[composite_key] = sub_v
        else:
            flattened[norm_key] = value

    # Step 2: Remove empty / null values and trim strings
    normalized: Dict[str, Any] = {}
    for key, value in flattened.items():
        if _is_empty(value):
            removed_fields.append(key)
        else:
            normalized[key] = _clean_value(value)

    return normalized, keys_normalized, flatten_ops, removed_fields
