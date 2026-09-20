"""v1 router: mounts all endpoint modules under /api/v1."""
from fastapi import APIRouter

from app.api.v1.endpoints import auth, demo

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(demo.router)
