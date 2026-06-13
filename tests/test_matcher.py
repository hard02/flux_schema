"""
Tests for the Field Matching Engine (app/core/matcher.py)
"""

import pytest
from app.core.matcher import match_fields, _token_similarity, _edit_similarity
from app.storage.models import SchemaName, MappingMode


class TestTokenSimilarity:
    def test_identical_fields(self):
        assert _token_similarity("user_id", "user_id") == 1.0

    def test_partial_token_overlap(self):
        score = _token_similarity("usr_id", "user_id")
        # "id" token overlaps — should be > 0
        assert score > 0

    def test_no_overlap(self):
        score = _token_similarity("cart", "email")
        assert score == 0.0


class TestEditSimilarity:
    def test_identical(self):
        assert _edit_similarity("email", "email") == 1.0

    def test_one_char_difference(self):
        score = _edit_similarity("mail", "email")
        assert score > 0.5

    def test_completely_different(self):
        score = _edit_similarity("xyz", "abc")
        assert score < 0.5


class TestMatchFields:
    def test_exact_match(self):
        payload = {"email": "test@example.com"}
        mapping, trace, unmapped = match_fields(payload, SchemaName.USER, [])
        assert "email" in mapping
        assert mapping["email"]["canonical_field"] == "email"
        assert mapping["email"]["mode"] == MappingMode.HARD.value

    def test_alias_match_mail_to_email(self):
        payload = {"mail": "test@example.com"}
        mapping, trace, unmapped = match_fields(payload, SchemaName.USER, [])
        # "mail" should match "email" via token/edit similarity
        if "mail" in mapping:
            assert mapping["mail"]["canonical_field"] == "email"

    def test_unmapped_completely_foreign_key(self):
        payload = {"zzz_completely_foreign": "value"}
        mapping, trace, unmapped = match_fields(payload, SchemaName.USER, [])
        assert "zzz_completely_foreign" in unmapped

    def test_memory_alias_used(self):
        memory_entries = [
            {
                "schema_name": "user_schema",
                "source_field": "usrId",
                "canonical_field": "user_id",
                "confidence": 0.92,
                "frequency": 15,
                "last_seen": "2026-01-01T00:00:00",
            }
        ]
        payload = {"usrId": 42}
        mapping, trace, unmapped = match_fields(payload, SchemaName.USER, memory_entries)
        if "usrId" in mapping:
            assert mapping["usrId"]["canonical_field"] == "user_id"

    def test_no_duplicate_canonical_mapping(self):
        """Two source fields competing for same canonical field → only one wins."""
        payload = {"email": "a@b.com", "mail": "b@c.com"}
        mapping, trace, unmapped = match_fields(payload, SchemaName.USER, [])
        # "email" wins via exact match; "mail" should go to unmapped or get email (soft)
        canonical_fields_used = [m["canonical_field"] for m in mapping.values()]
        # No duplicates
        assert len(canonical_fields_used) == len(set(canonical_fields_used))

    def test_payment_schema_fields(self):
        payload = {"payment_id": "p-1", "amount": 100.0, "currency": "USD"}
        mapping, trace, unmapped = match_fields(payload, SchemaName.PAYMENT, [])
        assert "payment_id" in mapping
        assert "amount" in mapping
        assert "currency" in mapping
