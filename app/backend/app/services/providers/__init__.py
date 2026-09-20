"""Provider connectors (Phase 4): OpenAI + Anthropic usage/cost sync.

Everything here is derived from the primary docs recorded in
specs/04-provider-integration-notes.md. We build only what the docs support:

- Token usage at per-model daily-bucket granularity → usage_events with
  DETERMINISTIC calculated costs (costing.price_event). cost_reported_usd
  stays NULL at this granularity: neither provider reports per-model dollars.
- Provider-reported USD buckets → provider_cost_reports (org level, kept
  separate; never allocated to models — that would be invented).
- No tenant/customer attribution is invented: provider APIs offer no such
  dimension. Optional extra group_by dims (api_key_id, workspace_id, …) are
  stored verbatim in usage_events.meta as raw material for a future
  key→tenant mapping UI.
"""
from app.services.providers import openai as openai_mod
from app.services.providers import anthropic as anthropic_mod
from app.services.providers.base import ProviderError
from app.services.providers.sync import SyncSummary, sync_provider

__all__ = [
    "ProviderError",
    "SyncSummary",
    "openai_mod",
    "anthropic_mod",
    "sync_provider",
]
