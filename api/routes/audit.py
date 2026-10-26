"""Audit query API routes.

Endpoints
---------
GET  /audit/events   — Query audit log with optional filters (requires X-API-Key).

This endpoint is intended for human auditors, compliance officers and the
Planner Agent.  It exposes a filtered view of the append-only audit log so
that reviewers can trace every tool call, model run and reasoning step
without direct access to the underlying log storage.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.auth import require_api_key
from audit.logger import get_audit_logger
from audit.schema import AuditEvent

router = APIRouter()


# ── Response wrapper ──────────────────────────────────────────────────────

from pydantic import BaseModel


class AuditQueryResponse(BaseModel):
    """Response body for ``GET /audit/events``."""

    total_returned: int
    events: list[AuditEvent]


# ── GET /audit/events ──────────────────────────────────────────────────────

@router.get(
    "/audit/events",
    response_model=AuditQueryResponse,
    summary="Audit Log — Query recorded events",
    description=(
        "Returns a filtered, newest-first list of audit events from the "
        "Transparency & Auditability Layer.  Supports filtering by agent, "
        "event type, run ID and date range.  Requires ``X-API-Key`` header. "
        "\n\n"
        "**Note:** When the ``postgres`` backend is active this endpoint "
        "performs a direct SQL query.  For the ``jsonl`` backend it performs "
        "a linear scan of the local log file — suitable for development and "
        "low-volume audit use."
    ),
    tags=["Audit"],
)
async def get_audit_events(
    agent_id: Optional[str] = Query(
        default=None,
        description="Filter by agent identifier ('planner', 'operational', 'system').",
    ),
    event_type: Optional[str] = Query(
        default=None,
        description=(
            "Filter by event type: 'tool_call', 'reasoning_step', "
            "'report_generated', or 'model_run'."
        ),
    ),
    run_id: Optional[str] = Query(
        default=None,
        description="Filter by pipeline run UUID to trace a specific execution.",
    ),
    date_start: Optional[datetime] = Query(
        default=None,
        description="Return events at or after this ISO-8601 UTC datetime.",
    ),
    date_end: Optional[datetime] = Query(
        default=None,
        description="Return events at or before this ISO-8601 UTC datetime.",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of events to return (newest first). Max 1000.",
    ),
    _key: str = Depends(require_api_key),
) -> AuditQueryResponse:
    audit = get_audit_logger()
    events = audit.read_events(
        agent_id=agent_id,
        event_type=event_type,
        run_id=run_id,
        date_start=date_start,
        date_end=date_end,
        limit=limit,
    )
    return AuditQueryResponse(total_returned=len(events), events=events)
