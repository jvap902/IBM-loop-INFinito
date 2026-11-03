"""Agent BFF route — ``POST /v1/agent/run``, ``GET /v1/agent/runs``, ``GET /v1/agent/runs/{run_id}``.

This endpoint wraps the LangGraph operational agent into a single HTTP call,
allowing the web UI (or any HTTP client) to trigger a full agent run without
CLI access.

Environment variables
---------------------
AGENT_RUN_TIMEOUT_SECONDS
    Maximum seconds to wait for the agent to complete before returning HTTP 504.
    Default: 120.  Set higher for large datasets or slow LLM providers.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import require_api_key
from audit.logger import get_audit_logger
from api.schemas import AgentRunRequest, AgentRunResponse, AgentRunSummary, ExplanationsBlock, InterpretationsBlock

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent"])

_TIMEOUT_SECONDS = float(os.getenv("AGENT_RUN_TIMEOUT_SECONDS", "120"))
_RUNS_DIR = Path(os.getenv("RUNS_DIR", "runs"))


def _persist_run(response: AgentRunResponse) -> None:
    """Write the AgentRunResponse JSON to runs/<run_id>.json."""
    try:
        _RUNS_DIR.mkdir(parents=True, exist_ok=True)
        path = _RUNS_DIR / f"{response.run_id}.json"
        path.write_text(
            response.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info('{"event": "run_persisted", "run_id": "%s", "path": "%s"}', response.run_id, path)
    except Exception:
        logger.exception('{"event": "run_persist_error", "run_id": "%s"}', response.run_id)


def _invoke_agent(request: AgentRunRequest) -> dict:
    """Build and invoke the LangGraph agent synchronously.

    Imported inside the function so that the heavy agent/ML dependencies are
    only loaded at call-time, not at FastAPI startup.
    """
    from agent.graph import build_graph
    from agent.state import AgentState
    from agent.tool_registry import ToolRegistry, reset_registry

    # Apply LLM provider override for this request only.
    # We restore the original value afterwards to avoid polluting the process
    # environment for concurrent requests.
    original_llm = os.environ.get("LLM_PROVIDER")
    os.environ["LLM_PROVIDER"] = request.llm_provider

    try:
        # Validate and normalise axes
        valid_axes = {"axis1", "axis2", "axis3"}
        axes = [a.lower().strip() for a in request.axes if a.lower().strip() in valid_axes]
        if not axes:
            axes = ["axis1", "axis2", "axis3"]

        reset_registry()
        registry = ToolRegistry(
            base_url=os.getenv("TOOL_API_BASE_URL", "http://localhost:8000"),
            api_key=os.getenv("TOOL_API_KEY", ""),
        )

        run_id = str(uuid.uuid4())
        initial_state: AgentState = {
            "region_scope": request.region,
            "axes_requested": axes,
            "force": request.force,
            "run_id": run_id,
            "audit_trail": [],
            "errors": [],
        }

        compiled_graph = build_graph(registry=registry)
        final_state: AgentState = compiled_graph.invoke(initial_state)
        return {
            "run_id": run_id,
            "final_state": final_state,
        }
    finally:
        # Restore original LLM_PROVIDER
        if original_llm is None:
            os.environ.pop("LLM_PROVIDER", None)
        else:
            os.environ["LLM_PROVIDER"] = original_llm


@router.post(
    "/agent/run",
    response_model=AgentRunResponse,
    summary="Run the full Operational Agent",
    description=(
        "Triggers the complete LangGraph Operational Agent pipeline — gap detection, "
        "tool selection, axis execution (Axis 1/2/3), result interpretation, and report "
        "generation — and returns the structured JSON report.\n\n"
        "The call is **synchronous**: it blocks until the agent finishes or until "
        "``AGENT_RUN_TIMEOUT_SECONDS`` (default 120 s) elapses, at which point HTTP 504 "
        "is returned.\n\n"
        "Requires ``X-API-Key`` header."
    ),
    responses={
        200: {"description": "Agent completed successfully."},
        504: {"description": "Agent did not complete within the configured timeout."},
        500: {"description": "Agent execution failed with an unrecoverable error."},
    },
)
async def run_agent(
    request: AgentRunRequest,
    _api_key: str = Depends(require_api_key),
) -> AgentRunResponse:
    """Run the full LangGraph operational agent and return the report JSON."""
    t0 = time.perf_counter()
    logger.info(
        '{"event": "agent_run_start", "region": "%s", "axes": %s, "llm": "%s"}',
        request.region,
        request.axes,
        request.llm_provider,
    )

    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_invoke_agent, request),
            timeout=_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            '{"event": "agent_run_timeout", "timeout_s": %s, "region": "%s"}',
            _TIMEOUT_SECONDS,
            request.region,
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=(
                f"Agent did not complete within {int(_TIMEOUT_SECONDS)} seconds. "
                "Increase AGENT_RUN_TIMEOUT_SECONDS or reduce the dataset scope."
            ),
        )
    except Exception as exc:
        logger.exception('{"event": "agent_run_error", "region": "%s"}', request.region)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent execution failed: {exc}",
        ) from exc

    duration = round(time.perf_counter() - t0, 3)
    run_id: str = result["run_id"]
    final_state = result["final_state"]
    report_json: dict = final_state.get("report_json", {})
    errors: list = final_state.get("errors", [])

    if errors and not report_json:
        # Hard failure — no report was produced
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent returned errors and produced no report.",
        )

    raw_summary = report_json.get("summary", {})
    summary = AgentRunSummary(
        n_critical_hexagons=raw_summary.get("n_critical_hexagons", 0),
        n_expansion_clusters=raw_summary.get("n_expansion_clusters", 0),
        n_market_segments=raw_summary.get("n_market_segments", 0),
        n_investment_hypotheses=raw_summary.get("n_investment_hypotheses", 0),
        total_tam_brl=raw_summary.get("total_tam_brl", 0.0),
        capex_proxy_brl=raw_summary.get("capex_proxy_brl", 0.0),
        p1_clusters=raw_summary.get("p1_clusters", 0),
        p2_clusters=raw_summary.get("p2_clusters", 0),
    )

    logger.info(
        '{"event": "agent_run_complete", "run_id": "%s", "duration_s": %s, "errors": %d}',
        run_id,
        duration,
        len(errors),
    )

    raw_interp = report_json.get("interpretations") or {}
    interp_block: InterpretationsBlock | None = None
    if raw_interp:
        try:
            interp_block = InterpretationsBlock(**raw_interp)
        except Exception:
            interp_block = None

    # Extract SHAP/Z-score explanations from the audit trail.
    # Each axis tool (axis1_run, axis2_run, axis3_run) generates its own
    # run_id (independent from the agent run_id) and logs the explanation
    # under that tool-level run_id.  We recover those run_ids from the
    # axis results stored in final_state and query per-tool.
    expl_axis1: dict | None = None
    expl_axis2: dict | None = None
    expl_axis3: dict | None = None
    try:
        audit = get_audit_logger()
        _tool_run_ids: dict[str, str | None] = {
            "axis1_run": (final_state.get("axis1_result") or {}).get("run_id"),
            "axis2_run": (final_state.get("axis2_result") or {}).get("run_id"),
            "axis3_run": (final_state.get("axis3_result") or {}).get("run_id"),
        }
        for tool_name, tool_run_id in _tool_run_ids.items():
            if not tool_run_id:
                continue
            events = audit.read_events(
                run_id=tool_run_id,
                event_type="tool_call",
                limit=5,
            )
            for evt in events:
                if evt.tool_name == tool_name and evt.explanation is not None:
                    if tool_name == "axis1_run":
                        expl_axis1 = evt.explanation
                    elif tool_name == "axis2_run":
                        expl_axis2 = evt.explanation
                    elif tool_name == "axis3_run":
                        expl_axis3 = evt.explanation
                    break
    except Exception:
        logger.warning('{"event": "explanations_read_error", "run_id": "%s"}', run_id)

    expl_block: ExplanationsBlock | None = None
    if any(v is not None for v in (expl_axis1, expl_axis2, expl_axis3)):
        expl_block = ExplanationsBlock(axis1=expl_axis1, axis2=expl_axis2, axis3=expl_axis3)

    response = AgentRunResponse(
        run_id=run_id,
        region_scope=str(final_state.get("region_scope", request.region)),
        axes_executed=list(final_state.get("axes_selected", request.axes)),
        duration_seconds=duration,
        summary=summary,
        interpretations=interp_block,
        explanations=expl_block,
        investment_hypotheses=report_json.get("investment_hypotheses", []),
        axis1_summary=report_json.get("axis1_summary"),
        axis2_summary=report_json.get("axis2_summary"),
        axis3_summary=report_json.get("axis3_summary"),
        errors=errors,
    )
    _persist_run(response)
    return response


# ── GET /agent/runs ────────────────────────────────────────────────────────

from pydantic import BaseModel  # noqa: E402


class RunMeta(BaseModel):
    run_id: str
    region_scope: str
    axes_executed: list[str]
    duration_seconds: float
    timestamp: str
    n_critical_hexagons: int
    n_expansion_clusters: int
    n_market_segments: int
    total_tam_brl: float
    p1_clusters: int
    p2_clusters: int


class RunListResponse(BaseModel):
    total: int
    runs: list[RunMeta]


@router.get(
    "/agent/runs",
    response_model=RunListResponse,
    summary="List persisted agent runs",
    tags=["Agent"],
)
async def list_runs(
    _api_key: str = Depends(require_api_key),
) -> RunListResponse:
    """Return a newest-first list of all persisted AgentRunResponse snapshots."""
    if not _RUNS_DIR.is_dir():
        return RunListResponse(total=0, runs=[])

    items: list[RunMeta] = []
    for path in sorted(_RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            summary = raw.get("summary", {})
            items.append(RunMeta(
                run_id=raw["run_id"],
                region_scope=raw.get("region_scope", "—"),
                axes_executed=raw.get("axes_executed", []),
                duration_seconds=raw.get("duration_seconds", 0.0),
                timestamp=datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M UTC"),
                n_critical_hexagons=summary.get("n_critical_hexagons", 0),
                n_expansion_clusters=summary.get("n_expansion_clusters", 0),
                n_market_segments=summary.get("n_market_segments", 0),
                total_tam_brl=summary.get("total_tam_brl", 0.0),
                p1_clusters=summary.get("p1_clusters", 0),
                p2_clusters=summary.get("p2_clusters", 0),
            ))
        except Exception:
            logger.warning('{"event": "run_list_parse_error", "file": "%s"}', path.name)

    return RunListResponse(total=len(items), runs=items)


@router.get(
    "/agent/runs/{run_id}",
    response_model=AgentRunResponse,
    summary="Load a persisted agent run",
    tags=["Agent"],
)
async def get_run(
    run_id: str,
    _api_key: str = Depends(require_api_key),
) -> AgentRunResponse:
    """Return the full AgentRunResponse for a previously persisted run."""
    safe = Path(run_id).name
    path = _RUNS_DIR / f"{safe}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Run '{safe}' not found.")
    try:
        return AgentRunResponse.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to parse run file: {exc}") from exc


@router.delete(
    "/agent/runs/{run_id}",
    status_code=204,
    summary="Delete a persisted agent run",
    tags=["Agent"],
)
async def delete_run(
    run_id: str,
    _api_key: str = Depends(require_api_key),
) -> None:
    """Delete the persisted JSON snapshot for a run. Returns 204 on success."""
    safe = Path(run_id).name
    path = _RUNS_DIR / f"{safe}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Run '{safe}' not found.")
    try:
        path.unlink()
        logger.info('{"event": "run_deleted", "run_id": "%s"}', safe)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete run: {exc}") from exc
