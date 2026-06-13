# FluxSchema

FluxSchema is a deterministic schema mediation and data fluxing engine that sits between heterogeneous upstream data producers and a strict canonical data model. It is designed to eliminate schema drift in distributed systems by transforming inconsistent, versioned, and semi-structured JSON payloads into a normalized and validated canonical format using rule-based normalization, similarity matching, and memory-driven reinforcement.

It is NOT a machine learning system. It does NOT use embeddings, probabilistic inference, or LLM reasoning. All behavior is deterministic, explainable, and fully traceable.

---

# Problem Statement

Modern distributed systems suffer from schema fragmentation:

- Different services emit the same semantic data using different field names
- APIs evolve independently and introduce version drift
- Event payloads become inconsistent across producers
- Downstream systems require strict schemas for processing and analytics

Example of the same concept across systems:

```json
// System A
{ "usrId": 123, "mail": "a@x.com" }

// System B
{ "user_id": 123, "emailAddress": "a@x.com" }

// System C
{ "uid": 123, "email": "a@x.com" }
```

FluxSchema solves this by enforcing a strict canonical model and continuously reconciling incoming schema variance through deterministic mapping and memory-based alias reinforcement.

---

# Supported Canonical Schemas

FluxSchema currently supports these schema targets:

- `user_schema`
- `payment_schema`
- `order_schema`
- `event_schema`
- `unknown_schema`

Each schema has a strict field template and an `unmapped_fields` container for any inputs that cannot be deterministically mapped.

---

# How It Works

The ingestion pipeline in `app/api/ingest.py` follows eight deterministic stages:

1. Ingest raw JSON payload
2. Normalize field names and structure (`app/core/normalize.py`)
3. Detect schema route using schema signals and memory alignment (`app/core/source_detector.py`)
4. Match fields to canonical target fields (`app/core/matcher.py`)
5. Heal mapped values and coerce types (`app/core/healer.py`)
6. Validate canonical compliance (`app/core/canonicalizer.py`)
7. Update schema memory for future routing and alias resolution (`app/services/learning_service.py`)
8. Build a full observability trace (`app/services/observability_service.py`)

The API is implemented as a FastAPI service in `app/main.py` and exposes `/api/v1/ingest` plus a `/health` endpoint.

---

# Input Normalization

Normalization is deterministic and includes:

- Converting field names to lowercase snake_case
- Replacing spaces and hyphens with underscores
- Flattening one level of nested objects
- Removing null and empty-string values
- Trimming whitespace from string values

---

# Schema Routing

Schema routing is based on:

- schema signal overlap for known schema categories
- memory-based alignment with previously observed field aliases
- structural similarity heuristics
- optional `source_system` hints

A payload that cannot be confidently routed is classified as `unknown_schema`.

---

# Field Matching and Healing

Matching is performed using a deterministic hierarchy:

- exact canonical field match
- memory alias match
- token similarity
- edit distance
- frequency-weighted alias reinforcement

Healing then applies the chosen mapping and performs type coercion for values such as timestamps, numeric strings, and boolean-like inputs. Any unmapped or failed values are preserved inside `unmapped_fields`.

---

# Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

# Run Locally

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then visit:

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/health`

---

# API Example

```bash
curl -X POST http://127.0.0.1:8000/api/v1/ingest \
  -H 'Content-Type: application/json' \
  -d '{"payload":{"usrId":42,"mail":"test@example.com"},"debug":true}'
```

Example response:

```json
{
  "request_id": "...",
  "selected_schema": "user_schema",
  "canonical_output": {
    "entity_id": null,
    "user_id": null,
    "email": null,
    "timestamp": null,
    "source_system": "unknown",
    "unmapped_fields": {
      "usrId": 42,
      "mail": "test@example.com"
    }
  },
  "trace": { ... }
}
```

---

# Notes

- The project is intentionally deterministic and does not rely on machine learning.
- The canonical output always includes `unmapped_fields` to preserve unknown inputs.
- A local SQLite database file such as `fluxschema.db` is also ignored.

---

# Git Setup

This repository is intended to be initialized as its own Git repository in the workspace root. The included `.gitignore` excludes:

- `.venv/`
- `fluxschema.db`
- Python cache files and editor artifacts
