"""Unit tests for ml/eda_utils.py and ml/baseline_runners.py (Sub-Task 2)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.eda_utils import (
    compute_correlation_matrix,
    compute_vif,
    pca_explained_variance,
    silhouette,
    X_HI_COLUMNS,
)
from ml.baseline_runners import (
    run_axis1_baseline,
    run_axis2_baseline,
    run_axis3_baseline,
    run_all_baselines,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def synthetic_gold() -> pd.DataFrame:
    """Small but realistic synthetic Gold DataFrame (300 rows, 3 segments)."""
    np.random.seed(0)
    N = 300
    seg = np.random.choice(["premium", "mid", "low"], size=N, p=[0.3, 0.4, 0.3])

    def s(p, m, l):
        return np.where(seg == "premium", p, np.where(seg == "mid", m, l))

    return pd.DataFrame({
        "h3_id":     [f"8a2a{i:07x}fffff" for i in range(N)],
        "d_down":    np.clip(np.random.normal(s(100, 40, 15), s(20, 10, 5)), 1, 400),
        "d_up":      np.clip(np.random.normal(s(50, 20, 8), s(10, 5, 3)), 0.5, 200),
        "lat":       np.clip(np.random.normal(s(15, 35, 65), s(5, 10, 20)), 5, 200),
        "vol_test":  np.clip(np.random.normal(s(8, 5, 2), 1.5), 1, 30),
        "n_dom":     np.clip(np.random.normal(s(200, 100, 40), s(40, 25, 15)), 1, 800),
        "n_com":     np.clip(np.random.normal(s(50, 20, 8), s(10, 6, 4)), 0, 200),
        "ren_med":   np.clip(np.random.normal(s(4000, 1800, 900), s(500, 300, 150)), 300, 9000),
        "n_erb":     np.clip(np.random.poisson(s(12, 6, 2), N).astype(float), 0, 60),
        "HHI":       np.clip(np.random.normal(s(2000, 4000, 5500), 500), 0, 10000),
        "vol_reclam": np.clip(np.random.exponential(s(3, 8, 15), N), 0, 80),
    })


# ── eda_utils tests ────────────────────────────────────────────────────────

class TestComputeCorrelationMatrix:
    def test_shape(self, synthetic_gold):
        corr = compute_correlation_matrix(synthetic_gold)
        assert corr.shape == (10, 10)

    def test_diagonal_is_one(self, synthetic_gold):
        corr = compute_correlation_matrix(synthetic_gold)
        assert np.allclose(np.diag(corr.values), 1.0)

    def test_symmetric(self, synthetic_gold):
        corr = compute_correlation_matrix(synthetic_gold)
        assert np.allclose(corr.values, corr.values.T)

    def test_spearman_returns_valid(self, synthetic_gold):
        corr = compute_correlation_matrix(synthetic_gold, method="spearman")
        assert corr.shape == (10, 10)
        assert ((corr.values >= -1.0) & (corr.values <= 1.0)).all()

    def test_too_few_features_raises(self, synthetic_gold):
        with pytest.raises(ValueError, match="Need"):
            compute_correlation_matrix(synthetic_gold, features=["d_down"])


class TestComputeVIF:
    def test_returns_all_features(self, synthetic_gold):
        vif = compute_vif(synthetic_gold)
        assert len(vif) == 10

    def test_required_columns(self, synthetic_gold):
        vif = compute_vif(synthetic_gold)
        assert set(vif.columns) == {"feature", "VIF", "flag_multicollinearity"}

    def test_vif_positive(self, synthetic_gold):
        vif = compute_vif(synthetic_gold)
        assert (vif["VIF"] > 0).all()

    def test_flag_column_is_bool(self, synthetic_gold):
        vif = compute_vif(synthetic_gold)
        assert vif["flag_multicollinearity"].dtype == bool


class TestPCAExplainedVariance:
    def test_returns_embedding(self, synthetic_gold):
        result = pca_explained_variance(synthetic_gold, n_components=2)
        assert result["embedding"].shape == (300, 2)

    def test_explained_variance_sums_correctly(self, synthetic_gold):
        result = pca_explained_variance(synthetic_gold, n_components=3)
        assert abs(result["total_variance"] - sum(result["explained_variance"])) < 1e-9

    def test_total_variance_in_range(self, synthetic_gold):
        result = pca_explained_variance(synthetic_gold, n_components=2)
        assert 0.0 < result["total_variance"] <= 1.0


class TestSilhouette:
    def test_valid_labels(self, synthetic_gold):
        X = synthetic_gold[["d_down", "ren_med"]].values.astype(float)
        labels = np.array([0] * 100 + [1] * 100 + [2] * 100)
        score = silhouette(X, labels)
        assert -1.0 <= score <= 1.0

    def test_single_cluster_returns_nan(self, synthetic_gold):
        X = synthetic_gold[["d_down", "ren_med"]].values.astype(float)
        labels = np.zeros(300, dtype=int)
        score = silhouette(X, labels)
        assert np.isnan(score)

    def test_noise_points_excluded(self, synthetic_gold):
        X = synthetic_gold[["d_down", "ren_med"]].values.astype(float)
        labels = np.array([0] * 150 + [1] * 100 + [-1] * 50)
        score = silhouette(X, labels)
        assert not np.isnan(score)


# ── baseline_runners tests ─────────────────────────────────────────────────

class TestRunAxis1Baseline:
    def test_returns_baseline_result_keys(self, synthetic_gold):
        result = run_axis1_baseline(synthetic_gold)
        for key in ("axis", "algorithm", "metric_name", "metric_value", "decision", "rationale", "extra"):
            assert key in result

    def test_axis_identifier(self, synthetic_gold):
        result = run_axis1_baseline(synthetic_gold)
        assert result["axis"] == "1_manutencao_e_criticidade"

    def test_metric_value_in_range(self, synthetic_gold):
        result = run_axis1_baseline(synthetic_gold)
        assert 0.0 <= result["metric_value"] <= 1.0

    def test_decision_valid(self, synthetic_gold):
        result = run_axis1_baseline(synthetic_gold)
        assert result["decision"] in ("CONFIRM", "ADJUST")

    def test_with_cloudflare_ground_truth(self, synthetic_gold):
        cf_ids = set(synthetic_gold["h3_id"].iloc[:10].tolist())
        result = run_axis1_baseline(synthetic_gold, cloudflare_outage_h3_ids=cf_ids)
        assert result["metric_value"] >= 0.0

    def test_missing_features_raises(self):
        with pytest.raises(ValueError):
            run_axis1_baseline(pd.DataFrame({"h3_id": ["abc"], "other": [1.0]}))


class TestRunAxis2Baseline:
    def test_returns_baseline_result_keys(self, synthetic_gold):
        result = run_axis2_baseline(synthetic_gold)
        for key in ("axis", "algorithm", "metric_name", "metric_value", "decision", "rationale", "extra"):
            assert key in result

    def test_axis_identifier(self, synthetic_gold):
        result = run_axis2_baseline(synthetic_gold)
        assert result["axis"] == "2_novos_negocios_e_expansao"

    def test_silhouette_stored(self, synthetic_gold):
        result = run_axis2_baseline(synthetic_gold)
        assert "silhouette" in result["metric_name"].lower()

    def test_n_clusters_positive(self, synthetic_gold):
        result = run_axis2_baseline(synthetic_gold)
        assert result["extra"]["n_clusters"] >= 0

    def test_decision_valid(self, synthetic_gold):
        result = run_axis2_baseline(synthetic_gold)
        assert result["decision"] in ("CONFIRM", "ADJUST")


class TestRunAxis3Baseline:
    def test_returns_baseline_result_keys(self, synthetic_gold):
        result = run_axis3_baseline(synthetic_gold)
        for key in ("axis", "algorithm", "metric_name", "metric_value", "decision", "rationale", "extra"):
            assert key in result

    def test_axis_identifier(self, synthetic_gold):
        result = run_axis3_baseline(synthetic_gold)
        assert result["axis"] == "3_regioes_propicias_para_promocoes"

    def test_cluster_stats_has_three_entries_when_k3(self, synthetic_gold):
        result = run_axis3_baseline(synthetic_gold, k=3, sweep=False)
        assert len(result["extra"]["cluster_stats"]) == 3

    def test_best_k_in_sweep_range(self, synthetic_gold):
        result = run_axis3_baseline(synthetic_gold, k=3, sweep=True)
        assert result["extra"]["best_k"] in [3, 4, 5, 6]

    def test_decision_valid(self, synthetic_gold):
        result = run_axis3_baseline(synthetic_gold)
        assert result["decision"] in ("CONFIRM", "ADJUST")


class TestRunAllBaselines:
    def test_returns_three_results(self, synthetic_gold):
        results = run_all_baselines(synthetic_gold)
        assert len(results) == 3

    def test_axes_in_correct_order(self, synthetic_gold):
        results = run_all_baselines(synthetic_gold)
        axes = [r["axis"] for r in results]
        assert axes == [
            "1_manutencao_e_criticidade",
            "2_novos_negocios_e_expansao",
            "3_regioes_propicias_para_promocoes",
        ]
