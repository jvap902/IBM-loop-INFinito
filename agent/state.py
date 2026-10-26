"""AgentState — shared mutable context for the LangGraph Operational Agent.

The state is passed between every node in the StateGraph.  Each node reads
what it needs and writes its outputs back into the dict; LangGraph merges
updates via the ``Annotated[list, operator.add]`` accumulator for lists and
plain last-write-wins for scalars.

All geographic identifiers are H3 cell IDs (resolution 8 or 9) or
aggregated region names — no subscriber-level PII is ever stored here.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, Optional
from typing_extensions import TypedDict


class AgentState(TypedDict, total=False):
    """Shared state envelope for the Operational Agent LangGraph workflow.

    Fields
    ------
    region_scope
        Human-readable region label or list of H3 parent cell IDs (res 5/6)
        used to spatially scope all axis runs.
    axes_requested
        List of axis identifiers the caller wants to run, e.g. ["axis1",
        "axis2", "axis3"].  If empty the tool_selector node decides.
    force
        When True the gap_detector skips freshness checks and always runs.
    run_id
        UUID assigned to this agent execution (propagated to all audit events).

    gap_report
        Dict produced by gap_detector describing stale or missing regions.
    axes_selected
        Final list of axes to invoke, decided by tool_selector.
    tool_selector_rationale
        LLM Chain-of-Thought text explaining the axis selection decision.

    axis1_result
        Full JSON payload returned by POST /v1/tools/axis1/run.
    axis2_result
        Full JSON payload returned by POST /v1/tools/axis2/run.
    axis3_result
        Full JSON payload returned by POST /v1/tools/axis3/run.

    investment_hypotheses
        List of structured hypothesis dicts produced by result_interpreter.
        Each entry carries cluster_id, priority_class, tam_estimate, and
        a rationale string.
    cross_matrix
        The raw cross-axis intersection matrix as a list of dicts.

    report_markdown
        Final Markdown report text (all 7 mandatory sections).
    report_json
        Machine-readable dict version of the final report.

    audit_trail
        Accumulated list of AuditEvent dicts recorded during this run.
        Uses ``operator.add`` so each node can append without overwriting.
    errors
        Accumulated list of error dicts; uses ``operator.add``.
    """

    # ── Inputs ────────────────────────────────────────────────────────────
    region_scope: str | list[str]
    axes_requested: list[str]
    force: bool
    run_id: str

    # ── Gap detection ─────────────────────────────────────────────────────
    gap_report: dict[str, Any]

    # ── Tool selection ────────────────────────────────────────────────────
    axes_selected: list[str]
    tool_selector_rationale: str

    # ── Axis results ──────────────────────────────────────────────────────
    axis1_result: Optional[dict[str, Any]]
    axis2_result: Optional[dict[str, Any]]
    axis3_result: Optional[dict[str, Any]]

    # ── Interpretation ────────────────────────────────────────────────────
    investment_hypotheses: list[dict[str, Any]]
    cross_matrix: list[dict[str, Any]]

    # ── Report ────────────────────────────────────────────────────────────
    report_markdown: str
    report_json: dict[str, Any]

    # ── Audit & error accumulation (append-only via operator.add) ─────────
    audit_trail: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[dict[str, Any]], operator.add]
