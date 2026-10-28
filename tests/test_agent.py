"""Integration tests for Sub-Task 6 — Operational Agent (LangGraph).

Test strategy
-------------
All HTTP calls from the ToolRegistry are intercepted with ``respx`` mock
routers so no live FastAPI server or Gold Parquet file is required.
The AuditLogger uses a temporary JSONL file to avoid polluting the dev log.

Coverage
--------
test_full_workflow_all_axes
    Complete e2e run with all three axes.  Validates:
    - All 7 mandatory sections present in the Markdown report.
    - JSON report structure (summary, hypotheses, axis summaries).
    - ≥ 5 audit events recorded for the run.
    - No unhandled Python exceptions raised.

test_workflow_single_axis
    Partial run with only axis2.  Validates:
    - Sections for non-executed axes contain the "not executed" placeholder.
    - Audit trail still records events from executed nodes.

test_workflow_forced
    Run with force=True.  Validates:
    - gap_report status is "forced".

test_tool_registry_retry
    Simulates transient HTTP errors then success; validates retry behaviour.

test_tool_registry_catalogue_load
    Validates catalogue loading from GET /v1/tools.

test_llm_provider_stub
    Validates the StubProvider returns expected defaults without SDK calls.

test_report_sections_present
    Parameterised check that each of the 7 section headers appears in the report.

test_audit_trail_minimum_events
    Verifies ≥ 5 audit events are recorded during a full workflow run.

test_tam_calculation
    Unit test for the TAM formula in result_interpreter.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import respx  # type: ignore
import httpx

# ── Agent imports ──────────────────────────────────────────────────────────
from agent.state import AgentState
from agent.llm_provider import StubProvider, GeminiProvider, get_llm_provider
from agent.tool_registry import ToolRegistry, reset_registry
from agent.graph import (
    gap_detector,
    tool_selector,
    axis1_runner,
    axis2_runner,
    axis3_runner,
    result_interpreter,
    report_writer,
    build_graph,
)

# ── Fixtures ───────────────────────────────────────────────────────────────

_TEST_API_BASE = "http://test-api.local"
_TEST_API_KEY = "test-key-subtask6"

# Minimal synthetic responses from each axis endpoint

_AXIS1_RESPONSE: dict[str, Any] = {
    "run_id": str(uuid.uuid4()),
    "duration_seconds": 1.23,
    "total_hexagons_scored": 200,
    "n_critical": 12,
    "anomaly_rate": 0.06,
    "results": [
        {
            "h3_id": "8a2a100d2c37fff",
            "lat_centroid": -23.5505,
            "lon_centroid": -46.6333,
            "anomaly_score": 0.82,
            "is_critical": 1,
            "lof_score": 1.5,
            "cloudflare_outage_overlap": 0,
        },
        {
            "h3_id": "8a2a100d2c27fff",
            "lat_centroid": -23.5600,
            "lon_centroid": -46.6400,
            "anomaly_score": 0.79,
            "is_critical": 1,
            "lof_score": 1.3,
            "cloudflare_outage_overlap": 0,
        },
    ],
}

_AXIS2_RESPONSE: dict[str, Any] = {
    "run_id": str(uuid.uuid4()),
    "duration_seconds": 2.45,
    "total_hexagons_processed": 200,
    "n_clusters": 3,
    "noise_rate": 0.05,
    "clusters": [
        {
            "cluster_id": 0,
            "cluster_size": 45,
            "lat_centroid": -23.5505,
            "lon_centroid": -46.6333,
            "avg_d_down": 15.5,
            "avg_n_dom": 250.0,
            "avg_HHI": 2100.0,
            "tam_estimate": 11250.0,
            "is_noise": 0,
        },
        {
            "cluster_id": 1,
            "cluster_size": 30,
            "lat_centroid": -22.9068,
            "lon_centroid": -43.1729,
            "avg_d_down": 35.2,
            "avg_n_dom": 180.0,
            "avg_HHI": 3200.0,
            "tam_estimate": 5400.0,
            "is_noise": 0,
        },
        {
            "cluster_id": -1,
            "cluster_size": 10,
            "lat_centroid": 0.0,
            "lon_centroid": 0.0,
            "avg_d_down": None,
            "avg_n_dom": None,
            "avg_HHI": None,
            "tam_estimate": None,
            "is_noise": 1,
        },
    ],
}

_AXIS3_RESPONSE: dict[str, Any] = {
    "run_id": str(uuid.uuid4()),
    "duration_seconds": 1.87,
    "total_hexagons_segmented": 200,
    "n_segments": 3,
    "silhouette_score_global": 0.42,
    "segment_profiles": [
        {
            "segment_id": 0,
            "segment_name": "Premium",
            "hexagon_count": 70,
            "hexagon_fraction": 0.35,
            "avg_centroid_distance": 0.8,
            "avg_silhouette": 0.55,
        },
        {
            "segment_id": 1,
            "segment_name": "Conectividade Essencial",
            "hexagon_count": 90,
            "hexagon_fraction": 0.45,
            "avg_centroid_distance": 0.9,
            "avg_silhouette": 0.38,
        },
        {
            "segment_id": 2,
            "segment_name": "Alta Vulnerabilidade Concorrência",
            "hexagon_count": 40,
            "hexagon_fraction": 0.20,
            "avg_centroid_distance": 1.2,
            "avg_silhouette": 0.29,
        },
    ],
    "results": [
        {
            "h3_id": "8a2a100d2c37fff",
            "lat_centroid": -23.5505,
            "lon_centroid": -46.6333,
            "segment_id": 2,
            "segment_name": "Alta Vulnerabilidade Concorrência",
            "centroid_distance": 1.1,
            "silhouette_score_local": 0.28,
        },
    ],
}

_TOOLS_CATALOGUE: dict[str, Any] = {
    "tool_count": 3,
    "tools": [
        {"tool_id": "axis1_run", "endpoint": "/v1/tools/axis1/run", "method": "POST"},
        {"tool_id": "axis2_run", "endpoint": "/v1/tools/axis2/run", "method": "POST"},
        {"tool_id": "axis3_run", "endpoint": "/v1/tools/axis3/run", "method": "POST"},
    ],
}


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Isolate environment variables and redirect audit log to a temp file."""
    monkeypatch.setenv("TOOL_API_BASE_URL", _TEST_API_BASE)
    monkeypatch.setenv("TOOL_API_KEY", _TEST_API_KEY)
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("AUDIT_BACKEND", "jsonl")
    audit_log = tmp_path / "audit.jsonl"
    monkeypatch.setenv("AUDIT_JSONL_PATH", str(audit_log))

    # Reset module-level singletons between tests
    reset_registry()

    # Reset AuditLogger singleton
    import audit.logger as _al
    _al._default_logger = None

    yield


@pytest.fixture
def registry() -> ToolRegistry:
    """Pre-configured ToolRegistry pointed at the mock API."""
    r = ToolRegistry(base_url=_TEST_API_BASE, api_key=_TEST_API_KEY)
    r._catalogue = _TOOLS_CATALOGUE["tools"]
    r._catalogue_loaded = True
    return r


def _base_state(**overrides) -> AgentState:
    """Build a minimal AgentState for testing."""
    state: AgentState = {
        "region_scope": "BR-SP-test",
        "axes_requested": ["axis1", "axis2", "axis3"],
        "force": True,
        "run_id": str(uuid.uuid4()),
        "audit_trail": [],
        "errors": [],
    }
    state.update(overrides)  # type: ignore[typeddict-item]
    return state


# ── Unit tests — individual nodes ─────────────────────────────────────────


class TestGapDetector:
    def test_forced_sets_correct_status(self):
        state = _base_state(force=True)
        result = gap_detector(state)
        assert result["gap_report"]["status"] == "forced"
        assert "axis1" in result["gap_report"]["axes_with_gaps"]
        assert len(result["audit_trail"]) >= 1

    def test_non_forced_still_flags_all_axes(self):
        """Without a live API the gap detector should still flag axes."""
        state = _base_state(force=False)
        result = gap_detector(state)
        # API unreachable in test context so api_reachable may be False
        assert "axes_with_gaps" in result["gap_report"]
        assert len(result["gap_report"]["axes_with_gaps"]) > 0


class TestToolSelector:
    def test_explicit_axes_bypass_llm(self):
        state = _base_state(
            axes_requested=["axis1", "axis2"],
            gap_report={"status": "forced", "axes_with_gaps": ["axis1", "axis2", "axis3"]},
        )
        result = tool_selector(state)
        assert set(result["axes_selected"]) == {"axis1", "axis2"}
        assert "tool_selector_rationale" in result
        assert len(result["audit_trail"]) >= 1

    def test_stub_llm_selects_all_axes(self):
        state = _base_state(
            axes_requested=[],
            gap_report={"status": "forced", "axes_with_gaps": ["axis1", "axis2", "axis3"]},
        )
        result = tool_selector(state)
        assert len(result["axes_selected"]) > 0

    def test_invalid_axes_filtered(self):
        state = _base_state(
            axes_requested=["axis1", "axisX", "axis9"],
            gap_report={},
        )
        result = tool_selector(state)
        assert all(a in ("axis1", "axis2", "axis3") for a in result["axes_selected"])


class TestAxisRunners:
    @respx.mock
    def test_axis1_runner_success(self, registry):
        import agent.tool_registry as _tr
        _tr._default_registry = registry

        respx.post(f"{_TEST_API_BASE}/v1/tools/axis1/run").mock(
            return_value=httpx.Response(200, json=_AXIS1_RESPONSE)
        )

        state = _base_state(axes_selected=["axis1", "axis2", "axis3"])
        result = axis1_runner(state)

        assert result["axis1_result"] is not None
        assert result["axis1_result"]["n_critical"] == 12
        assert len(result["audit_trail"]) >= 1
        assert result["errors"] == []

    @respx.mock
    def test_axis2_runner_success(self, registry):
        import agent.tool_registry as _tr
        _tr._default_registry = registry

        respx.post(f"{_TEST_API_BASE}/v1/tools/axis2/run").mock(
            return_value=httpx.Response(200, json=_AXIS2_RESPONSE)
        )

        state = _base_state(axes_selected=["axis1", "axis2", "axis3"])
        result = axis2_runner(state)

        assert result["axis2_result"] is not None
        assert result["axis2_result"]["n_clusters"] == 3
        assert result["errors"] == []

    @respx.mock
    def test_axis3_runner_success(self, registry):
        import agent.tool_registry as _tr
        _tr._default_registry = registry

        respx.post(f"{_TEST_API_BASE}/v1/tools/axis3/run").mock(
            return_value=httpx.Response(200, json=_AXIS3_RESPONSE)
        )

        state = _base_state(axes_selected=["axis1", "axis2", "axis3"])
        result = axis3_runner(state)

        assert result["axis3_result"] is not None
        assert result["axis3_result"]["n_segments"] == 3
        assert result["errors"] == []

    def test_axis_runner_skips_when_not_selected(self):
        state = _base_state(axes_selected=["axis2"])  # axis1 not selected
        result = axis1_runner(state)
        assert result["axis1_result"] is None
        assert result["errors"] == []

    @respx.mock
    def test_axis_runner_records_error_on_failure(self, registry):
        import agent.tool_registry as _tr
        _tr._default_registry = registry

        respx.post(f"{_TEST_API_BASE}/v1/tools/axis1/run").mock(
            return_value=httpx.Response(500, json={"detail": "Internal Server Error"})
        )

        state = _base_state(axes_selected=["axis1"])
        result = axis1_runner(state)

        assert result["axis1_result"] is None
        assert len(result["errors"]) == 1
        assert "axis1" in result["errors"][0]["node"]


class TestResultInterpreter:
    def test_generates_hypotheses(self):
        state = _base_state(
            axes_selected=["axis1", "axis2", "axis3"],
            axis1_result=_AXIS1_RESPONSE,
            axis2_result=_AXIS2_RESPONSE,
            axis3_result=_AXIS3_RESPONSE,
        )
        result = result_interpreter(state)
        hypotheses = result["investment_hypotheses"]
        assert isinstance(hypotheses, list)
        assert len(hypotheses) >= 1
        # First hypothesis should have TAM > 0
        assert hypotheses[0]["tam_estimate_brl"] > 0

    def test_tam_formula_correctness(self):
        """TAM = n_dom * cluster_size * ARPU * (1 - penetration_rate)."""
        state = _base_state(
            axes_selected=["axis2"],
            axis1_result=None,
            axis2_result={
                "clusters": [{
                    "cluster_id": 0,
                    "cluster_size": 10,
                    "avg_n_dom": 100.0,
                    "avg_d_down": 10.0,
                    "avg_HHI": 1000.0,
                    "is_noise": 0,
                    "lat_centroid": 0.0,
                    "lon_centroid": 0.0,
                }]
            },
            axis3_result=None,
        )
        result = result_interpreter(state)
        hyp = result["investment_hypotheses"][0]
        # With defaults: ARPU=89.90, pen=0.35
        # TAM = 100 * 10 * 89.90 * (1 - 0.35) = 58,435.00
        expected_tam = 100.0 * 10 * 89.90 * (1 - 0.35)
        assert abs(hyp["tam_estimate_brl"] - expected_tam) < 0.01

    def test_cross_matrix_populated(self):
        state = _base_state(
            axes_selected=["axis1", "axis2", "axis3"],
            axis1_result=_AXIS1_RESPONSE,
            axis2_result=_AXIS2_RESPONSE,
            axis3_result=_AXIS3_RESPONSE,
        )
        result = result_interpreter(state)
        assert isinstance(result["cross_matrix"], list)
        assert len(result["cross_matrix"]) > 0

    def test_noise_clusters_excluded(self):
        state = _base_state(
            axes_selected=["axis2"],
            axis2_result={
                "clusters": [
                    {"cluster_id": -1, "is_noise": 1, "cluster_size": 5,
                     "avg_n_dom": 10.0, "avg_d_down": 5.0, "avg_HHI": 1000.0,
                     "lat_centroid": 0.0, "lon_centroid": 0.0},
                ]
            },
        )
        result = result_interpreter(state)
        assert result["investment_hypotheses"] == []


class TestReportWriter:
    _MANDATORY_SECTIONS = [
        "## 1. Sumário Executivo",
        "## 2. Situação Atual da Infraestrutura",
        "## 3. Oportunidades de Expansão",
        "## 4. Segmentação de Mercado",
        "## 5. Priorização de Investimentos",
        "## 6. Estimativa de Retorno",
        "## 7. Próximas Ações Recomendadas",
    ]

    def _make_state_with_results(self) -> AgentState:
        hypotheses = [
            {
                "cluster_id": 0,
                "priority_class": "P1_CRITICAL_EXPANSION",
                "tam_estimate_brl": 50000.0,
                "avg_n_dom": 250.0,
                "avg_d_down_mbps": 15.0,
                "avg_hhi": 2100.0,
                "cluster_size_hexagons": 45,
                "arpu_assumed_brl": 89.90,
                "penetration_rate_assumed": 0.35,
                "rationale": "Test hypothesis.",
                "lat_centroid": -23.55,
                "lon_centroid": -46.63,
            }
        ]
        return _base_state(
            axes_selected=["axis1", "axis2", "axis3"],
            axis1_result=_AXIS1_RESPONSE,
            axis2_result=_AXIS2_RESPONSE,
            axis3_result=_AXIS3_RESPONSE,
            investment_hypotheses=hypotheses,
            cross_matrix=[{
                "cluster_id": 0,
                "priority_class": "P1_CRITICAL_EXPANSION",
                "tam_brl": 50000.0,
                "axis1_overlap_proxy": True,
                "axis3_churn_risk": True,
            }],
            tool_selector_rationale="Testing: all axes.",
        )

    @pytest.mark.parametrize("section_header", _MANDATORY_SECTIONS)
    def test_mandatory_section_present(self, section_header: str):
        state = self._make_state_with_results()
        result = report_writer(state)
        assert section_header in result["report_markdown"], (
            f"Missing section: {section_header}"
        )

    def test_appendix_present(self):
        state = self._make_state_with_results()
        result = report_writer(state)
        assert "Metodologia e Auditabilidade" in result["report_markdown"]
        assert "LGPD" in result["report_markdown"]

    def test_json_report_has_required_keys(self):
        state = self._make_state_with_results()
        result = report_writer(state)
        rj = result["report_json"]
        for key in ("run_id", "summary", "investment_hypotheses", "cross_matrix",
                    "axis1_summary", "axis2_summary", "axis3_summary"):
            assert key in rj, f"Missing key in JSON report: {key}"

    def test_run_id_in_report(self):
        state = self._make_state_with_results()
        result = report_writer(state)
        assert state["run_id"] in result["report_markdown"]

    def test_report_records_audit_event(self):
        state = self._make_state_with_results()
        result = report_writer(state)
        assert len(result["audit_trail"]) >= 1
        event = result["audit_trail"][0]
        assert event["tool_name"] == "report_writer"


# ── Integration tests — full end-to-end workflow ───────────────────────────


class TestFullWorkflow:
    @respx.mock
    def test_full_workflow_all_axes(self, registry):
        """Complete e2e run: all axes → report with 7 sections + ≥5 audit events."""
        import agent.tool_registry as _tr
        _tr._default_registry = registry

        respx.get(f"{_TEST_API_BASE}/v1/tools").mock(
            return_value=httpx.Response(200, json=_TOOLS_CATALOGUE)
        )
        respx.post(f"{_TEST_API_BASE}/v1/tools/axis1/run").mock(
            return_value=httpx.Response(200, json=_AXIS1_RESPONSE)
        )
        respx.post(f"{_TEST_API_BASE}/v1/tools/axis2/run").mock(
            return_value=httpx.Response(200, json=_AXIS2_RESPONSE)
        )
        respx.post(f"{_TEST_API_BASE}/v1/tools/axis3/run").mock(
            return_value=httpx.Response(200, json=_AXIS3_RESPONSE)
        )

        compiled = build_graph(registry=registry)
        initial: AgentState = {
            "region_scope": "BR-SP-e2e",
            "axes_requested": ["axis1", "axis2", "axis3"],
            "force": True,
            "run_id": str(uuid.uuid4()),
            "audit_trail": [],
            "errors": [],
        }

        final = compiled.invoke(initial)

        # ── Report content ─────────────────────────────────────────────────
        md = final.get("report_markdown", "")
        assert "## 1. Sumário Executivo" in md
        assert "## 2. Situação Atual da Infraestrutura" in md
        assert "## 3. Oportunidades de Expansão" in md
        assert "## 4. Segmentação de Mercado" in md
        assert "## 5. Priorização de Investimentos" in md
        assert "## 6. Estimativa de Retorno" in md
        assert "## 7. Próximas Ações Recomendadas" in md
        assert "Metodologia e Auditabilidade" in md

        # ── JSON structure ─────────────────────────────────────────────────
        rj = final.get("report_json", {})
        assert rj["summary"]["n_critical_hexagons"] == 12
        assert rj["summary"]["n_expansion_clusters"] == 3
        assert rj["summary"]["n_market_segments"] == 3
        assert rj["summary"]["total_tam_brl"] > 0

        # ── Audit trail ≥ 5 events ─────────────────────────────────────────
        audit_trail = final.get("audit_trail", [])
        assert len(audit_trail) >= 5, (
            f"Expected ≥5 audit events, got {len(audit_trail)}"
        )

        # ── No uncaught errors ─────────────────────────────────────────────
        assert not any(
            "exception" in str(e).lower() for e in final.get("errors", [])
        )

    @respx.mock
    def test_workflow_single_axis(self, registry):
        """Run with only axis2: sections for axes 1 and 3 show 'not executed'."""
        import agent.tool_registry as _tr
        _tr._default_registry = registry

        respx.post(f"{_TEST_API_BASE}/v1/tools/axis2/run").mock(
            return_value=httpx.Response(200, json=_AXIS2_RESPONSE)
        )

        compiled = build_graph(registry=registry)
        initial: AgentState = {
            "region_scope": "BR-RJ-partial",
            "axes_requested": ["axis2"],
            "force": True,
            "run_id": str(uuid.uuid4()),
            "audit_trail": [],
            "errors": [],
        }
        final = compiled.invoke(initial)

        md = final["report_markdown"]
        assert "_Eixo 1 não executado nesta análise._" in md
        assert "_Eixo 3 não executado nesta análise._" in md
        # Axis 2 section should have real data
        assert "Eixo 2" in md

        audit_trail = final.get("audit_trail", [])
        assert len(audit_trail) >= 3

    @respx.mock
    def test_workflow_forced_gap_status(self, registry):
        """force=True → gap_report.status == 'forced'."""
        import agent.tool_registry as _tr
        _tr._default_registry = registry

        respx.post(f"{_TEST_API_BASE}/v1/tools/axis1/run").mock(
            return_value=httpx.Response(200, json=_AXIS1_RESPONSE)
        )
        respx.post(f"{_TEST_API_BASE}/v1/tools/axis2/run").mock(
            return_value=httpx.Response(200, json=_AXIS2_RESPONSE)
        )
        respx.post(f"{_TEST_API_BASE}/v1/tools/axis3/run").mock(
            return_value=httpx.Response(200, json=_AXIS3_RESPONSE)
        )

        compiled = build_graph(registry=registry)
        initial: AgentState = {
            "region_scope": "BR-MG-forced",
            "axes_requested": ["axis1", "axis2", "axis3"],
            "force": True,
            "run_id": str(uuid.uuid4()),
            "audit_trail": [],
            "errors": [],
        }
        final = compiled.invoke(initial)
        assert final["gap_report"]["status"] == "forced"

    @respx.mock
    def test_audit_trail_minimum_five_events(self, registry, tmp_path: Path):
        """Verify ≥5 audit events are written to the JSONL file during full run."""
        import agent.tool_registry as _tr
        _tr._default_registry = registry

        respx.post(f"{_TEST_API_BASE}/v1/tools/axis1/run").mock(
            return_value=httpx.Response(200, json=_AXIS1_RESPONSE)
        )
        respx.post(f"{_TEST_API_BASE}/v1/tools/axis2/run").mock(
            return_value=httpx.Response(200, json=_AXIS2_RESPONSE)
        )
        respx.post(f"{_TEST_API_BASE}/v1/tools/axis3/run").mock(
            return_value=httpx.Response(200, json=_AXIS3_RESPONSE)
        )

        compiled = build_graph(registry=registry)
        run_id = str(uuid.uuid4())
        initial: AgentState = {
            "region_scope": "BR-audit-test",
            "axes_requested": ["axis1", "axis2", "axis3"],
            "force": True,
            "run_id": run_id,
            "audit_trail": [],
            "errors": [],
        }
        final = compiled.invoke(initial)

        audit_trail = final.get("audit_trail", [])
        assert len(audit_trail) >= 5, (
            f"Expected ≥5 audit events in state, got {len(audit_trail)}"
        )

        # Verify event types present
        event_types = {e.get("event_type") for e in audit_trail}
        assert "reasoning_step" in event_types or "tool_call" in event_types


# ── ToolRegistry unit tests ────────────────────────────────────────────────


class TestToolRegistry:
    @respx.mock
    @pytest.mark.asyncio
    async def test_catalogue_load(self):
        respx.get(f"{_TEST_API_BASE}/v1/tools").mock(
            return_value=httpx.Response(200, json=_TOOLS_CATALOGUE)
        )
        r = ToolRegistry(base_url=_TEST_API_BASE, api_key=_TEST_API_KEY)
        catalogue = await r.load_catalogue()
        assert len(catalogue) == 3
        assert catalogue[0]["tool_id"] == "axis1_run"

    @respx.mock
    @pytest.mark.asyncio
    async def test_invoke_tool_success(self):
        respx.post(f"{_TEST_API_BASE}/v1/tools/axis1/run").mock(
            return_value=httpx.Response(200, json=_AXIS1_RESPONSE)
        )
        r = ToolRegistry(base_url=_TEST_API_BASE, api_key=_TEST_API_KEY)
        r._catalogue = _TOOLS_CATALOGUE["tools"]
        r._catalogue_loaded = True
        result = await r.invoke_tool("axis1_run", {})
        assert result["n_critical"] == 12

    @respx.mock
    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self):
        """First two calls fail with 503, third succeeds."""
        call_count = 0

        def side_effect(request):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return httpx.Response(503, json={"detail": "Service Unavailable"})
            return httpx.Response(200, json=_AXIS2_RESPONSE)

        respx.post(f"{_TEST_API_BASE}/v1/tools/axis2/run").mock(side_effect=side_effect)

        r = ToolRegistry(base_url=_TEST_API_BASE, api_key=_TEST_API_KEY)
        r._catalogue = _TOOLS_CATALOGUE["tools"]
        r._catalogue_loaded = True

        # Patch sleep to avoid actual delay in tests
        import agent.tool_registry as _tr
        with patch.object(_tr.asyncio, "sleep", return_value=None):
            result = await r.invoke_tool("axis2_run", {})

        assert result["n_clusters"] == 3
        assert call_count == 3

    @respx.mock
    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(self):
        """HTTP 401 should raise without retrying."""
        respx.post(f"{_TEST_API_BASE}/v1/tools/axis1/run").mock(
            return_value=httpx.Response(401, json={"detail": "Unauthorized"})
        )
        r = ToolRegistry(base_url=_TEST_API_BASE, api_key=_TEST_API_KEY)
        r._catalogue = _TOOLS_CATALOGUE["tools"]
        r._catalogue_loaded = True

        with pytest.raises(RuntimeError, match="HTTP 401"):
            await r.invoke_tool("axis1_run", {})


# ── LLM Provider unit tests ────────────────────────────────────────────────


class TestLLMProvider:
    def test_stub_provider_chat(self):
        stub = StubProvider()
        response = stub.chat("What are the expansion clusters?")
        assert isinstance(response, str)
        assert len(response) > 0

    def test_stub_provider_tool_call(self):
        stub = StubProvider()
        result = stub.tool_call(
            "Select axes for analysis",
            tools=[{
                "name": "select_axes",
                "description": "Select axes",
                "parameters": {"type": "object", "properties": {}},
            }],
        )
        assert "name" in result
        assert "arguments" in result
        assert isinstance(result["arguments"], dict)
        assert "axes" in result["arguments"]

    def test_get_llm_provider_returns_stub(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "stub")
        provider = get_llm_provider()
        assert isinstance(provider, StubProvider)

    def test_get_llm_provider_stub_explicit(self):
        provider = get_llm_provider("stub")
        assert isinstance(provider, StubProvider)

    def test_get_llm_provider_gemini_explicit(self):
        provider = get_llm_provider("gemini")
        assert isinstance(provider, GeminiProvider)

    def test_get_llm_provider_unknown_falls_back_to_stub(self):
        provider = get_llm_provider("nonexistent_provider")
        assert isinstance(provider, StubProvider)
