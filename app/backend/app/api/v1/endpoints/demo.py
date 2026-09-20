"""Demo APIs — all on clearly-labeled synthetic data, all numbers computed by
the real cost engine over seeded usage events (never hardcoded).

  POST /demo/seed        create the DemoCo dataset
  DELETE /demo/reset    delete the DemoCo dataset
  GET  /demo/pnl        per-tenant revenue / AI cost / margin / status
  POST /demo/investigate {tenant_external_id} -> deterministic root-cause facts

Thin wrappers over the shared services (app.services.pnl /
app.services.investigate) — the same engine that powers customer data.
Every response carries "data_label": "demo".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import models as m
from app.api.v1 import deps
from app.core.db import get_db
from app.schemas import demo as schemas
from app.services import seed_demo
from app.services.investigate import TenantNotFoundError, investigate_tenant
from app.services.pnl import compute_pnl

router = APIRouter(prefix="/demo", tags=["demo"])

WINDOW_DAYS = 30


@router.post("/seed", status_code=status.HTTP_201_CREATED)
def seed(db: Session = Depends(get_db)):
    deps.set_rls_org(db, seed_demo.demo_org_id())
    try:
        return seed_demo.seed_demo_org(db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/reset")
def reset(db: Session = Depends(get_db)):
    deps.set_rls_org(db, seed_demo.demo_org_id())
    return seed_demo.reset_demo_org(db)


@router.get("/pnl", response_model=schemas.PnLResponse)
def pnl(org: m.Organization = Depends(deps.get_demo_org), db: Session = Depends(get_db)):
    project = deps.get_demo_project(db, org)
    rows = compute_pnl(db, org.id, project.id, days=WINDOW_DAYS)
    return schemas.PnLResponse(tenants=[schemas.PnLRow(**r) for r in rows])


@router.post("/investigate", response_model=schemas.InvestigateResponse)
def investigate(payload: schemas.InvestigateRequest,
                org: m.Organization = Depends(deps.get_demo_org),
                db: Session = Depends(get_db)):
    project = deps.get_demo_project(db, org)
    try:
        result = investigate_tenant(db, org.id, project.id,
                                    payload.tenant_external_id, days=WINDOW_DAYS)
    except TenantNotFoundError:
        raise HTTPException(status_code=404, detail="tenant not found in demo dataset")
    return schemas.InvestigateResponse(**result)
