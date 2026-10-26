"""Unit tests for ml/drift_detector.py (Sub-Task 3 — Data Drift Detection)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.drift_detector import (
    compute_psi,
    compute_psi_report,
    detect_drift,
    DriftReport,
    PSI_NO_DRIFT,
    PSI_SIGNIFICANT_DRIFT,
    X_HI_COLUMNS,
)


# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def stable_pair() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Two identically-distributed DataFrames — PSI should be near 0."""
    np.random.seed(0)
    N = 500
    data = {col: np.random.normal(loc=50, scale=10, size=N) for col in X_HI_COLUMNS}
    df_a = pd.DataFrame(data)
    df_b = pd.DataFrame(data)  # same distribution, different rows
    return df_a, df_b


@pytest.fixture(scope="module")
def drifted_pair() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Two DataFrames with significant distributional shift on all features."""
    np.random.seed(1)
    N = 500
    expected = pd.DataFrame({
        col: np.random.normal(loc=50, scale=10, size=N) for col in X_HI_COLUMNS
    })
    actual = pd.DataFrame({
        col: np.random.normal(loc=100, scale=20, size=N) for col in X_HI_COLUMNS
    })
    return expected, actual


@pytest.fixture(scope="module")
def partial_drift_pair() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Only 'HHI' and 'vol_reclam' drift; others remain stable."""
    np.random.seed(2)
    N = 500
    expected = pd.DataFrame({
        col: np.random.normal(loc=50, scale=10, size=N) for col in X_HI_COLUMNS
    })
    actual = expected.copy()
    # Apply large shift only on HHI and vol_reclam
    actual["HHI"] = np.random.normal(loc=9000, scale=100, size=N)
    actual["vol_reclam"] = np.random.normal(loc=9000, scale=100, size=N)
    return expected, actual


# ── compute_psi tests ──────────────────────────────────────────────────────

class TestComputePsi:
    def test_identical_distributions_near_zero(self):
        np.random.seed(0)
        data = np.random.normal(50, 10, 1000)
        psi = compute_psi(data, data.copy())
        assert psi < PSI_NO_DRIFT

    def test_large_shift_above_threshold(self):
        np.random.seed(0)
        expected = np.random.normal(50, 5, 1000)
        actual   = np.random.normal(200, 5, 1000)
        psi = compute_psi(expected, actual)
        assert psi > PSI_SIGNIFICANT_DRIFT

    def test_psi_is_non_negative(self):
        np.random.seed(0)
        a = np.random.normal(50, 10, 500)
        b = np.random.normal(55, 10, 500)
        assert compute_psi(a, b) >= 0.0

    def test_constant_reference_returns_zero(self):
        expected = np.ones(100)    # constant → PSI undefined → returns 0
        actual   = np.random.normal(0, 1, 100)
        psi = compute_psi(expected, actual)
        assert psi == 0.0

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            compute_psi(np.array([]), np.array([1.0, 2.0]))

    def test_bin_count_parameter(self):
        """Different bin counts should not flip the stability classification."""
        np.random.seed(3)
        data = np.random.normal(50, 10, 500)
        psi_10 = compute_psi(data, data.copy(), bins=10)
        psi_20 = compute_psi(data, data.copy(), bins=20)
        # Both should be near zero (stable)
        assert psi_10 < PSI_NO_DRIFT
        assert psi_20 < PSI_NO_DRIFT


# ── compute_psi_report tests ───────────────────────────────────────────────

class TestComputePsiReport:
    def test_returns_dataframe(self, stable_pair):
        exp, act = stable_pair
        report = compute_psi_report(exp, act)
        assert isinstance(report, pd.DataFrame)

    def test_report_columns(self, stable_pair):
        exp, act = stable_pair
        report = compute_psi_report(exp, act)
        assert set(report.columns) == {"feature", "psi", "drift_level", "alert"}

    def test_all_features_present(self, stable_pair):
        exp, act = stable_pair
        report = compute_psi_report(exp, act)
        assert set(report["feature"]) == set(X_HI_COLUMNS)

    def test_stable_pair_no_alerts(self, stable_pair):
        exp, act = stable_pair
        report = compute_psi_report(exp, act)
        assert not report["alert"].any()

    def test_stable_pair_drift_level(self, stable_pair):
        exp, act = stable_pair
        report = compute_psi_report(exp, act)
        assert (report["drift_level"] == "stable").all()

    def test_drifted_pair_all_alerts(self, drifted_pair):
        exp, act = drifted_pair
        report = compute_psi_report(exp, act)
        assert report["alert"].all(), (
            f"Expected all features to be flagged; got:\n{report[['feature','psi','alert']]}"
        )

    def test_sorted_by_psi_descending(self, drifted_pair):
        exp, act = drifted_pair
        report = compute_psi_report(exp, act)
        assert (report["psi"].diff().dropna() <= 0).all()

    def test_column_subset(self, stable_pair):
        exp, act = stable_pair
        subset = ["d_down", "HHI"]
        report = compute_psi_report(exp, act, columns=subset)
        assert set(report["feature"]) == set(subset)

    def test_no_matching_columns_raises(self, stable_pair):
        exp, act = stable_pair
        with pytest.raises(ValueError, match="No matching columns"):
            compute_psi_report(exp, act, columns=["nonexistent_col"])


# ── detect_drift tests ─────────────────────────────────────────────────────

class TestDetectDrift:
    def test_returns_drift_report(self, stable_pair):
        exp, act = stable_pair
        result = detect_drift(exp, act)
        assert isinstance(result, DriftReport)

    def test_stable_no_retrain(self, stable_pair):
        exp, act = stable_pair
        result = detect_drift(exp, act, period_expected="2024-01", period_actual="2024-02")
        assert not result.retrain_recommended
        assert result.flagged_features == []

    def test_drifted_recommends_retrain(self, drifted_pair):
        exp, act = drifted_pair
        result = detect_drift(exp, act)
        assert result.retrain_recommended
        assert len(result.flagged_features) > 0

    def test_partial_drift_only_flags_drifted_features(self, partial_drift_pair):
        exp, act = partial_drift_pair
        result = detect_drift(exp, act)
        assert result.retrain_recommended
        # HHI and vol_reclam must be flagged
        assert "HHI" in result.flagged_features
        assert "vol_reclam" in result.flagged_features
        # Stable features must NOT be flagged
        stable_feats = [c for c in X_HI_COLUMNS if c not in ("HHI", "vol_reclam")]
        for feat in stable_feats:
            assert feat not in result.flagged_features, (
                f"Feature '{feat}' incorrectly flagged as drifted."
            )

    def test_period_labels_propagated(self, stable_pair):
        exp, act = stable_pair
        result = detect_drift(exp, act, period_expected="Jan", period_actual="Feb")
        assert result.period_expected == "Jan"
        assert result.period_actual == "Feb"

    def test_psi_table_is_dataframe(self, stable_pair):
        exp, act = stable_pair
        result = detect_drift(exp, act)
        assert isinstance(result.psi_table, pd.DataFrame)

    def test_summary_string_non_empty(self, stable_pair):
        exp, act = stable_pair
        result = detect_drift(exp, act)
        assert isinstance(result.summary, str) and len(result.summary) > 0

    def test_to_dict_serialisable(self, stable_pair):
        exp, act = stable_pair
        result = detect_drift(exp, act)
        d = result.to_dict()
        assert "retrain_recommended" in d
        assert "flagged_features" in d
        assert isinstance(d["psi_table"], list)
