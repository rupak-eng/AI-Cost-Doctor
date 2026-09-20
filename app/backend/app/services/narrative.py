"""Investigation narratives — deterministic facts in, prose out.

The template path is the default and always available: it renders the
computed investigation facts into plain-English prose without inventing any
number. An optional LLM polish layer may reword the template output when
`NARRATIVE_LLM_API_KEY` is configured; it receives the template text plus
the fact table with strict instructions to reword only. Any failure (no key,
network error, bad response) falls back to the template — the endpoint never
fails because the polisher did.

The LLM is never given raw events and never asked to compute: every dollar
figure in the narrative already exists in the template it rewords.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from app.core.config import settings

log = logging.getLogger(__name__)

_POLISH_SYSTEM_PROMPT = (
    "You reword a cost-investigation summary for a B2B SaaS founder. Rules: "
    "reword for clarity and tone only; NEVER change, add, or remove any "
    "number, percentage, dollar figure, model name, or application name; "
    "never invent recommendations or savings figures; keep it under 200 "
    "words; plain paragraphs, no markdown headings."
)


def template_narrative(facts: dict) -> str:
    """Deterministic prose from investigation facts. No numbers are invented."""
    tenant = facts.get("tenant_name") or "This customer"
    margin = facts.get("margin_usd")
    if margin is None:
        head = (f"{tenant} has no recorded revenue, so AI margin cannot be "
                f"computed yet. ")
    elif margin < 0:
        head = (f"{tenant} is losing about ${abs(margin):,.0f}/month on AI margin. ")
    else:
        head = (f"{tenant} is earning about ${margin:,.0f}/month in AI margin. ")

    drivers = facts.get("drivers") or {}
    by_app = drivers.get("by_app") or []
    by_model = drivers.get("by_model") or []
    body = ""
    if by_app:
        top = by_app[0]
        body += (f"{top['pct']:.0f}% of AI cost comes from {top['app']}. ")
    if by_model:
        top = by_model[0]
        body += (f"{top['model']} is the costliest model at "
                 f"${top['cost_usd']:,.0f} ({top['pct']:.0f}% of AI cost). ")

    vvt = facts.get("volume_vs_tokens") or {}
    vol_fx = vvt.get("volume_effect_usd")
    tok_fx = vvt.get("token_intensity_effect_usd")
    if vol_fx is not None and tok_fx is not None:
        if abs(vol_fx) >= abs(tok_fx):
            body += (f"Cost movement is driven more by request volume "
                     f"(${vol_fx:+,.0f}) than by tokens per request (${tok_fx:+,.0f}). ")
        else:
            body += (f"Cost movement is driven more by tokens per request "
                     f"(${tok_fx:+,.0f}) than by request volume (${vol_fx:+,.0f}). ")

    recs = facts.get("recommendations") or []
    if recs:
        top_rec = recs[0]
        body += (f"Top recommended action: {top_rec['action']} — estimated "
                 f"savings ~${top_rec['est_savings_usd_mo']:,.0f}/month "
                 f"(confidence: {top_rec['confidence']}). "
                 f"Estimates are not guarantees.")
    else:
        body += "No savings opportunity above the cost threshold was found."
    return head + body


def _llm_polish(template_text: str) -> str | None:
    """Reword via OpenAI chat completions. Returns None on any failure."""
    api_key = settings.narrative_llm_api_key
    if not api_key:
        return None
    try:
        import httpx
        resp = httpx.post(
            f"{settings.narrative_llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": settings.narrative_llm_model,
                "messages": [
                    {"role": "system", "content": _POLISH_SYSTEM_PROMPT},
                    {"role": "user", "content": template_text},
                ],
                "temperature": 0.2,
                "max_tokens": 400,
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        choices = resp.json().get("choices") or []
        text = (choices[0].get("message") or {}).get("content")
        return text.strip() if text and text.strip() else None
    except Exception as exc:  # never fail the endpoint because polish failed
        log.warning("narrative LLM polish failed, using template: %s", exc)
        return None


def explain(facts: dict,
            polish: Callable[[str], str | None] = _llm_polish) -> tuple[str, str]:
    """Return (narrative, source) where source is 'template' or 'llm'.

    Any polish failure — no key, network error, bad response, or a custom
    polisher raising — falls back to the deterministic template.
    """
    template_text = template_narrative(facts)
    try:
        polished = polish(template_text)
    except Exception as exc:  # never fail because polish failed
        log.warning("narrative polish failed, using template: %s", exc)
        polished = None
    if polished:
        return polished, "llm"
    return template_text, "template"
