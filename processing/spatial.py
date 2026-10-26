"""Spatial indexing utilities.

All coordinate → H3 conversions in the pipeline funnel through this module
so that resolution choices and error-handling are centralised.

Functions
---------
latlon_to_h3(lat_series, lon_series, resolution)
    Vectorised lat/lon → H3 index assignment.
    Returns (index_series, failed_count).

quadkey_to_h3(quadkey_series, resolution)
    Convert Web-Mercator Zoom-16 quadkeys (Ookla format) to H3.
    Returns (index_series, failed_count).

h3_parent(h3_series, parent_resolution)
    Return the parent H3 cell at a coarser resolution.

h3_disk_neighbours(h3_index, ring_size)
    Return list of H3 cells within *ring_size* rings (used for spatial median
    imputation in sanitisation).
"""
from __future__ import annotations

import logging
from typing import Tuple

import pandas as pd

logger = logging.getLogger(__name__)


def latlon_to_h3(
    lat: pd.Series,
    lon: pd.Series,
    resolution: int,
) -> Tuple[pd.Series, int]:
    """Convert latitude/longitude Series to H3 cell index strings.

    Parameters
    ----------
    lat, lon   : pandas Series of float coordinates
    resolution : H3 resolution (0–15; project uses 8 and 9)

    Returns
    -------
    (h3_series, failed_count)
    h3_series     : Series of H3 index strings; None where conversion failed.
    failed_count  : Number of rows where conversion failed.
    """
    try:
        import h3
    except ImportError:
        logger.error(
            "[spatial] h3 library not installed. "
            "Run: pip install h3"
        )
        return pd.Series([None] * len(lat)), len(lat)

    def _safe_convert(row):
        lt, ln = row
        try:
            if pd.isna(lt) or pd.isna(ln):
                return None
            return h3.latlng_to_cell(float(lt), float(ln), resolution)
        except Exception:
            return None

    result = pd.Series(
        [_safe_convert((lt, ln)) for lt, ln in zip(lat, lon)],
        index=lat.index,
        dtype=object,
    )
    failed = result.isna().sum()
    if failed:
        logger.debug(
            "[spatial] latlon_to_h3(res=%d): %d/%d conversions failed",
            resolution,
            failed,
            len(lat),
        )
    return result, int(failed)


def quadkey_to_h3(
    quadkey_series: pd.Series,
    resolution: int,
) -> Tuple[pd.Series, int]:
    """Convert Ookla-style Zoom-16 quadkeys to H3 cell index strings.

    The quadkey is first decoded to a (lat, lon) tile centroid using the
    ``mercantile`` library, then converted to H3.

    Parameters
    ----------
    quadkey_series : pandas Series of quadkey strings
    resolution     : H3 resolution

    Returns
    -------
    (h3_series, failed_count)
    """
    try:
        import mercantile
    except ImportError:
        logger.error(
            "[spatial] mercantile library not installed. "
            "Run: pip install mercantile"
        )
        return pd.Series([None] * len(quadkey_series)), len(quadkey_series)

    def _qk_to_latlon(qk: str):
        try:
            t = mercantile.quadkey_to_tile(str(qk))
            b = mercantile.bounds(t)
            return (b.south + b.north) / 2.0, (b.west + b.east) / 2.0
        except Exception:
            return None, None

    lats, lons = zip(*[_qk_to_latlon(qk) for qk in quadkey_series])
    lat_s = pd.Series(lats, index=quadkey_series.index, dtype=float)
    lon_s = pd.Series(lons, index=quadkey_series.index, dtype=float)
    return latlon_to_h3(lat_s, lon_s, resolution)


def h3_parent(h3_series: pd.Series, parent_resolution: int) -> pd.Series:
    """Return the parent H3 cell of each index at *parent_resolution*."""
    try:
        import h3
    except ImportError:
        logger.error("[spatial] h3 library not installed.")
        return pd.Series([None] * len(h3_series), index=h3_series.index)

    def _safe_parent(idx):
        try:
            return h3.cell_to_parent(idx, parent_resolution)
        except Exception:
            return None

    return h3_series.map(_safe_parent)


def h3_disk_neighbours(h3_index: str, ring_size: int = 1) -> list[str]:
    """Return H3 cells within *ring_size* rings of *h3_index* (k-ring).

    Used by the sanitisation layer for spatial median imputation.
    Ring 0 = the cell itself; ring 1 = immediate neighbours (6–7 cells).
    """
    try:
        import h3
        return list(h3.grid_disk(h3_index, ring_size))
    except Exception as exc:
        logger.warning(
            "[spatial] h3_disk_neighbours failed for %s (ring=%d): %s",
            h3_index,
            ring_size,
            exc,
        )
        return []


def h3_resolution_bridge(
    df: pd.DataFrame,
    source_col: str,
    target_resolution: int,
    target_col: str | None = None,
) -> pd.DataFrame:
    """Add a column with the parent (or child) H3 cell at *target_resolution*.

    If *target_col* is None, it defaults to ``h3_r{target_resolution}``.
    """
    if target_col is None:
        target_col = f"h3_r{target_resolution}"
    df[target_col] = h3_parent(df[source_col], target_resolution)
    return df
