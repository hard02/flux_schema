"""
Tests for the Healing Engine (app/core/healer.py)
"""

import pytest
from app.core.healer import heal, _normalize_timestamp, _normalize_boolean, _coerce_value


class TestTimestampNormalization:
    def test_iso_string(self):
        result = _normalize_timestamp("2024-01-15T10:30:00Z")
        assert result is not None
        assert "T" in result

    def test_unix_timestamp(self):
        result = _normalize_timestamp(1700000000)
        assert result is not None
        assert "T" in result

    def test_human_readable(self):
        result = _normalize_timestamp("January 15, 2024")
        assert result is not None

    def test_invalid_timestamp(self):
        result = _normalize_timestamp("not-a-date")
        assert result is None

    def test_none_input(self):
        result = _normalize_timestamp(None)
        assert result is None


class TestBooleanNormalization:
    def test_string_true(self):
        assert _normalize_boolean("true") is True
        assert _normalize_boolean("yes") is True
        assert _normalize_boolean("1") is True

    def test_string_false(self):
        assert _normalize_boolean("false") is False
        assert _normalize_boolean("no") is False
        assert _normalize_boolean("0") is False

    def test_bool_passthrough(self):
        assert _normalize_boolean(True) is True
        assert _normalize_boolean(False) is False

    def test_unknown_string(self):
        assert _normalize_boolean("maybe") is None


class TestHeal:
    def test_basic_user_healing(self):
        normalized = {"usr_id": 42, "mail": "test@x.com"}
        field_map = {
            "usr_id": {"canonical_field": "user_id", "confidence": 0.9, "mode": "HARD", "method": "token"},
            "mail":   {"canonical_field": "email",   "confidence": 0.85, "mode": "HARD", "method": "edit"},
        }
        output, coercions, unmapped = heal(normalized, field_map, [], "user_schema", "user")
        assert output["user_id"] == 42
        assert output["email"] == "test@x.com"
        assert output["source_system"] == "user"
        # All unmapped canonical fields must be null
        assert output["entity_id"] is None
        assert output["timestamp"] is None

    def test_unmapped_keys_captured(self):
        normalized = {"foo": "bar"}
        output, _, unmapped = heal(normalized, {}, ["foo"], "user_schema", "unknown")
        assert "foo" in unmapped
        assert unmapped["foo"] == "bar"

    def test_numeric_string_coercion(self):
        normalized = {"amount": "99"}
        field_map = {"amount": {"canonical_field": "amount", "confidence": 0.95, "mode": "HARD", "method": "exact"}}
        output, coercions, _ = heal(normalized, field_map, [], "payment_schema", "payment")
        assert output["amount"] == 99
        assert any("numeric" in c for c in coercions)

    def test_timestamp_coercion(self):
        normalized = {"timestamp": "2024-01-01 12:00:00"}
        field_map = {"timestamp": {"canonical_field": "timestamp", "confidence": 1.0, "mode": "HARD", "method": "exact"}}
        output, coercions, _ = heal(normalized, field_map, [], "user_schema", "user")
        assert output["timestamp"] is not None
        assert "T" in output["timestamp"]  # ISO-8601 format

    def test_unmapped_fields_always_present(self):
        normalized = {}
        output, _, _ = heal(normalized, {}, [], "user_schema", "user")
        assert "unmapped_fields" in output
