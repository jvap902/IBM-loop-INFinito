"""M-Lab NDT connector.

Source  : BigQuery public dataset
Tables  : measurement-lab.ndt.unified_downloads
          measurement-lab.ndt.unified_uploads
Auth    : Google Cloud IAM / Application Default Credentials
          (env var GOOGLE_APPLICATION_CREDENTIALS or service account JSON)
Format  : BigQuery → pandas DataFrame

Features produced
-----------------
Per H3 hexagon (res 8 & 9):
  - lat            : median MinRTT ms   (maps to x_hi.lat)
  - mlab_d_down    : mean MeanThroughputMbps downloads
  - mlab_d_up      : mean MeanThroughputMbps uploads
  - loss_rate      : mean LossRate

These supplement / cross-validate the Ookla latency feature in Axis 1.

LGPD note: Client.Geo coordinates are approximate (city-level precision from
MaxMind). They are used only to assign H3 indexes; raw coordinates are not
persisted.

Audit trail
-----------
The BigQuery SQL query is logged at INFO level before execution for full
reproducibility of every run.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import pandas as pd

from data_ingestion.connectors.base import BaseConnector
from data_ingestion.processing.spatial import latlon_to_h3

logger = logging.getLogger(__name__)

_GCP_PROJECT = os.getenv("GCP_PROJECT", "")
_DATE_RANGE_DAYS = int(os.getenv("MLAB_DATE_RANGE_DAYS", "30"))
_H3_RESOLUTIONS = [8, 9]

_LAT_MIN, _LAT_MAX = -33.8, 5.3
_LON_MIN, _LON_MAX = -73.9, -32.4

_QUERY_TEMPLATE = """\
SELECT
    a.MeanThroughputMbps       AS mean_throughput_mbps,
    a.MinRTT                   AS min_rtt_ms,
    a.LossRate                 AS loss_rate,
    client.Geo.Latitude        AS client_lat,
    client.Geo.Longitude       AS client_lon,
    client.Network.ASNumber    AS as_number
FROM `{table}`
WHERE
    client.Geo.Latitude  BETWEEN {lat_min} AND {lat_max}
    AND client.Geo.Longitude BETWEEN {lon_min} AND {lon_max}
    AND DATE(TestTime)   BETWEEN '{date_start}' AND '{date_end}'
    AND a.MeanThroughputMbps IS NOT NULL
    AND a.MinRTT IS NOT NULL
"""


class MLABConnector(BaseConnector):
    """Ingests M-Lab NDT measurements for Brazil via BigQuery."""

    source_id = "mlab_ndt"

    def __init__(
        self,
        date_end: str | None = None,
        date_range_days: int = _DATE_RANGE_DAYS,
        h3_resolutions: list[int] | None = None,
    ) -> None:
        self.h3_resolutions = h3_resolutions or _H3_RESOLUTIONS
        if date_end is None:
            date_end = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.date_end = date_end
        self.date_start = (
            datetime.strptime(date_end, "%Y-%m-%d") - timedelta(days=date_range_days)
        ).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    def extract(self) -> pd.DataFrame:
        try:
            from google.cloud import bigquery
        except ImportError:
            logger.warning(
                "[mlab] google-cloud-bigquery not installed. "
                "Returning empty DataFrame."
            )
            return _empty_schema(self.h3_resolutions)

        if not _GCP_PROJECT:
            logger.warning(
                "[mlab] GCP_PROJECT env var not set. Returning empty DataFrame."
            )
            return _empty_schema(self.h3_resolutions)

        client = bigquery.Client(project=_GCP_PROJECT)
        frames = []

        for table, direction in [
            ("measurement-lab.ndt.unified_downloads", "download"),
            ("measurement-lab.ndt.unified_uploads", "upload"),
        ]:
            sql = _QUERY_TEMPLATE.format(
                table=table,
                lat_min=_LAT_MIN, lat_max=_LAT_MAX,
                lon_min=_LON_MIN, lon_max=_LON_MAX,
                date_start=self.date_start, date_end=self.date_end,
            )
            logger.info("[mlab] BigQuery SQL (%s):\n%s", direction, sql)
            try:
                df = client.query(sql).to_dataframe()
                df["direction"] = direction
                logger.info("[mlab] %s rows fetched: %d", direction, len(df))
                frames.append(df)
            except Exception as exc:
                logger.warning(
                    "[mlab] BigQuery query failed for %s (%s).", direction, exc
                )

        if not frames:
            return _empty_schema(self.h3_resolutions)

        raw = pd.concat(frames, ignore_index=True)
        raw["client_lat"] = pd.to_numeric(raw["client_lat"], errors="coerce")
        raw["client_lon"] = pd.to_numeric(raw["client_lon"], errors="coerce")
        raw = raw.dropna(subset=["client_lat", "client_lon"])

        res_primary = self.h3_resolutions[0]
        col_primary = f"h3_r{res_primary}"
        raw[col_primary], failed = latlon_to_h3(
            raw["client_lat"], raw["client_lon"], res_primary
        )
        if failed:
            logger.warning(
                "[mlab] %d rows failed H3 assignment at res %d", failed, res_primary
            )
        for res in self.h3_resolutions[1:]:
            col = f"h3_r{res}"
            raw[col], _ = latlon_to_h3(raw["client_lat"], raw["client_lon"], res)

        dl = raw[raw["direction"] == "download"]
        ul = raw[raw["direction"] == "upload"]

        def _agg(grp: pd.DataFrame, suffix: str) -> pd.DataFrame:
            return (
                grp.groupby(col_primary)
                .agg(**{
                    f"mlab_{suffix}_mbps": ("mean_throughput_mbps", "mean"),
                    "mlab_min_rtt_ms": ("min_rtt_ms", "median"),
                    "mlab_loss_rate": ("loss_rate", "mean"),
                })
                .reset_index()
            )

        dl_agg = _agg(dl, "down")
        ul_agg = _agg(ul, "up")

        result = dl_agg.merge(
            ul_agg[[col_primary, "mlab_up_mbps"]], on=col_primary, how="outer",
        )
        logger.info(
            "[mlab] Aggregated hexagons (res %d): %d", res_primary, len(result)
        )
        return result


def _empty_schema(h3_resolutions: list[int]) -> pd.DataFrame:
    cols = (
        [f"h3_r{r}" for r in h3_resolutions]
        + ["mlab_down_mbps", "mlab_up_mbps", "mlab_min_rtt_ms", "mlab_loss_rate"]
    )
    return pd.DataFrame(columns=cols)
