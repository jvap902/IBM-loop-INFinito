"""Axis 2 — Expansion Opportunities Pipeline.

Flow
----
Gold Feature Store (features: n_dom, n_com, d_down, n_erb, HHI)
    → StandardScaler
    → UMAP (n_components=2, recommended by eda-findings.md §2)
    → HDBSCAN (min_cluster_size=50 production default)
    → cluster enrichment (avg_d_down, avg_n_dom, avg_HHI per cluster)
    → validate_output()
    → Gold output table: [h3_id, cluster_id, cluster_size, avg_d_down,
                          avg_n_dom, avg_HHI, is_noise]
    → MLflow tracking (params, metrics, model artefact)

EDA-confirmed decisions (eda-findings.md §4.2)
------------------------------------------------
* Features: ["n_dom", "n_com", "d_down", "n_erb", "HHI"]
* UMAP pre-reduction recommended (trustworthiness=0.9614, §2)
* HDBSCAN: confirmed — noise rate 3.15 % in baseline (well below 25 % limit)
* Production min_cluster_size raised to 50 for H3 res-8 national datasets
  (baseline used 5 on a 2 000-row synthetic set; scale accordingly).
* Noise threshold for validation: < 25 %
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
AXIS2_FEATURES: list[str] = ["n_dom", "n_com", "d_down", "n_erb", "HHI"]
UMAP_N_COMPONENTS: int = 2
UMAP_N_NEIGHBORS: int = 15
UMAP_MIN_DIST: float = 0.0        # 0.0 recommended for clustering (tight clusters)
HDBSCAN_MIN_CLUSTER_SIZE: int = 50
HDBSCAN_MIN_SAMPLES: int = 5
NOISE_RATE_MAX: float = 0.25      # validation: < 25 % noise
N_CLUSTERS_MIN: int = 2           # validation floor
N_CLUSTERS_MAX: int = 50          # validation ceiling
MLFLOW_EXPERIMENT: str = "axis2_expansion_opportunities"


# ── Output validation ──────────────────────────────────────────────────────

def validate_output(df: pd.DataFrame) -> None:
    """Validate Axis 2 output DataFrame before persistence.

    Checks
    ------
    1. Required columns are present.
    2. No nulls in mandatory columns.
    3. Noise rate (is_noise) is below 25 %.
    4. Number of real clusters is in [N_CLUSTERS_MIN, N_CLUSTERS_MAX].

    Raises
    ------
    ValueError if any check fails.
    """
    required = {"h3_id", "cluster_id", "cluster_size", "avg_d_down",
                "avg_n_dom", "avg_HHI", "is_noise"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"[axis2] Output missing required columns: {missing}")

    null_cols = [c for c in ["h3_id", "cluster_id", "is_noise"] if df[c].isnull().any()]
    if null_cols:
        raise ValueError(f"[axis2] Null values found in mandatory columns: {null_cols}")

    noise_rate = float(df["is_noise"].mean())
    if noise_rate >= NOISE_RATE_MAX:
        raise ValueError(
            f"[axis2] Noise rate {noise_rate:.2%} exceeds maximum {NOISE_RATE_MAX:.0%}. "
            "Consider reducing min_cluster_size or reviewing input data quality."
        )

    # Use explicit boolean mask (is_noise is int 0/1, not bool)
    n_clusters = int(df[df["is_noise"] == 0]["cluster_id"].nunique())
    if not (N_CLUSTERS_MIN <= n_clusters <= N_CLUSTERS_MAX):
        raise ValueError(
            f"[axis2] {n_clusters} clusters found, expected [{N_CLUSTERS_MIN}, "
            f"{N_CLUSTERS_MAX}]. Tune HDBSCAN min_cluster_size."
        )

    logger.info(
        "[axis2] validate_output PASSED — %d rows, %d clusters, noise_rate=%.2f%%",
        len(df), n_clusters, noise_rate * 100,
    )


# ── Core pipeline ──────────────────────────────────────────────────────────

def run(
    gold_df: pd.DataFrame,
    umap_n_components: int = UMAP_N_COMPONENTS,
    umap_n_neighbors: int = UMAP_N_NEIGHBORS,
    umap_min_dist: float = UMAP_MIN_DIST,
    hdbscan_min_cluster_size: int = HDBSCAN_MIN_CLUSTER_SIZE,
    hdbscan_min_samples: int = HDBSCAN_MIN_SAMPLES,
    h3_id_col: str = "h3_id",
    skip_umap: bool = False,
    mlflow_tracking_uri: Optional[str] = None,
    enable_mlflow: bool = True,
) -> pd.DataFrame:
    """Run the Axis 2 production pipeline.

    Parameters
    ----------
    gold_df                  : Gold Feature Store DataFrame.
    umap_n_components        : UMAP output dimensions (default 2).
    umap_n_neighbors         : UMAP n_neighbors (controls local/global balance).
    umap_min_dist            : UMAP min_dist (0.0 tightens clusters for HDBSCAN).
    hdbscan_min_cluster_size : Minimum points to form a cluster.
    hdbscan_min_samples      : Core point sample size (controls noise tolerance).
    h3_id_col                : Name of the H3 cell-ID column.
    skip_umap                : If True, feed scaled features directly into HDBSCAN
                               (fallback when umap-learn is unavailable).
    mlflow_tracking_uri      : Optional MLflow server URI.
    enable_mlflow            : Set False to skip MLflow (useful in tests).

    Returns
    -------
    DataFrame with columns:
        h3_id, cluster_id, cluster_size, avg_d_down, avg_n_dom, avg_HHI, is_noise
    """
    # ── 1. Feature selection & null-row removal ────────────────────────────
    cols = [c for c in AXIS2_FEATURES if c in gold_df.columns]
    if not cols:
        raise ValueError(
            f"[axis2] No Axis 2 features found in DataFrame. "
            f"Expected at least one of {AXIS2_FEATURES}."
        )
    if h3_id_col not in gold_df.columns:
        raise ValueError(f"[axis2] h3_id column '{h3_id_col}' not found in DataFrame.")

    work_df = gold_df[[h3_id_col] + cols].dropna(subset=cols).copy()
    n_rows = len(work_df)
    logger.info("[axis2] Running on %d hexagons with features %s", n_rows, cols)

    # ── 2. Scaling ─────────────────────────────────────────────────────────
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(work_df[cols].values.astype(float))

    # ── 3. UMAP dimensionality reduction ───────────────────────────────────
    umap_reducer = None
    if skip_umap:
        X_reduced = X_scaled
        logger.info("[axis2] UMAP skipped — using scaled features directly.")
    else:
        try:
            import umap as umap_lib  # noqa: PLC0415

            umap_reducer = umap_lib.UMAP(
                n_components=umap_n_components,
                n_neighbors=umap_n_neighbors,
                min_dist=umap_min_dist,
                random_state=42,
                low_memory=True,
            )
            X_reduced = umap_reducer.fit_transform(X_scaled)
            logger.info(
                "[axis2] UMAP reduction: %s → (%d, %d)",
                X_scaled.shape, *X_reduced.shape,
            )
        except ImportError:
            logger.warning(
                "[axis2] umap-learn not installed — falling back to scaled features. "
                "Install with: pip install umap-learn"
            )
            X_reduced = X_scaled

    # ── 4. HDBSCAN clustering ──────────────────────────────────────────────
    # sklearn.cluster.HDBSCAN uses exact nearest-neighbour search by default,
    # making it fully deterministic without requiring a random_state seed.
    from sklearn.cluster import HDBSCAN  # noqa: PLC0415

    clusterer = HDBSCAN(
        min_cluster_size=hdbscan_min_cluster_size,
        min_samples=hdbscan_min_samples,
    )
    labels = clusterer.fit_predict(X_reduced)

    # ── 5. Cluster enrichment ──────────────────────────────────────────────
    n_clusters = int((np.unique(labels) != -1).sum())
    noise_count = int((labels == -1).sum())
    noise_rate = noise_count / n_rows

    logger.info(
        "[axis2] HDBSCAN: %d clusters | %d noise points (%.1f%%)",
        n_clusters, noise_count, noise_rate * 100,
    )

    # Compute per-cluster stats using original (unscaled) feature values
    work_df = work_df.copy()
    work_df["_cluster_id"] = labels

    cluster_sizes = (
        work_df.groupby("_cluster_id")["_cluster_id"]
        .count()
        .rename("cluster_size")
    )

    # Enrichment features — use what's available
    enrich_cols = {
        "avg_d_down": "d_down",
        "avg_n_dom":  "n_dom",
        "avg_HHI":    "HHI",
    }
    cluster_means: dict[str, pd.Series] = {}
    for out_col, src_col in enrich_cols.items():
        if src_col in work_df.columns:
            cluster_means[out_col] = (
                work_df.groupby("_cluster_id")[src_col].mean().round(4)
            )
        else:
            cluster_means[out_col] = pd.Series(
                np.nan, index=cluster_sizes.index, name=out_col
            )

    # Map cluster-level stats back to hexagon rows
    def _map_cluster(col_series: pd.Series) -> pd.Series:
        return work_df["_cluster_id"].map(col_series)

    output_df = pd.DataFrame({
        h3_id_col:    work_df[h3_id_col].values,
        "cluster_id": labels.astype(int),
        "cluster_size": _map_cluster(cluster_sizes).values,
        "avg_d_down": _map_cluster(cluster_means["avg_d_down"]).values,
        "avg_n_dom":  _map_cluster(cluster_means["avg_n_dom"]).values,
        "avg_HHI":    _map_cluster(cluster_means["avg_HHI"]).values,
        "is_noise":   (labels == -1).astype(int),
    })

    # Noise points get cluster_size = 1 (they form no cluster)
    output_df.loc[output_df["is_noise"] == 1, "cluster_size"] = 1

    # ── 6. Validation ──────────────────────────────────────────────────────
    validate_output(output_df)

    # ── 7. MLflow tracking ─────────────────────────────────────────────────
    if enable_mlflow:
        _log_mlflow(
            scaler=scaler,
            umap_reducer=umap_reducer,
            clusterer=clusterer,
            params={
                "umap_n_components": umap_n_components,
                "umap_n_neighbors": umap_n_neighbors,
                "umap_min_dist": umap_min_dist,
                "hdbscan_min_cluster_size": hdbscan_min_cluster_size,
                "hdbscan_min_samples": hdbscan_min_samples,
                "skip_umap": skip_umap,
                "n_features": len(cols),
                "features": ",".join(cols),
                "n_rows": n_rows,
            },
            metrics={
                "n_clusters": n_clusters,
                "noise_rate": noise_rate,
                "noise_count": noise_count,
            },
            tracking_uri=mlflow_tracking_uri,
        )

    return output_df


# ── MLflow integration ─────────────────────────────────────────────────────

def _log_mlflow(
    scaler: StandardScaler,
    umap_reducer,
    clusterer,
    params: dict,
    metrics: dict,
    tracking_uri: Optional[str],
) -> None:
    """Log params, metrics and serialised model artefacts to MLflow."""
    try:
        import mlflow  # noqa: PLC0415
    except ImportError:
        logger.warning("[axis2] mlflow not installed — skipping tracking.")
        return

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)

    mlflow.set_experiment(MLFLOW_EXPERIMENT)

    with mlflow.start_run():
        mlflow.log_params(params)
        mlflow.log_metrics({k: float(v) for k, v in metrics.items()})

        with tempfile.TemporaryDirectory() as tmpdir:
            artefact_path = Path(tmpdir) / "axis2_models.pkl"
            joblib.dump(
                {
                    "scaler": scaler,
                    "umap_reducer": umap_reducer,
                    "clusterer": clusterer,
                },
                artefact_path,
            )
            mlflow.log_artifact(str(artefact_path), artifact_path="models")

        logger.info("[axis2] MLflow run logged to experiment '%s'.", MLFLOW_EXPERIMENT)
