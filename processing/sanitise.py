"""Sanitisation rules for the Silver layer.

Rules applied (per the Sub-Task 1 specification)
-------------------------------------------------
1. Outlier clipping   : clip each numeric feature to [Q1 - 3×IQR, Q3 + 3×IQR].
2. Spatial median     : impute missing cell values using the median of ring-1
                        H3 neighbours (up to 6 neighbours).
3. Low-confidence flag: hexagons with fewer than 3 Ookla tests are tagged
                        ``low_confidence = True``.  They remain in the dataset
                        but downstream models may down-weight them.

All discards and imputations are logged with justification for auditability.
"""
from __future__ import annotations

import logging
from typing import Sequence

import pandas as pd
import numpy as np

from processing.spatial import h3_disk_neighbours

logger = logging.getLogger(__name__)

# Features subject to IQR outlier clipping
_NUMERIC_FEATURES = [
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


def clip_outliers(
    df: pd.DataFrame,
    features: Sequence[str] | None = None,
    iqr_multiplier: float = 3.0,
) -> pd.DataFrame:
    """Clip outliers to [Q1 - k*IQR, Q3 + k*IQR] for each numeric feature.

    Parameters
    ----------
    df             : Input DataFrame (Silver layer, pre-imputation).
    features       : Columns to clip; defaults to ``_NUMERIC_FEATURES``.
    iqr_multiplier : Multiplier applied to IQR for fence computation.
                     Spec mandates 3.0 (equivalent to ~99.7% of normal dist).

    Returns
    -------
    DataFrame with outlier values replaced by fence values (not dropped).
    """
    features = [f for f in (features or _NUMERIC_FEATURES) if f in df.columns]
    total_cells = len(df)
    df = df.copy()

    for feat in features:
        col = df[feat].dropna()
        if col.empty:
            continue
        q1 = col.quantile(0.25)
        q3 = col.quantile(0.75)
        iqr = q3 - q1
        lower = q1 - iqr_multiplier * iqr
        upper = q3 + iqr_multiplier * iqr

        out_of_range = ((df[feat] < lower) | (df[feat] > upper)).sum()
        if out_of_range:
            logger.info(
                "[sanitise] clip_outliers | feature=%r | lower=%.4f | upper=%.4f | "
                "clipped=%d (%.1f%%) | justification=IQR×%.1f fence",
                feat,
                lower,
                upper,
                out_of_range,
                100.0 * out_of_range / total_cells,
                iqr_multiplier,
            )
        df[feat] = df[feat].clip(lower=lower, upper=upper)

    return df


def impute_spatial_median(
    df: pd.DataFrame,
    h3_col: str = "h3_r8",
    features: Sequence[str] | None = None,
    ring_size: int = 1,
) -> pd.DataFrame:
    """Impute missing values via the spatial median of ring-1 H3 neighbours.

    For each null value in a feature column:
    1. Retrieve the ring-1 H3 neighbours of that cell.
    2. Compute the median value of those neighbours from *df*.
    3. If no neighbour has a value, the cell remains null
       (will be caught by quality checks).

    Parameters
    ----------
    df        : Silver layer DataFrame with an H3 index column.
    h3_col    : Column name holding the H3 index string.
    features  : Columns to impute; defaults to ``_NUMERIC_FEATURES``.
    ring_size : Number of H3 rings to consider (spec: ring-1 = 1).

    Returns
    -------
    DataFrame with imputed values.  Imputation counts are logged per feature.
    """
    features = [f for f in (features or _NUMERIC_FEATURES) if f in df.columns]
    df = df.copy()

    # Build a lookup dict: h3_index → row position for fast neighbour access
    h3_to_idx = {h3: i for i, h3 in enumerate(df[h3_col])}

    for feat in features:
        null_mask = df[feat].isna()
        null_count = null_mask.sum()
        if null_count == 0:
            continue

        imputed = 0
        not_imputed = 0
        values = df[feat].values.copy()

        for row_i in df.index[null_mask]:
            h3_idx = df.at[row_i, h3_col]
            neighbours = h3_disk_neighbours(h3_idx, ring_size)
            # Exclude the cell itself (ring_size=0 is the cell; disk includes it)
            neighbour_values = [
                values[h3_to_idx[n]]
                for n in neighbours
                if n != h3_idx and n in h3_to_idx and not np.isnan(values[h3_to_idx[n]])
            ]
            if neighbour_values:
                df.at[row_i, feat] = float(np.median(neighbour_values))
                imputed += 1
            else:
                not_imputed += 1

        if null_count:
            logger.info(
                "[sanitise] impute_spatial_median | feature=%r | nulls=%d | "
                "imputed=%d | still_null=%d | method=ring-%d spatial median",
                feat,
                null_count,
                imputed,
                not_imputed,
                ring_size,
            )
            if not_imputed:
                logger.warning(
                    "[sanitise] %d cells for feature %r could not be imputed "
                    "(no neighbour data); will be flagged in quality checks.",
                    not_imputed,
                    feat,
                )

    return df


def flag_low_confidence(
    df: pd.DataFrame,
    vol_test_col: str = "vol_test",
    threshold: int = 3,
) -> pd.DataFrame:
    """Flag hexagons with fewer than *threshold* Ookla tests as low-confidence.

    Low-confidence hexagons are NOT removed — they remain in the Gold layer
    so analysts can see coverage gaps.  ML pipelines may optionally filter
    them via the ``low_confidence`` column.

    Parameters
    ----------
    df           : Silver/Gold DataFrame.
    vol_test_col : Column holding the normalised test count.
    threshold    : Minimum number of tests required for high confidence.
                   Spec mandates 3.

    Returns
    -------
    DataFrame with a boolean ``low_confidence`` column added/updated.
    """
    if vol_test_col not in df.columns:
        logger.warning(
            "[sanitise] Column %r not found; all cells flagged low_confidence=False.",
            vol_test_col,
        )
        df["low_confidence"] = False
        return df

    df = df.copy()
    df["low_confidence"] = df[vol_test_col] < threshold
    low_count = df["low_confidence"].sum()
    logger.info(
        "[sanitise] flag_low_confidence | threshold=%d | flagged=%d (%.1f%%)",
        threshold,
        low_count,
        100.0 * low_count / max(len(df), 1),
    )
    return df


def run_sanitisation(
    df: pd.DataFrame,
    h3_col: str = "h3_r8",
    iqr_multiplier: float = 3.0,
    ring_size: int = 1,
) -> pd.DataFrame:
    """Run the full sanitisation pipeline in the specified order.

    Order
    -----
    1. Clip outliers (IQR × 3).
    2. Impute missing via spatial median.
    3. Flag low-confidence hexagons.

    All steps are logged; no rows are dropped.
    """
    logger.info("[sanitise] Starting sanitisation on %d rows …", len(df))
    df = clip_outliers(df, iqr_multiplier=iqr_multiplier)
    df = impute_spatial_median(df, h3_col=h3_col, ring_size=ring_size)
    df = flag_low_confidence(df)
    logger.info("[sanitise] Sanitisation complete. Output: %d rows.", len(df))
    return df
