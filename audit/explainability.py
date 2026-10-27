"""Model explainability module for the Transparency & Auditability Layer.

Three explanation strategies, one per analytical axis
------------------------------------------------------

Axis 1 — IsolationForest (anomaly detection)
    Uses ``shap.TreeExplainer`` to compute exact SHAP values for the
    IsolationForest model.  Returns the top-3 features with the highest mean
    absolute SHAP contribution across critical hexagons.

Axis 2 — HDBSCAN (density clustering)
    HDBSCAN has no native SHAP interface.  A proxy approach is used:
    per-cluster feature means are compared to the global distribution via
    Z-scores.  The top-3 most deviant features per cluster are returned as
    the "explanation" — this is a well-established post-hoc interpretability
    technique for clustering.

Axis 3 — K-Means++ (promotional segmentation)
    Uses ``shap.KernelExplainer`` with a small background sample (50 rows)
    and a predict function based on centroid distance.  Returns the top-3
    features with highest mean absolute SHAP value per segment.

Performance notes
-----------------
* Axis 1 TreeExplainer operates on the full critical-hexagon subset — fast
  because IsolationForest trees are shallow.
* Axis 3 KernelExplainer is sub-sampled (up to MAX_KERNEL_ROWS rows) to
  bound latency.  For large datasets this keeps SHAP time under ~2 s.
* Axis 2 Z-score proxy is O(N×F) — always fast.
* All functions degrade gracefully: if ``shap`` is not installed they return
  a structured "shap_unavailable" payload without raising.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# Limit the number of rows fed to KernelExplainer to control latency.
MAX_KERNEL_ROWS: int = 200
MAX_KERNEL_BACKGROUND: int = 50
TOP_N_FEATURES: int = 3


# ── Shared helpers ─────────────────────────────────────────────────────────

def _top_n_by_abs(values: np.ndarray, feature_names: list[str], n: int) -> list[dict[str, Any]]:
    """Return the top-n features sorted by absolute value, descending."""
    ranked = sorted(
        zip(feature_names, values.tolist()),
        key=lambda x: abs(x[1]),
        reverse=True,
    )
    return [
        {"feature": name, "shap_value": round(val, 6)}
        for name, val in ranked[:n]
    ]


def _shap_unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "shap_unavailable",
        "reason": reason,
        "top_features": [],
    }


# ── Axis 1: IsolationForest — TreeExplainer ───────────────────────────────

def explain_axis1(
    X_scaled: np.ndarray,
    feature_names: list[str],
    iforest: IsolationForest,
    is_critical_mask: np.ndarray,
    top_n: int = TOP_N_FEATURES,
) -> dict[str, Any]:
    """Compute SHAP feature importances for Axis 1 (IsolationForest).

    Parameters
    ----------
    X_scaled        : Scaled feature matrix used to fit the model (N × F).
    feature_names   : Ordered list of feature column names.
    iforest         : Fitted IsolationForest instance.
    is_critical_mask: Boolean/int mask; True where hexagon is critical.
    top_n           : Number of top features to return.

    Returns
    -------
    Dict with keys:
        status          "ok" or "shap_unavailable"
        method          "TreeExplainer"
        n_explained     Number of critical hexagons explained.
        top_features    List of {feature, shap_value} dicts (mean |SHAP|).
        global_importance  Per-feature mean absolute SHAP across all rows.
    """
    try:
        import shap  # noqa: PLC0415
    except ImportError:
        return _shap_unavailable("shap not installed (pip install shap)")

    critical_X = X_scaled[is_critical_mask.astype(bool)]
    if len(critical_X) == 0:
        return _shap_unavailable("no critical hexagons to explain")

    try:
        explainer = shap.TreeExplainer(iforest)
        shap_values = explainer.shap_values(critical_X)  # (N_crit, F)
        if isinstance(shap_values, list):
            # Multi-output; use first output
            shap_values = shap_values[0]

        mean_abs_shap = np.abs(shap_values).mean(axis=0)  # (F,)
        global_importance = {
            feat: round(float(val), 6)
            for feat, val in zip(feature_names, mean_abs_shap.tolist())
        }

        return {
            "status": "ok",
            "method": "TreeExplainer",
            "n_explained": int(len(critical_X)),
            "top_features": _top_n_by_abs(mean_abs_shap, feature_names, top_n),
            "global_importance": global_importance,
        }
    except Exception as exc:
        logger.warning("[explainability] Axis 1 SHAP failed: %s", exc)
        return _shap_unavailable(str(exc))


# ── Axis 2: HDBSCAN — Z-score proxy ───────────────────────────────────────

def explain_axis2(
    X_original: np.ndarray,
    feature_names: list[str],
    cluster_labels: np.ndarray,
    top_n: int = TOP_N_FEATURES,
) -> dict[str, Any]:
    """Compute per-cluster feature Z-score explanations for Axis 2 (HDBSCAN).

    HDBSCAN is a density estimator with no tree structure amenable to exact
    SHAP.  The proxy approach compares each cluster's feature means to the
    global distribution using Z-scores.  A large |Z| for a feature in a
    given cluster indicates that feature drives the cluster's distinctiveness.

    Parameters
    ----------
    X_original      : Original (unscaled) feature matrix (N × F).
    feature_names   : Ordered list of feature column names.
    cluster_labels  : HDBSCAN integer labels (-1 = noise).
    top_n           : Number of top features to return per cluster.

    Returns
    -------
    Dict with keys:
        status          "ok"
        method          "cluster_zscore_proxy"
        clusters        Dict mapping cluster_id → {top_features, means, zscores}
    """
    global_mean = X_original.mean(axis=0)
    global_std = X_original.std(axis=0) + 1e-9  # avoid divide-by-zero

    unique_labels = np.unique(cluster_labels)
    clusters_out: dict[str, Any] = {}

    for label in unique_labels:
        if label == -1:
            continue  # Skip noise

        mask = cluster_labels == label
        cluster_X = X_original[mask]
        cluster_mean = cluster_X.mean(axis=0)
        z_scores = (cluster_mean - global_mean) / global_std

        ranked = sorted(
            zip(feature_names, z_scores.tolist(), cluster_mean.tolist()),
            key=lambda x: abs(x[1]),
            reverse=True,
        )
        top_features = [
            {
                "feature": name,
                "z_score": round(z, 4),
                "cluster_mean": round(m, 4),
                "global_mean": round(float(global_mean[i]), 4),
            }
            for i, (name, z, m) in enumerate(ranked[:top_n])
        ]

        clusters_out[str(int(label))] = {
            "cluster_id": int(label),
            "n_hexagons": int(mask.sum()),
            "top_features": top_features,
        }

    return {
        "status": "ok",
        "method": "cluster_zscore_proxy",
        "n_clusters_explained": len(clusters_out),
        "clusters": clusters_out,
    }


# ── Axis 3: K-Means++ — KernelExplainer ───────────────────────────────────

def explain_axis3(
    X_scaled: np.ndarray,
    feature_names: list[str],
    centroids: np.ndarray,
    segment_labels: np.ndarray,
    top_n: int = TOP_N_FEATURES,
) -> dict[str, Any]:
    """Compute SHAP feature importances for Axis 3 (K-Means++ segmentation).

    Uses ``shap.KernelExplainer`` with a predict function defined as the
    centroid-distance-based softmax probability.  A random subsample
    (≤ MAX_KERNEL_ROWS) keeps latency bounded.

    Parameters
    ----------
    X_scaled        : Scaled feature matrix (N × F).
    feature_names   : Ordered list of feature column names.
    centroids       : K-Means centroid matrix (k × F).
    segment_labels  : Integer cluster assignment per row (N,).
    top_n           : Number of top features to return per segment.

    Returns
    -------
    Dict with keys:
        status          "ok" or "shap_unavailable"
        method          "KernelExplainer"
        n_explained     Number of rows actually explained (subsample).
        segments        Dict mapping segment_id → {top_features, mean_abs_shap}
    """
    try:
        import shap  # noqa: PLC0415
    except ImportError:
        return _shap_unavailable("shap not installed (pip install shap)")

    n_rows, n_features = X_scaled.shape
    k = len(centroids)

    if n_rows == 0 or k == 0:
        return _shap_unavailable("empty data or no centroids")

    # ── Predict function: negative mean squared distance to each centroid ──
    # Returns a (N, k) probability-like matrix (softmax over neg distances).
    def _predict(X: np.ndarray) -> np.ndarray:
        dists = np.array([
            np.sum((X - centroids[c]) ** 2, axis=1)
            for c in range(k)
        ]).T  # (N, k)
        neg_dists = -dists
        # Softmax for numerical stability
        exp_d = np.exp(neg_dists - neg_dists.max(axis=1, keepdims=True))
        return exp_d / exp_d.sum(axis=1, keepdims=True)

    # ── Subsample for KernelExplainer ─────────────────────────────────────
    rng = np.random.default_rng(42)
    bg_size = min(MAX_KERNEL_BACKGROUND, n_rows)
    bg_idx = rng.choice(n_rows, size=bg_size, replace=False)
    background = X_scaled[bg_idx]

    sample_size = min(MAX_KERNEL_ROWS, n_rows)
    sample_idx = rng.choice(n_rows, size=sample_size, replace=False)
    X_sample = X_scaled[sample_idx]
    labels_sample = segment_labels[sample_idx]

    try:
        explainer = shap.KernelExplainer(_predict, background)
        # nsamples controls the Shapley sampling budget per row
        shap_values = explainer.shap_values(X_sample, nsamples=64, silent=True)
        # Normalise: ensure shap_values is always a list of k arrays (sample_size, n_features)
        if isinstance(shap_values, np.ndarray):
            if shap_values.ndim == 3:
                # (k, sample_size, n_features) — split along axis 0
                shap_values = [shap_values[i] for i in range(shap_values.shape[0])]
            else:
                # (sample_size, n_features) — single output; wrap in list
                shap_values = [shap_values] * k
    except Exception as exc:
        logger.warning("[explainability] Axis 3 SHAP failed: %s", exc)
        return _shap_unavailable(str(exc))

    segments_out: dict[str, Any] = {}
    for seg_idx in range(k):
        sv = shap_values[seg_idx]          # (sample_size, n_features)
        seg_mask = labels_sample == seg_idx
        # Guard: mask must match sv row count
        if len(seg_mask) != len(sv):
            seg_mask = np.zeros(len(sv), dtype=bool)
        if seg_mask.sum() == 0:
            sv_seg = sv                    # fall back to global if no samples
        else:
            sv_seg = sv[seg_mask]

        mean_abs = np.abs(sv_seg).mean(axis=0)
        mean_abs_dict = {
            feat: round(float(val), 6)
            for feat, val in zip(feature_names, mean_abs.tolist())
        }
        segments_out[str(seg_idx)] = {
            "segment_id": seg_idx,
            "n_samples_explained": int(seg_mask.sum()),
            "top_features": _top_n_by_abs(mean_abs, feature_names, top_n),
            "mean_abs_shap": mean_abs_dict,
        }

    return {
        "status": "ok",
        "method": "KernelExplainer",
        "n_explained": int(sample_size),
        "segments": segments_out,
    }


# ── Convenience wrappers used by api/routes/tools.py ──────────────────────

def explain_axis1_from_pipeline(
    gold_df: pd.DataFrame,
    result_df: pd.DataFrame,
    scaler: StandardScaler,
    iforest: IsolationForest,
    feature_cols: list[str],
) -> dict[str, Any]:
    """Wrapper that scales gold_df features and calls explain_axis1.

    Parameters
    ----------
    gold_df     : Gold Feature Store DataFrame (pre-filtered).
    result_df   : Output of pipeline_axis1.run() containing ``is_critical``.
    scaler      : Fitted StandardScaler from the pipeline run.
    iforest     : Fitted IsolationForest from the pipeline run.
    feature_cols: Feature columns actually used (intersection with gold_df).
    """
    cols = [c for c in feature_cols if c in gold_df.columns]
    if not cols:
        return _shap_unavailable("no matching feature columns in gold_df")

    common_ids = result_df["h3_id"].values
    work = gold_df[gold_df["h3_id"].isin(common_ids)].copy()
    work = work.dropna(subset=cols).reset_index(drop=True)

    if work.empty:
        return _shap_unavailable("empty feature matrix after NA drop")

    X_scaled = scaler.transform(work[cols].values.astype(float))

    # Align is_critical mask to work_df rows
    crit_map = result_df.set_index("h3_id")["is_critical"].to_dict()
    is_critical = np.array([crit_map.get(h3, 0) for h3 in work["h3_id"]])

    return explain_axis1(X_scaled, cols, iforest, is_critical)


def explain_axis2_from_pipeline(
    gold_df: pd.DataFrame,
    result_df: pd.DataFrame,
    feature_cols: list[str],
) -> dict[str, Any]:
    """Wrapper that builds original-scale feature matrix and calls explain_axis2."""
    cols = [c for c in feature_cols if c in gold_df.columns]
    if not cols:
        return _shap_unavailable("no matching feature columns in gold_df")

    common_ids = result_df["h3_id"].values
    work = gold_df[gold_df["h3_id"].isin(common_ids)].copy()
    work = work.dropna(subset=cols).reset_index(drop=True)

    if work.empty:
        return _shap_unavailable("empty feature matrix after NA drop")

    X_orig = work[cols].values.astype(float)
    label_map = result_df.set_index("h3_id")["cluster_id"].to_dict()
    labels = np.array([label_map.get(h3, -1) for h3 in work["h3_id"]])

    return explain_axis2(X_orig, cols, labels)


def explain_axis3_from_pipeline(
    gold_df: pd.DataFrame,
    result_df: pd.DataFrame,
    scaler: StandardScaler,
    centroids: np.ndarray,
    feature_cols: list[str],
) -> dict[str, Any]:
    """Wrapper that scales gold_df features and calls explain_axis3."""
    cols = [c for c in feature_cols if c in gold_df.columns]
    if not cols:
        return _shap_unavailable("no matching feature columns in gold_df")

    common_ids = result_df["h3_id"].values
    work = gold_df[gold_df["h3_id"].isin(common_ids)].copy()
    work = work.dropna(subset=cols).reset_index(drop=True)

    if work.empty:
        return _shap_unavailable("empty feature matrix after NA drop")

    X_scaled = scaler.transform(work[cols].values.astype(float))
    label_map = result_df.set_index("h3_id")["segment_id"].to_dict()
    labels = np.array([label_map.get(h3, 0) for h3 in work["h3_id"]])

    return explain_axis3(X_scaled, cols, centroids, labels)
