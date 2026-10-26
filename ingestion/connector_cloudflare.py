"""Cloudflare Radar API connector.

Source  : https://api.cloudflare.com/client/v4/radar
Auth    : Bearer Token (env var CLOUDFLARE_API_TOKEN)
Format  : JSON

Endpoints used
--------------
/annotations/outages        → connectivity outage events (date-range)
/traffic_anomalies          → real-time traffic statistical deviations

Usage in the pipeline
---------------------
The Cloudflare data is NOT part of the static feature vector x_hi.
It is stored as a time-series reference table used in two places:
  1. Cross-validation of Axis 1 anomaly detections (Sub-Task 3).
  2. POST /tools/axis1/crossvalidate endpoint (Sub-Task 4).

Feature columns persisted (per outage/anomaly record)
------------------------------------------------------
event_id, event_type, start_time, end_time, location_code, asn,
description, scope (global/regional/provider)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests

from ingestion.base import BaseConnector

logger = logging.getLogger(__name__)

_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")
_BASE_URL = "https://api.cloudflare.com/client/v4/radar"
_DATE_RANGE_DAYS = int(os.getenv("CLOUDFLARE_DATE_RANGE_DAYS", "30"))
_PAGE_LIMIT = 100  # items per request


class CloudflareRadarConnector(BaseConnector):
    """Fetches Cloudflare Radar outage annotations and traffic anomalies.

    The result is persisted as a time-series reference table (Bronze layer),
    not merged into the static feature store.
    """

    source_id = "cloudflare_radar"

    def __init__(
        self,
        date_end: str | None = None,
        date_range_days: int = _DATE_RANGE_DAYS,
    ) -> None:
        if date_end is None:
            date_end = datetime.utcnow().strftime("%Y-%m-%d")
        self.date_end = date_end
        self.date_start = (
            datetime.strptime(date_end, "%Y-%m-%d") - timedelta(days=date_range_days)
        ).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    def extract(self) -> pd.DataFrame:
        if not _API_TOKEN:
            logger.warning(
                "[cloudflare] CLOUDFLARE_API_TOKEN not set. "
                "Returning empty reference table."
            )
            return _empty_schema()

        outages = self._fetch_outages()
        anomalies = self._fetch_traffic_anomalies()
        result = pd.concat([outages, anomalies], ignore_index=True)
        logger.info(
            "[cloudflare] Total reference events: %d "
            "(outages=%d, anomalies=%d)",
            len(result),
            len(outages),
            len(anomalies),
        )
        return result

    # ------------------------------------------------------------------
    def _fetch_outages(self) -> pd.DataFrame:
        records = self._paginate(
            endpoint="/annotations/outages",
            params={
                "dateRange": f"{self.date_start}..{self.date_end}",
                "limit": _PAGE_LIMIT,
                "location": "BR",  # Filter to Brazil
            },
            result_key="annotations",
        )
        rows = []
        for r in records:
            rows.append(
                {
                    "event_id": r.get("id"),
                    "event_type": "outage",
                    "start_time": r.get("startDate"),
                    "end_time": r.get("endDate"),
                    "location_code": r.get("locations", [""])[0]
                    if r.get("locations")
                    else "",
                    "asn": r.get("linkedUrl", {}).get("asn") if r.get("linkedUrl") else None,
                    "description": r.get("description", ""),
                    "scope": r.get("scope", ""),
                }
            )
        df = pd.DataFrame(rows) if rows else _empty_schema()
        logger.info("[cloudflare] Outage events fetched: %d", len(df))
        return df

    def _fetch_traffic_anomalies(self) -> pd.DataFrame:
        records = self._paginate(
            endpoint="/traffic_anomalies",
            params={
                "dateRange": f"{self.date_start}..{self.date_end}",
                "limit": _PAGE_LIMIT,
                "location": "BR",
            },
            result_key="trafficAnomalies",
        )
        rows = []
        for r in records:
            rows.append(
                {
                    "event_id": r.get("uuid"),
                    "event_type": "traffic_anomaly",
                    "start_time": r.get("startDate"),
                    "end_time": r.get("endDate"),
                    "location_code": r.get("locations", [""])[0]
                    if r.get("locations")
                    else "",
                    "asn": r.get("asn"),
                    "description": r.get("type", ""),
                    "scope": r.get("status", ""),
                }
            )
        df = pd.DataFrame(rows) if rows else _empty_schema()
        logger.info("[cloudflare] Traffic anomaly events fetched: %d", len(df))
        return df

    # ------------------------------------------------------------------
    def _paginate(
        self, endpoint: str, params: dict[str, Any], result_key: str
    ) -> list[dict]:
        """Paginate through a Cloudflare Radar endpoint."""
        headers = {
            "Authorization": f"Bearer {_API_TOKEN}",
            "Content-Type": "application/json",
        }
        all_records: list[dict] = []
        offset = 0
        while True:
            params_page = {**params, "offset": offset}
            try:
                resp = requests.get(
                    f"{_BASE_URL}{endpoint}",
                    headers=headers,
                    params=params_page,
                    timeout=30,
                )
                resp.raise_for_status()
                body = resp.json()
                records = body.get("result", {}).get(result_key, [])
                if not records:
                    break
                all_records.extend(records)
                if len(records) < _PAGE_LIMIT:
                    break
                offset += _PAGE_LIMIT
            except Exception as exc:
                logger.warning(
                    "[cloudflare] Request failed (offset=%d, endpoint=%s): %s",
                    offset,
                    endpoint,
                    exc,
                )
                break
        return all_records


def _empty_schema() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            "event_type",
            "start_time",
            "end_time",
            "location_code",
            "asn",
            "description",
            "scope",
        ]
    )
