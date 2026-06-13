"""
Tests for the Normalization Layer (app/core/normalize.py)
"""

import pytest
from app.core.normalize import normalize, normalize_key


class TestNormalizeKey:
    def test_camel_case(self):
        assert normalize_key("userId") == "user_id"

    def test_pascal_case(self):
        assert normalize_key("UserEmail") == "user_email"

    def test_kebab_case(self):
        assert normalize_key("user-email") == "user_email"

    def test_already_snake(self):
        assert normalize_key("user_id") == "user_id"

    def test_upper_acronym(self):
        # userID → user_id (camelCase normalization collapses ID as a unit)
        assert normalize_key("userID") == "user_id"

    def test_leading_trailing_underscores(self):
        assert normalize_key("_user_id_") == "user_id"

    def test_multiple_separators(self):
        assert normalize_key("user--email") == "user_email"


class TestNormalize:
    def test_basic_normalization(self):
        payload = {"usrId": 42, "mail": "test@example.com"}
        result, keys_norm, flatten_ops, removed = normalize(payload)
        assert "usr_id" in result
        assert "mail" in result
        assert result["usr_id"] == 42
        assert result["mail"] == "test@example.com"


    def test_removes_null_values(self):
        payload = {"user_id": 1, "email": None, "name": ""}
        result, _, _, removed = normalize(payload)
        assert "email" not in result
        assert "name" not in result
        assert "user_id" in result
        assert "email" in removed or "name" in removed

    def test_trims_whitespace(self):
        payload = {"email": "  test@x.com  "}
        result, _, _, _ = normalize(payload)
        assert result["email"] == "test@x.com"

    def test_flattens_nested_one_level(self):
        payload = {"user": {"id": 5, "email": "a@b.com"}}
        result, _, flatten_ops, _ = normalize(payload)
        assert flatten_ops == 1
        # Nested fields should be accessible at top level
        assert any("id" in k or "email" in k for k in result)

    def test_tracks_keys_normalized(self):
        payload = {"userId": 1}
        _, keys_norm, _, _ = normalize(payload)
        assert any("userId" in kn for kn in keys_norm)

    def test_empty_payload(self):
        result, _, _, _ = normalize({})
        assert result == {}

    def test_preserves_numeric_values(self):
        payload = {"amount": 99.99, "quantity": 3}
        result, _, _, _ = normalize(payload)
        assert result["amount"] == 99.99
        assert result["quantity"] == 3
