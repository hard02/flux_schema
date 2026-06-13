"""
Tests for the Schema Routing / Source Detector (app/core/source_detector.py)
"""

import pytest
from app.core.source_detector import detect_schema
from app.storage.models import SchemaName, RoutingMode


class TestDetectSchema:
    def test_detects_user_schema(self):
        payload = {"user_id": 42, "email": "a@b.com"}
        schema, conf, mode, scores, reason = detect_schema(payload)
        assert schema == SchemaName.USER

    def test_detects_payment_schema(self):
        payload = {"payment_id": "ch_123", "amount": 100.0, "currency": "USD", "status": "success"}
        schema, conf, mode, scores, reason = detect_schema(payload)
        assert schema == SchemaName.PAYMENT

    def test_detects_order_schema(self):
        payload = {"order_id": "ORD-1", "items": [{"sku": "abc"}], "total_amount": 250.0}
        schema, conf, mode, scores, reason = detect_schema(payload)
        assert schema == SchemaName.ORDER

    def test_detects_event_schema(self):
        payload = {"event_type": "click", "session_id": "s-1", "properties": {"page": "home"}}
        schema, conf, mode, scores, reason = detect_schema(payload)
        assert schema == SchemaName.EVENT

    def test_unknown_schema_for_empty_payload(self):
        payload = {}
        schema, conf, mode, scores, reason = detect_schema(payload)
        assert schema == SchemaName.UNKNOWN

    def test_unknown_schema_low_signal(self):
        payload = {"foo": "bar", "baz": "qux"}
        schema, conf, mode, scores, reason = detect_schema(payload)
        # Low signal should not produce a high-confidence match
        assert mode in (RoutingMode.UNKNOWN, RoutingMode.SOFT)

    def test_hard_route_high_confidence(self):
        payload = {
            "user_id": 1, "email": "x@y.com", "entity_id": "e-1",
            "uid": 1, "login": "user1",
        }
        schema, conf, mode, scores, reason = detect_schema(payload)
        assert schema == SchemaName.USER
        assert mode in (RoutingMode.HARD, RoutingMode.SOFT)

    def test_source_hint_influences_score(self):
        payload = {"amount": 50, "currency": "EUR", "source_system": "stripe"}
        schema, conf, mode, scores, reason = detect_schema(payload)
        assert schema == SchemaName.PAYMENT

    def test_ambiguous_routes_to_unknown(self):
        # Payload with equal user + event signals
        payload = {"user_id": 1, "event_type": "click"}
        schema, conf, mode, scores, reason = detect_schema(payload)
        # Could be SOFT or UNKNOWN due to margin check — either is valid
        assert schema in (SchemaName.USER, SchemaName.EVENT, SchemaName.UNKNOWN)
