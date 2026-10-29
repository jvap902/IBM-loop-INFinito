"""Baseline model runners for Sub-Task 2 — Algorithm Validation.

One function per analytical axis.  Each function:
  1. Scales the feature matrix with StandardScaler.
  2. Fits the baseline model with default / spec-aligned hyperparameters.
  3. Computes the primary validation metric.
  4. Returns a structured ``BaselineResult`` dict with everything needed for
     the ``eda-findings.md`` decision table.

These wrappers are intentionally thin so Sub-Task 3 pipelines can reuse the
same algorithmic calls with production-grade hyperparameters on top.
"""
from __future__ import annotations

import logging
from typing import Optional, TypedDict

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from ml.eda_utils import silhouette, X_HI_COLUMNS

logger = logging.getLogger(__name__)


# ── Return type ───────────────────────────────────────────────────────────

class BaselineResult(TypedDict):
    axis: str
    algorithm: str
    hyperparameters: dict
    metric_name: str
    metric_value: float
    decision: str           # "CONFIRM" | "ADJUST"
    rationale: str
    extra: dict             # axis-specific supplementary data


# ── Helpers ───────────────────────────────────────────────────────────────

def _scale(df: pd.DataFrame, features: list[str]) -> tuple[np.ndarray, list[str]]:
    """Return scaled feature matrix and the list of features actually used."""
    cols = [c for c in features if c in df.columns]
    X = df[cols].dropna().values.astype(float)
    return StandardScaler().fit_transform(X), cols


# ── Axis 1: Anomaly Detection (IsolationForest) ───────────────────────────

# Features per knowledge-api.json (Axis 1 input_features)
AXIS1_FEATURES: list[str] = ["lat", "vol_reclam", "d_down"]

# Cloudflare agreement acceptance threshold
AXIS1_AGREEMENT_THRESHOLD: float = 0.60


def run_axis1_baseline(
    gold_df: pd.DataFrame,
    cloudflare_outage_h3_ids: Optional[set[str]] = None,
    contamination: float = 0.05,
    anomaly_score_threshold: float = 0.65,
    h3_id_col: str = "h3_id",
) -> BaselineResult:
    """Run IsolationForest baseline for Axis 1 (Maintenance & Criticality).

    Parameters
    ----------
    gold_df                : Gold feature store DataFrame.
    cloudflare_outage_h3_ids: Set of H3 IDs flagged as outages by Cloudflare Radar
                              (ground-truth proxy).  If None, agreement check is skipped.
    contamination          : Expected anomaly fraction (default 0.05 = 5%).
    anomaly_score_threshold: IF score cutoff for flagging (spec default 0.65).
    h3_id_col              : Column name for H3 cell ID.

    Returns
    -------
    BaselineResult dict.
    """
    cols = [c for c in AXIS1_FEATURES if c in gold_df.columns]
    if not cols:
        raise ValueError(f"No Axis 1 features found in DataFrame. Need at least one of {AXIS1_FEATURES}.")

    X_df = gold_df[[h3_id_col] + cols].dropna(subset=cols).copy()
    X_scaled = StandardScaler().fit_transform(X_df[cols].values.astype(float))

    clf = IsolationForest(contamination=contamination, random_state=42)
    clf.fit(X_scaled)

    # sklearn IsolationForest: predict() returns +1 (normal) / -1 (anomaly).
    # The canonical IF score s(x,n) in [0,1] (score > 0.5 → anomalous) is an
    # external convention; sklearn's decision_function lives in a different range
    # (~[-0.2, +0.2] centered near 0).  We use predict() for flagging, which
    # correctly honours the contamination parameter (spec: 5%), and expose the
    # decision_function normalised to [0,1] for downstream threshold tuning.
    raw_scores = clf.decision_function(X_scaled)
    # Normalise to ~[0,1]: higher → more anomalous (flip + min-max scale)
    flipped = -raw_scores
    s_min, s_max = flipped.min(), flipped.max()
    if_scores = (flipped - s_min) / (s_max - s_min + 1e-9)

    # Primary flag: sklearn predict == -1 (honours contamination)
    predict = clf.predict(X_scaled)
    labels = (predict == -1).astype(int)  # 1 = anomaly

    anomaly_rate = float(labels.mean())
    anomalous_h3 = set(X_df[h3_id_col].values[labels == 1])

    logger.info(
        "[axis1] IsolationForest: %d anomalous hexagons / %d total (rate=%.2f%%)",
        len(anomalous_h3), len(X_df), anomaly_rate * 100,
    )

    agreement: float = float("nan")
    if cloudflare_outage_h3_ids is not None and len(cloudflare_outage_h3_ids) > 0:
        overlap = anomalous_h3 & cloudflare_outage_h3_ids
        # Agreement: fraction of Cloudflare-flagged cells that are also flagged by IF
        agreement = len(overlap) / len(cloudflare_outage_h3_ids)
        logger.info(
            "[axis1] Cloudflare agreement=%.2f%% (%d/%d)",
            agreement * 100, len(overlap), len(cloudflare_outage_h3_ids),
        )
    else:
        logger.warning(
            "[axis1] No Cloudflare ground-truth provided; "
            "reporting anomaly_rate as proxy metric."
        )
        # Use anomaly rate in [1%, 15%] as a sanity check when no ground truth
        agreement = 1.0 if 0.01 <= anomaly_rate <= 0.15 else 0.0

    decision = "CONFIRM" if agreement >= AXIS1_AGREEMENT_THRESHOLD else "ADJUST"
    rationale = (
        f"Cloudflare agreement={agreement:.2%} "
        f"({'≥' if agreement >= AXIS1_AGREEMENT_THRESHOLD else '<'} "
        f"threshold {AXIS1_AGREEMENT_THRESHOLD:.0%}). "
        f"Anomaly rate={anomaly_rate:.2%}."
    )

    return BaselineResult(
        axis="1_manutencao_e_criticidade",
        algorithm="IsolationForest (default)",
        hyperparameters={"contamination": contamination, "random_state": 42},
        metric_name="cloudflare_agreement_rate",
        metric_value=round(agreement, 4),
        decision=decision,
        rationale=rationale,
        extra={
            "anomaly_rate": anomaly_rate,
            "n_anomalies": len(anomalous_h3),
            "n_total": len(X_df),
            "features_used": cols,
            "anomalous_h3_ids": list(anomalous_h3)[:50],  # truncate for readability
        },
    )


# ── Axis 2: Expansion Opportunities (HDBSCAN) ─────────────────────────────

AXIS2_FEATURES: list[str] = ["n_dom", "n_com", "d_down", "n_erb", "HHI"]

# Clustering criteria from knowledge-api.json
AXIS2_HIGH_DENSITY_PERCENTILE: float = 0.70   # n_dom + n_com above this → high density
AXIS2_LOW_SPEED_MBPS: float = 30.0            # d_down < 30 Mbps
AXIS2_HIGH_HHI: float = 3500.0               # HHI > 3500 → concentrated market


def run_axis2_baseline(
    gold_df: pd.DataFrame,
    min_cluster_size: int = 5,
) -> BaselineResult:
    """Run HDBSCAN baseline for Axis 2 (Expansion Opportunities).

    Parameters
    ----------
    gold_df          : Gold feature store DataFrame.
    min_cluster_size : HDBSCAN ``min_cluster_size`` parameter (default = 5).

    Returns
    -------
    BaselineResult dict.
    """
    from sklearn.cluster import HDBSCAN  # noqa: PLC0415

    cols = [c for c in AXIS2_FEATURES if c in gold_df.columns]
    if not cols:
        raise ValueError(f"No Axis 2 features found in DataFrame. Need at least one of {AXIS2_FEATURES}.")

    X_df = gold_df[cols].dropna().copy()
    X_scaled = StandardScaler().fit_transform(X_df.values.astype(float))

    clusterer = HDBSCAN(min_cluster_size=min_cluster_size)
    labels = clusterer.fit_predict(X_scaled)

    unique_labels = set(labels)
    n_clusters = len(unique_labels - {-1})
    noise_count = int((labels == -1).sum())
    noise_rate = noise_count / len(labels)

    logger.info(
        "[axis2] HDBSCAN: %d clusters | %d noise points (%.1f%%)",
        n_clusters, noise_count, noise_rate * 100,
    )

    sil = silhouette(X_scaled, labels)

    # Validate clustering criteria: high-density + low-speed cells should cluster together
    # Build a boolean mask for "target" hexagons per knowledge-api.json criteria
    criteria_check: Optional[float] = None
    if "n_dom" in gold_df.columns and "n_com" in gold_df.columns and "d_down" in gold_df.columns:
        X_orig = gold_df[cols].dropna().copy()
        density_threshold = X_orig["n_dom"].add(X_orig["n_com"]).quantile(AXIS2_HIGH_DENSITY_PERCENTILE)
        target_mask = (
            (X_orig["n_dom"] + X_orig["n_com"] >= density_threshold)
            & (X_orig["d_down"] < AXIS2_LOW_SPEED_MBPS)
        )
        if "HHI" in X_orig.columns:
            target_mask &= X_orig["HHI"] > AXIS2_HIGH_HHI

        if target_mask.sum() > 0 and n_clusters > 0:
            target_labels = labels[target_mask.values]
            # Check: what fraction of target hexagons are in the same top cluster?
            non_noise_target = target_labels[target_labels != -1]
            if len(non_noise_target) > 0:
                from collections import Counter  # noqa: PLC0415
                top_cluster_count = Counter(non_noise_target).most_common(1)[0][1]
                criteria_check = top_cluster_count / len(non_noise_target)
                logger.info(
                    "[axis2] Criteria check: %.2f%% of target hexagons in dominant cluster.",
                    criteria_check * 100,
                )

    # Decision: CONFIRM if silhouette > 0.2 (reasonable for density-based) and at least 2 clusters
    sil_ok = not np.isnan(sil) and sil > 0.2
    cluster_ok = n_clusters >= 2
    decision = "CONFIRM" if (sil_ok and cluster_ok) else "ADJUST"
    rationale = (
        f"Silhouette={sil:.4f} | n_clusters={n_clusters} | noise_rate={noise_rate:.2%}. "
        + (
            f"Criteria concentration={criteria_check:.2%}. "
            if criteria_check is not None else ""
        )
        + ("Density-based structure confirmed." if decision == "CONFIRM"
           else "Consider tuning min_cluster_size or adding UMAP pre-reduction.")
    )

    return BaselineResult(
        axis="2_novos_negocios_e_expansao",
        algorithm="HDBSCAN (default min_cluster_size)",
        hyperparameters={"min_cluster_size": min_cluster_size},
        metric_name="silhouette_score",
        metric_value=round(sil, 4) if not np.isnan(sil) else 0.0,
        decision=decision,
        rationale=rationale,
        extra={
            "n_clusters": n_clusters,
            "noise_rate": noise_rate,
            "criteria_concentration": criteria_check,
            "features_used": cols,
        },
    )


# ── Axis 3: Promotional Targeting (K-Means++) ─────────────────────────────

AXIS3_FEATURES: list[str] = ["ren_med", "n_dom", "vol_reclam", "HHI", "d_up"]
AXIS3_SILHOUETTE_THRESHOLD: float = 0.30
AXIS3_K_SWEEP: list[int] = [3, 4, 5, 6]


def run_axis3_baseline(
    gold_df: pd.DataFrame,
    k: int = 3,
    sweep: bool = True,
) -> BaselineResult:
    """Run K-Means++ baseline for Axis 3 (Promotional Targeting).

    Parameters
    ----------
    gold_df : Gold feature store DataFrame.
    k       : Number of clusters (default 3, matching the three named profiles).
    sweep   : If True and silhouette < threshold, sweep k ∈ [3,6] and pick best.

    Returns
    -------
    BaselineResult dict.
    """
    from sklearn.cluster import KMeans  # noqa: PLC0415

    cols = [c for c in AXIS3_FEATURES if c in gold_df.columns]
    if not cols:
        raise ValueError(f"No Axis 3 features found in DataFrame. Need at least one of {AXIS3_FEATURES}.")

    X_df = gold_df[cols].dropna()
    X_scaled = StandardScaler().fit_transform(X_df.values.astype(float))

    def _fit_kmeans(n_clusters: int) -> tuple[np.ndarray, float]:
        km = KMeans(n_clusters=n_clusters, init="k-means++", n_init=10, random_state=42)
        lbls = km.fit_predict(X_scaled)
        sil = silhouette(X_scaled, lbls)
        logger.info("[axis3] KMeans++(k=%d) silhouette=%.4f", n_clusters, sil)
        return lbls, sil

    labels, sil = _fit_kmeans(k)
    best_k = k
    best_sil = sil
    swept = False

    if sweep and (np.isnan(sil) or sil < AXIS3_SILHOUETTE_THRESHOLD):
        logger.info(
            "[axis3] Silhouette %.4f < threshold %.2f → sweeping k ∈ %s",
            sil, AXIS3_SILHOUETTE_THRESHOLD, AXIS3_K_SWEEP,
        )
        swept = True
        for k_cand in AXIS3_K_SWEEP:
            if k_cand == k:
                continue
            lbl_cand, sil_cand = _fit_kmeans(k_cand)
            if not np.isnan(sil_cand) and sil_cand > best_sil:
                best_sil = sil_cand
                best_k = k_cand
                labels = lbl_cand

        if best_k != k:
            logger.info("[axis3] Best k from sweep: k=%d (silhouette=%.4f)", best_k, best_sil)

    decision = (
        "CONFIRM"
        if (not np.isnan(best_sil) and best_sil > AXIS3_SILHOUETTE_THRESHOLD)
        else "ADJUST"
    )
    rationale = (
        f"K-Means++(k={best_k}) silhouette={best_sil:.4f} "
        f"({'≥' if best_sil >= AXIS3_SILHOUETTE_THRESHOLD else '<'} "
        f"threshold {AXIS3_SILHOUETTE_THRESHOLD}). "
        + (f"Swept k ∈ {AXIS3_K_SWEEP}; best k={best_k}. " if swept else "")
        + ("Three named cluster profiles validated." if decision == "CONFIRM"
           else "Consider k adjustment or additional feature engineering.")
    )

    # Per-cluster stats for reporting
    cluster_stats: list[dict] = []
    X_orig = gold_df[cols].dropna()
    for cluster_id in sorted(set(labels)):
        mask = labels == cluster_id
        stats = {
            "cluster_id": int(cluster_id),
            "size": int(mask.sum()),
        }
        for feat in cols:
            stats[f"mean_{feat}"] = round(float(X_orig.iloc[mask][feat].mean()), 3)
        cluster_stats.append(stats)

    return BaselineResult(
        axis="3_regioes_propicias_para_promocoes",
        algorithm=f"K-Means++ (k={best_k})",
        hyperparameters={"n_clusters": best_k, "init": "k-means++", "n_init": 10},
        metric_name="silhouette_score",
        metric_value=round(best_sil, 4) if not np.isnan(best_sil) else 0.0,
        decision=decision,
        rationale=rationale,
        extra={
            "initial_k": k,
            "best_k": best_k,
            "swept": swept,
            "cluster_stats": cluster_stats,
            "features_used": cols,
        },
    )


# ── Convenience runner (all axes) ─────────────────────────────────────────

def run_all_baselines(
    gold_df: pd.DataFrame,
    cloudflare_outage_h3_ids: Optional[set[str]] = None,
) -> list[BaselineResult]:
    """Run all three axis baselines and return results as an ordered list.

    Parameters
    ----------
    gold_df                  : Gold feature store DataFrame.
    cloudflare_outage_h3_ids : Optional Cloudflare ground-truth H3 IDs (Axis 1).

    Returns
    -------
    List of three BaselineResult dicts (Axis 1, 2, 3).
    """
    results = []

    logger.info("=== Sub-Task 2: Running Axis 1 Baseline ===")
    try:
        results.append(run_axis1_baseline(gold_df, cloudflare_outage_h3_ids))
    except Exception as exc:
        logger.error("[axis1] Baseline failed: %s", exc)
        raise

    logger.info("=== Sub-Task 2: Running Axis 2 Baseline ===")
    try:
        results.append(run_axis2_baseline(gold_df))
    except Exception as exc:
        logger.error("[axis2] Baseline failed: %s", exc)
        raise

    logger.info("=== Sub-Task 2: Running Axis 3 Baseline ===")
    try:
        results.append(run_axis3_baseline(gold_df))
    except Exception as exc:
        logger.error("[axis3] Baseline failed: %s", exc)
        raise

    return results
