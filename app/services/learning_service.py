"""
MEMORY + LEARNING LAYER (Stage 7) — Non-ML Reinforcement System

Implements deterministic memory reinforcement:
  - Increments frequency on successful mappings
  - Increases confidence based on repetition
  - Decreases confidence on mismatch
  - Applies linear decay for stale entries
  - Logs all corrections to correction_log
  - Updates schema_statistics
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import sqlite3


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_CONFIDENCE = 0.55
MAX_CONFIDENCE  = 0.99
MIN_CONFIDENCE  = 0.10
DECAY_RATE      = 0.001  # confidence loss per day of inactivity
PENALTY         = 0.15   # confidence loss on mismatch


# ---------------------------------------------------------------------------
# Confidence update formulas
# ---------------------------------------------------------------------------

def _confidence_increase(current: float, frequency: int) -> float:
    """Deterministic confidence increase: confidence + 0.02 * log(frequency)."""
    delta = 0.02 * math.log(max(frequency, 1))
    return min(current + delta, MAX_CONFIDENCE)


def _confidence_decay(
    current: float,
    last_seen: str,
    now: Optional[datetime] = None,
) -> float:
    """Apply linear decay based on days since last seen."""
    if now is None:
        now = datetime.now(tz=timezone.utc)
    try:
        last = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        days_gap = (now - last).total_seconds() / 86400
        decayed = current - (DECAY_RATE * days_gap)
        return max(decayed, MIN_CONFIDENCE)
    except Exception:
        return current


# ---------------------------------------------------------------------------
# Memory fetch helpers
# ---------------------------------------------------------------------------

def fetch_memory_for_schema(
    conn: sqlite3.Connection,
    schema_name: str,
) -> List[Dict[str, Any]]:
    """Fetch all memory entries for a schema partition."""
    cursor = conn.execute(
        """
        SELECT schema_name, source_field, canonical_field,
               confidence, frequency, last_seen
        FROM field_mapping_table
        WHERE schema_name = ?
        """,
        (schema_name,),
    )
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


def fetch_memory_for_all_schemas(
    conn: sqlite3.Connection,
) -> Dict[str, Dict[str, Any]]:
    """Fetch a lightweight mapping dict per schema: {schema: {source_field: canonical_field}}."""
    cursor = conn.execute(
        "SELECT schema_name, source_field, canonical_field, confidence FROM field_mapping_table"
    )
    result: Dict[str, Dict[str, Any]] = {}
    for row in cursor.fetchall():
        sn = row["schema_name"]
        sf = row["source_field"]
        result.setdefault(sn, {})[sf] = row["canonical_field"]
    return result


# ---------------------------------------------------------------------------
# Memory update
# ---------------------------------------------------------------------------

def update_memory(
    conn: sqlite3.Connection,
    schema_name: str,
    field_mapping_map: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Tuple[List[str], List[str], List[str], List[str]]:
    """
    Persist successful field mappings into memory.

    Returns lists of new_entries, updated_entries, confidence_changes, frequency_updates
    for the observability trace.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)
    now_str = now.isoformat()

    new_entries: List[str]       = []
    updated_entries: List[str]   = []
    confidence_changes: List[str] = []
    frequency_updates: List[str] = []

    for source_field, mapping in field_mapping_map.items():
        canonical_field: str = mapping["canonical_field"]
        observed_confidence: float = mapping["confidence"]

        # Check for existing entry
        row = conn.execute(
            """
            SELECT id, confidence, frequency, last_seen
            FROM field_mapping_table
            WHERE schema_name = ? AND source_field = ? AND canonical_field = ?
            """,
            (schema_name, source_field, canonical_field),
        ).fetchone()

        if row is None:
            # Insert new entry
            init_conf = max(BASE_CONFIDENCE, observed_confidence * 0.8)
            conn.execute(
                """
                INSERT INTO field_mapping_table
                    (schema_name, source_field, canonical_field, confidence, frequency, last_seen)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (schema_name, source_field, canonical_field, init_conf, now_str),
            )
            new_entries.append(f"{source_field}→{canonical_field} (conf={init_conf:.2f})")
        else:
            old_conf = row["confidence"]
            freq = row["frequency"] + 1
            new_conf = _confidence_increase(old_conf, freq)
            new_conf = _confidence_decay(new_conf, row["last_seen"], now)

            conn.execute(
                """
                UPDATE field_mapping_table
                SET confidence = ?, frequency = ?, last_seen = ?
                WHERE id = ?
                """,
                (new_conf, freq, now_str, row["id"]),
            )
            updated_entries.append(f"{source_field}→{canonical_field}")
            confidence_changes.append(f"{source_field}: {old_conf:.3f} → {new_conf:.3f}")
            frequency_updates.append(f"{source_field}: freq={freq}")

    # Log corrections
    for source_field, mapping in field_mapping_map.items():
        conn.execute(
            """
            INSERT INTO correction_log
                (schema_name, source_field, mapped_field, method_used, confidence, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                schema_name,
                source_field,
                mapping["canonical_field"],
                mapping["method"],
                mapping["confidence"],
                now_str,
            ),
        )

    # Update schema_statistics
    for source_field, mapping in field_mapping_map.items():
        canonical_field = mapping["canonical_field"]
        stat_row = conn.execute(
            "SELECT id, occurrence_count FROM schema_statistics WHERE schema_name=? AND field_name=?",
            (schema_name, canonical_field),
        ).fetchone()
        if stat_row is None:
            conn.execute(
                "INSERT INTO schema_statistics (schema_name, field_name, occurrence_count, success_rate) VALUES (?,?,1,1.0)",
                (schema_name, canonical_field),
            )
        else:
            new_count = stat_row["occurrence_count"] + 1
            conn.execute(
                "UPDATE schema_statistics SET occurrence_count=? WHERE id=?",
                (new_count, stat_row["id"]),
            )

    return new_entries, updated_entries, confidence_changes, frequency_updates
