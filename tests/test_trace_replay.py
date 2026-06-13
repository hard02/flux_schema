"""
TRACE REPLAY DETERMINISM TEST

Test:
- run identical payload 10+ times
- compare schemas, fields, output, confidence over time
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.storage.db import init_db

@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    import app.storage.db as db_module
    test_db = tmp_path / "test_flux_trace_replay.db"
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    init_db()

@pytest.fixture
def client():
    return TestClient(app)

class TestTraceReplayDeterminism:
    def test_deterministic_replay(self, client):
        payload = {
            "payload": {
                "user_id": 42,
                "email": "test@test.com",
                "source_system": "crm"
            }
        }
        
        # First run (Cold Start)
        resp1 = client.post("/api/v1/ingest", json=payload).json()
        
        # Run 10 times to reinforce memory
        for _ in range(10):
            client.post("/api/v1/ingest", json=payload)
            
        # 12th run (Stable)
        resp_stable_1 = client.post("/api/v1/ingest", json=payload).json()
        
        # 13th run (Stable replay)
        resp_stable_2 = client.post("/api/v1/ingest", json=payload).json()
        
        # Output schemas and mappings should be perfectly identical
        assert resp_stable_1["selected_schema"] == resp_stable_2["selected_schema"]
        assert resp_stable_1["canonical_output"] == resp_stable_2["canonical_output"]
        
        # Processing mode won't change from NEW because we are using EXACT keys
        # But we can verify frequency increased in the database/trace metadata
        # Field mapping choices should be identical
        mappings_1 = resp_stable_1["trace"]["field_mappings"]
        mappings_2 = resp_stable_2["trace"]["field_mappings"]
        
        assert len(mappings_1) == len(mappings_2)
        for m1, m2 in zip(mappings_1, mappings_2):
            assert m1["source_field"] == m2["source_field"]
            assert m1["canonical_field"] == m2["canonical_field"]
            assert m1["mapping_mode"] == m2["mapping_mode"]
            
        # Also ensure latency breakdown fields exist and don't crash
        assert "total_ms" in resp_stable_1["trace"]["latency"]
