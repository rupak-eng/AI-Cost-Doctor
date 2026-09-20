"""OpenAI organization usage/cost connector.

Docs: specs/04-provider-integration-notes.md §1
(primary: platform.openai.com/docs/api-reference/usage,
 cookbook.openai.com/examples/completions_usage_api)

Auth: Admin API key, `Authorization: Bearer <key>`.
Endpoints used:
- GET /v1/organization/usage/completions (tokens, group_by model [+ extras])
- GET /v1/organization/costs            (USD, bucket_width=1d, group_by line_item)
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.services.providers.base import BaseProviderClient, paged_get

GROUP_BY_ALLOWLIST = frozenset(
    {"model", "project_id", "user_id", "api_key_id", "batch", "service_tier"})


class OpenAIClient(BaseProviderClient):
    provider = "openai"
    base_url = "https://api.openai.com"

    def _headers(self, api_key: str) -> dict:
        return {"Authorization": f"Bearer {api_key}"}

    # -- validation ------------------------------------------------------
    def validate(self) -> None:
        """Cheap proof the key is an Admin key: one 1-day cost bucket."""
        now = int(datetime.now(timezone.utc).timestamp())
        self._get("/v1/organization/costs",
                  {"start_time": now - 7 * 86400, "limit": 1})

    # -- usage (tokens) --------------------------------------------------
    def iter_usage(self, *, start_ts: int, end_ts: int,
                   group_by: list[str]) -> list[tuple[datetime, dict]]:
        """Return [(bucket_start_utc, result), ...] for completions usage."""
        buckets = paged_get(
            self, "/v1/organization/usage/completions",
            {"start_time": start_ts, "end_time": end_ts,
             "bucket_width": "1d", "group_by": group_by, "limit": 180})
        out: list[tuple[datetime, dict]] = []
        for bucket in buckets:
            start = datetime.fromtimestamp(bucket["start_time"], tz=timezone.utc)
            for result in bucket.get("results", []) or []:
                out.append((start, result))
        return out

    # -- costs (USD, org level) ------------------------------------------
    def iter_costs(self, *, start_ts: int, end_ts: int,
                   group_by: list[str]) -> list[tuple[datetime, dict]]:
        """Return [(bucket_start_utc, result), ...]. bucket_width is 1d-only
        per the official API reference."""
        buckets = paged_get(
            self, "/v1/organization/costs",
            {"start_time": start_ts, "end_time": end_ts,
             "bucket_width": "1d", "group_by": group_by, "limit": 180})
        out: list[tuple[datetime, dict]] = []
        for bucket in buckets:
            start = datetime.fromtimestamp(bucket["start_time"], tz=timezone.utc)
            for result in bucket.get("results", []) or []:
                out.append((start, result))
        return out


def parse_usage_result(result: dict) -> dict | None:
    """Normalize one completions result → canonical token counts.

    Returns None when the row has no model (can't attribute it).
    `input_tokens` includes cached tokens per the docs, so uncached input =
    input_tokens - input_cached_tokens.
    """
    model = result.get("model")
    if not model:
        return None
    input_cached = int(result.get("input_cached_tokens") or 0)
    input_total = int(result.get("input_tokens") or 0)
    return {
        "model": model,
        "input_tokens": max(input_total - input_cached, 0),
        "output_tokens": int(result.get("output_tokens") or 0),
        "cached_input_tokens": input_cached,
        "reasoning_tokens": 0,  # completions endpoint has no reasoning split
        "num_model_requests": int(result.get("num_model_requests") or 0),
        "api_key_id": result.get("api_key_id"),
        "user_id": result.get("user_id"),
        "project_id": result.get("project_id"),
        "service_tier": result.get("service_tier"),
        "batch": result.get("batch"),
    }


def parse_cost_result(result: dict) -> dict | None:
    """Normalize one costs result → (group_key, amount_usd)."""
    amount = result.get("amount") or {}
    try:
        value = amount.get("value")
        amount_usd = float(value)  # converted to Decimal by the caller
    except (TypeError, ValueError):
        return None
    return {
        "group_key": result.get("line_item") or result.get("project_id"),
        "amount_usd": amount_usd,
        "currency": (amount.get("currency") or "usd").lower(),
    }
