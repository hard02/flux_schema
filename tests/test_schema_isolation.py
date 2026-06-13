"""
CROSS-SCHEMA CONTAMINATION TEST

Test:
- ensure memory updates in one schema NEVER affect others
- validate separate alias learning per schema
"""

import pytest
from datetime import datetime, timezone
from app.storage.db import init_db, get_db
from app.services.learning_service import update_memory, fetch_memory_for_schema
from app.storage.models import SchemaName
from app.core.matcher import match_fields

@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    import app.storage.db as db_module
    test_db = tmp_path / "test_flux_schema_isolation.db"
    monkeypatch.setattr(db_module, "DB_PATH", test_db)
    init_db()

def test_schema_isolation():
    now = datetime.now(tz=timezone.utc)
    
    # 1. Learn an alias in USER schema: 'id' -> 'user_id'
    for _ in range(10):
        with get_db() as conn:
            update_memory(conn, SchemaName.USER.value, {
                "id": {"canonical_field": "user_id", "confidence": 0.95, "mode": "HARD", "method": "exact"}
            }, now=now)
        
    # 2. Learn a different alias in PAYMENT schema: 'id' -> 'payment_id'
    for _ in range(10):
        with get_db() as conn:
            update_memory(conn, SchemaName.PAYMENT.value, {
                "id": {"canonical_field": "payment_id", "confidence": 0.95, "mode": "HARD", "method": "exact"}
            }, now=now)
        
    # 3. Retrieve memory for USER schema
    with get_db() as conn:
        user_mem = fetch_memory_for_schema(conn, SchemaName.USER.value)
        payment_mem = fetch_memory_for_schema(conn, SchemaName.PAYMENT.value)
        
    # Verify isolation at DB level
    assert len(user_mem) == 1
    assert user_mem[0]["canonical_field"] == "user_id"
    
    assert len(payment_mem) == 1
    assert payment_mem[0]["canonical_field"] == "payment_id"
    
    # 4. Verify isolation during Matching
    payload = {"id": 123}
    
    # Matching under USER schema
    user_mapping, _, _ = match_fields(payload, SchemaName.USER, user_mem)
    assert user_mapping["id"]["canonical_field"] == "user_id"
    
    # Matching under PAYMENT schema
    payment_mapping, _, _ = match_fields(payload, SchemaName.PAYMENT, payment_mem)
    assert payment_mapping["id"]["canonical_field"] == "payment_id"
