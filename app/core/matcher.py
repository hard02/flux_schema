"""
SCHEMA MATCHING ENGINE (Stage 4)

Maps normalized payload fields → canonical schema fields using a strict
5-level priority hierarchy:

  Level 1: Exact match
  Level 2: Memory alias match (schema-scoped)
  Level 3: Token similarity match
  Level 4: Edit distance (Levenshtein via rapidfuzz)
  Level 5: Frequency-weighted match

Scoring formula (from schema_mediation_engine_architecture.md):
  field_score =
      0.35 * alias_confidence +
      0.30 * token_similarity +
      0.20 * edit_similarity +
      0.15 * frequency_weight

Decision thresholds:
  ≥ 0.85  → HARD MAP
  0.65–0.84 → SOFT MAP
  < 0.65  → UNMAPPED
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz.distance import Levenshtein
from rapidfuzz import fuzz

from app.storage.models import SchemaName, MappingMode, MatchingMethod


# ---------------------------------------------------------------------------
# Canonical field definitions per schema
# ---------------------------------------------------------------------------

CANONICAL_FIELDS: Dict[str, List[str]] = {
    SchemaName.USER.value: ["entity_id", "user_id", "email", "timestamp", "source_system"],
    SchemaName.PAYMENT.value: ["payment_id", "user_id", "amount", "currency", "status", "timestamp", "source_system"],
    SchemaName.ORDER.value: ["order_id", "user_id", "items", "total_amount", "status", "timestamp", "source_system"],
    SchemaName.EVENT.value: ["event_id", "user_id", "event_type", "properties", "timestamp", "source_system"],
}


# ---------------------------------------------------------------------------
# Token splitting helpers
# ---------------------------------------------------------------------------

def _tokenize(field: str) -> List[str]:
    """Split an identifier into constituent tokens."""
    # Split on underscores first
    parts = field.split("_")
    tokens = []
    for p in parts:
        # Further split camelCase fragments that might remain
        sub = re.sub(r"([a-z])([A-Z])", r"\1 \2", p).split()
        tokens.extend([s.lower() for s in sub if s])
    return tokens


def _token_similarity(source: str, canonical: str) -> float:
    """Jaccard similarity between token sets of two field names."""
    src_tokens = set(_tokenize(source))
    can_tokens = set(_tokenize(canonical))
    if not src_tokens and not can_tokens:
        return 1.0
    if not src_tokens or not can_tokens:
        return 0.0
    intersection = src_tokens & can_tokens
    union = src_tokens | can_tokens
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# Edit distance helpers
# ---------------------------------------------------------------------------

def _edit_similarity(source: str, canonical: str) -> float:
    """Normalized Levenshtein similarity [0, 1]."""
    if source == canonical:
        return 1.0
    max_len = max(len(source), len(canonical))
    if max_len == 0:
        return 1.0
    distance = Levenshtein.distance(source, canonical)
    return 1.0 - (distance / max_len)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _compute_field_score(
    alias_confidence: float,
    token_similarity: float,
    edit_similarity: float,
    frequency_weight: float,
) -> float:
    return (
        0.35 * alias_confidence +
        0.30 * token_similarity +
        0.20 * edit_similarity +
        0.15 * frequency_weight
    )


def _frequency_weight(frequency: int) -> float:
    """Normalize frequency to [0, 1] using log normalization."""
    return min(math.log(1 + frequency) / math.log(1 + 1000), 1.0)


# ---------------------------------------------------------------------------
# Memory alias lookup
# ---------------------------------------------------------------------------

def _lookup_memory(
    source_field: str,
    schema_name: str,
    memory_entries: List[Dict[str, Any]],
) -> Optional[Tuple[str, float, int]]:
    """
    Look up schema-scoped memory for a source_field.
    Returns (canonical_field, confidence, frequency) for best match or None.
    """
    candidates = [
        e for e in memory_entries
        if e["schema_name"] == schema_name and e["source_field"] == source_field
    ]
    if not candidates:
        return None
    # Sort by confidence desc, then frequency desc, then most recent
    candidates.sort(key=lambda e: (e["confidence"], e["frequency"]), reverse=True)
    best = candidates[0]
    return best["canonical_field"], best["confidence"], best["frequency"]


# ---------------------------------------------------------------------------
# Per-field matching
# ---------------------------------------------------------------------------

def _match_field(
    source_field: str,
    schema_name: str,
    canonical_fields: List[str],
    memory_entries: List[Dict[str, Any]],
) -> Tuple[Optional[str], float, MappingMode, MatchingMethod, List[str]]:
    """
    Match a single source field to a canonical field using the 5-level hierarchy.

    Returns:
        canonical_field     — matched canonical field or None
        confidence          — final score
        mapping_mode        — HARD / SOFT / UNMAPPED
        method              — which level resolved the match
        alternatives        — other candidates considered
    """
    alternatives: List[str] = []

    # Level 1: Exact match
    if source_field in canonical_fields:
        return source_field, 1.0, MappingMode.HARD, MatchingMethod.EXACT, alternatives

    # Level 2: Memory alias match
    mem_result = _lookup_memory(source_field, schema_name, memory_entries)
    alias_confidence = 0.0
    mem_canonical: Optional[str] = None
    mem_frequency: int = 0

    if mem_result:
        mem_canonical, alias_confidence, mem_frequency = mem_result
        if alias_confidence >= 0.85:
            return (
                mem_canonical,
                alias_confidence,
                MappingMode.HARD,
                MatchingMethod.MEMORY,
                alternatives,
            )

    # Levels 3–5: score each canonical field
    best_field: Optional[str] = None
    best_score: float = 0.0
    best_method = MatchingMethod.TOKEN

    scored: List[Tuple[str, float]] = []
    for canonical in canonical_fields:
        token_sim = _token_similarity(source_field, canonical)
        edit_sim = _edit_similarity(source_field, canonical)

        # Alias confidence applies only to memory-matched canonical field
        alias_conf = alias_confidence if canonical == mem_canonical else 0.0
        freq_w = _frequency_weight(mem_frequency) if canonical == mem_canonical else 0.0

        score = _compute_field_score(alias_conf, token_sim, edit_sim, freq_w)
        scored.append((canonical, round(score, 4)))

    scored.sort(key=lambda x: x[1], reverse=True)
    alternatives = [f"{c}({s:.2f})" for c, s in scored[1:4]]

    if scored:
        best_field, best_score = scored[0]
        # Determine primary method
        if alias_confidence > 0 and best_field == mem_canonical:
            best_method = MatchingMethod.MEMORY
        elif _token_similarity(source_field, best_field) >= 0.5:
            best_method = MatchingMethod.TOKEN
        elif _edit_similarity(source_field, best_field) >= 0.5:
            best_method = MatchingMethod.EDIT
        else:
            best_method = MatchingMethod.FREQUENCY

    # Decision thresholds
    if best_score >= 0.85:
        mode = MappingMode.HARD
    elif best_score >= 0.65:
        mode = MappingMode.SOFT
    else:
        return None, best_score, MappingMode.UNMAPPED, best_method, alternatives

    return best_field, best_score, mode, best_method, alternatives


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_fields(
    normalized_payload: Dict[str, Any],
    schema_name: SchemaName,
    memory_entries: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[str]]:
    """
    Map all fields in normalized_payload to the selected schema's canonical fields.

    Returns:
        field_mapping_map       — {source_field: {canonical_field, confidence, mode, method}}
        mapping_trace_list      — list of trace dicts for observability
        unmapped_keys           — list of source fields that could not be mapped
    """
    canonical = CANONICAL_FIELDS.get(schema_name.value, [])
    field_mapping_map: Dict[str, Any] = {}
    mapping_trace_list: List[Dict[str, Any]] = []
    unmapped_keys: List[str] = []

    # Track which canonical fields are already claimed (1:1 constraint)
    claimed_canonicals: Dict[str, Tuple[str, float]] = {}  # canonical → (source, score)

    # Score all fields first
    all_results: List[Tuple[str, Optional[str], float, MappingMode, MatchingMethod, List[str]]] = []
    for source_field in normalized_payload:
        can_f, score, mode, method, alts = _match_field(
            source_field, schema_name.value, canonical, memory_entries
        )
        all_results.append((source_field, can_f, score, mode, method, alts))

    # Sort by score desc to resolve conflicts deterministically (highest confidence wins)
    all_results.sort(key=lambda x: x[2], reverse=True)

    for source_field, can_f, score, mode, method, alts in all_results:
        if mode == MappingMode.UNMAPPED or can_f is None:
            unmapped_keys.append(source_field)
            mapping_trace_list.append({
                "source_field": source_field,
                "canonical_field": None,
                "matching_method": method.value,
                "confidence": score,
                "mapping_mode": MappingMode.UNMAPPED.value,
                "schema_context": schema_name.value,
                "alternatives_considered": alts,
            })
            continue

        # Conflict resolution: if canonical is already claimed
        if can_f in claimed_canonicals:
            existing_source, existing_score = claimed_canonicals[can_f]
            if score <= existing_score:
                unmapped_keys.append(source_field)
                mapping_trace_list.append({
                    "source_field": source_field,
                    "canonical_field": None,
                    "matching_method": method.value,
                    "confidence": score,
                    "mapping_mode": MappingMode.UNMAPPED.value,
                    "schema_context": schema_name.value,
                    "alternatives_considered": alts,
                    "conflict_note": f"canonical '{can_f}' already claimed by '{existing_source}'",
                })
                continue

        claimed_canonicals[can_f] = (source_field, score)
        field_mapping_map[source_field] = {
            "canonical_field": can_f,
            "confidence": score,
            "mode": mode.value,
            "method": method.value,
        }
        mapping_trace_list.append({
            "source_field": source_field,
            "canonical_field": can_f,
            "matching_method": method.value,
            "confidence": score,
            "mapping_mode": mode.value,
            "schema_context": schema_name.value,
            "alternatives_considered": alts,
        })

    return field_mapping_map, mapping_trace_list, unmapped_keys
