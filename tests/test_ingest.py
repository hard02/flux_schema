"""
End-to-end integration tests for POST /api/v1/ingest
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage.db import init_db


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    """Point DB to a temp file for isolated test runs."""
    import app.storage.db as db_module
    test_db = tmp_path / "test_flux.db"
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    init_db()


@pytest.fixture
def client():
    return TestClient(app)


class TestIngestEndpoint:
    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_ingest_user_payload(self, client):
        payload = {"payload": {"usrId": 42, "mail": "test@example.com"}}
        resp = client.post("/api/v1/ingest", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "canonical_output" in data
        assert "trace" in data
        assert data["trace"]["selected_schema"] in (
            "user_schema", "unknown_schema"
        )

    def test_ingest_payment_payload(self, client):
        payload = {
            "payload": {
                "paymentId": "ch_123",
                "amount": "99.99",
                "currency": "USD",
                "status": "success",
            }
        }
        resp = client.post("/api/v1/ingest", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["selected_schema"] == "payment_schema"
        canonical = data["canonical_output"]
        # Amount should be coerced from string to float/int
        assert canonical.get("amount") in (99.99, 99)

    def test_ingest_order_payload(self, client):
        payload = {
            "payload": {
                "orderId": "ORD-001",
                "items": [{"sku": "prod-1", "qty": 2}],
                "totalAmount": 200.0,
            }
        }
        resp = client.post("/api/v1/ingest", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["selected_schema"] == "order_schema"

    def test_ingest_event_payload(self, client):
        payload = {
            "payload": {
                "eventType": "page_view",
                "sessionId": "s-abc",
                "properties": {"page": "/home"},
            }
        }
        resp = client.post("/api/v1/ingest", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["selected_schema"] == "event_schema"

    def test_ingest_unknown_payload(self, client):
        payload = {"payload": {"foo": "bar", "baz": "qux"}}
        resp = client.post("/api/v1/ingest", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        # Should fall back to unknown schema without crashing
        assert "canonical_output" in data
        assert "trace" in data

    def test_trace_always_present(self, client):
        payload = {"payload": {"user_id": 1, "email": "a@b.com"}}
        resp = client.post("/api/v1/ingest", json=payload)
        assert resp.status_code == 200
        trace = resp.json()["trace"]
        assert "request_id" in trace
        assert "selected_schema" in trace
        assert "latency" in trace
        assert "field_mappings" in trace

    def test_debug_mode_exposes_more(self, client):
        payload = {
            "payload": {"user_id": 1, "email": "a@b.com"},
            "debug": True,
        }
        resp = client.post("/api/v1/ingest", json=payload)
        assert resp.status_code == 200
        trace = resp.json()["trace"]
        assert "field_mappings" in trace

    def test_memory_reinforcement_over_repeated_calls(self, client):
        """Repeated calls with same payload should increase memory frequency."""
        payload = {"payload": {"usr_id": 5, "mail": "user@test.com"}}
        for _ in range(3):
            resp = client.post("/api/v1/ingest", json=payload)
            assert resp.status_code == 200
        # Last call should show LEARNED or MIXED processing mode
        data = resp.json()
        assert data["trace"]["processing_mode"] in ("NEW", "LEARNED", "MIXED")

    def test_unmapped_fields_preserved(self, client):
        payload = {
            "payload": {
                "user_id": 1,
                "email": "a@b.com",
                "custom_internal_flag": "value_xyz",
            }
        }
        resp = client.post("/api/v1/ingest", json=payload)
        assert resp.status_code == 200
        canonical = resp.json()["canonical_output"]
        unmapped = canonical.get("unmapped_fields", {})
        # custom_internal_flag should appear in unmapped_fields
        assert "custom_internal_flag" in unmapped

    def test_request_id_is_unique(self, client):
        payload = {"payload": {"user_id": 1}}
        r1 = client.post("/api/v1/ingest", json=payload).json()
        r2 = client.post("/api/v1/ingest", json=payload).json()
        assert r1["request_id"] != r2["request_id"]
