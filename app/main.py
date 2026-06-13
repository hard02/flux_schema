"""
FluxSchema — FastAPI Application Entry Point

Initializes the app, configures routes, startup/shutdown hooks,
and registers global exception handlers.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.storage.db import init_db
from app.api.ingest import router as ingest_router

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

app = FastAPI(
    title="FluxSchema",
    description=(
        "A deterministic schema mediation and data fluxing engine. "
        "Transforms heterogeneous JSON payloads into strict canonical schemas "
        "using rule-based normalization, similarity matching, and memory-driven reinforcement."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Lifecycle hooks
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup_event() -> None:
    """Initialize the SQLite database tables on startup."""
    init_db()


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error_type": "internal_error",
            "message": str(exc),
            "stage": "unknown",
            "recoverable": False,
        },
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(ingest_router, prefix="/api/v1", tags=["Ingestion"])


@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    return {
        "status": "healthy",
        "service": "FluxSchema",
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }
