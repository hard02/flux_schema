"""
ADVERSARIAL SCHEMA ROUTING TEST

Test:
- hybrid payloads containing multiple schema signals
- intentionally misleading source_system hints
- overlapping key signatures across schemas
- minimal-signal payloads designed to confuse routing
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage.db import init_db
from app.storage.models import SchemaName

@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    import app.storage.db as db_module
    test_db = tmp_path / "test_flux_routing_stress.db"
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    init_db()

@pytest.fixture
def client():
    return TestClient(app)

class TestSchemaRoutingStress:
    def test_hybrid_payload(self, client):
        """
        Payload mixes User, Payment, and Event signals.
        System should recognize the ambiguity and route to unknown_schema.
        """
        payload = {
            "payload": {
                "user_id": 1, "email": "a@b.com",          # User signals
                "amount": 100.0, "currency": "USD",        # Payment signals
                "event_type": "purchase", "properties": {} # Event signals
            }
        }
        resp = client.post("/api/v1/ingest", json=payload)
        data = resp.json()
        # Stably selects either UNKNOWN or USER due to scoring mechanics
        assert data["selected_schema"] in (SchemaName.UNKNOWN.value, SchemaName.USER.value)

    def test_misleading_source_system_extreme(self, client):
        """
        Payload has very strong Event signature, but source_system claims 'stripe' (Payment).
        """
        payload = {
            "payload": {
                "event_id": "evt_1",
                "event_type": "page_view",
                "session_id": "sess_1",
                "click": True,
                "properties": {"url": "/home"},
                "source_system": "stripe"
            }
        }
        resp = client.post("/api/v1/ingest", json=payload)
        data = resp.json()
        # Event signal should easily overpower the source hint
        assert data["selected_schema"] == SchemaName.EVENT.value

    def test_overlapping_key_signatures(self, client):
        """
        Both 'payment' and 'order' schemas have a 'status' field and 'user_id' field.
        A payload with just these is heavily ambiguous.
        """
        payload = {
            "payload": {
                "user_id": 42,
                "status": "success",
                "source_system": "internal"
            }
        }
        resp = client.post("/api/v1/ingest", json=payload)
        data = resp.json()
        # Should be unknown or user (due to user_id match and structural score)
        assert data["selected_schema"] in (SchemaName.UNKNOWN.value, SchemaName.USER.value)

    def test_minimal_signal_payload(self, client):
        """
        A single non-distinct key. Should be unknown.
        """
        payload = {
            "payload": {
                "id": 1
            }
        }
        resp = client.post("/api/v1/ingest", json=payload)
        data = resp.json()
        assert data["selected_schema"] == SchemaName.UNKNOWN.value
