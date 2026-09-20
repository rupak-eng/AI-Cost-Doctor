"""FastAPI application entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import settings

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
