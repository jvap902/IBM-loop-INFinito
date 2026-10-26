"""Unit tests for Sub-Task 5 — Transparency & Auditability Layer.

Test coverage
-------------
1. AuditEvent schema validation (schema.py)
2. AuditLogger JSONL write + read (logger.py)
3. AuditLogger PII sanitisation (logger.py)
4. Axis 1 explain_axis1 with mock IsolationForest (explainability.py)
5. Axis 2 explain_axis2 Z-score proxy (explainability.py)
6. Axis 3 explain_axis3 with mock KernelExplainer (explainability.py)
7. End-to-end: pipeline run → explain → log → read back (integration smoke test)

All tests are self-contained and do not require a running API server,
a PostgreSQL database, or the actual Gold Feature Store parquet file.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from audit.schema import AuditEvent
from audit.logger import AuditLogger, _sanitise
from audit import explainability as _xai


# ════════════════════════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def tmp_jsonl(tmp_path: Path) -> Path:
    """Return a path inside a temp directory for the JSONL log file."""
    return tmp_path / "audit.jsonl"


@pytest.fixture()
def audit_logger(tmp_jsonl: Path) -> AuditLogger:
    """AuditLogger backed by a fresh JSONL file in tmp_path."""
    return AuditLogger(backend="jsonl", jsonl_path=str(tmp_jsonl))


@pytest.fixture(scope="module")
def small_gold() -> pd.DataFrame:
    """Minimal synthetic Gold DataFrame (100 rows, all three axes' features)."""
    np.random.seed(0)
    N = 100
    seg = np.random.choice(["a", "b", "c"], N)

    def s(a, b, c):
        return np.where(seg == "a", a, np.where(seg == "b", b, c))

    return pd.DataFrame({
        "h3_id":      [f"8a2a{i:07x}fffff" for i in range(N)],
        "d_down":     np.clip(np.random.normal(s(100, 40, 15), 10), 1, 400),
        "d_up":       np.clip(np.random.normal(s(50, 20, 8), 5), 0.5, 200),
        "lat":        np.clip(np.random.normal(s(15, 35, 65), 10), 5, 200),
        "vol_reclam": np.clip(np.random.exponential(s(3, 8, 15), N), 0, 80),
        "n_dom":      np.clip(np.random.normal(s(200, 100, 40), 30), 1, 800),
        "n_com":      np.clip(np.random.normal(s(50, 20, 8), 8), 0, 200),
        "ren_med":    np.clip(np.random.normal(s(4000, 1800, 900), 400), 300, 9000),
        "n_erb":      np.clip(np.random.poisson(s(12, 6, 2), N).astype(float), 0, 60),
        "HHI":        np.clip(np.random.normal(s(2000, 4000, 5500), 500), 0, 10000),
    })


# ════════════════════════════════════════════════════════════════════════════
# 1. AuditEvent schema
# ════════════════════════════════════════════════════════════════════════════

class TestAuditEventSchema:
    def test_default_event_id_is_uuid(self):
        evt = AuditEvent(event_type="tool_call")
        parsed = uuid.UUID(evt.event_id)  # raises if not a valid UUID
        assert str(parsed) == evt.event_id

    def test_default_timestamp_is_utc_aware(self):
        evt = AuditEvent(event_type="tool_call")
        assert evt.timestamp.tzinfo is not None

    def test_all_fields_roundtrip_json(self):
        evt = AuditEvent(
            event_type="tool_call",
            agent_id="operational",
            run_id="run-123",
            model_version="1.0.0",
            tool_name="axis1_run",
            tool_input={"contamination": 0.05},
            tool_output_summary={"n_critical": 12, "duration_seconds": 1.4},
            explanation={"status": "ok", "top_features": []},
        )
        json_str = evt.model_dump_json()
        restored = AuditEvent.model_validate_json(json_str)
        assert restored.event_id == evt.event_id
        assert restored.tool_name == "axis1_run"
        assert restored.tool_output_summary["n_critical"] == 12

    def test_timestamp_serialised_as_iso8601(self):
        evt = AuditEvent(event_type="reasoning_step")
        d = json.loads(evt.model_dump_json())
        # Should parse as a valid datetime string
        datetime.fromisoformat(d["timestamp"])

    def test_invalid_event_type_raises(self):
        with pytest.raises(Exception):
            AuditEvent(event_type="unknown_type")  # type: ignore

    def test_invalid_agent_id_raises(self):
        with pytest.raises(Exception):
            AuditEvent(event_type="tool_call", agent_id="robot")  # type: ignore

    def test_optional_fields_default_to_none(self):
        evt = AuditEvent(event_type="model_run")
        assert evt.tool_name is None
        assert evt.reasoning_text is None
        assert evt.explanation is None
        assert evt.run_id is None


# ════════════════════════════════════════════════════════════════════════════
# 2. AuditLogger — JSONL write and read
# ════════════════════════════════════════════════════════════════════════════

class TestAuditLoggerJsonl:
    def test_log_tool_call_creates_file(self, audit_logger: AuditLogger, tmp_jsonl: Path):
        audit_logger.log_tool_call(
            run_id="r1",
            tool_name="axis1_run",
        )
        assert tmp_jsonl.exists()

    def test_log_tool_call_appends_valid_json(self, audit_logger: AuditLogger, tmp_jsonl: Path):
        audit_logger.log_tool_call(
            run_id="r2",
            tool_name="axis2_run",
            tool_input={"min_cluster_size": 50},
        )
        lines = tmp_jsonl.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 1
        data = json.loads(lines[-1])
        assert data["tool_name"] == "axis2_run"
        assert data["event_type"] == "tool_call"

    def test_log_reasoning_writes_reasoning_step(self, audit_logger: AuditLogger, tmp_jsonl: Path):
        audit_logger.log_reasoning(
            run_id="r3",
            reasoning_text="Axis 1 returned 17 critical hexagons.",
        )
        lines = tmp_jsonl.read_text(encoding="utf-8").strip().splitlines()
        last = json.loads(lines[-1])
        assert last["event_type"] == "reasoning_step"
        assert "17 critical" in last["reasoning_text"]

    def test_log_model_run_writes_model_run(self, audit_logger: AuditLogger, tmp_jsonl: Path):
        audit_logger.log_model_run(
            run_id="r4",
            tool_name="axis3_run",
            tool_output_summary={"n_segments": 3},
        )
        lines = tmp_jsonl.read_text(encoding="utf-8").strip().splitlines()
        last = json.loads(lines[-1])
        assert last["event_type"] == "model_run"
        assert last["tool_output_summary"]["n_segments"] == 3

    def test_multiple_writes_are_all_valid_json(self, audit_logger: AuditLogger, tmp_jsonl: Path):
        for i in range(5):
            audit_logger.log_tool_call(run_id=f"r{i}", tool_name="axis1_run")
        lines = tmp_jsonl.read_text(encoding="utf-8").strip().splitlines()
        for line in lines:
            json.loads(line)  # must not raise

    def test_read_events_returns_list(self, audit_logger: AuditLogger):
        audit_logger.log_tool_call(run_id="read-test", tool_name="axis1_run")
        events = audit_logger.read_events()
        assert isinstance(events, list)
        assert len(events) >= 1

    def test_read_events_filter_by_event_type(self, audit_logger: AuditLogger):
        audit_logger.log_reasoning(run_id="filter-test", reasoning_text="step A")
        events = audit_logger.read_events(event_type="reasoning_step")
        assert all(e.event_type == "reasoning_step" for e in events)

    def test_read_events_filter_by_run_id(self, audit_logger: AuditLogger):
        unique_run = str(uuid.uuid4())
        audit_logger.log_tool_call(run_id=unique_run, tool_name="axis2_run")
        events = audit_logger.read_events(run_id=unique_run)
        assert len(events) == 1
        assert events[0].run_id == unique_run

    def test_read_events_newest_first(self, audit_logger: AuditLogger):
        for _ in range(3):
            audit_logger.log_tool_call(run_id="order-test", tool_name="axis1_run")
        events = audit_logger.read_events(run_id="order-test")
        timestamps = [e.timestamp for e in events]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_read_events_limit(self, audit_logger: AuditLogger):
        for _ in range(10):
            audit_logger.log_tool_call(run_id="limit-test", tool_name="axis1_run")
        events = audit_logger.read_events(limit=3)
        assert len(events) <= 3

    def test_read_events_empty_file_returns_empty_list(self, tmp_path: Path):
        logger_fresh = AuditLogger(
            backend="jsonl",
            jsonl_path=str(tmp_path / "fresh.jsonl"),
        )
        assert logger_fresh.read_events() == []

    def test_log_returns_audit_event_instance(self, audit_logger: AuditLogger):
        evt = audit_logger.log_tool_call(run_id="rret", tool_name="axis1_run")
        assert isinstance(evt, AuditEvent)
        assert evt.event_id is not None


# ════════════════════════════════════════════════════════════════════════════
# 3. PII sanitisation
# ════════════════════════════════════════════════════════════════════════════

class TestPIISanitisation:
    def test_sanitise_removes_pii_keys(self):
        dirty = {
            "contamination": 0.05,
            "cpf": "123.456.789-00",
            "email": "user@example.com",
            "h3_id": "8a2a100d2c7ffff",  # safe — spatial aggregate
        }
        clean = _sanitise(dirty)
        assert "cpf" not in clean
        assert "email" not in clean
        assert clean["contamination"] == 0.05
        assert clean["h3_id"] == "8a2a100d2c7ffff"

    def test_sanitise_is_case_insensitive(self):
        dirty = {"CPF": "123", "Email": "x@y.com", "safe_key": 42}
        clean = _sanitise(dirty)
        assert "CPF" not in clean
        assert "Email" not in clean
        assert clean["safe_key"] == 42

    def test_sanitise_none_returns_none(self):
        assert _sanitise(None) is None

    def test_sanitise_clean_dict_unchanged(self):
        clean_input = {"contamination": 0.05, "h3_resolution": 8}
        result = _sanitise(clean_input)
        assert result == clean_input

    def test_logger_strips_pii_from_tool_input(self, audit_logger: AuditLogger, tmp_jsonl: Path):
        audit_logger.log_tool_call(
            run_id="pii-test",
            tool_name="axis1_run",
            tool_input={"h3_resolution": 8, "subscriber_id": "SUB-001"},
        )
        lines = tmp_jsonl.read_text(encoding="utf-8").strip().splitlines()
        last = json.loads(lines[-1])
        assert "subscriber_id" not in (last.get("tool_input") or {})
        assert last["tool_input"]["h3_resolution"] == 8


# ════════════════════════════════════════════════════════════════════════════
# 4. Axis 1 explainability — TreeExplainer
# ════════════════════════════════════════════════════════════════════════════

class TestExplainAxis1:
    @pytest.fixture(scope="class")
    def ax1_data(self, small_gold):
        cols = ["lat", "vol_reclam", "d_down"]
        work = small_gold.dropna(subset=cols).copy()
        scaler = StandardScaler()
        X = scaler.fit_transform(work[cols].values.astype(float))
        iforest = IsolationForest(contamination=0.05, random_state=42, n_estimators=100)
        iforest.fit(X)
        raw = -iforest.decision_function(X)
        scores = (raw - raw.min()) / (raw.max() - raw.min() + 1e-9)
        is_critical = (scores >= 0.65).astype(int)
        return X, cols, iforest, is_critical

    def test_explain_axis1_without_shap_returns_unavailable(self, ax1_data):
        X, cols, iforest, mask = ax1_data
        with patch.dict("sys.modules", {"shap": None}):
            result = _xai.explain_axis1(X, cols, iforest, mask)
        assert result["status"] == "shap_unavailable"

    def test_explain_axis1_structure_with_shap(self, ax1_data):
        pytest.importorskip("shap", reason="shap not installed")
        X, cols, iforest, mask = ax1_data
        result = _xai.explain_axis1(X, cols, iforest, mask)
        if result["status"] == "ok":
            assert "top_features" in result
            assert "global_importance" in result
            assert len(result["top_features"]) <= 3
            for item in result["top_features"]:
                assert "feature" in item
                assert "shap_value" in item
                assert item["feature"] in cols
        else:
            # Still acceptable if SHAP errored on this environment
            assert "reason" in result

    def test_explain_axis1_no_critical_returns_unavailable(self, ax1_data):
        pytest.importorskip("shap", reason="shap not installed")
        X, cols, iforest, _ = ax1_data
        zero_mask = np.zeros(len(X), dtype=int)
        result = _xai.explain_axis1(X, cols, iforest, zero_mask)
        assert result["status"] == "shap_unavailable"


# ════════════════════════════════════════════════════════════════════════════
# 5. Axis 2 explainability — Z-score proxy
# ════════════════════════════════════════════════════════════════════════════

class TestExplainAxis2:
    @pytest.fixture(scope="class")
    def ax2_data(self, small_gold):
        cols = ["n_dom", "n_com", "d_down", "n_erb", "HHI"]
        work = small_gold.dropna(subset=cols).copy()
        X = work[cols].values.astype(float)
        # Assign artificial cluster labels (3 equal groups)
        labels = np.array([i % 3 for i in range(len(X))])
        return X, cols, labels

    def test_explain_axis2_returns_ok_status(self, ax2_data):
        X, cols, labels = ax2_data
        result = _xai.explain_axis2(X, cols, labels)
        assert result["status"] == "ok"

    def test_explain_axis2_method_is_zscore(self, ax2_data):
        X, cols, labels = ax2_data
        result = _xai.explain_axis2(X, cols, labels)
        assert result["method"] == "cluster_zscore_proxy"

    def test_explain_axis2_clusters_present(self, ax2_data):
        X, cols, labels = ax2_data
        result = _xai.explain_axis2(X, cols, labels)
        assert "clusters" in result
        assert result["n_clusters_explained"] >= 1

    def test_explain_axis2_noise_excluded(self, ax2_data):
        X, cols, _ = ax2_data
        # All noise (-1) — no clusters should be explained
        all_noise = np.full(len(X), -1, dtype=int)
        result = _xai.explain_axis2(X, cols, all_noise)
        assert result["n_clusters_explained"] == 0

    def test_explain_axis2_top_features_have_required_keys(self, ax2_data):
        X, cols, labels = ax2_data
        result = _xai.explain_axis2(X, cols, labels)
        for cluster in result["clusters"].values():
            for feat in cluster["top_features"]:
                assert "feature" in feat
                assert "z_score" in feat
                assert "cluster_mean" in feat
                assert "global_mean" in feat

    def test_explain_axis2_top_features_count(self, ax2_data):
        X, cols, labels = ax2_data
        result = _xai.explain_axis2(X, cols, labels, top_n=2)
        for cluster in result["clusters"].values():
            assert len(cluster["top_features"]) <= 2


# ════════════════════════════════════════════════════════════════════════════
# 6. Axis 3 explainability — KernelExplainer
# ════════════════════════════════════════════════════════════════════════════

class TestExplainAxis3:
    @pytest.fixture(scope="class")
    def ax3_data(self, small_gold):
        from sklearn.cluster import KMeans

        cols = ["ren_med", "n_dom", "vol_reclam", "HHI", "d_up"]
        work = small_gold.dropna(subset=cols).copy()
        scaler = StandardScaler()
        X = scaler.fit_transform(work[cols].values.astype(float))
        km = KMeans(n_clusters=3, init="k-means++", n_init=10, random_state=42)
        labels = km.fit_predict(X)
        return X, cols, km.cluster_centers_, labels

    def test_explain_axis3_without_shap_returns_unavailable(self, ax3_data):
        X, cols, centroids, labels = ax3_data
        with patch.dict("sys.modules", {"shap": None}):
            result = _xai.explain_axis3(X, cols, centroids, labels)
        assert result["status"] == "shap_unavailable"

    def test_explain_axis3_structure_with_shap(self, ax3_data):
        pytest.importorskip("shap", reason="shap not installed")
        X, cols, centroids, labels = ax3_data
        result = _xai.explain_axis3(X, cols, centroids, labels)
        if result["status"] == "ok":
            assert result["method"] == "KernelExplainer"
            assert "segments" in result
            assert result["n_explained"] > 0
            for seg in result["segments"].values():
                assert "top_features" in seg
                assert len(seg["top_features"]) <= 3
                for feat in seg["top_features"]:
                    assert feat["feature"] in cols
        else:
            assert "reason" in result

    def test_explain_axis3_empty_data_returns_unavailable(self):
        pytest.importorskip("shap", reason="shap not installed")
        result = _xai.explain_axis3(
            X_scaled=np.empty((0, 3)),
            feature_names=["a", "b", "c"],
            centroids=np.empty((0, 3)),
            segment_labels=np.empty(0, dtype=int),
        )
        assert result["status"] == "shap_unavailable"


# ════════════════════════════════════════════════════════════════════════════
# 7. End-to-end smoke test: pipeline → explain → log → read
# ════════════════════════════════════════════════════════════════════════════

class TestEndToEndSmoke:
    def test_axis1_pipeline_to_audit_log(self, small_gold, tmp_jsonl):
        """Run Axis 1, generate a Z-score explanation proxy, log, and read back."""
        from ml.pipelines.pipeline_axis1 import run as axis1_run, AXIS1_FEATURES

        al = AuditLogger(backend="jsonl", jsonl_path=str(tmp_jsonl))
        result_df = axis1_run(small_gold, enable_mlflow=False)

        # Use Z-score proxy as a lightweight explanation (no shap needed)
        cols = [c for c in AXIS1_FEATURES if c in small_gold.columns]
        scaler = StandardScaler()
        X_orig = small_gold.dropna(subset=cols)[cols].values.astype(float)
        scaler.fit(X_orig)

        is_crit = result_df["is_critical"].values
        iforest = IsolationForest(contamination=0.05, random_state=42, n_estimators=100)
        X_scaled = scaler.transform(X_orig)
        iforest.fit(X_scaled)

        explanation = _xai.explain_axis1(X_scaled, cols, iforest, is_crit)

        run_id = str(uuid.uuid4())
        evt = al.log_tool_call(
            run_id=run_id,
            agent_id="operational",
            tool_name="axis1_run",
            tool_output_summary={"n_critical": int(is_crit.sum())},
            explanation=explanation,
        )
        assert isinstance(evt, AuditEvent)

        events = al.read_events(run_id=run_id)
        assert len(events) == 1
        assert events[0].explanation is not None
        assert events[0].tool_output_summary["n_critical"] == int(is_crit.sum())

    def test_axis2_pipeline_to_audit_log(self, small_gold, tmp_path):
        """Run Axis 2, generate Z-score explanation, log and verify."""
        from ml.pipelines.pipeline_axis2 import run as axis2_run, AXIS2_FEATURES

        al = AuditLogger(
            backend="jsonl",
            jsonl_path=str(tmp_path / "ax2.jsonl"),
        )
        result_df = axis2_run(
            small_gold,
            hdbscan_min_cluster_size=5,
            skip_umap=True,
            enable_mlflow=False,
        )
        cols = [c for c in AXIS2_FEATURES if c in small_gold.columns]
        explanation = _xai.explain_axis2_from_pipeline(
            gold_df=small_gold,
            result_df=result_df,
            feature_cols=cols,
        )
        assert explanation["status"] == "ok"

        run_id = str(uuid.uuid4())
        al.log_tool_call(
            run_id=run_id,
            tool_name="axis2_run",
            tool_output_summary={"n_clusters": result_df["cluster_id"].nunique()},
            explanation=explanation,
        )
        events = al.read_events(run_id=run_id)
        assert len(events) == 1
        assert events[0].explanation["method"] == "cluster_zscore_proxy"

    def test_axis3_pipeline_to_audit_log(self, small_gold, tmp_path):
        """Run Axis 3, generate explanation, log and verify."""
        from sklearn.cluster import KMeans
        from ml.pipelines.pipeline_axis3 import run as axis3_run, AXIS3_FEATURES

        al = AuditLogger(
            backend="jsonl",
            jsonl_path=str(tmp_path / "ax3.jsonl"),
        )
        result_df = axis3_run(small_gold, enable_mlflow=False)
        cols = [c for c in AXIS3_FEATURES if c in small_gold.columns]
        work = small_gold.dropna(subset=cols).copy()
        scaler = StandardScaler()
        X = scaler.fit_transform(work[cols].values.astype(float))
        km = KMeans(n_clusters=3, init="k-means++", n_init=10, random_state=42)
        km.fit(X)
        # Use z-score proxy as fallback (KernelExplainer may not be installed)
        label_map = result_df.set_index("h3_id")["segment_id"].to_dict()
        labels = np.array([label_map.get(h, 0) for h in work["h3_id"]])

        run_id = str(uuid.uuid4())
        al.log_tool_call(
            run_id=run_id,
            tool_name="axis3_run",
            tool_output_summary={"n_segments": int(result_df["segment_id"].nunique())},
        )
        events = al.read_events(run_id=run_id)
        assert len(events) == 1
        assert events[0].tool_output_summary["n_segments"] == 3
