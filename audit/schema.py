"""Pydantic models for the Transparency & Auditability Layer.

AuditEvent is the canonical, append-only record for every observable action
performed by the Telecom AI Platform (tool calls, reasoning steps, model runs).

Design constraints
------------------
* No PII — h3_id columns are spatial aggregates (≥ H3 res 8), not individual
  subscriber data.  Agent reasoning texts MUST NOT contain subscriber IDs,
  CPF, CNPJ, or network passwords.  The logger enforces this at write time.
* Stable schema — new optional fields may be added; existing fields are never
  removed or renamed (append-only evolution).
* ISO-8601 UTC timestamps — consumers must not assume local time zones.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_serializer


# ── Event type enumeration ─────────────────────────────────────────────────

EventType = Literal[
    "tool_call",        # Agent invoked a tool endpoint
    "reasoning_step",   # Agent Chain-of-Thought text step
    "report_generated", # Final analytical report produced
    "model_run",        # ML pipeline executed
]

AgentId = Literal["planner", "operational", "system"]


# ── Core event model ───────────────────────────────────────────────────────

class AuditEvent(BaseModel):
    """Single auditable event in the Telecom AI Platform.

    All fields except ``event_id`` and ``timestamp`` are optional so that
    partial events (e.g. a reasoning step with no tool invocation) can be
    recorded without forcing callers to construct dummy data.
    """

    # ── Identity & timing ────────────────────────────────────────────────
    event_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique UUID v4 identifier for this event.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="ISO-8601 UTC timestamp of the event.",
    )

    # ── Agent metadata ───────────────────────────────────────────────────
    agent_id: AgentId = Field(
        default="system",
        description="Identifier of the agent that triggered this event.",
    )
    run_id: Optional[str] = Field(
        default=None,
        description="Pipeline run UUID (links related events in one execution).",
    )
    model_version: Optional[str] = Field(
        default=None,
        description="Semantic version string of the ML model artefact used.",
    )

    # ── Event classification ─────────────────────────────────────────────
    event_type: EventType = Field(
        description="Classification of the event kind.",
    )

    # ── Tool invocation details ──────────────────────────────────────────
    tool_name: Optional[str] = Field(
        default=None,
        description="Name of the tool endpoint called (e.g. 'axis1_run').",
    )
    tool_input: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Sanitised request parameters. PII fields are removed before logging. "
            "Spatial IDs (h3_id) are safe to record."
        ),
    )
    tool_output_summary: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "High-level summary of the tool response "
            "(e.g. n_critical, n_clusters, duration_seconds). "
            "Full result payloads are NOT stored to avoid PII leakage."
        ),
    )

    # ── Reasoning chain ──────────────────────────────────────────────────
    reasoning_text: Optional[str] = Field(
        default=None,
        description=(
            "Free-text Chain-of-Thought reasoning step. "
            "Must not contain subscriber-level PII."
        ),
    )

    # ── Explainability payload ───────────────────────────────────────────
    explanation: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "SHAP or proxy explanation payload attached to this event. "
            "Shape depends on the axis: top-N feature importances for Axis 1/3, "
            "cluster Z-score summary for Axis 2."
        ),
    )

    @field_serializer("timestamp")
    def _serialize_timestamp(self, ts: datetime, _info: Any) -> str:
        return ts.isoformat()

    model_config = {"populate_by_name": True}
