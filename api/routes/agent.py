"""Agent BFF route — ``POST /v1/agent/run``.

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
import logging
import os
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import require_api_key
from api.schemas import AgentRunRequest, AgentRunResponse, AgentRunSummary, InterpretationsBlock

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent"])

_TIMEOUT_SECONDS = float(os.getenv("AGENT_RUN_TIMEOUT_SECONDS", "120"))


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

    return AgentRunResponse(
        run_id=run_id,
        region_scope=str(final_state.get("region_scope", request.region)),
        axes_executed=list(final_state.get("axes_selected", request.axes)),
        duration_seconds=duration,
        summary=summary,
        interpretations=interp_block,
        investment_hypotheses=report_json.get("investment_hypotheses", []),
        axis1_summary=report_json.get("axis1_summary"),
        axis2_summary=report_json.get("axis2_summary"),
        axis3_summary=report_json.get("axis3_summary"),
        errors=errors,
    )
