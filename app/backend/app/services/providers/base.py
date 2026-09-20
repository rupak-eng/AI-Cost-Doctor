"""Shared plumbing for provider connectors.

ProviderError is the only exception that crosses the service boundary toward
the API layer: its message is safe to surface (never contains key material).
"""
from __future__ import annotations

import httpx


class ProviderError(RuntimeError):
    """A provider call failed. `detail` is safe to show to the user."""

    def __init__(self, provider: str, detail: str, *,
                 status_code: int | None = None,
                 kind: str = "provider_error"):
        super().__init__(f"[{provider}] {detail}")
        self.provider = provider
        self.detail = detail
        self.status_code = status_code
        self.kind = kind  # invalid_key | forbidden | rate_limited | provider_error


def _truncate(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "…"


def raise_for_status(provider: str, resp: httpx.Response) -> None:
    """Map HTTP failures to ProviderError with safe, actionable messages."""
    if resp.status_code < 400:
        return
    body = ""
    try:
        data = resp.json()
        # OpenAI: {"error": {"message": ...}} ; Anthropic: {"type":"error","error":{...}}
        err = data.get("error", data)
        if isinstance(err, dict):
            body = str(err.get("message", err.get("type", "")))
        else:
            body = str(err)
    except Exception:
        body = resp.text or ""
    body = _truncate(body) or f"HTTP {resp.status_code}"
    if resp.status_code == 401:
        raise ProviderError(provider, f"invalid API key ({body})",
                            status_code=401, kind="invalid_key")
    if resp.status_code == 403:
        raise ProviderError(
            provider,
            "key rejected: this endpoint requires an Admin API key — "
            "a regular inference key will not work. "
            "Create one in the provider's organization/admin settings. "
            f"Provider said: {body}",
            status_code=403, kind="forbidden")
    if resp.status_code == 429:
        raise ProviderError(provider, f"rate limited by provider ({body})",
                            status_code=429, kind="rate_limited")
    raise ProviderError(provider, f"provider request failed: {body}",
                        status_code=resp.status_code)


def paged_get(client: "BaseProviderClient", path: str, params: dict,
              *, max_pages: int = 500) -> list[dict]:
    """Follow has_more/next_page pagination. Returns all `data` buckets."""
    buckets: list[dict] = []
    page: str | None = None
    for _ in range(max_pages):
        p = dict(params)
        if page:
            p["page"] = page
        payload = client._get(path, p)
        buckets.extend(payload.get("data", []) or [])
        if not payload.get("has_more"):
            return buckets
        page = payload.get("next_page")
        if not page:
            # Provider contract violation: has_more without a cursor.
            raise ProviderError(
                client.provider,
                "provider said has_more=true but gave no next_page cursor")
    raise ProviderError(client.provider,
                        f"pagination exceeded {max_pages} pages — aborting")


class BaseProviderClient:
    """Thin authenticated HTTP wrapper. Subclasses add endpoints."""

    provider = "base"
    base_url = ""

    def __init__(self, api_key: str, *,
                 transport: httpx.BaseTransport | None = None) -> None:
        if not api_key:
            raise ProviderError(self.provider, "empty API key")
        self._http = httpx.Client(
            base_url=self.base_url, headers=self._headers(api_key),
            timeout=httpx.Timeout(30.0), transport=transport)

    def _headers(self, api_key: str) -> dict:  # noqa: ARG002
        raise NotImplementedError

    def _get(self, path: str, params: dict) -> dict:
        try:
            resp = self._http.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderError(self.provider, f"request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(self.provider, f"network error: {exc}") from exc
        raise_for_status(self.provider, resp)
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderError(self.provider,
                                "provider returned non-JSON response") from exc

    def close(self) -> None:
        self._http.close()
