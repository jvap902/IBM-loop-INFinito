"""Data Drift Detector — Population Stability Index (PSI).

Purpose
-------
Monitor month-over-month distributional shift in the Gold Feature Store.
PSI > 0.2 on any feature triggers a retraining flag and an actionable alert.

PSI interpretation (industry standard)
---------------------------------------
PSI < 0.10  — No significant drift.  Model stable.
0.10–0.20   — Minor drift. Monitor closely.
PSI > 0.20  — Significant drift.  ⚠️ Recommend re-training.

Public API
----------
compute_psi(expected, actual, column, bins)  → float
compute_psi_report(expected_df, actual_df, columns, bins)
    → DataFrame with columns [feature, psi, alert, drift_level]
detect_drift(expected_df, actual_df, ...)
    → DriftReport (dataclass)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Threshold constants ────────────────────────────────────────────────────
PSI_NO_DRIFT: float = 0.10        # below this: stable
PSI_MINOR_DRIFT: float = 0.20     # 0.10–0.20: watch
PSI_SIGNIFICANT_DRIFT: float = 0.20  # above this: retrain

# All 10 feature-vector columns (from knowledge-api.json)
X_HI_COLUMNS: list[str] = [
    "d_down", "d_up", "lat", "vol_test",
    "n_dom", "n_com", "ren_med", "n_erb",
    "HHI", "vol_reclam",
]


# ── PSI helpers ────────────────────────────────────────────────────────────

def _psi_bins(
    expected: np.ndarray,
    actual: np.ndarray,
    bins: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute PSI bucket boundaries and per-bucket percentages.

    Bin edges are derived from ``expected`` only, so ``actual`` is always
    measured against a fixed reference.  Edge values include the global min/max
    of both distributions to ensure all ``actual`` points fall in a valid bucket.

    Returns
    -------
    (expected_pcts, actual_pcts, edges)
        Percentages sum to 1.0 each; zero-count buckets are floored at 1e-4
        (standard PSI practice to avoid log(0)).
    """
    global_min = min(expected.min(), actual.min())
    global_max = max(expected.max(), actual.max())

    # Build edges from expected distribution; always include global extremes
    _, ref_edges = np.histogram(expected, bins=bins)
    edges = np.concatenate([[global_min], ref_edges[1:-1], [global_max]])
    edges = np.unique(edges)  # deduplicate if ranges overlap

    expected_counts, _ = np.histogram(expected, bins=edges)
    actual_counts,   _ = np.histogram(actual,   bins=edges)

    # Convert to proportions; floor at 1e-4 to avoid log(0)
    floor = 1e-4
    expected_pcts = np.maximum(expected_counts / len(expected), floor)
    actual_pcts   = np.maximum(actual_counts   / len(actual),   floor)

    # Re-normalise after flooring so they sum to 1.0
    expected_pcts /= expected_pcts.sum()
    actual_pcts   /= actual_pcts.sum()

    return expected_pcts, actual_pcts, edges


def compute_psi(
    expected: np.ndarray,
    actual: np.ndarray,
    bins: int = 10,
) -> float:
    """Compute Population Stability Index between two 1-D distributions.

    PSI = Σ (actual_pct_i − expected_pct_i) × ln(actual_pct_i / expected_pct_i)

    Parameters
    ----------
    expected : Reference distribution (e.g. training month feature values).
    actual   : Current distribution (e.g. latest month feature values).
    bins     : Number of equal-width bins (default 10).

    Returns
    -------
    PSI value ≥ 0.  Higher = more drift.
    """
    expected = np.asarray(expected, dtype=float)
    actual   = np.asarray(actual,   dtype=float)

    if len(expected) == 0 or len(actual) == 0:
        raise ValueError("compute_psi: expected and actual must not be empty.")

    # If the column is constant in the reference, PSI is undefined (0 drift assumed)
    if np.ptp(expected) < 1e-9:
        logger.debug("compute_psi: constant reference column — returning PSI=0.0")
        return 0.0

    exp_pcts, act_pcts, _ = _psi_bins(expected, actual, bins=bins)
    psi = float(np.sum((act_pcts - exp_pcts) * np.log(act_pcts / exp_pcts)))
    return round(psi, 6)


def _drift_level(psi: float) -> str:
    """Translate PSI value to a human-readable drift level."""
    if psi < PSI_NO_DRIFT:
        return "stable"
    if psi < PSI_MINOR_DRIFT:
        return "minor"
    return "significant"  # PSI >= 0.20 → retrain recommended


def compute_psi_report(
    expected_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    columns: Optional[list[str]] = None,
    bins: int = 10,
) -> pd.DataFrame:
    """Compute PSI for each feature column.

    Parameters
    ----------
    expected_df : Reference DataFrame (one month).
    actual_df   : Current DataFrame (next month).
    columns     : Feature columns to monitor (default: X_HI_COLUMNS).
    bins        : Number of bins for PSI computation.

    Returns
    -------
    DataFrame with columns:
        [feature, psi, drift_level, alert]
    Sorted by psi descending.
    """
    if columns is None:
        columns = X_HI_COLUMNS

    cols = [c for c in columns if c in expected_df.columns and c in actual_df.columns]
    if not cols:
        raise ValueError(
            "No matching columns found between expected and actual DataFrames. "
            f"Requested: {columns}"
        )

    rows: list[dict] = []
    for col in cols:
        exp_vals = expected_df[col].dropna().values
        act_vals = actual_df[col].dropna().values
        if len(exp_vals) == 0 or len(act_vals) == 0:
            logger.warning("[drift] Skipping '%s' — empty after dropna.", col)
            continue
        psi = compute_psi(exp_vals, act_vals, bins=bins)
        level = _drift_level(psi)
        alert = psi >= PSI_SIGNIFICANT_DRIFT
        rows.append({
            "feature":    col,
            "psi":        psi,
            "drift_level": level,
            "alert":      alert,
        })

    report_df = (
        pd.DataFrame(rows)
        .sort_values("psi", ascending=False)
        .reset_index(drop=True)
    )

    n_alerts = int(report_df["alert"].sum())
    logger.info(
        "[drift] PSI report: %d features checked, %d alerts (PSI > %.2f).",
        len(report_df), n_alerts, PSI_SIGNIFICANT_DRIFT,
    )
    return report_df


# ── High-level DriftReport ─────────────────────────────────────────────────

@dataclass
class DriftReport:
    """Full drift detection result returned by :func:`detect_drift`."""

    period_expected: str                   # label for reference period
    period_actual:   str                   # label for current period
    psi_table:       pd.DataFrame          # full per-feature PSI table
    flagged_features: list[str] = field(default_factory=list)
    retrain_recommended: bool = False
    summary: str = ""

    def to_dict(self) -> dict:
        """Serialisable dict (excludes DataFrame for JSON compatibility)."""
        return {
            "period_expected":    self.period_expected,
            "period_actual":      self.period_actual,
            "retrain_recommended": self.retrain_recommended,
            "flagged_features":   self.flagged_features,
            "summary":            self.summary,
            "psi_table":          self.psi_table.to_dict(orient="records"),
        }


def detect_drift(
    expected_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    columns: Optional[list[str]] = None,
    bins: int = 10,
    period_expected: str = "T-1",
    period_actual:   str = "T",
) -> DriftReport:
    """Run full drift detection and return a structured DriftReport.

    This is the main entry-point for the monthly monitoring job.

    Parameters
    ----------
    expected_df      : Reference Gold DataFrame (previous month).
    actual_df        : Current Gold DataFrame (this month).
    columns          : Feature columns to monitor (default: all X_HI_COLUMNS).
    bins             : PSI bin count.
    period_expected  : Human-readable label for the reference period.
    period_actual    : Human-readable label for the current period.

    Returns
    -------
    DriftReport with populated ``flagged_features`` and ``retrain_recommended``.
    Alert is raised (logged as WARNING) if any feature PSI > 0.20.
    """
    report_df = compute_psi_report(
        expected_df=expected_df,
        actual_df=actual_df,
        columns=columns,
        bins=bins,
    )

    flagged = report_df[report_df["alert"]]["feature"].tolist()
    retrain = len(flagged) > 0

    if retrain:
        logger.warning(
            "[drift] ⚠️  RETRAIN ALERT — %d feature(s) with PSI > %.2f: %s",
            len(flagged), PSI_SIGNIFICANT_DRIFT, flagged,
        )
    else:
        logger.info(
            "[drift] ✅ No significant drift detected (%s → %s). Models stable.",
            period_expected, period_actual,
        )

    # Human-readable summary
    lines = [
        f"Drift Report: {period_expected} → {period_actual}",
        f"Features checked : {len(report_df)}",
        f"Features flagged : {len(flagged)} (PSI > {PSI_SIGNIFICANT_DRIFT})",
    ]
    if flagged:
        lines.append(f"Action required  : Retrain models for features {flagged}")
        for feat in flagged:
            psi_val = float(report_df.loc[report_df["feature"] == feat, "psi"].iloc[0])
            lines.append(f"  • {feat}: PSI={psi_val:.4f}")
    else:
        lines.append("Action required  : None — all features stable.")

    summary = "\n".join(lines)

    return DriftReport(
        period_expected=period_expected,
        period_actual=period_actual,
        psi_table=report_df,
        flagged_features=flagged,
        retrain_recommended=retrain,
        summary=summary,
    )
