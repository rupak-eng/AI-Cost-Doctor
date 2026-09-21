"""Tenant investigation — deterministic root-cause fact gathering.

The shared engine behind both the demo investigate endpoint and the
customer project investigate endpoint. Every number aggregates usage
events; narratives are template-generated from computed facts only, with
an optional LLM polish layer (services/narrative.py) that may reword but
never invents numbers.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import models as m
from app.services import narrative, recommend
from app.services.recommend import DISCLAIMER

WINDOW_DAYS = 30
RECENT_DAYS = 7


class TenantNotFoundError(LookupError):
    """Raised when the tenant external_id is unknown for the project."""


def _drivers(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
             tenant_ext: str, start: datetime, end: datetime,
             column, key_name: str):
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


def _window_stats(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                  tenant_ext: str, start: datetime, end: datetime):
    """(requests, total_tokens, total_cost) for the tenant in [start, end)."""
    row = (
        db.query(func.count(m.UsageEvent.id),
                 func.sum(m.UsageEvent.input_tokens + m.UsageEvent.output_tokens),
                 func.sum(m.UsageEvent.cost_calculated_usd))
        .filter(m.UsageEvent.org_id == org_id, m.UsageEvent.project_id == project_id,
                m.UsageEvent.tenant_id == tenant_ext,
                m.UsageEvent.occurred_at >= start, m.UsageEvent.occurred_at < end)
        .one()
    )
    return (row[0] or 0, row[1] or 0, row[2] or Decimal(0))


def _volume_vs_tokens(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                      tenant_ext: str, start: datetime, end: datetime,
                      recent_start: datetime) -> dict:
    """Decompose the cost change (recent 7d vs prior window) into $ effects.

    Laspeyres-style decomposition, all from usage_events aggregates:
      volume_effect_usd         cost change from request-count change alone
                                (prior tokens/request and prior $/token)
      token_intensity_effect_usd  cost change from tokens/request change
                                (at recent $/token)
      mix_effect_usd            residual: model/price-mix and rounding
    """
    req_recent, tok_recent, cost_recent = _window_stats(
        db, org_id, project_id, tenant_ext, recent_start, end)
    req_prior, tok_prior, cost_prior = _window_stats(
        db, org_id, project_id, tenant_ext, start, recent_start)

    prior_days = max((recent_start - start).days, 1)
    requests_delta = ((req_recent / 7) - (req_prior / prior_days)) / (req_prior / prior_days) * 100 if req_prior else 0.0
    tpr_recent = tok_recent / req_recent if req_recent else 0.0
    tpr_prior = tok_prior / req_prior if req_prior else 0.0
    tpr_delta = (tpr_recent - tpr_prior) / tpr_prior * 100 if tpr_prior else 0.0

    volume_effect = token_effect = mix_effect = None
    if req_prior and tok_prior and req_recent:
        # Normalize the prior window to a per-day rate, then scale to 7 days
        # so both windows describe the same length of time. All Decimal —
        # these figures feed dollar attribution shown to customers.
        scale = Decimal(7) / Decimal(prior_days)
        r0 = Decimal(req_prior) * scale
        k0 = Decimal(tok_prior) * scale
        t0 = k0 / r0 if r0 else Decimal(0)
        p0 = (cost_prior * scale / k0) if k0 else Decimal(0)
        p1 = (cost_recent / Decimal(tok_recent)) if tok_recent else Decimal(0)
        volume_effect = ((Decimal(req_recent) - r0) * t0 * p0).quantize(Decimal("0.01"))
        token_effect = ((Decimal(tok_recent) - Decimal(req_recent) * t0) * p1).quantize(Decimal("0.01"))
        mix_effect = (cost_recent - cost_prior * scale
                      - volume_effect - token_effect).quantize(Decimal("0.01"))

    return {
        # Pct deltas are display fields declared as float in the schemas;
        # coerce explicitly: on Postgres, sum() over integer columns comes
        # back as Decimal while SQLite returns int.
        "requests_delta_pct": float(round(requests_delta, 1)),
        "avg_tokens_per_request_delta_pct": float(round(tpr_delta, 1)),
        "window_note": "last 7 days vs prior 23 days",
        "volume_effect_usd": volume_effect,
        "token_intensity_effect_usd": token_effect,
        "mix_effect_usd": mix_effect,
    }


def _usd_whole(x: Decimal) -> str:
    """Whole-dollar prose formatting: -$42, $182."""
    q = f"{abs(x):,.0f}"
    return f"-${q}" if x < 0 else f"${q}"


def _summary(tenant_name: str, margin: Decimal | None, *, top_app_name: str,
             top_app_pct: float, top_model_in_app: str, model_in_app_pct: float,
             recommendation: dict | None) -> str:
    """Template narrative — numbers only ever come from computed facts."""
    if margin is None:
        s = (f"{tenant_name} has no recorded revenue, so AI margin cannot be "
             f"computed yet. ")
    elif margin < 0:
        s = (f"{tenant_name} is currently generating approximately "
             f"{_usd_whole(abs(margin))}/month in negative AI margin. ")
    else:
        s = (f"{tenant_name} is currently generating approximately "
             f"{_usd_whole(margin)}/month in positive AI margin. ")
    s += f"{top_app_pct:.0f}% of their AI cost comes from the {top_app_name}. "
    s += (f"{top_model_in_app} represents {model_in_app_pct:.0f}% "
          f"of their {top_app_name} spend. ")
    if recommendation:
        rec_app = recommendation["detail"].get("application", top_app_name)
        s += (f"Routing suitable {rec_app} requests to a lower-cost model could "
              f"potentially reduce AI cost by ~{_usd_whole(recommendation['est_savings_usd_mo'])}/month. "
              f"Estimated post-change margin: approximately "
              f"{_usd_whole(recommendation['post_change_margin_usd'])}/month. "
              f"Confidence: {str(recommendation['confidence']).capitalize()}. "
              f"{DISCLAIMER}")
    else:
        s += "No model-routing opportunity above the cost threshold was found for this tenant."
    return s


def _anomaly_followups(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                       tenant_ext: str, start: datetime,
                       margin_usd: Decimal | None) -> list[dict]:
    """Pointer recommendations for open cost anomalies on this tenant.

    Pure join over existing deterministic anomaly rows — no new math. The
    estimated value is the anomaly's observed dollar delta.
    """
    rows = (
        db.query(m.CostAnomaly)
        .filter(m.CostAnomaly.org_id == org_id,
                m.CostAnomaly.project_id == project_id,
                m.CostAnomaly.dimension == "tenant",
                m.CostAnomaly.dimension_value == tenant_ext,
                m.CostAnomaly.status == "open",
                m.CostAnomaly.detected_at >= start)
        .order_by(m.CostAnomaly.detected_at.desc())
        .all()
    )
    recs = []
    for a in rows:
        est = a.abs_delta_usd or Decimal(0)
        ev = a.evidence or {}
        a_title = ev.get("title") or a.detector or "Anomaly"
        a_detail = ev.get("detail", "")
        rec = asdict(recommend.Recommendation(
            type="anomaly_followup",
            title=f"Resolve: {a_title}",
            action=f"Investigate the detected {a.detector} anomaly for this customer",
            explanation=(f"{a_detail} Resolving the underlying cause could "
                         f"recover up to ~${est:,.2f}/mo."),
            est_savings_usd_mo=est,
            confidence="low",
            detail={"anomaly_id": str(a.id), "detector": a.detector,
                    "severity": a.severity,
                    "note": "Pointer to an existing deterministic anomaly — "
                            "not a new cost estimate."},
        ))
        rec["post_change_margin_usd"] = (
            (margin_usd + est) if margin_usd is not None else None)
        recs.append(rec)
    return recs


def investigate_tenant(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                       tenant_external_id: str, days: int = 30) -> dict:
    """Deterministic root-cause facts for one tenant over the trailing `days`.

    Returns a dict shaped like the investigate response (minus data_label):
    tenant_external_id, tenant_name, summary, drivers{by_model, by_app},
    volume_vs_tokens (with $ attribution), expensive_workflows,
    recommendation (top routing opportunity, or None),
    recommendations (all generators, sorted by estimated savings),
    disclaimer.

    Raises TenantNotFoundError when the tenant is unknown for the project.
    """
    tenant = (db.query(m.Tenant)
              .filter_by(org_id=org_id, project_id=project_id,
                         external_id=tenant_external_id).first())
    if tenant is None:
        raise TenantNotFoundError(
            f"tenant '{tenant_external_id}' not found for project {project_id}")

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    recent_start = end - timedelta(days=RECENT_DAYS)

    by_model, total = _drivers(db, org_id, project_id, tenant.external_id,
                               start, end, m.UsageEvent.model, "model")
    by_app, _ = _drivers(db, org_id, project_id, tenant.external_id,
                         start, end, m.UsageEvent.application, "app")

    volume_vs_tokens = _volume_vs_tokens(db, org_id, project_id, tenant.external_id,
                                         start, end, recent_start)

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
        .filter(m.UsageEvent.org_id == org_id, m.UsageEvent.project_id == project_id,
                m.UsageEvent.tenant_id == tenant.external_id,
                m.UsageEvent.occurred_at >= start, m.UsageEvent.occurred_at < end)
        .group_by(m.UsageEvent.application, m.UsageEvent.provider, m.UsageEvent.model)
        .order_by(func.sum(m.UsageEvent.cost_calculated_usd).desc())
        .all()
    )
    workflows, pairs = [], []
    for app_name, provider, model, n, cost, in_tok, out_tok, cached_tok, reas_tok in wf_rows:
        cost = cost or Decimal(0)
        workflows.append({
            "app": app_name or "unknown", "model": model, "requests": n,
            "cost_usd": cost, "cost_per_request_usd": (cost / n) if n else Decimal(0)})
        pairs.append(recommend.PairStats(
            application=app_name or "unknown", provider=provider, model=model,
            requests=n, input_tokens=int(in_tok or 0), output_tokens=int(out_tok or 0),
            cached_input_tokens=int(cached_tok or 0), reasoning_tokens=int(reas_tok or 0),
            cost_usd=cost))

    # Margin (needed for post-change margin on recommendations).
    revenue = tenant.monthly_revenue_usd
    margin = (revenue - total) if revenue is not None and revenue != 0 else None

    # Recommendations: all deterministic generators, sorted by savings.
    routing = recommend.model_routing_opportunity(pairs)[:3]
    caching = recommend.prompt_caching_opportunity(pairs)[:2]
    rec_objs: list[recommend.Recommendation] = (
        [recommend.routing_recommendation(o) for o in routing]
        + [recommend.caching_recommendation(o) for o in caching]
    )
    rec_objs.sort(key=lambda r: r.est_savings_usd_mo, reverse=True)
    recommendations = []
    for r in rec_objs:
        d = asdict(r)
        d["post_change_margin_usd"] = (
            (margin + r.est_savings_usd_mo) if margin is not None else None)
        recommendations.append(d)
    recommendations += _anomaly_followups(db, org_id, project_id,
                                          tenant.external_id, start, margin)

    # Legacy single recommendation: top routing opportunity (unchanged shape).
    recommendation = None
    if routing:
        top = routing[0]
        post_margin = (margin + top.est_savings_usd_mo) if margin is not None else None
        recommendation = {
            "action": (f"Routing suitable {top.application} requests from {top.from_model} "
                       f"to {top.to_model} (lower-cost model)"),
            "est_savings_usd_mo": top.est_savings_usd_mo,
            "confidence": top.confidence,
            "post_change_margin_usd": post_margin,
            "detail": {**top.detail, "application": top.application,
                       "from_model": top.from_model, "to_model": top.to_model,
                       "current_cost_usd_mo": str(top.current_cost_usd_mo)},
            "disclaimer": DISCLAIMER,
        }

    # Top app, and the top model *within* that app (for the narrative).
    top_app = by_app[0] if by_app else None
    top_app_name = top_app["app"] if top_app else "unknown"
    top_app_pct = top_app["pct"] if top_app else 0.0
    app_wfs = [w for w in workflows if w["app"] == top_app_name]
    top_wf = app_wfs[0] if app_wfs else None
    if top_wf and top_app:
        model_in_app_pct = float(top_wf["cost_usd"] / top_app["cost_usd"] * 100) if top_app["cost_usd"] else 0.0
    else:
        model_in_app_pct = 0.0
    top_model_in_app = top_wf["model"] if top_wf else "unknown"

    summary = _summary(
        tenant.name, margin,
        top_app_name=top_app_name, top_app_pct=top_app_pct,
        top_model_in_app=top_model_in_app, model_in_app_pct=model_in_app_pct,
        recommendation=recommendation,
    )
    return {
        "tenant_external_id": tenant.external_id,
        "tenant_name": tenant.name,
        "summary": summary,
        "margin_usd": margin,
        "drivers": {"by_model": by_model, "by_app": by_app},
        "volume_vs_tokens": volume_vs_tokens,
        "expensive_workflows": workflows,
        "recommendation": recommendation,
        "recommendations": recommendations,
        "disclaimer": DISCLAIMER,
    }


def explain_investigation(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                          tenant_external_id: str, days: int = 30) -> dict:
    """Narrative explanation of the investigation facts.

    Deterministic facts in, prose out. Template by default; optional LLM
    rewording when configured (never invents numbers). Raises
    TenantNotFoundError for unknown tenants.
    """
    facts = investigate_tenant(db, org_id, project_id, tenant_external_id, days=days)
    narrative_text, source = narrative.explain(facts)
    return {"narrative": narrative_text, "narrative_source": source}
