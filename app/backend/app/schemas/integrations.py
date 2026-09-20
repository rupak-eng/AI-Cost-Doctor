"""CSV upload schemas (POST /integrations/csv/upload, JWT auth)."""
from __future__ import annotations

from pydantic import BaseModel


class CsvUploadResponse(BaseModel):
    rows_parsed: int
    rows_valid: int
    rows_invalid: int
    invalid_sample: list[dict]  # [{row: int, reason: str}], first few
    preview: list[dict]  # first 5 valid rows: canonical fields + computed costs
    committed: int  # 0 on dry run; events inserted on commit
