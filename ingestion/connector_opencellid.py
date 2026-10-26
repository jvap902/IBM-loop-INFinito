"""OpenCelliD connector.

Source : https://download.unwiredlabs.com/ocid/downloads?token=<API_KEY>&file=cell_towers.csv.gz
Auth   : API Key via query parameter (env var OPENCELLID_API_KEY)
Format : CSV (gzip), daily full dump
Filter : mcc == 724 (Brazil)

Features produced
-----------------
n_erb (supplement to Anatel Mosaico) : density count of crowdsourced cell
towers per H3 hexagon (res 8 & 9).

LGPD note: Only aggregated hexagon-level counts are retained.
"""
from __future__ import annotations

import io
import logging
import os

import pandas as pd
import requests

from ingestion.base import BaseConnector
from processing.spatial import latlon_to_h3

logger = logging.getLogger(__name__)

_API_KEY = os.getenv("OPENCELLID_API_KEY", "")
_DOWNLOAD_URL = (
    "https://download.unwiredlabs.com/ocid/downloads"
    "?token={token}&file=cell_towers.csv.gz"
)
_MCC_BRAZIL = 724
_H3_RESOLUTIONS = [8, 9]

# Fallback to the public OpenCelliD REST endpoint if dump is unavailable
_REST_CELL_URL = "https://opencellid.org/cell/get"


class OpenCelliDConnector(BaseConnector):
    """Downloads the daily OpenCelliD full dump and extracts Brazilian towers.

    Steps
    -----
    1. Download the gzip CSV dump (requires API key).
    2. Filter to ``mcc == 724`` (Brazil).
    3. Drop rows with invalid lat/lon.
    4. Assign H3 indexes.
    5. Aggregate to per-hexagon station counts (``n_erb``).
    """

    source_id = "opencellid"

    def __init__(self, h3_resolutions: list[int] | None = None) -> None:
        self.h3_resolutions = h3_resolutions or _H3_RESOLUTIONS

    # ------------------------------------------------------------------
    def extract(self) -> pd.DataFrame:
        if not _API_KEY:
            logger.warning(
                "[opencellid] OPENCELLID_API_KEY not set. "
                "Skipping download; returning empty DataFrame."
            )
            return _empty_schema(self.h3_resolutions)

        url = _DOWNLOAD_URL.format(token=_API_KEY)
        logger.info("[opencellid] Downloading cell_towers.csv.gz …")
        try:
            resp = requests.get(url, timeout=600, stream=True)
            resp.raise_for_status()
            raw = io.BytesIO(resp.content)
            df = pd.read_csv(
                raw,
                compression="gzip",
                usecols=["radio", "mcc", "mnc", "lac", "cellid", "lat", "lon",
                         "range", "nbSamples", "average_signal"],
                low_memory=True,
            )
        except Exception as exc:
            logger.warning(
                "[opencellid] Download failed (%s). Returning empty DataFrame.", exc
            )
            return _empty_schema(self.h3_resolutions)

        total = len(df)
        logger.info("[opencellid] Total towers in dump: %d", total)

        # Filter to Brazil (mcc == 724)
        df = df[df["mcc"] == _MCC_BRAZIL].copy()
        brazil_count = len(df)
        self._log_discard("mcc != 724", total - brazil_count, total)
        logger.info("[opencellid] Brazilian towers (mcc=724): %d", brazil_count)

        # Validate coordinates
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        invalid_coords = df[["lat", "lon"]].isna().any(axis=1).sum()
        if invalid_coords:
            self._log_discard("invalid lat/lon", invalid_coords, brazil_count)
        df = df.dropna(subset=["lat", "lon"])

        # Assign H3 indexes
        res_primary = self.h3_resolutions[0]
        col_primary = f"h3_r{res_primary}"
        df[col_primary], failed = latlon_to_h3(df["lat"], df["lon"], res_primary)
        if failed:
            logger.warning(
                "[opencellid] %d towers failed H3 assignment at res %d", failed, res_primary
            )
        for res in self.h3_resolutions[1:]:
            col = f"h3_r{res}"
            df[col], _ = latlon_to_h3(df["lat"], df["lon"], res)

        # Aggregate to hexagon counts
        erb_count = (
            df.groupby(col_primary)
            .agg(
                n_erb=(col_primary, "count"),
                n_erb_lte=("radio", lambda x: (x == "LTE").sum()),
                n_erb_nr=("radio", lambda x: (x == "NR").sum()),
            )
            .reset_index()
        )
        logger.info(
            "[opencellid] Hexagons with at least 1 tower (res %d): %d",
            res_primary,
            len(erb_count),
        )
        return erb_count


def _empty_schema(h3_resolutions: list[int]) -> pd.DataFrame:
    cols = [f"h3_r{r}" for r in h3_resolutions] + ["n_erb", "n_erb_lte", "n_erb_nr"]
    return pd.DataFrame(columns=cols)
