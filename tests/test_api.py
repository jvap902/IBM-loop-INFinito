"""Integration tests for Sub-Task 4 — Tool API Layer.

Tests use ``httpx.AsyncClient`` + FastAPI's ``ASGITransport`` (no live server
required) and mock the ML pipelines + Gold Feature Store so tests are fast and
self-contained.

Coverage
--------
* GET  /health                     — always returns 200
* GET  /v1/tools                   — always returns catalogue (no auth)
* POST /v1/tools/axis1/run         — valid request, invalid request, auth cases
* POST /v1/tools/axis1/crossvalidate — valid + missing CF token
* POST /v1/tools/axis2/run         — valid, invalid region, cluster error
* POST /v1/tools/axis3/run         — valid, resolution out of range, auth
* Auth middleware                  — missing key → 401, wrong key → 403

All ML calls are patched via ``unittest.mock.patch`` to return minimal
synthetic DataFrames so no Gold Parquet file is needed.
"""
from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio
import httpx
from fastapi.testclient import TestClient

# ── App import ─────────────────────────────────────────────────────────────
from api.main import app

# ── Test API key ───────────────────────────────────────────────────────────
_TEST_KEY = "test-api-key-secret"
_VALID_HEADERS = {"X-API-Key": _TEST_KEY}


@pytest.fixture(autouse=True)
def set_api_key(monkeypatch: pytest.MonkeyPatch):
    """Inject a known API key for every test in this module."""
    monkeypatch.setenv("TOOL_API_KEY", _TEST_KEY)


# ── Synthetic DataFrames ───────────────────────────────────────────────────

def _make_gold_df(n: int = 50) -> pd.DataFrame:
    """Minimal Gold Feature Store DataFrame for pipeline mocking."""
    np.random.seed(0)
    return pd.DataFrame({
        "h3_id":      [f"8a2a{i:07x}fffff" for i in range(n)],
        "d_down":     np.random.uniform(5, 120, n),
        "d_up":       np.random.uniform(2, 60, n),
        "lat":        np.random.uniform(5, 80, n),
        "vol_test":   np.random.uniform(1, 20, n),
        "n_dom":      np.random.uniform(10, 500, n),
        "n_com":      np.random.uniform(1, 100, n),
        "ren_med":    np.random.uniform(500, 5000, n),
        "n_erb":      np.random.uniform(0, 20, n),
        "HHI":        np.random.uniform(1000, 8000, n),
        "vol_reclam": np.random.uniform(0, 30, n),
        "h3_res":     [8] * n,
    })


def _make_axis1_output(n: int = 50) -> pd.DataFrame:
    np.random.seed(1)
    labels = np.zeros(n, dtype=int)
    labels[:5] = 1  # 5 critical  → 10 % rate, inside [1 %, 15 %]
    scores = np.where(labels == 1,
                      np.random.uniform(0.65, 1.0, n),
                      np.random.uniform(0.0, 0.64, n))
    return pd.DataFrame({
        "h3_id":                   [f"8a2a{i:07x}fffff" for i in range(n)],
        "anomaly_score":           np.round(scores, 6),
        "is_critical":             labels,
        "lof_score":               np.random.uniform(0, 1, n).round(6),
        "cloudflare_outage_overlap": np.zeros(n, dtype=int),
    })


def _make_axis2_output(n: int = 50) -> pd.DataFrame:
    np.random.seed(2)
    cluster_ids = np.random.choice([0, 1, 2], size=n)
    return pd.DataFrame({
        "h3_id":       [f"8a2a{i:07x}fffff" for i in range(n)],
        "cluster_id":  cluster_ids.astype(int),
        "cluster_size": np.where(cluster_ids >= 0, 15, 1),
        "avg_d_down":  np.random.uniform(5, 80, n).round(4),
        "avg_n_dom":   np.random.uniform(50, 400, n).round(4),
        "avg_HHI":     np.random.uniform(1000, 7000, n).round(4),
        "is_noise":    np.zeros(n, dtype=int),
    })


def _make_axis3_output(n: int = 50) -> pd.DataFrame:
    np.random.seed(3)
    seg_ids = np.random.choice([0, 1, 2], size=n)
    seg_names_map = {
        0: "Alta Vulnerabilidade Concorrencia",
        1: "Premium",
        2: "Conectividade Essencial",
    }
    return pd.DataFrame({
        "h3_id":                [f"8a2a{i:07x}fffff" for i in range(n)],
        "segment_id":           seg_ids.astype(int),
        "segment_name":         [seg_names_map[s] for s in seg_ids],
        "centroid_distance":    np.random.uniform(0, 3, n).round(6),
        "silhouette_score_local": np.random.uniform(-0.1, 0.9, n).round(6),
    })


# ── Test client fixture ────────────────────────────────────────────────────

@pytest.fixture
def client() -> TestClient:
    """Synchronous test client — sufficient for most endpoint tests."""
    return TestClient(app, raise_server_exceptions=True)


# ═══════════════════════════════════════════════════════════════════════════
# Health & Discovery
# ═══════════════════════════════════════════════════════════════════════════

class TestHealth:
    def test_health_ok(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_no_auth_required(self, client: TestClient):
        """Health endpoint must not require authentication."""
        resp = client.get("/health")
        assert resp.status_code == 200


class TestToolCatalogue:
    def test_returns_200(self, client: TestClient):
        resp = client.get("/v1/tools")
        assert resp.status_code == 200

    def test_no_auth_required(self, client: TestClient):
        """GET /tools is publicly accessible."""
        resp = client.get("/v1/tools", headers={})
        assert resp.status_code == 200

    def test_catalogue_structure(self, client: TestClient):
        data = client.get("/v1/tools").json()
        assert "tools" in data
        assert "tool_count" in data
        assert data["tool_count"] == len(data["tools"])
        assert data["tool_count"] >= 4  # axis1_run, axis1_cv, axis2_run, axis3_run

    def test_tool_fields(self, client: TestClient):
        tools = client.get("/v1/tools").json()["tools"]
        for tool in tools:
            assert "tool_id" in tool
            assert "name" in tool
            assert "endpoint" in tool
            assert "method" in tool
            assert "parameters" in tool

    def test_tool_ids(self, client: TestClient):
        ids = {t["tool_id"] for t in client.get("/v1/tools").json()["tools"]}
        assert "axis1_run" in ids
        assert "axis1_crossvalidate" in ids
        assert "axis2_run" in ids
        assert "axis3_run" in ids


# ═══════════════════════════════════════════════════════════════════════════
# Authentication
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthentication:
    """Verify that run endpoints enforce X-API-Key correctly."""

    def test_missing_key_returns_401(self, client: TestClient):
        with (
            patch("api.routes.tools.os.path.exists", return_value=True),
            patch("api.routes.tools._load_gold", return_value=_make_gold_df()),
            patch("api.routes.tools.pipeline_axis1.run", return_value=_make_axis1_output()),
        ):
            resp = client.post("/v1/tools/axis1/run", json={})
            assert resp.status_code == 401

    def test_wrong_key_returns_403(self, client: TestClient):
        with (
            patch("api.routes.tools._load_gold", return_value=_make_gold_df()),
            patch("api.routes.tools.pipeline_axis1.run", return_value=_make_axis1_output()),
        ):
            resp = client.post(
                "/v1/tools/axis1/run",
                json={},
                headers={"X-API-Key": "completely-wrong-key"},
            )
            assert resp.status_code == 403

    def test_valid_key_is_accepted(self, client: TestClient):
        with (
            patch("api.routes.tools._load_gold", return_value=_make_gold_df()),
            patch("api.routes.tools.pipeline_axis1.run", return_value=_make_axis1_output()),
        ):
            resp = client.post(
                "/v1/tools/axis1/run",
                json={},
                headers=_VALID_HEADERS,
            )
            # 200 or 422 (validation) — not 401/403
            assert resp.status_code not in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════
# Axis 1 — /tools/axis1/run
# ═══════════════════════════════════════════════════════════════════════════

class TestAxis1Run:
    @patch("api.routes.tools.pipeline_axis1.run", return_value=_make_axis1_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_valid_request_returns_200(self, mock_gold, mock_run, client: TestClient):
        resp = client.post(
            "/v1/tools/axis1/run",
            json={"anomaly_threshold": 0.65, "top_n": 10},
            headers=_VALID_HEADERS,
        )
        assert resp.status_code == 200

    @patch("api.routes.tools.pipeline_axis1.run", return_value=_make_axis1_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_response_schema(self, mock_gold, mock_run, client: TestClient):
        resp = client.post("/v1/tools/axis1/run", json={}, headers=_VALID_HEADERS)
        data = resp.json()
        assert "run_id" in data
        assert "axis" in data
        assert data["axis"] == "axis1"
        assert "results" in data
        assert "total_hexagons_scored" in data
        assert "n_critical" in data
        assert "anomaly_rate" in data

    @patch("api.routes.tools.pipeline_axis1.run", return_value=_make_axis1_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_top_n_limits_results(self, mock_gold, mock_run, client: TestClient):
        resp = client.post(
            "/v1/tools/axis1/run",
            json={"top_n": 2},
            headers=_VALID_HEADERS,
        )
        data = resp.json()
        assert len(data["results"]) <= 2

    @patch("api.routes.tools.pipeline_axis1.run", return_value=_make_axis1_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_result_has_geo_fields(self, mock_gold, mock_run, client: TestClient):
        resp = client.post("/v1/tools/axis1/run", json={}, headers=_VALID_HEADERS)
        for row in resp.json()["results"]:
            assert "h3_id" in row
            assert "lat_centroid" in row
            assert "lon_centroid" in row

    def test_invalid_resolution_returns_422(self, client: TestClient):
        resp = client.post(
            "/v1/tools/axis1/run",
            json={"h3_resolution": 7},
            headers=_VALID_HEADERS,
        )
        assert resp.status_code == 422

    def test_threshold_out_of_range_returns_422(self, client: TestClient):
        resp = client.post(
            "/v1/tools/axis1/run",
            json={"anomaly_threshold": 1.5},
            headers=_VALID_HEADERS,
        )
        assert resp.status_code == 422

    @patch("api.routes.tools._load_gold")
    def test_pipeline_value_error_returns_422(self, mock_gold, client: TestClient):
        mock_gold.return_value = _make_gold_df()
        with patch(
            "api.routes.tools.pipeline_axis1.run",
            side_effect=ValueError("No features found"),
        ):
            resp = client.post("/v1/tools/axis1/run", json={}, headers=_VALID_HEADERS)
        assert resp.status_code == 422

    @patch("api.routes.tools._load_gold")
    def test_pipeline_runtime_error_returns_500(self, mock_gold, client: TestClient):
        mock_gold.return_value = _make_gold_df()
        with patch(
            "api.routes.tools.pipeline_axis1.run",
            side_effect=RuntimeError("Unexpected ML failure"),
        ):
            resp = client.post("/v1/tools/axis1/run", json={}, headers=_VALID_HEADERS)
        assert resp.status_code == 500

    def test_gold_not_found_returns_404(self, client: TestClient):
        with patch("api.routes.tools._load_gold", side_effect=lambda *a, **kw: (_ for _ in ()).throw(
            __import__("fastapi").HTTPException(status_code=404, detail="Gold not found")
        )):
            resp = client.post("/v1/tools/axis1/run", json={}, headers=_VALID_HEADERS)
        assert resp.status_code == 404

    @patch("api.routes.tools.pipeline_axis1.run", return_value=_make_axis1_output())
    @patch("api.routes.tools._load_gold")
    def test_empty_region_filter_returns_400(self, mock_gold, mock_run, client: TestClient):
        from fastapi import HTTPException
        mock_gold.side_effect = HTTPException(
            status_code=400,
            detail="The applied region_filter produced an empty dataset.",
        )
        resp = client.post(
            "/v1/tools/axis1/run",
            json={"region_filter": ["invalid_h3_parent"]},
            headers=_VALID_HEADERS,
        )
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# Axis 1 — /tools/axis1/crossvalidate
# ═══════════════════════════════════════════════════════════════════════════

class TestAxis1CrossValidate:
    @patch("api.routes.tools.pipeline_axis1.run", return_value=_make_axis1_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_valid_request_returns_200(self, mock_gold, mock_run, client: TestClient):
        resp = client.post(
            "/v1/tools/axis1/crossvalidate",
            json={"date_start": "2024-01-01", "date_end": "2024-01-31"},
            headers=_VALID_HEADERS,
        )
        assert resp.status_code == 200

    @patch("api.routes.tools.pipeline_axis1.run", return_value=_make_axis1_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_response_schema(self, mock_gold, mock_run, client: TestClient):
        resp = client.post(
            "/v1/tools/axis1/crossvalidate",
            json={"date_start": "2024-01-01", "date_end": "2024-01-31"},
            headers=_VALID_HEADERS,
        )
        data = resp.json()
        assert "run_id" in data
        assert "agreement_rate" in data
        assert "n_cloudflare_outages_fetched" in data
        assert "overlapping_events" in data

    @patch("api.routes.tools.pipeline_axis1.run", return_value=_make_axis1_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_no_cf_token_still_returns_200(
        self, mock_gold, mock_run, monkeypatch: pytest.MonkeyPatch, client: TestClient
    ):
        """When CLOUDFLARE_API_TOKEN is absent, endpoint returns empty overlap list."""
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
        resp = client.post(
            "/v1/tools/axis1/crossvalidate",
            json={"date_start": "2024-01-01", "date_end": "2024-01-31"},
            headers=_VALID_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["n_cloudflare_outages_fetched"] == 0

    def test_missing_dates_returns_422(self, client: TestClient):
        resp = client.post(
            "/v1/tools/axis1/crossvalidate",
            json={},
            headers=_VALID_HEADERS,
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# Axis 2 — /tools/axis2/run
# ═══════════════════════════════════════════════════════════════════════════

class TestAxis2Run:
    @patch("api.routes.tools.pipeline_axis2.run", return_value=_make_axis2_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_valid_request_returns_200(self, mock_gold, mock_run, client: TestClient):
        resp = client.post(
            "/v1/tools/axis2/run",
            json={"min_cluster_size": 5},
            headers=_VALID_HEADERS,
        )
        assert resp.status_code == 200

    @patch("api.routes.tools.pipeline_axis2.run", return_value=_make_axis2_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_response_schema(self, mock_gold, mock_run, client: TestClient):
        resp = client.post("/v1/tools/axis2/run", json={}, headers=_VALID_HEADERS)
        data = resp.json()
        assert "run_id" in data
        assert "clusters" in data
        assert "n_clusters" in data
        assert "noise_rate" in data

    @patch("api.routes.tools.pipeline_axis2.run", return_value=_make_axis2_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_cluster_has_geo_and_tam(self, mock_gold, mock_run, client: TestClient):
        resp = client.post("/v1/tools/axis2/run", json={}, headers=_VALID_HEADERS)
        for cluster in resp.json()["clusters"]:
            assert "lat_centroid" in cluster
            assert "lon_centroid" in cluster
            assert "cluster_id" in cluster
            assert "cluster_size" in cluster

    def test_invalid_resolution_returns_422(self, client: TestClient):
        resp = client.post(
            "/v1/tools/axis2/run",
            json={"h3_resolution": 10},
            headers=_VALID_HEADERS,
        )
        assert resp.status_code == 422

    @patch("api.routes.tools._load_gold")
    def test_pipeline_value_error_returns_422(self, mock_gold, client: TestClient):
        mock_gold.return_value = _make_gold_df()
        with patch(
            "api.routes.tools.pipeline_axis2.run",
            side_effect=ValueError("No axis2 features"),
        ):
            resp = client.post("/v1/tools/axis2/run", json={}, headers=_VALID_HEADERS)
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# Axis 3 — /tools/axis3/run
# ═══════════════════════════════════════════════════════════════════════════

class TestAxis3Run:
    @patch("api.routes.tools.pipeline_axis3.run", return_value=_make_axis3_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_valid_request_returns_200(self, mock_gold, mock_run, client: TestClient):
        resp = client.post(
            "/v1/tools/axis3/run",
            json={"n_clusters": 3},
            headers=_VALID_HEADERS,
        )
        assert resp.status_code == 200

    @patch("api.routes.tools.pipeline_axis3.run", return_value=_make_axis3_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_response_schema(self, mock_gold, mock_run, client: TestClient):
        resp = client.post("/v1/tools/axis3/run", json={}, headers=_VALID_HEADERS)
        data = resp.json()
        assert "run_id" in data
        assert "segment_profiles" in data
        assert "results" in data
        assert "n_segments" in data

    @patch("api.routes.tools.pipeline_axis3.run", return_value=_make_axis3_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_result_has_geo_fields(self, mock_gold, mock_run, client: TestClient):
        resp = client.post("/v1/tools/axis3/run", json={}, headers=_VALID_HEADERS)
        for row in resp.json()["results"]:
            assert "h3_id" in row
            assert "lat_centroid" in row
            assert "lon_centroid" in row
            assert "segment_id" in row
            assert "segment_name" in row

    @patch("api.routes.tools.pipeline_axis3.run", return_value=_make_axis3_output())
    @patch("api.routes.tools._load_gold", return_value=_make_gold_df())
    def test_segment_profiles_coverage(self, mock_gold, mock_run, client: TestClient):
        resp = client.post("/v1/tools/axis3/run", json={}, headers=_VALID_HEADERS)
        profiles = resp.json()["segment_profiles"]
        total_fraction = sum(p["hexagon_fraction"] for p in profiles)
        assert abs(total_fraction - 1.0) < 0.01  # fractions sum to 1

    def test_n_clusters_out_of_range_returns_422(self, client: TestClient):
        resp = client.post(
            "/v1/tools/axis3/run",
            json={"n_clusters": 11},
            headers=_VALID_HEADERS,
        )
        assert resp.status_code == 422

    def test_missing_auth_returns_401(self, client: TestClient):
        resp = client.post("/v1/tools/axis3/run", json={})
        assert resp.status_code == 401

    @patch("api.routes.tools._load_gold")
    def test_pipeline_value_error_returns_422(self, mock_gold, client: TestClient):
        mock_gold.return_value = _make_gold_df()
        with patch(
            "api.routes.tools.pipeline_axis3.run",
            side_effect=ValueError("No axis3 features"),
        ):
            resp = client.post("/v1/tools/axis3/run", json={}, headers=_VALID_HEADERS)
        assert resp.status_code == 422
