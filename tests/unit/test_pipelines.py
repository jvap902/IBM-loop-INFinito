"""Unit tests for Sub-Task 3 ML pipelines (Axes 1, 2, 3).

All tests use a compact synthetic Gold DataFrame (300 rows) so they run
quickly without any external dependencies.  MLflow and UMAP are disabled
in every test to avoid network/file-system side-effects.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.pipelines.pipeline_axis1 import (
    run as axis1_run,
    validate_output as axis1_validate,
    ANOMALY_SCORE_THRESHOLD,
    ANOMALY_RATE_MIN,
    ANOMALY_RATE_MAX,
)
from ml.pipelines.pipeline_axis2 import (
    run as axis2_run,
    validate_output as axis2_validate,
    NOISE_RATE_MAX,
    N_CLUSTERS_MIN,
)
from ml.pipelines.pipeline_axis3 import (
    run as axis3_run,
    validate_output as axis3_validate,
    _assign_segment_names,
    SILHOUETTE_THRESHOLD,
)


# ── Shared fixture ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def gold() -> pd.DataFrame:
    """Compact synthetic Gold DataFrame with three well-separated segments."""
    np.random.seed(42)
    N = 300
    seg = np.random.choice(["premium", "mid", "low"], size=N, p=[0.3, 0.4, 0.3])

    def s(p, m, l):
        return np.where(seg == "premium", p, np.where(seg == "mid", m, l))

    df = pd.DataFrame({
        "h3_id":      [f"8a2a{i:07x}fffff" for i in range(N)],
        "d_down":     np.clip(np.random.normal(s(100, 40, 15), s(20, 10, 5)), 1, 400),
        "d_up":       np.clip(np.random.normal(s(50, 20, 8),  s(10, 5, 3)),  0.5, 200),
        "lat":        np.clip(np.random.normal(s(15, 35, 65), s(5, 10, 20)), 5, 200),
        "vol_test":   np.clip(np.random.normal(s(8, 5, 2), 1.5), 1, 30),
        "n_dom":      np.clip(np.random.normal(s(200, 100, 40), s(40, 25, 15)), 1, 800),
        "n_com":      np.clip(np.random.normal(s(50, 20, 8), s(10, 6, 4)), 0, 200),
        "ren_med":    np.clip(np.random.normal(s(4000, 1800, 900), s(500, 300, 150)), 300, 9000),
        "n_erb":      np.clip(np.random.poisson(s(12, 6, 2), N).astype(float), 0, 60),
        "HHI":        np.clip(np.random.normal(s(2000, 4000, 5500), 500), 0, 10000),
        "vol_reclam": np.clip(np.random.exponential(s(3, 8, 15), N), 0, 80),
    })
    return df


# ── Axis 1 tests ───────────────────────────────────────────────────────────

class TestAxis1Pipeline:
    def test_output_columns(self, gold):
        out = axis1_run(gold, enable_mlflow=False)
        assert set(out.columns) == {
            "h3_id", "anomaly_score", "is_critical", "lof_score",
            "cloudflare_outage_overlap",
        }

    def test_row_count(self, gold):
        out = axis1_run(gold, enable_mlflow=False)
        assert len(out) == len(gold)

    def test_anomaly_score_range(self, gold):
        out = axis1_run(gold, enable_mlflow=False)
        assert out["anomaly_score"].between(0.0, 1.0).all()

    def test_lof_score_range(self, gold):
        out = axis1_run(gold, enable_mlflow=False)
        assert out["lof_score"].between(0.0, 1.0).all()

    def test_is_critical_is_binary(self, gold):
        out = axis1_run(gold, enable_mlflow=False)
        assert set(out["is_critical"].unique()).issubset({0, 1})

    def test_cloudflare_overlap_binary(self, gold):
        cf_ids = {gold["h3_id"].iloc[0], gold["h3_id"].iloc[1]}
        out = axis1_run(gold, cloudflare_outage_h3_ids=cf_ids, enable_mlflow=False)
        assert set(out["cloudflare_outage_overlap"].unique()).issubset({0, 1})
        # The two known outage cells must have overlap=1
        overlap_h3 = set(out[out["cloudflare_outage_overlap"] == 1]["h3_id"].values)
        assert cf_ids.issubset(overlap_h3)

    def test_anomaly_rate_within_bounds(self, gold):
        out = axis1_run(gold, enable_mlflow=False)
        rate = out["is_critical"].mean()
        assert ANOMALY_RATE_MIN <= rate <= ANOMALY_RATE_MAX

    def test_no_nulls_in_mandatory_columns(self, gold):
        out = axis1_run(gold, enable_mlflow=False)
        for col in ["h3_id", "anomaly_score", "is_critical", "lof_score"]:
            assert out[col].isnull().sum() == 0

    def test_validate_output_passes(self, gold):
        out = axis1_run(gold, enable_mlflow=False)
        # Should not raise
        axis1_validate(out)

    def test_validate_output_rejects_missing_column(self, gold):
        out = axis1_run(gold, enable_mlflow=False)
        with pytest.raises(ValueError, match="Colunas obrigatórias ausentes"):
            axis1_validate(out.drop(columns=["anomaly_score"]))

    def test_validate_output_rejects_high_anomaly_rate(self, gold):
        out = axis1_run(gold, enable_mlflow=False).copy()
        out["is_critical"] = 1  # 100 % anomaly rate → should fail
        with pytest.raises(ValueError, match="Taxa de anomalia"):
            axis1_validate(out)

    def test_missing_feature_raises(self, gold):
        stripped = gold.drop(columns=["lat", "vol_reclam", "d_down"])
        with pytest.raises(ValueError, match="Nenhuma feature do Eixo 1"):
            axis1_run(stripped, enable_mlflow=False)

    def test_missing_h3_id_raises(self, gold):
        stripped = gold.drop(columns=["h3_id"])
        with pytest.raises(ValueError, match="Coluna h3_id"):
            axis1_run(stripped, enable_mlflow=False)


# ── Axis 2 tests ───────────────────────────────────────────────────────────

class TestAxis2Pipeline:
    """UMAP is disabled (skip_umap=True) so umap-learn is not required."""

    def test_output_columns(self, gold):
        out = axis2_run(
            gold,
            hdbscan_min_cluster_size=5,
            skip_umap=True,
            enable_mlflow=False,
        )
        assert set(out.columns) == {
            "h3_id", "cluster_id", "cluster_size", "avg_d_down",
            "avg_n_dom", "avg_HHI", "is_noise",
        }

    def test_row_count(self, gold):
        out = axis2_run(
            gold, hdbscan_min_cluster_size=5, skip_umap=True, enable_mlflow=False
        )
        assert len(out) == len(gold)

    def test_noise_column_binary(self, gold):
        out = axis2_run(
            gold, hdbscan_min_cluster_size=5, skip_umap=True, enable_mlflow=False
        )
        assert set(out["is_noise"].unique()).issubset({0, 1})

    def test_noise_rate_below_threshold(self, gold):
        out = axis2_run(
            gold, hdbscan_min_cluster_size=5, skip_umap=True, enable_mlflow=False
        )
        noise_rate = out["is_noise"].mean()
        assert noise_rate < NOISE_RATE_MAX

    def test_at_least_n_clusters(self, gold):
        out = axis2_run(
            gold, hdbscan_min_cluster_size=5, skip_umap=True, enable_mlflow=False
        )
        n_real = out[out["is_noise"] == 0]["cluster_id"].nunique()
        assert n_real >= N_CLUSTERS_MIN

    def test_noise_cluster_id_is_minus_one(self, gold):
        out = axis2_run(
            gold, hdbscan_min_cluster_size=5, skip_umap=True, enable_mlflow=False
        )
        assert (out[out["is_noise"] == 1]["cluster_id"] == -1).all()

    def test_no_nulls_in_mandatory_columns(self, gold):
        out = axis2_run(
            gold, hdbscan_min_cluster_size=5, skip_umap=True, enable_mlflow=False
        )
        for col in ["h3_id", "cluster_id", "is_noise"]:
            assert out[col].isnull().sum() == 0

    def test_validate_output_passes(self, gold):
        out = axis2_run(
            gold, hdbscan_min_cluster_size=5, skip_umap=True, enable_mlflow=False
        )
        axis2_validate(out)

    def test_validate_output_rejects_missing_column(self, gold):
        out = axis2_run(
            gold, hdbscan_min_cluster_size=5, skip_umap=True, enable_mlflow=False
        )
        with pytest.raises(ValueError, match="Colunas obrigatórias ausentes"):
            axis2_validate(out.drop(columns=["cluster_id"]))

    def test_validate_output_rejects_high_noise(self, gold):
        out = axis2_run(
            gold, hdbscan_min_cluster_size=5, skip_umap=True, enable_mlflow=False
        ).copy()
        out["is_noise"] = 1      # 100 % noise → should fail
        out["cluster_id"] = -1
        with pytest.raises(ValueError, match="Taxa de ruído"):
            axis2_validate(out)

    def test_missing_feature_raises(self, gold):
        stripped = gold.drop(columns=["n_dom", "n_com", "d_down", "n_erb", "HHI"])
        with pytest.raises(ValueError, match="Nenhuma feature do Eixo 2"):
            axis2_run(stripped, skip_umap=True, enable_mlflow=False)


# ── Axis 3 tests ───────────────────────────────────────────────────────────

class TestAxis3Pipeline:
    def test_output_columns(self, gold):
        out = axis3_run(gold, enable_mlflow=False)
        assert set(out.columns) == {
            "h3_id", "segment_id", "segment_name",
            "centroid_distance", "silhouette_score_local",
        }

    def test_row_count(self, gold):
        out = axis3_run(gold, enable_mlflow=False)
        assert len(out) == len(gold)

    def test_three_segments(self, gold):
        out = axis3_run(gold, enable_mlflow=False)
        assert out["segment_id"].nunique() == 3

    def test_segment_names_are_valid(self, gold):
        out = axis3_run(gold, enable_mlflow=False)
        valid_names = {
            "Premium",
            "Conectividade Essencial",
            "Alta Vulnerabilidade Concorrencia",
        }
        assert set(out["segment_name"].unique()) == valid_names

    def test_centroid_distance_non_negative(self, gold):
        out = axis3_run(gold, enable_mlflow=False)
        assert (out["centroid_distance"] >= 0).all()

    def test_silhouette_local_range(self, gold):
        out = axis3_run(gold, enable_mlflow=False)
        valid = out["silhouette_score_local"].dropna()
        assert valid.between(-1.0, 1.0).all()

    def test_no_nulls_in_mandatory_columns(self, gold):
        out = axis3_run(gold, enable_mlflow=False)
        for col in ["h3_id", "segment_id", "segment_name", "centroid_distance"]:
            assert out[col].isnull().sum() == 0

    def test_silhouette_above_threshold(self, gold):
        """The synthetic data should yield a silhouette well above 0.30."""
        from sklearn.metrics import silhouette_score
        from sklearn.preprocessing import StandardScaler

        feats = ["ren_med", "n_dom", "vol_reclam", "HHI", "d_up"]
        cols = [c for c in feats if c in gold.columns]
        X = StandardScaler().fit_transform(gold[cols].values)
        out = axis3_run(gold, enable_mlflow=False)
        sil = silhouette_score(X, out["segment_id"].values)
        assert sil > SILHOUETTE_THRESHOLD

    def test_validate_output_passes(self, gold):
        out = axis3_run(gold, enable_mlflow=False)
        axis3_validate(out)

    def test_validate_output_rejects_missing_column(self, gold):
        out = axis3_run(gold, enable_mlflow=False)
        with pytest.raises(ValueError, match="Colunas obrigatórias ausentes"):
            axis3_validate(out.drop(columns=["segment_name"]))

    def test_validate_output_rejects_wrong_k(self, gold):
        out = axis3_run(gold, enable_mlflow=False).copy()
        # Manually corrupt segment_ids to have 4 unique values
        out.iloc[0, out.columns.get_loc("segment_id")] = 99
        with pytest.raises(ValueError, match="segmentos"):
            axis3_validate(out, k=3)

    def test_missing_feature_raises(self, gold):
        stripped = gold.drop(columns=["ren_med", "n_dom", "vol_reclam", "HHI", "d_up"])
        with pytest.raises(ValueError, match="Nenhuma feature do Eixo 3"):
            axis3_run(stripped, enable_mlflow=False)

    def test_assign_segment_names_income_ordering(self, gold):
        """Premium should be the highest-income centroid."""
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler

        feats = ["ren_med", "n_dom", "vol_reclam", "HHI", "d_up"]
        cols = [c for c in feats if c in gold.columns]
        X = StandardScaler().fit_transform(gold[cols].values)
        km = KMeans(n_clusters=3, init="k-means++", n_init=10, random_state=42)
        km.fit(X)

        mapping = _assign_segment_names(km, cols)
        # Find cluster with highest ren_med centroid
        ren_idx = cols.index("ren_med")
        highest_income_cluster = int(np.argmax(km.cluster_centers_[:, ren_idx]))
        assert mapping[highest_income_cluster] == "Premium"
