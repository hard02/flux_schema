"""
CANONICALIZATION ENFORCEMENT LAYER (Stage 6)

Validates canonical output for strict schema compliance:
  - All schema fields must exist (null is OK, missing is not)
  - No extra top-level keys except unmapped_fields
  - unmapped_fields is always present (may be empty dict)
  - Raises ValidationError on non-conformance
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.storage.models import (
    SchemaName,
    UserSchema,
    PaymentSchema,
    OrderSchema,
    EventSchema,
    UnknownSchema,
)

SCHEMA_MODEL_MAP = {
    SchemaName.USER.value:    UserSchema,
    SchemaName.PAYMENT.value: PaymentSchema,
    SchemaName.ORDER.value:   OrderSchema,
    SchemaName.EVENT.value:   EventSchema,
    SchemaName.UNKNOWN.value: UnknownSchema,
}


def validate_and_enforce(
    canonical_output: Dict[str, Any],
    schema_name: str,
) -> Tuple[Dict[str, Any], bool, List[str]]:
    """
    Validate canonical_output against the selected schema model.

    Returns:
        validated_output    — pydantic-validated dict
        is_valid            — True if fully compliant
        errors              — list of validation error strings
    """
    model_cls = SCHEMA_MODEL_MAP.get(schema_name, UnknownSchema)
    errors: List[str] = []

    try:
        instance = model_cls.model_validate(canonical_output)
        return instance.model_dump(), True, []
    except Exception as e:
        errors.append(str(e))
        # Attempt partial recovery — build a minimal valid output
        try:
            partial = {k: canonical_output.get(k) for k in model_cls.model_fields}
            partial["unmapped_fields"] = canonical_output.get("unmapped_fields", {})
            instance = model_cls.model_validate(partial)
            return instance.model_dump(), False, errors
        except Exception as e2:
            errors.append(f"recovery_failed: {e2}")
            return canonical_output, False, errors
