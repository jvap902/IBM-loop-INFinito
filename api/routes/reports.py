"""Reports API routes.

Endpoints
---------
GET  /reports         — List all generated Markdown reports.
GET  /reports/{name}  — Return the raw Markdown content of a specific report.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))


# ── Response models ────────────────────────────────────────────────────────

class ReportMeta(BaseModel):
    """Metadata entry for a single report file."""
    filename: str
    region: str
    date: str
    size_bytes: int


class ReportListResponse(BaseModel):
    reports: list[ReportMeta]


class ReportContentResponse(BaseModel):
    filename: str
    content: str


# ── Helpers ────────────────────────────────────────────────────────────────

def _parse_meta(filename: str) -> tuple[str, str]:
    """Extract (region, date) from a filename like 'BR-SP_2026-10-28.md'."""
    stem = Path(filename).stem  # e.g. 'BR-SP_2026-10-28'
    parts = stem.rsplit("_", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return stem, ""


# ── GET /reports ───────────────────────────────────────────────────────────

@router.get(
    "/reports",
    response_model=ReportListResponse,
    summary="Reports — List available reports",
    tags=["Reports"],
)
async def list_reports() -> ReportListResponse:
    if not _REPORTS_DIR.is_dir():
        return ReportListResponse(reports=[])

    items: list[ReportMeta] = []
    for path in sorted(_REPORTS_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        region, date = _parse_meta(path.name)
        items.append(ReportMeta(
            filename=path.name,
            region=region,
            date=date,
            size_bytes=path.stat().st_size,
        ))
    return ReportListResponse(reports=items)


# ── GET /reports/{filename} ────────────────────────────────────────────────

@router.get(
    "/reports/{filename}",
    response_model=ReportContentResponse,
    summary="Reports — Get report content",
    tags=["Reports"],
)
async def get_report(filename: str) -> ReportContentResponse:
    # Prevent path traversal
    safe = Path(filename).name
    path = _REPORTS_DIR / safe
    if not path.exists() or path.suffix != ".md":
        raise HTTPException(status_code=404, detail=f"Report '{safe}' not found.")
    return ReportContentResponse(filename=safe, content=path.read_text(encoding="utf-8"))
