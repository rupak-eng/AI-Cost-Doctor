"""Deterministic anomaly detection over usage events.

Three explainable detectors — no ML, no black boxes:

  spend_spike             tenant (or project-wide) daily spend vs the
                          trailing-14-day median. Fires when observed >
                          2.5x the median AND the absolute delta exceeds
                          $25 (keeps tiny spenders from paging you).
  new_expensive_model     a model whose (input + output) rate is above the
                          project's median model rate shows up in the last
                          3 days for a tenant that never used it before.
                          Fires when the projected monthly run-rate >= $50.
  margin_killer_emergence a tenant's P&L status crosses from healthy/at_risk
                          to margin_killer between consecutive 30-day
                          windows (uses the shared P&L engine).

Every input figure is an aggregation of usage_events.cost_calculated_usd —
the deterministic engine's output. Provider-reported numbers are never
inputs. Date bucketing is done in Python (not SQL date_trunc) so results are
identical on PostgreSQL and SQLite.

Detection is refresh-on-read: listing anomalies runs the detectors and
upserts rows keyed by a deterministic fingerprint, so repeated reads never
duplicate. A fingerprint is only re-inserted once no non-terminal
(open/acknowledged/investigated) row carries it.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app import models as m
from app.services import pnl as pnl_service
from app.services.costing import PriceNotFoundError, load_catalog_from_db, price_for

# Detector ids (persisted on cost_anomalies.detector).
SPEND_SPIKE = "spend_spike"
NEW_EXPENSIVE_MODEL = "new_expensive_model"
MARGIN_KILLER_EMERGENCE = "margin_killer_emergence"

# -- spend_spike tuning -------------------------------------------------------
SPIKE_BASELINE_DAYS = 14
# A series needs this many baseline days with any usage before a spike can
# fire — avoids flagging brand-new tenants on their second day.
SPIKE_MIN_BASELINE_ACTIVE_DAYS = 7
SPIKE_RATIO = Decimal("2.5")
SPIKE_MIN_DELTA_USD = Decimal("25")
SPIKE_CRITICAL_RATIO = Decimal("5")
SPIKE_CRITICAL_DELTA_USD = Decimal("500")

# -- new_expensive_model tuning ------------------------------------------------
NEW_MODEL_RECENT_DAYS = 3
NEW_MODEL_HISTORY_DAYS = 90
NEW_MODEL_MIN_RUN_RATE_USD_MO = Decimal("50")
NEW_MODEL_CRITICAL_RUN_RATE_USD_MO = Decimal("1000")

# -- margin_killer_emergence tuning --------------------------------------------
MARGIN_WINDOW_DAYS = 30

SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
# Rows in one of these states block re-insertion of the same fingerprint.
NON_TERMINAL_STATUSES = ("open", "acknowledged", "investigated")
UNATTRIBUTED_LABEL = "Unattributed usage"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _usd(d: Decimal | None) -> str:
    if d is None:
        return "n/a"
    return f"${d.quantize(Decimal('0.01'))}"


def _tenant_names(db: Session, org_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, str]:
    return {
        t.external_id: t.name
        for t in db.query(m.Tenant).filter_by(org_id=org_id, project_id=project_id).all()
    }


def _label(dimension: str, dimension_value: str | None,
           tenant_names: dict[str, str]) -> str:
    if dimension == "overall":
        return "the project"
    if dimension_value is None:
        return UNATTRIBUTED_LABEL
    return tenant_names.get(dimension_value, dimension_value)


# ---------------------------------------------------------------------------
# Detector 1: spend spike
# ---------------------------------------------------------------------------

def _detect_spend_spikes(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                         now: datetime, tenant_names: dict[str, str]) -> list[dict]:
    start = now - timedelta(days=SPIKE_BASELINE_DAYS + 1)
    rows = (
        db.query(
            m.UsageEvent.tenant_id,
            m.UsageEvent.occurred_at,
            m.UsageEvent.cost_calculated_usd,
            m.UsageEvent.provider,
            m.UsageEvent.model,
            m.UsageEvent.application,
        )
        .filter(
            m.UsageEvent.org_id == org_id,
            m.UsageEvent.project_id == project_id,
            m.UsageEvent.occurred_at >= start,
            m.UsageEvent.occurred_at < now,
        )
        .all()
    )
    # Series key: ("tenant", external_id) plus ("overall", None).
    series: dict[tuple[str, str | None], list] = {}
    for r in rows:
        series.setdefault(("tenant", r[0]), []).append(r)
        series.setdefault(("overall", None), []).append(r)

    observed_day: date = now.date()
    baseline_days = [observed_day - timedelta(days=i)
                     for i in range(1, SPIKE_BASELINE_DAYS + 1)]
    findings: list[dict] = []
    for (dimension, dim_value), events in sorted(
            series.items(), key=lambda kv: (kv[0][0], kv[0][1] or "")):
        daily: dict[date, Decimal] = {}
        for _, occurred_at, cost, _, _, _ in events:
            d = occurred_at.date()
            daily[d] = daily.get(d, Decimal(0)) + (cost or Decimal(0))
        active_days = sum(1 for d in baseline_days if d in daily)
        if active_days < SPIKE_MIN_BASELINE_ACTIVE_DAYS:
            continue
        observed = daily.get(observed_day, Decimal(0))
        baseline_vals = [daily.get(d, Decimal(0)) for d in baseline_days]
        baseline = _median(baseline_vals)
        delta = observed - baseline
        if baseline > 0:
            ratio = observed / baseline
            change_pct = (delta / baseline * 100).quantize(Decimal("0.0001"))
            fires = observed > SPIKE_RATIO * baseline and delta > SPIKE_MIN_DELTA_USD
            ratio_display = f"{ratio.quantize(Decimal('0.1'))}x"
        else:
            ratio = None
            change_pct = None
            ratio_display = "n/a (no baseline spend)"
            fires = observed > 0 and delta > SPIKE_MIN_DELTA_USD
        if not fires:
            continue

        # Driver: costliest model and application on the spike day.
        day_events = [e for e in events if e[1].date() == observed_day]
        by_model: dict[str, Decimal] = {}
        by_app: dict[str, Decimal] = {}
        for _, _, cost, provider, model, application in day_events:
            c = cost or Decimal(0)
            by_model[f"{provider}/{model}"] = by_model.get(f"{provider}/{model}", Decimal(0)) + c
            app_label = application or "Unspecified"
            by_app[app_label] = by_app.get(app_label, Decimal(0)) + c
        top_model = max(by_model, key=by_model.get) if by_model else None
        top_app = max(by_app, key=by_app.get) if by_app else None

        severity = (
            "critical"
            if (ratio is not None and ratio >= SPIKE_CRITICAL_RATIO)
            or delta >= SPIKE_CRITICAL_DELTA_USD
            else "warning"
        )
        label = _label(dimension, dim_value, tenant_names)
        fingerprint = (f"{SPEND_SPIKE}:{dimension}:{dim_value or '-'}"
                       f":{observed_day.isoformat()}")
        title = f"Spend spike: {label}"
        detail = (
            f"{label.capitalize() if dimension == 'overall' else label} spent "
            f"{_usd(observed)} on {observed_day.isoformat()}, vs a "
            f"{SPIKE_BASELINE_DAYS}-day median of {_usd(baseline)} "
            f"(+{_usd(delta)}, {ratio_display})."
        )
        if top_model:
            detail += f" Top driver: {top_model}"
            detail += f" via {top_app}." if top_app else "."
        findings.append({
            "detector": SPEND_SPIKE,
            "dimension": dimension,
            "dimension_value": dim_value,
            "severity": severity,
            "baseline_usd": baseline,
            "observed_usd": observed,
            "change_pct": change_pct,
            "abs_delta_usd": delta,
            "fingerprint": fingerprint,
            "evidence": {
                "detector": SPEND_SPIKE,
                "fingerprint": fingerprint,
                "title": title,
                "detail": detail,
                "baseline_days": SPIKE_BASELINE_DAYS,
                "baseline_median_usd": str(baseline),
                "observed_day": observed_day.isoformat(),
                "observed_usd": str(observed),
                "delta_usd": str(delta),
                "ratio": str(ratio) if ratio is not None else None,
                "top_model": top_model,
                "top_application": top_app,
            },
        })
    return findings


# ---------------------------------------------------------------------------
# Detector 2: new expensive model adoption
# ---------------------------------------------------------------------------

def _detect_new_expensive_models(
        db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
        now: datetime, tenant_names: dict[str, str]) -> list[dict]:
    recent_start = now - timedelta(days=NEW_MODEL_RECENT_DAYS)
    history_start = now - timedelta(days=NEW_MODEL_HISTORY_DAYS)
    rows = (
        db.query(
            m.UsageEvent.tenant_id,
            m.UsageEvent.occurred_at,
            m.UsageEvent.cost_calculated_usd,
            m.UsageEvent.provider,
            m.UsageEvent.model,
        )
        .filter(
            m.UsageEvent.org_id == org_id,
            m.UsageEvent.project_id == project_id,
            m.UsageEvent.occurred_at >= history_start,
            m.UsageEvent.occurred_at < now,
        )
        .all()
    )
    if not rows:
        return []

    catalog = load_catalog_from_db(db)
    today = now.date()
    # NOTE: occurred_at comes back naive on SQLite but aware on Postgres, so
    # all comparisons below use .date() — never naive-vs-aware datetimes.
    recent_day = (now - timedelta(days=NEW_MODEL_RECENT_DAYS)).date()
    # The "project's normal" rates come from the history window only — the
    # newly adopted model must not lift the median it is judged against.
    history_day = (now - timedelta(days=NEW_MODEL_HISTORY_DAYS)).date()
    # (tenant_id, day, cost, provider, model)
    events = [(r[0], r[1].date(), r[2] or Decimal(0), r[3], r[4]) for r in rows]
    # Distinct models the project used before the recent window, priced at
    # today's catalog rates. Models with no current price are skipped — we
    # never guess a price to judge expensiveness.
    project_models = {(e[3], e[4]) for e in events
                      if history_day <= e[1] < recent_day}
    rates: dict[tuple[str, str], Decimal] = {}
    for provider, model in project_models:
        try:
            price = price_for(catalog, provider=provider, model=model, at=today)
        except PriceNotFoundError:
            continue
        rates[(provider, model)] = price.input_usd_per_1m + price.output_usd_per_1m
    if not rates:
        return []
    median_rate = _median(list(rates.values()))

    by_tenant: dict[str | None, list] = {}
    for e in events:
        by_tenant.setdefault(e[0], []).append(e)

    findings: list[dict] = []
    for tenant_id, tenant_events in sorted(by_tenant.items(), key=lambda kv: kv[0] or ""):
        recent_models = {(e[3], e[4]) for e in tenant_events if e[1] >= recent_day}
        older_models = {(e[3], e[4]) for e in tenant_events if e[1] < recent_day}
        for provider, model in sorted(recent_models - older_models):
            # Price the candidate directly from the catalog: it is new, so
            # by definition it is absent from the history-based rates map.
            # No current price → skip; we never guess a price.
            try:
                candidate = price_for(catalog, provider=provider, model=model, at=today)
            except PriceNotFoundError:
                continue
            rate = candidate.input_usd_per_1m + candidate.output_usd_per_1m
            if rate <= median_rate:
                continue
            recent_events = [e for e in tenant_events
                             if (e[3], e[4]) == (provider, model) and e[1] >= recent_day]
            cost_3d = sum((e[2] for e in recent_events), Decimal(0))
            requests = len(recent_events)
            run_rate = cost_3d / NEW_MODEL_RECENT_DAYS * 30
            if run_rate < NEW_MODEL_MIN_RUN_RATE_USD_MO:
                continue
            severity = ("critical"
                        if run_rate >= NEW_MODEL_CRITICAL_RUN_RATE_USD_MO
                        else "warning")
            label = _label("tenant", tenant_id, tenant_names)
            fingerprint = f"{NEW_EXPENSIVE_MODEL}:{tenant_id or '-'}:{provider}/{model}"
            title = f"New expensive model: {provider}/{model}"
            detail = (
                f"{label} started using {provider}/{model} in the last "
                f"{NEW_MODEL_RECENT_DAYS} days — its rate "
                f"(${rate}/1M tokens in+out) is above this project's median "
                f"model rate (${median_rate}/1M). {requests} requests cost "
                f"{_usd(cost_3d)} over {NEW_MODEL_RECENT_DAYS} days, a "
                f"projected run-rate of {_usd(run_rate)}/mo."
            )
            findings.append({
                "detector": NEW_EXPENSIVE_MODEL,
                "dimension": "tenant",
                "dimension_value": tenant_id,
                "severity": severity,
                "baseline_usd": Decimal(0),
                "observed_usd": cost_3d,
                "change_pct": None,
                "abs_delta_usd": cost_3d,
                "fingerprint": fingerprint,
                "evidence": {
                    "detector": NEW_EXPENSIVE_MODEL,
                    "fingerprint": fingerprint,
                    "title": title,
                    "detail": detail,
                    "provider": provider,
                    "model": model,
                    "model_rate_sum_per_1m_usd": str(rate),
                    "project_median_rate_sum_per_1m_usd": str(median_rate),
                    "recent_days": NEW_MODEL_RECENT_DAYS,
                    "recent_cost_usd": str(cost_3d),
                    "recent_requests": requests,
                    "projected_monthly_run_rate_usd": str(run_rate),
                },
            })
    return findings


# ---------------------------------------------------------------------------
# Detector 3: margin-killer emergence
# ---------------------------------------------------------------------------

def _detect_margin_killer_emergence(
        db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
        now: datetime, tenant_names: dict[str, str]) -> list[dict]:
    cur_end = now
    cur_start = now - timedelta(days=MARGIN_WINDOW_DAYS)
    prev_end = cur_start
    prev_start = prev_end - timedelta(days=MARGIN_WINDOW_DAYS)
    current = {r["tenant_external_id"]: r for r in pnl_service.compute_pnl_for_window(
        db, org_id, project_id, cur_start, cur_end)}
    previous = {r["tenant_external_id"]: r for r in pnl_service.compute_pnl_for_window(
        db, org_id, project_id, prev_start, prev_end)}

    findings: list[dict] = []
    for ext_id in sorted(current):
        cur, prev = current[ext_id], previous.get(ext_id)
        if prev is None:
            continue
        if prev["status"] not in ("healthy", "at_risk"):
            continue
        if cur["status"] != "margin_killer":
            continue
        label = tenant_names.get(ext_id, ext_id)
        month = cur_start.date().isoformat()[:7]
        fingerprint = f"{MARGIN_KILLER_EMERGENCE}:{ext_id}:{month}"
        title = f"Margin killer: {label}"
        detail = (
            f"{label} crossed into margin_killer (was {prev['status']}). "
            f"Revenue {_usd(cur['revenue_usd'])}/mo vs AI cost "
            f"{_usd(prev['ai_cost_usd'])} (prior 30d) → {_usd(cur['ai_cost_usd'])} "
            f"(last 30d); margin {_usd(cur['margin_usd'])}."
        )
        delta = (cur["margin_usd"] - prev["margin_usd"]
                 if cur["margin_usd"] is not None and prev["margin_usd"] is not None
                 else None)
        findings.append({
            "detector": MARGIN_KILLER_EMERGENCE,
            "dimension": "tenant",
            "dimension_value": ext_id,
            "severity": "critical",
            "baseline_usd": prev["margin_usd"],
            "observed_usd": cur["margin_usd"],
            "change_pct": None,
            "abs_delta_usd": delta,
            "fingerprint": fingerprint,
            "evidence": {
                "detector": MARGIN_KILLER_EMERGENCE,
                "fingerprint": fingerprint,
                "title": title,
                "detail": detail,
                "previous_status": prev["status"],
                "current_status": cur["status"],
                "revenue_usd": str(cur["revenue_usd"]) if cur["revenue_usd"] is not None else None,
                "ai_cost_previous_usd": str(prev["ai_cost_usd"]),
                "ai_cost_current_usd": str(cur["ai_cost_usd"]),
                "margin_previous_usd": (str(prev["margin_usd"])
                                        if prev["margin_usd"] is not None else None),
                "margin_current_usd": (str(cur["margin_usd"])
                                       if cur["margin_usd"] is not None else None),
            },
        })
    return findings


# ---------------------------------------------------------------------------
# Persistence + listing (refresh-on-read)
# ---------------------------------------------------------------------------

def _persist_finding(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                     finding: dict) -> m.CostAnomaly | None:
    """Insert unless a non-terminal row already carries the fingerprint."""
    existing = (
        db.query(m.CostAnomaly)
        .filter(
            m.CostAnomaly.project_id == project_id,
            m.CostAnomaly.fingerprint == finding["fingerprint"],
            m.CostAnomaly.status.in_(NON_TERMINAL_STATUSES),
        )
        .first()
    )
    if existing is not None:
        return None
    row = m.CostAnomaly(
        id=uuid.uuid4(),
        org_id=org_id,
        project_id=project_id,
        detected_at=_utcnow(),
        detector=finding["detector"],
        fingerprint=finding["fingerprint"],
        dimension=finding["dimension"],
        dimension_value=finding["dimension_value"],
        metric="cost_usd",
        baseline_usd=finding["baseline_usd"],
        observed_usd=finding["observed_usd"],
        change_pct=finding["change_pct"],
        abs_delta_usd=finding["abs_delta_usd"],
        severity=finding["severity"],
        status="open",
        evidence=finding["evidence"],
    )
    db.add(row)
    db.flush()
    return row


def detect_anomalies(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                     now: datetime | None = None) -> list[m.CostAnomaly]:
    """Run every detector and persist new findings. Returns newly created rows.

    Idempotent: findings whose fingerprint already has a non-terminal row
    are skipped.
    """
    now = now or _utcnow()
    tenant_names = _tenant_names(db, org_id, project_id)
    findings = []
    findings += _detect_spend_spikes(db, org_id, project_id, now, tenant_names)
    findings += _detect_new_expensive_models(db, org_id, project_id, now, tenant_names)
    findings += _detect_margin_killer_emergence(db, org_id, project_id, now, tenant_names)
    created = []
    for finding in findings:
        row = _persist_finding(db, org_id, project_id, finding)
        if row is not None:
            created.append(row)
    return created


def anomaly_to_dict(row: m.CostAnomaly, tenant_names: dict[str, str]) -> dict:
    evidence = row.evidence or {}
    return {
        "id": row.id,
        "detector": row.detector,
        "dimension": row.dimension,
        "dimension_value": row.dimension_value,
        "tenant_name": (tenant_names.get(row.dimension_value)
                        if row.dimension == "tenant" and row.dimension_value else None),
        "severity": row.severity,
        "status": row.status,
        "detected_at": row.detected_at,
        "baseline_usd": row.baseline_usd,
        "observed_usd": row.observed_usd,
        "change_pct": row.change_pct,
        "abs_delta_usd": row.abs_delta_usd,
        "title": evidence.get("title", row.detector or "Anomaly"),
        "detail": evidence.get("detail", ""),
        "evidence": evidence,
        "investigate_tenant_external_id": (
            row.dimension_value if row.dimension == "tenant" else None),
    }


def list_anomalies(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                   days: int = 30, now: datetime | None = None) -> dict:
    """Refresh-on-read: run detectors, then list anomalies from the trailing
    `days`, severity-ordered (critical → warning → info), newest first.

    Returns {"days", "anomalies", "unread_count"} where unread_count counts
    status == "open" rows in the window (for the UI badge).
    """
    now = now or _utcnow()
    detect_anomalies(db, org_id, project_id, now=now)
    since = now - timedelta(days=days)
    rows = (
        db.query(m.CostAnomaly)
        .filter(
            m.CostAnomaly.org_id == org_id,
            m.CostAnomaly.project_id == project_id,
            m.CostAnomaly.detected_at >= since,
        )
        .all()
    )
    tenant_names = _tenant_names(db, org_id, project_id)
    items = [anomaly_to_dict(r, tenant_names) for r in rows]
    items.sort(key=lambda a: (
        SEVERITY_RANK.get(a["severity"], 99),
        # detected_at may be naive (SQLite) or aware (Postgres) — never mixed
        # within one backend, so direct comparison is safe here.
        -(a["detected_at"].timestamp() if a["detected_at"] else 0),
        str(a["id"]),
    ))
    unread_count = sum(1 for a in items if a["status"] == "open")
    return {"days": days, "anomalies": items, "unread_count": unread_count}


def acknowledge_anomaly(db: Session, org_id: uuid.UUID, project_id: uuid.UUID,
                        anomaly_id: uuid.UUID) -> m.CostAnomaly | None:
    """Mark an anomaly acknowledged. Returns the row, or None when the id
    doesn't belong to this org/project (→ 404, never leaks existence)."""
    row = (
        db.query(m.CostAnomaly)
        .filter(
            m.CostAnomaly.id == anomaly_id,
            m.CostAnomaly.org_id == org_id,
            m.CostAnomaly.project_id == project_id,
        )
        .first()
    )
    if row is None:
        return None
    row.status = "acknowledged"
    db.flush()
    return row
