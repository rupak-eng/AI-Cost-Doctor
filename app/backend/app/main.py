"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.v1.router import router as v1_router
from app.core.config import ConfigurationError, settings, validate_startup_config
from app.core.db import engine

# --- Fail-fast startup validation -------------------------------------------
# Refuse to boot with a clear, named-variable error instead of a cryptic
# traceback when required secrets (FERNET_KEY, prod JWT_SECRET, ...) are
# missing or malformed. SystemExit(1) keeps container logs clean: the FATAL
# banner below is the whole story, no stack trace to decode.
try:
    validate_startup_config()
except ConfigurationError as exc:
    print(f"FATAL: invalid configuration — {exc}", file=sys.stderr)
    print("FATAL: refusing to start. Fix the environment and try again.",
          file=sys.stderr)
    raise SystemExit(1)

# --- Logging -----------------------------------------------------------------
# Uvicorn installs its own handlers; here we just honour LOG_LEVEL so
# operators can dial verbosity without rebuilding the image.
_log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
for _logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "ai-cost-doctor"):
    logging.getLogger(_logger_name).setLevel(_log_level)

app = FastAPI(
    title="AI Cost Doctor API",
    version="0.1.0",
    description="Per-customer AI unit economics, cost diagnosis, and savings recommendations.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router)


@app.get("/healthz", tags=["ops"])
def healthz() -> dict:
    """Liveness probe for compose healthchecks."""
    return {"status": "ok"}


@app.get("/readyz", tags=["ops"])
def readyz() -> JSONResponse:
    """Readiness probe: liveness plus a cheap database round-trip.

    Returns 200 when the DB answers, 503 otherwise. The failure detail is
    deliberately generic — no connection strings or driver errors leak.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "degraded"})
    return JSONResponse(status_code=200, content={"status": "ok"})
