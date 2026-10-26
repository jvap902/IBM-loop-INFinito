"""EDA utility functions for Sub-Task 2.

Reusable helpers consumed by:
  * notebooks/01_eda_feature_store.ipynb (interactive exploration)
  * ml/baseline_runners.py               (pre-processing)
  * ml/pipelines/*                       (Sub-Task 3 production pipelines)

All functions are pure (no side-effects beyond logging) and return plain
pandas / numpy / sklearn objects so they can be composed freely.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

# ── Feature vector canonical order (mirrors knowledge-api.json) ────────────
X_HI_COLUMNS: list[str] = [
    "d_down",
    "d_up",
    "lat",
    "vol_test",
    "n_dom",
    "n_com",
    "ren_med",
    "n_erb",
    "HHI",
    "vol_reclam",
]

# VIF multicollinearity threshold (literature standard)
VIF_THRESHOLD: float = 10.0


# ── Correlation helpers ────────────────────────────────────────────────────

def compute_correlation_matrix(
    df: pd.DataFrame,
    features: list[str] = X_HI_COLUMNS,
    method: str = "pearson",
) -> pd.DataFrame:
    """Compute a correlation matrix for the given features.

    Parameters
    ----------
    df       : DataFrame containing feature columns.
    features : Subset of columns to include (defaults to full x_hi vector).
    method   : ``"pearson"`` or ``"spearman"``.

    Returns
    -------
    Symmetric correlation DataFrame (features × features).
    """
    cols = [c for c in features if c in df.columns]
    if len(cols) < 2:
        raise ValueError(f"Need ≥2 features for correlation; got {cols}")
    corr = df[cols].corr(method=method)
    logger.info("[eda_utils] %s correlation matrix computed (%dx%d).", method, *corr.shape)
    return corr


# ── VIF ───────────────────────────────────────────────────────────────────

def compute_vif(
    df: pd.DataFrame,
    features: list[str] = X_HI_COLUMNS,
) -> pd.DataFrame:
    """Compute Variance Inflation Factor for each feature.

    Uses OLS R² of each feature regressed on all others:
        VIF_j = 1 / (1 - R²_j)

    Parameters
    ----------
    df       : DataFrame of numeric features (no NaNs).
    features : Feature columns to include.

    Returns
    -------
    DataFrame with columns ``["feature", "VIF", "flag_multicollinearity"]``
    sorted by VIF descending.  Rows with VIF > ``VIF_THRESHOLD`` are flagged.
    """
    from sklearn.linear_model import LinearRegression

    cols = [c for c in features if c in df.columns]
    X = df[cols].dropna().values.astype(float)

    if X.shape[0] < X.shape[1] + 1:
        raise ValueError(
            "Not enough rows to compute VIF. "
            f"Need > {X.shape[1] + 1} rows, got {X.shape[0]}."
        )

    vif_values: list[dict] = []
    for j, col in enumerate(cols):
        y = X[:, j]
        X_other = np.delete(X, j, axis=1)
        reg = LinearRegression().fit(X_other, y)
        r2 = reg.score(X_other, y)
        # Clamp to avoid division by zero / negative VIF due to numerical noise
        r2 = min(max(r2, 0.0), 1.0 - 1e-9)
        vif = 1.0 / (1.0 - r2)
        vif_values.append(
            {
                "feature": col,
                "VIF": round(vif, 3),
                "flag_multicollinearity": vif > VIF_THRESHOLD,
            }
        )

    result = pd.DataFrame(vif_values).sort_values("VIF", ascending=False).reset_index(drop=True)
    flagged = result[result["flag_multicollinearity"]]["feature"].tolist()
    if flagged:
        logger.warning("[eda_utils] VIF > %.0f for features: %s", VIF_THRESHOLD, flagged)
    else:
        logger.info("[eda_utils] No multicollinearity detected (all VIF ≤ %.0f).", VIF_THRESHOLD)
    return result


# ── Dimensionality reduction benchmark ────────────────────────────────────

def _scale(X: np.ndarray) -> np.ndarray:
    """StandardScaler wrapper that skips all-NaN columns."""
    scaler = StandardScaler()
    return scaler.fit_transform(X)


def pca_explained_variance(
    df: pd.DataFrame,
    features: list[str] = X_HI_COLUMNS,
    n_components: int = 2,
) -> dict:
    """Run PCA and return explained variance ratio.

    Returns
    -------
    dict with keys:
        ``embedding``        : (n_samples, n_components) np.ndarray
        ``explained_variance``: list of per-component ratios
        ``total_variance``   : cumulative explained variance (first n_components)
        ``components``       : pd.DataFrame of component loadings
    """
    cols = [c for c in features if c in df.columns]
    X = df[cols].dropna()
    Xs = _scale(X.values)

    pca = PCA(n_components=n_components, random_state=42)
    embedding = pca.fit_transform(Xs)

    loadings = pd.DataFrame(
        pca.components_.T,
        index=cols,
        columns=[f"PC{i+1}" for i in range(n_components)],
    )
    result = {
        "embedding": embedding,
        "explained_variance": pca.explained_variance_ratio_.tolist(),
        "total_variance": float(pca.explained_variance_ratio_.sum()),
        "components": loadings,
    }
    logger.info(
        "[eda_utils] PCA(%d) total explained variance=%.3f",
        n_components,
        result["total_variance"],
    )
    return result


def umap_embedding(
    df: pd.DataFrame,
    features: list[str] = X_HI_COLUMNS,
    n_components: int = 2,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
) -> dict:
    """Run UMAP and return 2-D (or n_components) embedding.

    Returns
    -------
    dict with keys:
        ``embedding``          : (n_samples, n_components) np.ndarray
        ``trustworthiness``    : sklearn trustworthiness metric (proxy for local
                                 structure preservation, range 0-1, higher = better)
        ``n_samples``          : number of rows used
    """
    try:
        import umap  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("umap-learn is required: pip install umap-learn") from exc

    from sklearn.manifold import trustworthiness as _trust

    cols = [c for c in features if c in df.columns]
    X = df[cols].dropna()
    Xs = _scale(X.values)

    reducer = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        random_state=random_state,
    )
    embedding = reducer.fit_transform(Xs)

    # trustworthiness measures how well local neighbourhoods are preserved
    tw = float(_trust(Xs, embedding, n_neighbors=n_neighbors))

    result = {
        "embedding": embedding,
        "trustworthiness": round(tw, 4),
        "n_samples": len(X),
    }
    logger.info(
        "[eda_utils] UMAP(%d) trustworthiness=%.4f  n_samples=%d",
        n_components, tw, len(X),
    )
    return result


def benchmark_dim_reduction(
    df: pd.DataFrame,
    features: list[str] = X_HI_COLUMNS,
    n_components: int = 2,
) -> dict:
    """Run PCA and UMAP and return a side-by-side comparison summary.

    Returns
    -------
    dict with sub-keys ``pca`` and ``umap``, each containing the output of
    :func:`pca_explained_variance` and :func:`umap_embedding` respectively.
    Also includes a ``recommendation`` string.
    """
    pca_res = pca_explained_variance(df, features=features, n_components=n_components)
    umap_res = umap_embedding(df, features=features, n_components=n_components)

    # Heuristic: UMAP is preferred when trustworthiness > 0.90 AND
    # PCA total explained variance < 0.80 (i.e. PCA loses too much structure).
    umap_preferred = (
        umap_res["trustworthiness"] > 0.90
        and pca_res["total_variance"] < 0.80
    )
    recommendation = (
        "UMAP" if umap_preferred else "PCA"
    )
    logger.info(
        "[eda_utils] Benchmark — PCA_var=%.3f | UMAP_trust=%.4f → recommend %s",
        pca_res["total_variance"],
        umap_res["trustworthiness"],
        recommendation,
    )
    return {
        "pca": pca_res,
        "umap": umap_res,
        "recommendation": recommendation,
    }


# ── Silhouette score helper ────────────────────────────────────────────────

def silhouette(
    X: np.ndarray,
    labels: np.ndarray,
    sample_size: Optional[int] = 5000,
    random_state: int = 42,
) -> float:
    """Compute silhouette score, ignoring noise points (label == -1).

    Parameters
    ----------
    X           : Feature matrix (already scaled).
    labels      : Cluster label array.
    sample_size : Sub-sample for large datasets.

    Returns
    -------
    Silhouette score in [-1, 1].  Returns NaN if fewer than 2 non-noise clusters.
    """
    from sklearn.metrics import silhouette_score

    mask = labels != -1
    X_valid = X[mask]
    y_valid = labels[mask]

    unique_labels = np.unique(y_valid)
    if len(unique_labels) < 2:
        logger.warning("[eda_utils] Silhouette undefined: fewer than 2 clusters (excluding noise).")
        return float("nan")

    if sample_size and len(X_valid) > sample_size:
        rng = np.random.default_rng(random_state)
        idx = rng.choice(len(X_valid), size=sample_size, replace=False)
        X_valid, y_valid = X_valid[idx], y_valid[idx]

    score = float(silhouette_score(X_valid, y_valid))
    logger.info("[eda_utils] Silhouette score=%.4f (n_valid=%d, n_clusters=%d)",
                score, len(X_valid), len(unique_labels))
    return score
