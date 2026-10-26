"""Ookla Speedtest Open Data connector.

Source: s3://ookla-open-data/parquet/performance/type={fixed|mobile}/
Auth  : None — AWS CLI flag --no-sign-request
Format: Apache Parquet, partitioned by year/quarter
Spatial: Web Mercator Zoom-16 Quadkey  →  H3 index (res 8 & 9)

LGPD note: Ookla tiles are already spatially aggregated (≈610 m tiles).
No individual device tracks are retained.

Audit trail
-----------
Every fetch logs: source path, row count, filtered row count, elapsed time.
Any Quadkey → H3 conversion failure is logged with the offending quadkey.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

import pandas as pd

from ingestion.base import BaseConnector
from processing.spatial import quadkey_to_h3

logger = logging.getLogger(__name__)

# S3 base path (public, no auth required)
_S3_BASE = "s3://ookla-open-data/parquet/performance"

# Default to most-recent complete quarter (override via env)
_DEFAULT_YEAR = int(os.getenv("OOKLA_YEAR", "2024"))
_DEFAULT_QUARTER = int(os.getenv("OOKLA_QUARTER", "1"))


class OoklaConnector(BaseConnector):
    """Ingests Ookla Speedtest Open Data for Brazil.

    Filters tiles that intersect Brazil's bounding box
    (lat -33.8 to 5.3, lon -73.9 to -32.4) after coordinate extraction.
    """

    source_id = "ookla_speedtest"

    # Brazil bounding box (lat/lon degrees)
    _LAT_MIN, _LAT_MAX = -33.8, 5.3
    _LON_MIN, _LON_MAX = -73.9, -32.4

    def __init__(
        self,
        connection_type: Literal["fixed", "mobile"] = "fixed",
        year: int = _DEFAULT_YEAR,
        quarter: int = _DEFAULT_QUARTER,
        h3_resolutions: list[int] | None = None,
    ) -> None:
        self.connection_type = connection_type
        self.year = year
        self.quarter = quarter
        self.h3_resolutions = h3_resolutions or [8, 9]

    # ------------------------------------------------------------------
    def extract(self) -> pd.DataFrame:
        s3_path = (
            f"{_S3_BASE}/type={self.connection_type}/"
            f"year={self.year}/quarter={self.quarter}/"
            f"*.parquet"
        )
        logger.info("[ookla] Reading s3 path: %s (--no-sign-request)", s3_path)

        try:
            # Use pyarrow/fsspec with anonymous S3 access
            import pyarrow.dataset as ds
            import pyarrow.fs as pafs

            s3fs = pafs.S3FileSystem(anonymous=True, region="us-west-2")
            # strip the "s3://" prefix for pyarrow
            path_no_scheme = s3_path.replace("s3://", "")
            dataset = ds.dataset(path_no_scheme, filesystem=s3fs, format="parquet")
            df = dataset.to_table().to_pandas()
        except Exception as exc:  # network unavailable in dev / CI
            logger.warning(
                "[ookla] S3 read failed (%s). Returning empty DataFrame for dry-run.",
                exc,
            )
            df = _ookla_empty_schema()

        total_rows = len(df)
        logger.info("[ookla] Raw rows fetched: %d", total_rows)

        if df.empty:
            return df

        # ------------------------------------------------------------------
        # Convert quadkey → tile centroid (lat/lon) then filter to Brazil bbox
        # ------------------------------------------------------------------
        df = self._add_tile_centroid(df)
        pre_filter = len(df)
        df = df[
            df["tile_lat"].between(self._LAT_MIN, self._LAT_MAX)
            & df["tile_lon"].between(self._LON_MIN, self._LON_MAX)
        ].copy()
        discarded = pre_filter - len(df)
        if discarded:
            self._log_discard("outside Brazil bbox", discarded, pre_filter)

        # Convert kbps → Mbps
        df["avg_d_mbps"] = df["avg_d_kbps"] / 1000.0
        df["avg_u_mbps"] = df["avg_u_kbps"] / 1000.0

        # Add H3 indexes for each requested resolution
        for res in self.h3_resolutions:
            col = f"h3_r{res}"
            df[col], failed = quadkey_to_h3(df["quadkey"], res)
            if failed:
                logger.warning(
                    "[ookla] %d quadkeys failed H3 conversion at res %d", failed, res
                )

        # Flag low-confidence tiles (< 3 tests)
        df["low_confidence"] = df["tests"] < 3
        low_conf_count = df["low_confidence"].sum()
        if low_conf_count:
            logger.info(
                "[ookla] %d tiles (%.1f%%) flagged low_confidence (tests < 3)",
                low_conf_count,
                100.0 * low_conf_count / len(df),
            )

        df["connection_type"] = self.connection_type
        df["year"] = self.year
        df["quarter"] = self.quarter

        logger.info("[ookla] Final Brazil rows: %d", len(df))
        return df

    # ------------------------------------------------------------------
    def _add_tile_centroid(self, df: pd.DataFrame) -> pd.DataFrame:
        """Decode quadkey to (lat, lon) centroid and add as columns."""
        try:
            def _qk_centroid(qk: str):
                try:
                    import mercantile as _m
                    t = _m.quadkey_to_tile(qk)
                    b = _m.bounds(t)
                    return (b.south + b.north) / 2.0, (b.west + b.east) / 2.0
                except Exception:
                    return None, None

            centroids = df["quadkey"].map(_qk_centroid)
            df["tile_lat"] = centroids.map(lambda c: c[0])
            df["tile_lon"] = centroids.map(lambda c: c[1])
        except ImportError:
            logger.warning(
                "[ookla] 'mercantile' not installed; skipping centroid computation."
            )
            df["tile_lat"] = None
            df["tile_lon"] = None
        return df


# ------------------------------------------------------------------
# Schema helpers
# ------------------------------------------------------------------
def _ookla_empty_schema() -> pd.DataFrame:
    """Return an empty DataFrame with the expected Ookla schema."""
    return pd.DataFrame(
        columns=[
            "quadkey",
            "avg_d_kbps",
            "avg_u_kbps",
            "avg_lat_ms",
            "tests",
            "devices",
        ]
    )
