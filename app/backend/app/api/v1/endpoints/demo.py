"""Demo APIs — all on clearly-labeled synthetic data, all numbers computed by
the real cost engine over seeded usage events (never hardcoded).

  POST /demo/seed        create the DemoCo dataset
  DELETE /demo/reset    delete the DemoCo dataset
  GET  /demo/pnl        per-tenant revenue / AI cost / margin / status
  POST /demo/investigate {tenant_external_id} -> deterministic root-cause facts

Every response carries "data_label": "demo".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models as m
from app.api.v1 import deps
from app.core.db import get_db
from app.schemas import demo as schemas
from app.services import recommend, seed_demo

router = APIRouter(prefix="/demo", tags=["demo"])

WINDOW_DAYS = 30
RECENT_DAYS = 7


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _window():
    now = _utcnow()
    return now - timedelta(days=WINDOW_DAYS), now


def tenant_status(margin_usd: Decimal, revenue_usd: Decimal) -> str:
    """Binding status rule (spec 03 API contract): margin_killer iff margin < 0;
    at_risk iff margin < 15% of revenue; else healthy."""
    if margin_usd < 0:
        return "margin_killer"
    if margin_usd < Decimal("0.15") * revenue_usd:
        return "at_risk"
    return "healthy"


def _tenant_costs(db: Session, org_id, project_id, start, end):
    """{tenant_external_id: (requests, cost_usd)} over the window."""
    rows = (
        db.query(
            m.UsageEvent.tenant_id,
            func.count(m.UsageEvent.id),
            func.sum(m.UsageEvent.cost_calculated_usd),
        )
        .filter(
            m.UsageEvent.org_id == org_id,
            m.UsageEvent.project_id == project_id,
            m.UsageEvent.occurred_at >= start,
            m.UsageEvent.occurred_at < end,
        )
        .group_by(m.UsageEvent.tenant_id)
        .all()
    )
    return {r[0]: (r[1], r[2] or Decimal(0)) for r in rows}


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
    start, end = _window()
    costs = _tenant_costs(db, org.id, project.id, start, end)
    tenants = (
        db.query(m.Tenant).filter_by(org_id=org.id, project_id=project.id)
        .order_by(m.Tenant.external_id).all()
    )
    rows = []
    for t in tenants:
        _, cost = costs.get(t.external_id, (0, Decimal(0)))
        revenue = t.monthly_revenue_usd or Decimal(0)
        margin = revenue - cost
        rows.append(schemas.PnLRow(
            tenant_id=t.id,
            tenant_external_id=t.external_id,
            name=t.name,
            revenue_usd=revenue,
            ai_cost_usd=cost,
            margin_usd=margin,
            status=tenant_status(margin, revenue),
        ))
    return schemas.PnLResponse(tenants=rows)


def _drivers(db: Session, org_id, project_id, tenant_ext: str, start, end, column, key_name: str):
    total = (
        db.query(func.sum(m.UsageEvent.cost_calculated_usd))
        .filter(m.UsageEvent.org_id == org_id, m.UsageEvent.project_id == project_id,
                m.UsageEvent.tenant_id == tenant_ext,
                m.UsageEvent.occurred_at >= start, m.UsageEvent.occurred_at < end)
        .scalar() or Decimal(0)
    )
    rows = (
        db.query(column, func.sum(m.UsageEvent.cost_calculated_usd))
        .filter(m.UsageEvent.org_id == org_id, m.UsageEvent.project_id == project_id,
                m.UsageEvent.tenant_id == tenant_ext,
                m.UsageEvent.occurred_at >= start, m.UsageEvent.occurred_at < end)
        .group_by(column).order_by(func.sum(m.UsageEvent.cost_calculated_usd).desc()).all()
    )
    out = []
    for value, cost in rows:
        cost = cost or Decimal(0)
        pct = float(cost / total * 100) if total else 0.0
        out.append({key_name: value or "unknown", "cost_usd": cost, "pct": round(pct, 1)})
    return out, total


def _volume_stats(db: Session, org_id, project_id, tenant_ext: str, start, end):
    row = (
        db.query(func.count(m.UsageEvent.id),
                 func.sum(m.UsageEvent.input_tokens + m.UsageEvent.output_tokens))
        .filter(m.UsageEvent.org_id == org_id, m.UsageEvent.project_id == project_id,
                m.UsageEvent.tenant_id == tenant_ext,
                m.UsageEvent.occurred_at >= start, m.UsageEvent.occurred_at < end)
        .one()
    )
    requests = row[0] or 0
    tokens = row[1] or 0
    return requests, (tokens / requests) if requests else 0.0


@router.post("/investigate", response_model=schemas.InvestigateResponse)
def investigate(payload: schemas.InvestigateRequest,
                org: m.Organization = Depends(deps.get_demo_org),
                db: Session = Depends(get_db)):
    project = deps.get_demo_project(db, org)
    tenant = (db.query(m.Tenant)
              .filter_by(org_id=org.id, project_id=project.id,
                         external_id=payload.tenant_external_id).first())
    if tenant is None:
        raise HTTPException(status_code=404, detail="tenant not found in demo dataset")

    start, end = _window()
    recent_start = end - timedelta(days=RECENT_DAYS)

    by_model, total = _drivers(db, org.id, project.id, tenant.external_id, start, end, m.UsageEvent.model, "model")
    by_app, _ = _drivers(db, org.id, project.id, tenant.external_id, start, end, m.UsageEvent.application, "app")

    # Volume vs tokens: last 7d vs prior 23d (30-day window).
    req_recent, tpr_recent = _volume_stats(db, org.id, project.id, tenant.external_id, recent_start, end)
    req_prior, tpr_prior = _volume_stats(db, org.id, project.id, tenant.external_id, start, recent_start)
    prior_days = (recent_start - start).days  # 23
    requests_delta = ((req_recent / 7) - (req_prior / prior_days)) / (req_prior / prior_days) * 100 if req_prior else 0.0
    tpr_delta = (tpr_recent - tpr_prior) / tpr_prior * 100 if tpr_prior else 0.0

    # Expensive workflows: (application, model) pairs by cost.
    wf_rows = (
        db.query(
            m.UsageEvent.application, m.UsageEvent.provider, m.UsageEvent.model,
            func.count(m.UsageEvent.id),
            func.sum(m.UsageEvent.cost_calculated_usd),
            func.sum(m.UsageEvent.input_tokens),
            func.sum(m.UsageEvent.output_tokens),
            func.sum(m.UsageEvent.cached_input_tokens),
            func.sum(m.UsageEvent.reasoning_tokens),
        )
        .filter(m.UsageEvent.org_id == org.id, m.UsageEvent.project_id == project.id,
                m.UsageEvent.tenant_id == tenant.external_id,
                m.UsageEvent.occurred_at >= start, m.UsageEvent.occurred_at < end)
        .group_by(m.UsageEvent.application, m.UsageEvent.provider, m.UsageEvent.model)
        .order_by(func.sum(m.UsageEvent.cost_calculated_usd).desc())
        .all()
    )
    workflows, pairs = [], []
    for app_name, provider, model, n, cost, in_tok, out_tok, cached_tok, reas_tok in wf_rows:
        cost = cost or Decimal(0)
        workflows.append(schemas.ExpensiveWorkflow(
            app=app_name or "unknown", model=model, requests=n, cost_usd=cost,
            cost_per_request_usd=(cost / n) if n else Decimal(0)))
        pairs.append(recommend.PairStats(
            application=app_name or "unknown", provider=provider, model=model,
            requests=n, input_tokens=int(in_tok or 0), output_tokens=int(out_tok or 0),
            cached_input_tokens=int(cached_tok or 0), reasoning_tokens=int(reas_tok or 0),
            cost_usd=cost))

    # Recommendation: top model-routing opportunity (shared engine).
    opportunities = recommend.model_routing_opportunity(pairs)
    revenue = tenant.monthly_revenue_usd or Decimal(0)
    margin = revenue - total
    recommendation = None
    if opportunities:
        top = opportunities[0]
        post_margin = margin + top.est_savings_usd_mo
        recommendation = schemas.RecommendationOut(
            action=(f"Routing suitable {top.application} requests from {top.from_model} "
                    f"to {top.to_model} (lower-cost model)"),
            est_savings_usd_mo=top.est_savings_usd_mo,
            confidence=top.confidence,
            post_change_margin_usd=post_margin,
            detail={**top.detail, "application": top.application,
                    "from_model": top.from_model, "to_model": top.to_model,
                    "current_cost_usd_mo": str(top.current_cost_usd_mo)},
        )

    # Top app, and the top model *within* that app (for the narrative).
    top_app = by_app[0] if by_app else None
    top_app_name = top_app["app"] if top_app else "unknown"
    top_app_pct = top_app["pct"] if top_app else 0.0
    app_wfs = [w for w in workflows if w.app == top_app_name]
    top_wf = app_wfs[0] if app_wfs else None
    if top_wf and top_app:
        model_in_app_pct = float(top_wf.cost_usd / top_app["cost_usd"] * 100) if top_app["cost_usd"] else 0.0
    else:
        model_in_app_pct = 0.0
    top_model_in_app = top_wf.model if top_wf else "unknown"

    summary = _summary(
        tenant.name, margin,
        top_app_name=top_app_name, top_app_pct=top_app_pct,
        top_model_in_app=top_model_in_app, model_in_app_pct=model_in_app_pct,
        recommendation=recommendation,
    )
    return schemas.InvestigateResponse(
        tenant_external_id=tenant.external_id,
        tenant_name=tenant.name,
        summary=summary,
        drivers=schemas.Drivers(
            by_model=[schemas.ModelCostDriver(**d) for d in by_model],
            by_app=[schemas.AppCostDriver(**d) for d in by_app],
        ),
        volume_vs_tokens=schemas.VolumeVsTokens(
            requests_delta_pct=round(requests_delta, 1),
            avg_tokens_per_request_delta_pct=round(tpr_delta, 1)),
        expensive_workflows=workflows,
        recommendation=recommendation,
    )


def _usd_whole(x: Decimal) -> str:
    """Whole-dollar prose formatting: -$42, $182."""
    q = f"{abs(x):,.0f}"
    return f"-${q}" if x < 0 else f"${q}"


def _summary(tenant_name: str, margin: Decimal, *, top_app_name: str, top_app_pct: float,
             top_model_in_app: str, model_in_app_pct: float,
             recommendation: schemas.RecommendationOut | None) -> str:
    """Template narrative — numbers only ever come from computed facts."""
    if margin < 0:
        s = (f"{tenant_name} is currently generating approximately "
             f"{_usd_whole(abs(margin))}/month in negative AI margin. ")
    else:
        s = (f"{tenant_name} is currently generating approximately "
             f"{_usd_whole(margin)}/month in positive AI margin. ")
    s += f"{top_app_pct:.0f}% of their AI cost comes from the {top_app_name}. "
    s += (f"{top_model_in_app} represents {model_in_app_pct:.0f}% "
          f"of their {top_app_name} spend. ")
    if recommendation:
        rec_app = recommendation.detail.get("application", top_app_name)
        s += (f"Routing suitable {rec_app} requests to a lower-cost model could "
              f"potentially reduce AI cost by ~{_usd_whole(recommendation.est_savings_usd_mo)}/month. "
              f"Estimated post-change margin: approximately "
              f"{_usd_whole(recommendation.post_change_margin_usd)}/month. "
              f"Confidence: {recommendation.confidence.capitalize()}.")
    else:
        s += "No model-routing opportunity above the cost threshold was found for this tenant."
    return s
