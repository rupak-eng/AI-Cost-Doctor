"""Anthropic organization usage/cost connector.

Docs: specs/04-provider-integration-notes.md §2
(primary: docs.anthropic.com/en/api/usage-cost-api and the Admin API
reference pages for get-messages-usage-report / get-cost-report)

Auth: Admin API key via `x-api-key` + `anthropic-version: 2023-06-01`.
Endpoints used:
- GET /v1/organizations/usage_report/messages (tokens, group_by model [+ extras])
- GET /v1/organizations/cost_report            (USD, 1d buckets)

Caveats honored:
- Token field names in usage results were not fully pinned by the extracted
  reference text → parse defensively, keep the raw result in meta.
- Cost amounts are decimal strings in USD *cents* (per the docs).
- Priority Tier costs are excluded from the cost endpoint; code-execution
  costs appear only there.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.providers.base import BaseProviderClient, paged_get

GROUP_BY_ALLOWLIST = frozenset(
    {"account_id", "api_key_id", "context_window", "inference_geo", "model",
     "service_account_id", "service_tier", "workspace_id"})
# `speed` intentionally excluded: needs the fast-mode-2026-02-01 beta header.


class AnthropicClient(BaseProviderClient):
    provider = "anthropic"
    base_url = "https://api.anthropic.com"

    def _headers(self, api_key: str) -> dict:
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}

    # -- validation ------------------------------------------------------
    def validate(self) -> None:
        """Cheap proof the key is an Admin key: one usage bucket."""
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        self._get("/v1/organizations/usage_report/messages",
                  {"starting_at": (start.isoformat()),
                   "ending_at": now.isoformat(),
                   "bucket_width": "1d", "limit": 1})

    # -- usage (tokens) --------------------------------------------------
    def iter_usage(self, *, starting_at: str, ending_at: str,
                   group_by: list[str]) -> list[tuple[datetime, dict]]:
        buckets = paged_get(
            self, "/v1/organizations/usage_report/messages",
            {"starting_at": starting_at, "ending_at": ending_at,
             "bucket_width": "1d", "group_by": group_by, "limit": 31})
        out: list[tuple[datetime, dict]] = []
        for bucket in buckets:
            start = _parse_ts(bucket.get("starting_at"))
            if start is None:
                continue
            for result in bucket.get("results", []) or []:
                out.append((start, result))
        return out

    # -- costs (USD, org level) ------------------------------------------
    def iter_costs(self, *, starting_at: str, ending_at: str,
                   group_by: list[str]) -> list[tuple[datetime, dict]]:
        buckets = paged_get(
            self, "/v1/organizations/cost_report",
            {"starting_at": starting_at, "ending_at": ending_at,
             "bucket_width": "1d", "group_by": group_by, "limit": 31})
        out: list[tuple[datetime, dict]] = []
        for bucket in buckets:
            start = _parse_ts(bucket.get("starting_at"))
            if start is None:
                continue
            for result in bucket.get("results", []) or []:
                out.append((start, result))
        return out


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    if s[-1:] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _first_int(result: dict, *keys: str) -> int:
    for key in keys:
        value = result.get(key)
        if value is None:
            continue
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if n >= 0:
            return n
    return 0


def parse_usage_result(result: dict) -> dict | None:
    """Normalize one usage result → canonical token counts.

    Returns None when the row has no model (can't attribute it).
    Field names are parsed defensively (see module docstring); the raw
    result is always preserved in meta by the sync layer.
    """
    model = result.get("model")
    if not model:
        return None
    cache_read = _first_int(result, "cache_read_input_tokens", "cached_input_tokens")
    cache_creation = _first_int(result, "cache_creation_input_tokens")
    return {
        "model": model,
        "input_tokens": _first_int(result, "input_tokens", "uncached_input_tokens"),
        "output_tokens": _first_int(result, "output_tokens"),
        # Priced at the catalog's cached-input rate:
        "cached_input_tokens": cache_read,
        # No catalog variant for cache creation → NOT priced (kept in meta,
        # surfaced honestly rather than folded into a wrong bucket):
        "cache_creation_input_tokens": cache_creation,
        "reasoning_tokens": 0,
        "num_model_requests": _first_int(result, "num_requests", "num_model_requests"),
        "api_key_id": result.get("api_key_id"),
        "workspace_id": result.get("workspace_id"),
        "service_tier": result.get("service_tier"),
    }


def parse_cost_result(result: dict) -> dict | None:
    """Normalize one cost result → (group_key, amount_usd).

    Docs: amounts are decimal strings in USD cents. The exact result-object
    shape was not pinned by the extracted reference text, so several
    candidate shapes are tried; the raw result is preserved in meta.
    Returns None when no parseable amount is found.
    """
    candidates: list[object] = []
    amount = result.get("amount")
    if isinstance(amount, dict):
        candidates.append(amount.get("value"))
    candidates.extend([amount, result.get("value"), result.get("cost"),
                       result.get("amount_usd")])
    cents = None
    for cand in candidates:
        if cand is None:
            continue
        try:
            cents = float(str(cand).strip())
            break
        except (TypeError, ValueError):
            continue
    if cents is None:
        return None
    description = result.get("description")
    if isinstance(description, dict):  # parsed description object, if any
        description = description.get("text") or description.get("raw") or str(description)
    return {
        "group_key": (str(description) if description is not None
                      else result.get("workspace_id")),
        "amount_usd": cents / 100.0,  # docs: lowest units (cents) → dollars
        "currency": "usd",
    }
