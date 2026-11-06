"""Axis 1 — Maintenance & Criticality Pipeline.

Flow
----
Gold Feature Store (features: lat, vol_reclam, d_down)
    → StandardScaler
    → IsolationForest  (anomaly scoring)
    → LOF              (local outlier scoring, novelty=True applied on scaled data)
    → Cloudflare Radar cross-reference
    → validate_output()
    → Gold output table: [h3_id, anomaly_score, is_critical, lof_score,
                          cloudflare_outage_overlap]
    → MLflow tracking (params, metrics, model artefact)

EDA-confirmed decisions (eda-findings.md §4.1)
------------------------------------------------
* Features: ["lat", "vol_reclam", "d_down"]
* IsolationForest contamination=0.05 (5 %)
* Flagging via predict() == -1 (honours contamination); normalised score exposed
* anomaly_score threshold for is_critical: 0.65
* LOF used in novelty=True mode so it can score new data post-fit
* Cloudflare agreement >= 60 % confirms axis health
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# ── Constants (from knowledge-api.json / eda-findings.md) ─────────────────
AXIS1_FEATURES: list[str] = ["lat", "vol_reclam", "d_down"]
ANOMALY_SCORE_THRESHOLD: float = 0.65   # is_critical gate
CONTAMINATION: float = 0.05             # 5 % expected anomaly rate
LOF_N_NEIGHBORS: int = 20
ANOMALY_RATE_MIN: float = 0.01          # validation: 1 % floor
ANOMALY_RATE_MAX: float = 0.15          # validation: 15 % ceiling
MLFLOW_EXPERIMENT: str = "axis1_maintenance_criticality"


# ── Output validation ──────────────────────────────────────────────────────

def validate_output(df: pd.DataFrame) -> None:
    """Validate Axis 1 output DataFrame before persistence.

    Checks
    ------
    1. Required columns are present.
    2. No nulls in mandatory columns.
    3. anomaly_score is in [0, 1].
    4. Anomaly rate (is_critical) is between 1 % and 15 %.

    Raises
    ------
    ValueError if any check fails.
    """
    required = {"h3_id", "anomaly_score", "is_critical", "lof_score",
                "cloudflare_outage_overlap"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"[axis1] Colunas obrigatórias ausentes no resultado: {missing}")

    null_cols = [c for c in ["h3_id", "anomaly_score", "is_critical", "lof_score"]
                 if df[c].isnull().any()]
    if null_cols:
        raise ValueError(f"[axis1] Valores nulos encontrados em colunas obrigatórias: {null_cols}")

    if not df["anomaly_score"].between(0.0, 1.0).all():
        raise ValueError("[axis1] Valores de anomaly_score fora do intervalo [0, 1].")

    anomaly_rate = float(df["is_critical"].mean())
    if not (ANOMALY_RATE_MIN <= anomaly_rate <= ANOMALY_RATE_MAX):
        raise ValueError(
            f"[axis1] Taxa de anomalia {anomaly_rate:.2%} fora do intervalo aceitável "
            f"[{ANOMALY_RATE_MIN:.0%}, {ANOMALY_RATE_MAX:.0%}]. "
            "Considere ajustar o parâmetro de contaminação."
        )

    logger.info(
        "[axis1] validate_output PASSED — %d rows, anomaly_rate=%.2f%%",
        len(df), anomaly_rate * 100,
    )


# ── Core pipeline ──────────────────────────────────────────────────────────

def run(
    gold_df: pd.DataFrame,
    cloudflare_outage_h3_ids: Optional[set[str]] = None,
    contamination: float = CONTAMINATION,
    anomaly_score_threshold: float = ANOMALY_SCORE_THRESHOLD,
    lof_n_neighbors: int = LOF_N_NEIGHBORS,
    h3_id_col: str = "h3_id",
    mlflow_tracking_uri: Optional[str] = None,
    enable_mlflow: bool = True,
) -> pd.DataFrame:
    """Run the Axis 1 production pipeline.

    Parameters
    ----------
    gold_df                  : Gold Feature Store DataFrame (must contain
                               ``h3_id`` + AXIS1_FEATURES columns).
    cloudflare_outage_h3_ids : Optional set of H3 IDs flagged as outages by
                               Cloudflare Radar (used for overlap tagging and
                               agreement metric).
    contamination            : IsolationForest expected anomaly fraction.
    anomaly_score_threshold  : Normalised IF score threshold for ``is_critical``.
    lof_n_neighbors          : LOF neighbourhood size.
    h3_id_col                : Name of the H3 cell-ID column.
    mlflow_tracking_uri      : Optional MLflow server URI (default: local ./mlruns).
    enable_mlflow            : Set False to skip MLflow tracking (useful in tests).

    Returns
    -------
    DataFrame with columns:
        h3_id, anomaly_score, is_critical, lof_score, cloudflare_outage_overlap
    """
    # ── 1. Feature selection & null-row removal ────────────────────────────
    cols = [c for c in AXIS1_FEATURES if c in gold_df.columns]
    if not cols:
        raise ValueError(
            f"[axis1] Nenhuma feature do Eixo 1 encontrada no DataFrame. "
            f"Esperada ao menos uma de {AXIS1_FEATURES}."
        )
    if h3_id_col not in gold_df.columns:
        raise ValueError(f"[axis1] Coluna h3_id '{h3_id_col}' não encontrada no DataFrame.")

    work_df = gold_df[[h3_id_col] + cols].dropna(subset=cols).copy()
    n_rows = len(work_df)
    logger.info("[axis1] Running on %d hexagons with features %s", n_rows, cols)

    # ── 2. Scaling ─────────────────────────────────────────────────────────
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(work_df[cols].values.astype(float))

    # ── 3. IsolationForest ─────────────────────────────────────────────────
    iforest = IsolationForest(
        contamination=contamination,
        random_state=42,
        n_estimators=200,
    )
    iforest.fit(X_scaled)

    # decision_function lives in sklearn's internal range (~[-0.2, +0.2]).
    # Normalise to [0, 1] where 1 = most anomalous (flip sign then min-max).
    raw_scores = iforest.decision_function(X_scaled)
    flipped = -raw_scores
    s_min, s_max = flipped.min(), flipped.max()
    anomaly_scores = (flipped - s_min) / (s_max - s_min + 1e-9)

    # Primary flag from predict(): honours contamination parameter exactly.
    if_labels = iforest.predict(X_scaled)  # +1 normal, -1 anomaly

    # ── 4. LOF (novelty mode — fitted then scored on the same data) ────────
    # novelty=True allows decision_function on training data and future data
    lof = LocalOutlierFactor(n_neighbors=lof_n_neighbors, novelty=True)
    lof.fit(X_scaled)
    # decision_function: negative_outlier_factor in (−∞, 0]; closer to 0 = normal.
    # Normalise to [0, 1] where 1 = most anomalous.
    lof_raw = lof.decision_function(X_scaled)
    lof_flipped = -lof_raw
    lof_min, lof_max = lof_flipped.min(), lof_flipped.max()
    lof_scores = (lof_flipped - lof_min) / (lof_max - lof_min + 1e-9)

    # ── 5. Ensemble: critical = IF anomaly AND score >= threshold ──────────
    is_critical = (
        (if_labels == -1) & (anomaly_scores >= anomaly_score_threshold)
    ).astype(int)

    # ── 6. Cloudflare overlap ──────────────────────────────────────────────
    cf_set = cloudflare_outage_h3_ids or set()
    cloudflare_overlap = work_df[h3_id_col].isin(cf_set).astype(int)

    # ── 7. Build output DataFrame ──────────────────────────────────────────
    output_df = pd.DataFrame({
        h3_id_col:                   work_df[h3_id_col].values,
        "anomaly_score":             np.round(anomaly_scores, 6),
        "is_critical":               is_critical,
        "lof_score":                 np.round(lof_scores, 6),
        "cloudflare_outage_overlap": cloudflare_overlap.values,
    })

    # ── 8. Validation ──────────────────────────────────────────────────────
    validate_output(output_df)

    # ── 9. Metrics for logging ─────────────────────────────────────────────
    anomaly_rate = float(is_critical.mean())
    cf_agreement: Optional[float] = None
    if cf_set:
        flagged_h3 = set(output_df[output_df["is_critical"] == 1][h3_id_col].values)
        cf_agreement = len(flagged_h3 & cf_set) / len(cf_set) if cf_set else float("nan")
        logger.info(
            "[axis1] Cloudflare agreement=%.2f%% (%d/%d known outage cells recovered)",
            cf_agreement * 100,
            len(flagged_h3 & cf_set),
            len(cf_set),
        )

    logger.info(
        "[axis1] Pipeline complete — %d critical hexagons / %d total (rate=%.2f%%)",
        int(is_critical.sum()), n_rows, anomaly_rate * 100,
    )

    # ── 10. MLflow tracking ────────────────────────────────────────────────
    if enable_mlflow:
        _log_mlflow(
            scaler=scaler,
            iforest=iforest,
            lof=lof,
            params={
                "contamination": contamination,
                "anomaly_score_threshold": anomaly_score_threshold,
                "lof_n_neighbors": lof_n_neighbors,
                "n_features": len(cols),
                "features": ",".join(cols),
                "n_rows": n_rows,
            },
            metrics={
                "anomaly_rate": anomaly_rate,
                "n_critical": int(is_critical.sum()),
                "cloudflare_agreement": cf_agreement if cf_agreement is not None else -1.0,
            },
            tracking_uri=mlflow_tracking_uri,
        )

    return output_df


# ── MLflow integration ─────────────────────────────────────────────────────

def _log_mlflow(
    scaler: StandardScaler,
    iforest: IsolationForest,
    lof: LocalOutlierFactor,
    params: dict,
    metrics: dict,
    tracking_uri: Optional[str],
) -> None:
    """Log params, metrics and serialised model artefacts to MLflow."""
    try:
        import mlflow  # noqa: PLC0415
    except ImportError:
        logger.warning("[axis1] mlflow not installed — skipping tracking.")
        return

    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)

    mlflow.set_experiment(MLFLOW_EXPERIMENT)

    with mlflow.start_run():
        mlflow.log_params(params)
        mlflow.log_metrics({k: v for k, v in metrics.items() if v is not None})

        with tempfile.TemporaryDirectory() as tmpdir:
            artefact_path = Path(tmpdir) / "axis1_models.pkl"
            joblib.dump(
                {"scaler": scaler, "iforest": iforest, "lof": lof},
                artefact_path,
            )
            mlflow.log_artifact(str(artefact_path), artifact_path="models")

        logger.info("[axis1] MLflow run logged to experiment '%s'.", MLFLOW_EXPERIMENT)
