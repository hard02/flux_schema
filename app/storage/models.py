"""
Pydantic models for canonical schemas, observability traces, and API responses.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, model_validator
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SchemaName(str, Enum):
    USER = "user_schema"
    PAYMENT = "payment_schema"
    ORDER = "order_schema"
    EVENT = "event_schema"
    UNKNOWN = "unknown_schema"


class RoutingMode(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"
    UNKNOWN = "UNKNOWN"


class MappingMode(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"
    UNMAPPED = "UNMAPPED"


class ProcessingMode(str, Enum):
    NEW = "NEW"
    LEARNED = "LEARNED"
    MIXED = "MIXED"


class MatchingMethod(str, Enum):
    EXACT = "exact"
    MEMORY = "memory"
    TOKEN = "token"
    EDIT = "edit"
    FREQUENCY = "frequency"


# ---------------------------------------------------------------------------
# Canonical Schemas
# ---------------------------------------------------------------------------

class UserSchema(BaseModel):
    entity_id: Optional[Any] = None
    user_id: Optional[Any] = None
    email: Optional[Any] = None
    timestamp: Optional[str] = None
    source_system: Optional[str] = None
    unmapped_fields: Dict[str, Any] = {}


class PaymentSchema(BaseModel):
    payment_id: Optional[Any] = None
    user_id: Optional[Any] = None
    amount: Optional[Any] = None
    currency: Optional[Any] = None
    status: Optional[Any] = None
    timestamp: Optional[str] = None
    source_system: Optional[str] = None
    unmapped_fields: Dict[str, Any] = {}


class OrderSchema(BaseModel):
    order_id: Optional[Any] = None
    user_id: Optional[Any] = None
    items: Optional[Any] = None
    total_amount: Optional[Any] = None
    status: Optional[Any] = None
    timestamp: Optional[str] = None
    source_system: Optional[str] = None
    unmapped_fields: Dict[str, Any] = {}


class EventSchema(BaseModel):
    event_id: Optional[Any] = None
    user_id: Optional[Any] = None
    event_type: Optional[Any] = None
    properties: Dict[str, Any] = {}
    timestamp: Optional[str] = None
    source_system: Optional[str] = None
    unmapped_fields: Dict[str, Any] = {}


class UnknownSchema(BaseModel):
    source_system: str = "unknown"
    unmapped_fields: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Observability / Trace Models
# ---------------------------------------------------------------------------

class IngestionTrace(BaseModel):
    raw_payload_size: int
    json_valid: bool
    request_id: str


class NormalizationTrace(BaseModel):
    keys_normalized: List[str]
    flatten_operations: int
    removed_fields: List[str]


class CandidateScores(BaseModel):
    user_schema: float = 0.0
    payment_schema: float = 0.0
    order_schema: float = 0.0
    event_schema: float = 0.0


class RoutingTrace(BaseModel):
    candidate_scores: CandidateScores
    selected_schema: str
    decision_threshold: float
    routing_reason: str
    routing_mode: RoutingMode


class FieldMappingTrace(BaseModel):
    source_field: str
    canonical_field: str
    matching_method: MatchingMethod
    confidence: float
    mapping_mode: MappingMode
    schema_context: str
    alternatives_considered: List[str] = []


class HealingTrace(BaseModel):
    type_coercions: List[str] = []
    missing_fields_filled: List[str] = []
    unmapped_fields_captured: Dict[str, Any] = {}
    final_schema_compliance: bool = True


class MemoryHit(BaseModel):
    source_field: str
    schema_name: str
    matched_canonical_field: str
    confidence: float
    frequency: int


class MemoryUpdateTrace(BaseModel):
    new_entries: List[str] = []
    updated_entries: List[str] = []
    confidence_changes: List[str] = []
    frequency_updates: List[str] = []


class ErrorTrace(BaseModel):
    error_type: str
    stage: str
    message: str
    recoverable: bool
    fallback_action: str = ""


class LatencyBreakdown(BaseModel):
    ingestion_ms: float = 0
    normalization_ms: float = 0
    routing_ms: float = 0
    mapping_ms: float = 0
    healing_ms: float = 0
    memory_ms: float = 0
    total_ms: float = 0


class ObservabilityTrace(BaseModel):
    request_id: str
    ingestion_timestamp: str
    selected_schema: str
    routing_confidence: float
    routing_mode: RoutingMode
    processing_mode: ProcessingMode
    latency: LatencyBreakdown
    stages: Dict[str, Any] = {}
    field_mappings: List[FieldMappingTrace] = []
    unknown_fields: List[str] = []
    memory_hits: List[MemoryHit] = []
    errors: List[ErrorTrace] = []


# ---------------------------------------------------------------------------
# API Request / Response
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    payload: Dict[str, Any]
    debug: bool = False


class IngestResponse(BaseModel):
    request_id: str
    selected_schema: str
    canonical_output: Dict[str, Any]
    trace: ObservabilityTrace
