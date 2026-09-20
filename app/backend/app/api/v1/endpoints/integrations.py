"""CSV upload (POST /integrations/csv/upload, JWT auth).

Multipart form fields:
  file        CSV bytes (first row = header)
  project_id  target project (must belong to the caller's org)
  column_map  JSON: canonical field -> CSV header. Canonical fields:
                timestamp, provider, model, application, tenant,
                input_tokens, output_tokens, cost_reported
              (timestamp/provider/model/input_tokens/output_tokens required)
  revenues    optional JSON: {tenant_external_id: monthly_revenue_usd}
  dry_run     "true" (default) | "false"

Dry run parses + validates every row and previews computed costs without
writing anything (committed: 0). Commit inserts the valid rows as usage
events (source "csv"), upserts tenants, and applies revenues.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app import models as m
from app.api.v1 import deps
from app.core.db import get_db
from app.schemas import integrations as schemas
from app.services.costing import load_catalog_from_db, price_event

router = APIRouter(prefix="/integrations", tags=["integrations"])

CANONICAL_REQUIRED = {"timestamp", "provider", "model", "input_tokens", "output_tokens"}
CANONICAL_OPTIONAL = {"application", "tenant", "cost_reported"}
CANONICAL_ALL = CANONICAL_REQUIRED | CANONICAL_OPTIONAL

MAX_ROWS = 50_000
INVALID_SAMPLE_SIZE = 5
PREVIEW_SIZE = 5


class RowError(ValueError):
    """A single CSV row failed validation; message becomes the row's reason."""


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _parse_dry_run(value: str) -> bool:
    v = (value or "").strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    raise _bad("dry_run must be 'true' or 'false'")


def _parse_column_map(raw: str) -> dict[str, str]:
    try:
        cmap = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise _bad("column_map must be valid JSON")
    if not isinstance(cmap, dict) or not cmap:
        raise _bad("column_map must be a non-empty JSON object")
    unknown = set(cmap) - CANONICAL_ALL
    if unknown:
        raise _bad(f"column_map has unknown canonical fields: {sorted(unknown)}; "
                   f"allowed: {sorted(CANONICAL_ALL)}")
    missing = CANONICAL_REQUIRED - set(cmap)
    if missing:
        raise _bad(f"column_map is missing required fields: {sorted(missing)}")
    for field, header in cmap.items():
        if not isinstance(header, str) or not header.strip():
            raise _bad(f"column_map[{field!r}] must be a non-empty CSV header name")
    return {k: v.strip() for k, v in cmap.items()}


def _parse_revenues(raw: str | None) -> dict[str, Decimal]:
    if raw is None or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise _bad("revenues must be valid JSON")
    if not isinstance(data, dict):
        raise _bad("revenues must be a JSON object {tenant_id: monthly_revenue_usd}")
    out = {}
    for tenant_id, value in data.items():
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise _bad(f"revenues[{tenant_id!r}] is not a valid number")
        if amount < 0:
            raise _bad(f"revenues[{tenant_id!r}] must be >= 0")
        out[str(tenant_id)] = amount
    return out


def _parse_ts(value: str | None) -> datetime:
    if value is None or not value.strip():
        raise RowError("missing timestamp")
    s = value.strip()
    if s[-1:] in ("Z", "z"):  # fromisoformat handles 'Z' on 3.11+, belt-and-braces
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise RowError(f"invalid timestamp: {value!r}")
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _parse_int(value: str | None, field: str) -> int:
    if value is None or not str(value).strip():
        raise RowError(f"missing {field}")
    s = str(value).strip()
    try:
        n = int(s)
    except ValueError:
        try:
            f = float(s)
        except ValueError:
            raise RowError(f"invalid {field}: {value!r}")
        if not f.is_integer():
            raise RowError(f"invalid {field}: {value!r}")
        n = int(f)
    if n < 0:
        raise RowError(f"invalid {field}: negative value")
    return n


def _parse_decimal(value: str | None, field: str) -> Decimal | None:
    if value is None or not str(value).strip():
        return None
    try:
        return Decimal(str(value).strip())
    except InvalidOperation:
        raise RowError(f"invalid {field}: {value!r}")


def _opt_str(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _parse_row(raw: dict, cmap: dict[str, str], catalog) -> dict:
    """Validate one CSV row → canonical dict with computed costs (or raise RowError)."""
    def col(canonical: str):
        return raw.get(cmap[canonical])

    occurred_at = _parse_ts(col("timestamp"))
    provider = _opt_str(col("provider"))
    model = _opt_str(col("model"))
    if not provider:
        raise RowError("missing provider")
    if not model:
        raise RowError("missing model")
    input_tokens = _parse_int(col("input_tokens"), "input_tokens")
    output_tokens = _parse_int(col("output_tokens"), "output_tokens")

    cost_reported = _parse_decimal(
        col("cost_reported"), "cost_reported") if "cost_reported" in cmap else None
    calculated = price_event(
        catalog, provider=provider, model=model, at=occurred_at,
        input_tokens=input_tokens, output_tokens=output_tokens)
    return {
        "timestamp": occurred_at.isoformat(),
        "occurred_at": occurred_at,
        "provider": provider,
        "model": model,
        "application": _opt_str(col("application")) if "application" in cmap else None,
        "tenant": _opt_str(col("tenant")) if "tenant" in cmap else None,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_reported_usd": cost_reported,
        "cost_calculated_usd": calculated,
        "note": ("no catalog price for model — stored unpriced"
                 if calculated is None else None),
    }


def _upsert_tenants(db: Session, org_id, project_id,
                    tenant_ids: set[str], revenues: dict[str, Decimal]) -> None:
    all_ids = {t for t in tenant_ids if t} | set(revenues)
    if not all_ids:
        return
    existing = {
        t.external_id: t
        for t in db.query(m.Tenant)
        .filter_by(org_id=org_id, project_id=project_id)
        .filter(m.Tenant.external_id.in_(sorted(all_ids))).all()
    }
    for ext in sorted(all_ids):
        tenant = existing.get(ext)
        if tenant is None:
            tenant = m.Tenant(org_id=org_id, project_id=project_id,
                              external_id=ext, name=ext, monthly_revenue_usd=None)
            db.add(tenant)
        if ext in revenues:
            tenant.monthly_revenue_usd = revenues[ext]
    db.flush()


@router.post("/csv/upload", response_model=schemas.CsvUploadResponse)
async def upload_csv(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    column_map: str = Form(...),
    revenues: str | None = Form(None),
    dry_run: str = Form("true"),
    user: m.User = Depends(deps.get_current_user),
    db: Session = Depends(get_db),
):
    project = deps.get_org_project(db, user, project_id)
    dry = _parse_dry_run(dry_run)
    cmap = _parse_column_map(column_map)
    revenue_map = _parse_revenues(revenues)

    raw_bytes = await file.read()
    if not raw_bytes or not raw_bytes.strip():
        raise _bad("file is empty")
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _bad("file must be UTF-8 encoded")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise _bad("CSV has no header row")
    missing_headers = [cmap[f] for f in sorted(cmap) if cmap[f] not in reader.fieldnames]
    if missing_headers:
        raise _bad(f"CSV is missing mapped columns: {missing_headers}")

    catalog = load_catalog_from_db(db)
    valid, invalid = [], []
    for n, raw_row in enumerate(reader, start=2):  # row 1 = header
        if n - 1 > MAX_ROWS:
            raise _bad(f"CSV exceeds the {MAX_ROWS:,} row limit")
        try:
            valid.append(_parse_row(raw_row, cmap, catalog))
        except RowError as exc:
            invalid.append({"row": n, "reason": str(exc)})

    committed = 0
    if not dry:
        tenant_ids = {r["tenant"] for r in valid if r["tenant"]}
        _upsert_tenants(db, user.org_id, project.id, tenant_ids, revenue_map)
        db.add_all([m.UsageEvent(
            org_id=user.org_id, project_id=project.id, source="csv",
            provider=r["provider"], model=r["model"], application=r["application"],
            occurred_at=r["occurred_at"],
            input_tokens=r["input_tokens"], output_tokens=r["output_tokens"],
            tenant_id=r["tenant"],
            cost_reported_usd=r["cost_reported_usd"],
            cost_calculated_usd=r["cost_calculated_usd"],
            meta={},
        ) for r in valid])
        committed = len(valid)
        db.commit()

    preview = [
        {k: r[k] for k in ("timestamp", "provider", "model", "application", "tenant",
                           "input_tokens", "output_tokens",
                           "cost_reported_usd", "cost_calculated_usd", "note")}
        for r in valid[:PREVIEW_SIZE]
    ]
    return schemas.CsvUploadResponse(
        rows_parsed=len(valid) + len(invalid),
        rows_valid=len(valid),
        rows_invalid=len(invalid),
        invalid_sample=invalid[:INVALID_SAMPLE_SIZE],
        preview=preview,
        committed=committed,
    )
