"""Sync orchestration: provider API → usage_events + provider_cost_reports.

Idempotency: each sync deletes previously-synced rows for (org, project,
source) inside the requested window, then re-inserts. Re-running a sync is
always safe.

Cost labeling (never mixed silently):
- usage_events from providers carry cost_calculated_usd (deterministic
  catalog math via costing.price_event) and cost_reported_usd=NULL, because
  neither provider reports dollars at per-model granularity.
- provider_cost_reports carry the provider's own USD buckets (reported),
  keyed by line_item/description verbatim — org-level reconciliation only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app import models as m
from app.services import costing
from app.services.providers import anthropic as anthropic_mod
from app.services.providers import openai as openai_mod
from app.services.providers.base import ProviderError
from app.services.secrets import decrypt_secret

MAX_DAYS_BACK = 90
BUCKET_WIDTH = "1d"


@dataclass
class SyncSummary:
    provider: str
    project_id: str
    window_start: str
    window_end: str
    usage_buckets: int = 0
    events_written: int = 0
    cost_reports_written: int = 0
    unpriced_models: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _window(days_back: int) -> tuple[datetime, datetime]:
    if not 1 <= days_back <= MAX_DAYS_BACK:
        raise ProviderError("sync", f"days_back must be 1–{MAX_DAYS_BACK}")
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=days_back), end


def _resolve_group_by(provider: str, extra: tuple[str, ...]) -> list[str]:
    allow = (openai_mod.GROUP_BY_ALLOWLIST if provider == "openai"
             else anthropic_mod.GROUP_BY_ALLOWLIST)
    unknown = [g for g in extra if g not in allow]
    if unknown:
        raise ProviderError(
            provider,
            f"unsupported group_by dimensions for {provider}: {unknown}; "
            f"allowed: {sorted(allow)}")
    return ["model"] + [g for g in extra if g != "model"]


def _delete_window(db: Session, *, org_id, project_id, source: str,
                   start: datetime, end: datetime) -> None:
    db.query(m.UsageEvent).filter(
        m.UsageEvent.org_id == org_id,
        m.UsageEvent.project_id == project_id,
        m.UsageEvent.source == source,
        m.UsageEvent.occurred_at >= start,
        m.UsageEvent.occurred_at < end,
    ).delete(synchronize_session=False)
    db.query(m.ProviderCostReport).filter(
        m.ProviderCostReport.org_id == org_id,
        m.ProviderCostReport.project_id == project_id,
        m.ProviderCostReport.provider == source,
        m.ProviderCostReport.bucket_start >= start,
        m.ProviderCostReport.bucket_start < end,
    ).delete(synchronize_session=False)


def _insert_usage_events(db: Session, *, org_id, project_id, source: str,
                         rows: list[tuple[datetime, dict]],
                         parse, catalog) -> tuple[int, set[str]]:
    """Insert one usage_event per (bucket, model). Returns (count, unpriced_models)."""
    unpriced: set[str] = set()
    events: list[m.UsageEvent] = []
    for occurred_at, raw in rows:
        parsed = parse(raw)
        if parsed is None:
            continue
        model = parsed["model"]
        calculated = costing.price_event(
            catalog, provider=source, model=model, at=occurred_at,
            input_tokens=parsed["input_tokens"],
            output_tokens=parsed["output_tokens"],
            cached_input_tokens=parsed.get("cached_input_tokens", 0),
            reasoning_tokens=parsed.get("reasoning_tokens", 0))
        if calculated is None:
            unpriced.add(model)
        meta = {
            "bucket_width": BUCKET_WIDTH,
            "num_model_requests": parsed.get("num_model_requests", 0),
            "provider_raw": raw,
        }
        for dim in ("api_key_id", "user_id", "project_id", "workspace_id",
                    "service_tier", "batch"):
            if parsed.get(dim) is not None:
                meta[dim] = parsed[dim]
        # Anthropic cache-creation tokens have no catalog price variant:
        # surfaced in meta, never silently folded into another bucket.
        if parsed.get("cache_creation_input_tokens"):
            meta["cache_creation_input_tokens"] = parsed["cache_creation_input_tokens"]
        events.append(m.UsageEvent(
            org_id=org_id, project_id=project_id, source=source,
            provider=source, model=model,
            application=None, tenant_id=None,  # not offered by provider APIs
            occurred_at=occurred_at,
            input_tokens=parsed["input_tokens"],
            output_tokens=parsed["output_tokens"],
            cached_input_tokens=parsed.get("cached_input_tokens", 0),
            reasoning_tokens=parsed.get("reasoning_tokens", 0),
            cost_reported_usd=None,
            cost_calculated_usd=calculated,
            meta=meta,
        ))
    db.add_all(events)
    return len(events), unpriced


def _insert_cost_reports(db: Session, *, org_id, project_id, provider: str,
                         rows: list[tuple[datetime, dict]], parse) -> int:
    reports: list[m.ProviderCostReport] = []
    for bucket_start, raw in rows:
        parsed = parse(raw)
        if parsed is None:
            continue
        reports.append(m.ProviderCostReport(
            org_id=org_id, project_id=project_id, provider=provider,
            bucket_start=bucket_start, bucket_width=BUCKET_WIDTH,
            group_key=parsed["group_key"],
            amount_usd=Decimal(str(parsed["amount_usd"])),
            currency=parsed["currency"],
            meta={"provider_raw": raw},
        ))
    db.add_all(reports)
    return len(reports)


def sync_provider(db: Session, *, org_id, project_id,
                  credential: m.ProviderCredential,
                  days_back: int = 30,
                  extra_group_by: tuple[str, ...] = (),
                  transport: httpx.BaseTransport | None = None) -> SyncSummary:
    """Pull usage + costs for one credential and persist them.

    `transport` is for tests (httpx.MockTransport). Raises ProviderError on
    any provider failure; the credential row is marked error in that case.
    """
    provider = credential.provider
    if provider not in ("openai", "anthropic"):
        raise ProviderError(provider, f"unsupported provider: {provider}")

    start, end = _window(days_back)
    group_by = _resolve_group_by(provider, extra_group_by)
    catalog = costing.load_catalog_from_db(db)
    summary = SyncSummary(
        provider=provider, project_id=str(project_id),
        window_start=start.isoformat(), window_end=end.isoformat())

    try:
        api_key = decrypt_secret(credential.encrypted_key, org_id=str(org_id))
    except Exception as exc:
        raise ProviderError(provider, f"could not decrypt stored key: {exc}") from exc

    client = None
    try:
        if provider == "openai":
            client = openai_mod.OpenAIClient(api_key, transport=transport)
            usage_rows = client.iter_usage(
                start_ts=int(start.timestamp()), end_ts=int(end.timestamp()),
                group_by=group_by)
            cost_rows = client.iter_costs(
                start_ts=int(start.timestamp()), end_ts=int(end.timestamp()),
                group_by=["project_id", "line_item"])
            parse_usage, parse_cost = (openai_mod.parse_usage_result,
                                       openai_mod.parse_cost_result)
        else:
            client = anthropic_mod.AnthropicClient(api_key, transport=transport)
            usage_rows = client.iter_usage(
                starting_at=start.isoformat(), ending_at=end.isoformat(),
                group_by=group_by)
            cost_rows = client.iter_costs(
                starting_at=start.isoformat(), ending_at=end.isoformat(),
                group_by=["description"])
            parse_usage, parse_cost = (anthropic_mod.parse_usage_result,
                                       anthropic_mod.parse_cost_result)

        summary.usage_buckets = len(usage_rows)
        _delete_window(db, org_id=org_id, project_id=project_id,
                       source=provider, start=start, end=end)
        written, unpriced = _insert_usage_events(
            db, org_id=org_id, project_id=project_id, source=provider,
            rows=usage_rows, parse=parse_usage, catalog=catalog)
        summary.events_written = written
        summary.unpriced_models = sorted(unpriced)
        summary.cost_reports_written = _insert_cost_reports(
            db, org_id=org_id, project_id=project_id, provider=provider,
            rows=cost_rows, parse=parse_cost)
        if unpriced:
            summary.notes.append(
                f"{len(unpriced)} model(s) have no catalog price and were "
                f"stored unpriced (cost_calculated_usd=NULL): "
                f"{', '.join(sorted(unpriced))}")
        if provider == "anthropic":
            summary.notes.append(
                "Anthropic cache-creation tokens are reported in "
                "meta.cache_creation_input_tokens and are not priced "
                "(no catalog variant); Priority Tier costs are excluded "
                "from the provider cost report by Anthropic.")

        credential.status = "active"
        credential.last_sync_at = datetime.now(timezone.utc)
        db.add(credential)
        db.commit()
        return summary
    except ProviderError:
        credential.status = "error"
        db.add(credential)
        db.commit()
        raise
    finally:
        if client is not None:
            client.close()
