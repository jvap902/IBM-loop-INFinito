"""Axis 3 — Promotional Targeting Pipeline.

Flow
----
Gold Feature Store (features: ren_med, n_dom, vol_reclam, HHI, d_up)
    → StandardScaler
    → K-Means++ (k=3, confirmed by eda-findings.md §4.3)
    → Segment labelling (Premium / Conectividade Essencial / Alta Vulnerabilidade)
    → centroid distance & per-point silhouette computation
    → validate_output()
    → Gold output table: [h3_id, segment_id, segment_name, centroid_distance,
                          silhouette_score_local]
    → MLflow tracking (params, metrics, model artefact)

EDA-confirmed decisions (eda-findings.md §4.3)
------------------------------------------------
* Features: ["ren_med", "n_dom", "vol_reclam", "HHI", "d_up"]
* K-Means++ k=3 confirmed — silhouette=0.4798 >> 0.30 threshold
* Three named profiles validated empirically:
    Cluster 1 → Premium               (high income, low HHI, fast upload)
    Cluster 2 → Conectividade Essencial (mid income, mid HHI, slow upload)
    Cluster 0 → Alta Vulnerabilidade   (low income, high HHI, high complaints)
* Profile assignment is done by centroid comparison on standardised space so
  profiles remain stable across data refreshes.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_samples
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
AXIS3_FEATURES: list[str] = ["ren_med", "n_dom", "vol_reclam", "HHI", "d_up"]
K_DEFAULT: int = 3
K_SWEEP: list[int] = [3, 4, 5, 6]
SILHOUETTE_THRESHOLD: float = 0.30
N_CLUSTERS_EXPECTED: int = K_DEFAULT   # validation: must equal k

# Segment name tokens used for profile assignment.
# Each entry maps a canonical name to a "signal" of what makes that cluster
# distinct; the assignment heuristic uses centroid coordinates on scaled space.
SEGMENT_PROFILES: dict[int, str] = {
    0: "Alta Vulnerabilidade Concorrencia",
    1: "Premium",
    2: "Conectividade Essencial",
}

MLFLOW_EXPERIMENT: str = "axis3_promotional_targeting"


# ── Output validation ──────────────────────────────────────────────────────

def validate_output(df: pd.DataFrame, k: int = K_DEFAULT) -> None:
    """Validate Axis 3 output DataFrame before persistence.

    Checks
    ------
    1. Required columns are present.
    2. No nulls in mandatory columns.
    3. Number of unique segment_ids equals k.
    4. silhouette_score_local values are in [-1, 1].

    Raises
    ------
    ValueError if any check fails.
    """
    required = {"h3_id", "segment_id", "segment_name",
                "centroid_distance", "silhouette_score_local"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"[axis3] Colunas obrigatórias ausentes no resultado: {missing}")

    null_cols = [c for c in ["h3_id", "segment_id", "segment_name", "centroid_distance"]
                 if df[c].isnull().any()]
    if null_cols:
        raise ValueError(f"[axis3] Valores nulos encontrados em colunas obrigatórias: {null_cols}")

    n_segments = int(df["segment_id"].nunique())
    if n_segments != k:
        raise ValueError(
            f"[axis3] Esperados {k} segmentos, encontrados {n_segments}. "
            "Verifique a convergência do K-Means ou a qualidade dos dados."
        )

    sil_valid = df["silhouette_score_local"].dropna()
    if not sil_valid.empty and not sil_valid.between(-1.0, 1.0).all():
        raise ValueError("[axis3] Valores de silhouette_score_local fora do intervalo [-1, 1].")

    logger.info(
        "[axis3] validate_output PASSED — %d rows, %d segments.",
        len(df), n_segments,
    )


# ── Segment name assignment ────────────────────────────────────────────────

def _assign_segment_names(
    km: KMeans,
    feature_cols: list[str],
) -> dict[int, str]:
    """Map raw K-Means cluster indices to human-readable segment names.

    The assignment is based on the centroid ranking of ``ren_med`` (income)
    in scaled space:
    * Highest income centroid → "Premium"
    * Lowest income centroid  → "Alta Vulnerabilidade Concorrencia"
    * Remaining              → "Conectividade Essencial"

    Falls back to the default SEGMENT_PROFILES dict if ``ren_med`` is not
    in the feature set.

    Parameters
    ----------
    km           : Fitted KMeans instance.
    feature_cols : Ordered list of features used during fitting.

    Returns
    -------
    Dict mapping raw cluster index → segment name string.
    """
    if "ren_med" not in feature_cols:
        logger.warning(
            "[axis3] 'ren_med' not in features; using default profile indices."
        )
        return {i: SEGMENT_PROFILES.get(i, f"Segment_{i}") for i in range(km.n_clusters)}

    ren_idx = feature_cols.index("ren_med")
    centroids = km.cluster_centers_  # shape (k, n_features), in scaled space

    # Sort cluster indices by ren_med centroid value
    sorted_by_income = np.argsort(centroids[:, ren_idx])   # ascending
    low_income_cluster  = int(sorted_by_income[0])
    high_income_cluster = int(sorted_by_income[-1])

    mapping: dict[int, str] = {}
    for i in range(km.n_clusters):
        if i == high_income_cluster:
            mapping[i] = "Premium"
        elif i == low_income_cluster:
            mapping[i] = "Alta Vulnerabilidade Concorrencia"
        else:
            mapping[i] = "Conectividade Essencial"

    logger.info("[axis3] Segment name mapping: %s", mapping)
    return mapping


# ── Core pipeline ──────────────────────────────────────────────────────────

def run(
    gold_df: pd.DataFrame,
    k: int = K_DEFAULT,
    sweep_if_low_silhouette: bool = True,
    h3_id_col: str = "h3_id",
    mlflow_tracking_uri: Optional[str] = None,
    enable_mlflow: bool = True,
) -> pd.DataFrame:
    """Run the Axis 3 production pipeline.

    Parameters
    ----------
    gold_df                  : Gold Feature Store DataFrame.
    k                        : Number of clusters (default 3, EDA-confirmed).
    sweep_if_low_silhouette  : If True, sweep k ∈ [3,6] when silhouette < 0.30.
    h3_id_col                : Name of the H3 cell-ID column.
    mlflow_tracking_uri      : Optional MLflow server URI.
    enable_mlflow            : Set False to skip MLflow (useful in tests).

    Returns
    -------
    DataFrame with columns:
        h3_id, segment_id, segment_name, centroid_distance, silhouette_score_local
    """
    # ── 1. Feature selection & null-row removal ────────────────────────────
    cols = [c for c in AXIS3_FEATURES if c in gold_df.columns]
    if not cols:
        raise ValueError(
            f"[axis3] Nenhuma feature do Eixo 3 encontrada no DataFrame. "
            f"Esperada ao menos uma de {AXIS3_FEATURES}."
        )
    if h3_id_col not in gold_df.columns:
        raise ValueError(f"[axis3] Coluna h3_id '{h3_id_col}' não encontrada no DataFrame.")

    work_df = gold_df[[h3_id_col] + cols].dropna(subset=cols).copy()
    n_rows = len(work_df)
    logger.info("[axis3] Running on %d hexagons with features %s", n_rows, cols)

    # ── 2. Scaling ─────────────────────────────────────────────────────────
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(work_df[cols].values.astype(float))

    # ── 3. K-Means++ with optional k-sweep ────────────────────────────────
    def _fit(n_clusters: int) -> tuple[KMeans, np.ndarray, float]:
        km = KMeans(
            n_clusters=n_clusters,
            init="k-means++",
            n_init=10,
            max_iter=300,
            random_state=42,
        )
        lbls = km.fit_predict(X_scaled)
        # Global silhouette
        from sklearn.metrics import silhouette_score  # noqa: PLC0415
        try:
            sil = float(silhouette_score(X_scaled, lbls))
        except ValueError:
            sil = float("nan")
        logger.info("[axis3] KMeans++(k=%d) silhouette=%.4f", n_clusters, sil)
        return km, lbls, sil

    km, labels, sil = _fit(k)
    best_k, best_sil, best_km, best_labels = k, sil, km, labels
    swept = False

    if sweep_if_low_silhouette and (np.isnan(sil) or sil < SILHOUETTE_THRESHOLD):
        logger.info(
            "[axis3] Silhouette %.4f < %.2f → sweeping k ∈ %s",
            sil, SILHOUETTE_THRESHOLD, K_SWEEP,
        )
        swept = True
        for k_cand in K_SWEEP:
            if k_cand == k:
                continue
            km_c, lbl_c, sil_c = _fit(k_cand)
            if not np.isnan(sil_c) and sil_c > best_sil:
                best_k, best_sil, best_km, best_labels = k_cand, sil_c, km_c, lbl_c
        if best_k != k:
            logger.info("[axis3] k-sweep selected k=%d (silhouette=%.4f)", best_k, best_sil)

    # ── 4. Per-point silhouette scores ─────────────────────────────────────
    try:
        sil_samples = silhouette_samples(X_scaled, best_labels)
    except ValueError:
        sil_samples = np.full(n_rows, fill_value=np.nan)

    # ── 5. Centroid distances ──────────────────────────────────────────────
    centroids = best_km.cluster_centers_
    centroid_dists = np.array([
        float(np.linalg.norm(X_scaled[i] - centroids[best_labels[i]]))
        for i in range(n_rows)
    ])

    # ── 6. Segment name assignment ─────────────────────────────────────────
    name_map = _assign_segment_names(best_km, cols)
    segment_names = np.array([name_map[lbl] for lbl in best_labels])

    # ── 7. Build output DataFrame ──────────────────────────────────────────
    output_df = pd.DataFrame({
        h3_id_col:              work_df[h3_id_col].values,
        "segment_id":           best_labels.astype(int),
        "segment_name":         segment_names,
        "centroid_distance":    np.round(centroid_dists, 6),
        "silhouette_score_local": np.round(sil_samples, 6),
    })

    # ── 8. Validation ──────────────────────────────────────────────────────
    validate_output(output_df, k=best_k)

    # ── 9. Summary log ─────────────────────────────────────────────────────
    for seg_id, seg_name in name_map.items():
        count = int((best_labels == seg_id).sum())
        logger.info(
            "[axis3] Segment %d (%s): %d hexagons (%.1f%%)",
            seg_id, seg_name, count, 100 * count / n_rows,
        )

    # ── 10. MLflow tracking ────────────────────────────────────────────────
    if enable_mlflow:
        _log_mlflow(
            scaler=scaler,
            km=best_km,
            params={
                "k": best_k,
                "swept": swept,
                "init": "k-means++",
                "n_init": 10,
                "n_features": len(cols),
                "features": ",".join(cols),
                "n_rows": n_rows,
            },
            metrics={
                "silhouette_score_global": best_sil if not np.isnan(best_sil) else -1.0,
                "n_segments": best_k,
            },
            tracking_uri=mlflow_tracking_uri,
        )

    return output_df


# ── MLflow integration ─────────────────────────────────────────────────────

def _log_mlflow(
    scaler: StandardScaler,
    km: KMeans,
    params: dict,
    metrics: dict,
    tracking_uri: Optional[str],
) -> None:
    """Log params, metrics and serialised model artefacts to MLflow."""
    try:
        import mlflow  # noqa: PLC0415
    except ImportError:
        logger.warning("[axis3] mlflow not installed — skipping tracking.")
        return

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)

    mlflow.set_experiment(MLFLOW_EXPERIMENT)

    with mlflow.start_run():
        mlflow.log_params(params)
        mlflow.log_metrics({k: float(v) for k, v in metrics.items()})

        with tempfile.TemporaryDirectory() as tmpdir:
            artefact_path = Path(tmpdir) / "axis3_models.pkl"
            joblib.dump({"scaler": scaler, "kmeans": km}, artefact_path)
            mlflow.log_artifact(str(artefact_path), artifact_path="models")

        logger.info("[axis3] MLflow run logged to experiment '%s'.", MLFLOW_EXPERIMENT)
