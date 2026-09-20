"""v1 router: mounts all endpoint modules under /api/v1."""
from fastapi import APIRouter

from app.api.v1.endpoints import auth, billing, demo, ingest, integrations, projects, providers

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(billing.router)
router.include_router(demo.router)
router.include_router(projects.router)
router.include_router(ingest.router)
router.include_router(integrations.router)
router.include_router(providers.router)
