"""On-demand report generation route — ``POST /v1/agent/report``.

Generates a new Markdown report from an *existing* agent run without
re-executing the ML pipelines.  The endpoint:

1. Loads ``runs/{run_id}.json`` to reconstruct the analysis context.
2. Injects the user's free-text ``user_prompt`` into the ``AgentState``.
3. Calls ``report_writer(state)`` directly (no LangGraph graph compilation).
4. Persists the resulting Markdown as ``reports/{region}_{date}_{run_id[:8]}.md``.
5. Returns the filename and full content.

Environment variables
---------------------
RUNS_DIR      Directory where ``{run_id}.json`` files are persisted (default: runs).
REPORTS_DIR   Directory where generated ``.md`` files are saved (default: reports).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import require_api_key
from api.schemas import AgentReportRequest, AgentReportResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent"])

_RUNS_DIR = Path(os.getenv("RUNS_DIR", "runs"))
_REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))


# ── Helper ─────────────────────────────────────────────────────────────────

def _generate_report(request: AgentReportRequest) -> tuple[str, str]:
    """Load persisted run, reconstruct state, call report_writer.

    Returns
    -------
    (filename, markdown_content)
    """
    # ── Import heavy deps at call-time (same pattern as agent.py) ─────────
    from agent.graph import report_writer
    from agent.state import AgentState

    # ── Load persisted run context ─────────────────────────────────────────
    safe_id = Path(request.run_id).name  # prevent path traversal
    run_path = _RUNS_DIR / f"{safe_id}.json"
    if not run_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{safe_id}' not found. Run the agent first via POST /v1/agent/run.",
        )

    try:
        run_data: dict = json.loads(run_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load run context: {exc}",
        ) from exc

    # ── Apply LLM provider override (restore in finally) ──────────────────
    original_llm = os.environ.get("LLM_PROVIDER")
    os.environ["LLM_PROVIDER"] = request.llm_provider

    try:
        # ── Reconstruct AgentState from the persisted run JSON ─────────────
        # report_writer reads: region_scope, run_id, axes_selected,
        # axis1_result, axis2_result, axis3_result,
        # investment_hypotheses, cross_matrix, tool_selector_rationale, errors.
        # axis*_result must mirror the raw tool response shape (not the *_summary
        # condensed form), so we expand from axis*_summary where needed.

        a1_summary = run_data.get("axis1_summary") or {}
        a2_summary = run_data.get("axis2_summary") or {}
        a3_summary = run_data.get("axis3_summary") or {}

        # Expand axis1 summary → raw axis1 result shape expected by report_writer
        axis1_result: dict | None = None
        if a1_summary:
            axis1_result = {
                "n_critical": a1_summary.get("n_critical", 0),
                "total_hexagons_scored": a1_summary.get("total_hexagons_scored", 0),
                "anomaly_rate": a1_summary.get("anomaly_rate", 0.0),
                "duration_seconds": a1_summary.get("duration_seconds", 0.0),
                "results": a1_summary.get("top_critical", []),
            }

        # Expand axis2 summary → raw axis2 result shape
        axis2_result: dict | None = None
        if a2_summary:
            axis2_result = {
                "n_clusters": a2_summary.get("n_clusters", 0),
                "total_hexagons_processed": a2_summary.get("total_hexagons_processed", 0),
                "noise_rate": a2_summary.get("noise_rate", 0.0),
                "duration_seconds": a2_summary.get("duration_seconds", 0.0),
                "clusters": a2_summary.get("clusters", []),
            }

        # Expand axis3 summary → raw axis3 result shape
        axis3_result: dict | None = None
        if a3_summary:
            axis3_result = {
                "n_segments": a3_summary.get("n_segments", 0),
                "total_hexagons_segmented": a3_summary.get("total_hexagons_segmented", 0),
                "silhouette_score_global": a3_summary.get("silhouette_score_global"),
                "duration_seconds": a3_summary.get("duration_seconds", 0.0),
                "segment_profiles": a3_summary.get("segment_profiles", []),
            }

        state: AgentState = {
            "run_id": run_data.get("run_id", request.run_id),
            "region_scope": run_data.get("region_scope", "all"),
            "axes_requested": run_data.get("axes_executed", []),
            "axes_selected": run_data.get("axes_executed", []),
            "force": False,
            "user_prompt": request.user_prompt,
            "axis1_result": axis1_result,
            "axis2_result": axis2_result,
            "axis3_result": axis3_result,
            "investment_hypotheses": run_data.get("investment_hypotheses", []),
            "cross_matrix": run_data.get("cross_matrix", []),
            "tool_selector_rationale": "On-demand report generated from persisted run context.",
            "audit_trail": [],
            "errors": run_data.get("errors", []),
        }

        # ── Call report_writer directly ────────────────────────────────────
        result = report_writer(state)
        report_markdown: str = result["report_markdown"]

    finally:
        if original_llm is None:
            os.environ.pop("LLM_PROVIDER", None)
        else:
            os.environ["LLM_PROVIDER"] = original_llm

    # ── Persist the new report file ────────────────────────────────────────
    region = str(run_data.get("region_scope", "all")).replace("/", "-").replace(" ", "_")
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    run_id_short = request.run_id[:8]
    filename = f"{region}_{date_str}_{run_id_short}.md"

    try:
        _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (_REPORTS_DIR / filename).write_text(report_markdown, encoding="utf-8")
        logger.info(
            '{"event": "on_demand_report_saved", "filename": "%s", "run_id": "%s"}',
            filename, request.run_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Report was generated but could not be saved: {exc}",
        ) from exc

    return filename, report_markdown


# ── Route ──────────────────────────────────────────────────────────────────

@router.post(
    "/agent/report",
    response_model=AgentReportResponse,
    summary="Generate an on-demand report from an existing run",
    description=(
        "Generates a new Markdown report from a previously persisted agent run "
        "(identified by ``run_id``) without re-executing the ML pipelines.\n\n"
        "The ``user_prompt`` guides the LLM synthesis — e.g. *'Focus on P1 clusters "
        "and highlight CAPEX risk'*.  The resulting ``.md`` file is saved in "
        "``reports/`` and its name and content are returned.\n\n"
        "Requires ``X-API-Key`` header."
    ),
    responses={
        200: {"description": "Report generated and saved successfully."},
        404: {"description": "Run ID not found in persisted runs."},
        500: {"description": "Report generation or file persistence failed."},
    },
)
async def generate_report(
    request: AgentReportRequest,
    _api_key: str = Depends(require_api_key),
) -> AgentReportResponse:
    """Generate a new on-demand report from an existing persisted run."""
    t0 = time.perf_counter()
    logger.info(
        '{"event": "on_demand_report_start", "run_id": "%s", "llm": "%s"}',
        request.run_id, request.llm_provider,
    )

    import asyncio
    try:
        filename, content = await asyncio.to_thread(_generate_report, request)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            '{"event": "on_demand_report_error", "run_id": "%s"}', request.run_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Report generation failed: {exc}",
        ) from exc

    duration = round(time.perf_counter() - t0, 3)
    logger.info(
        '{"event": "on_demand_report_complete", "filename": "%s", "duration_s": %s}',
        filename, duration,
    )
    return AgentReportResponse(filename=filename, content=content)
