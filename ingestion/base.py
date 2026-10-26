"""Base connector interface for all data source ingestion connectors."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """Abstract base class for every source-specific ingestion connector.

    Each connector must implement :meth:`extract` to pull raw data and
    :meth:`load_to_bronze` to persist it to the Bronze layer.
    """

    source_id: str = ""

    def run(self, bronze_dir: Path) -> pd.DataFrame:
        """Full extract → load pipeline.  Returns the raw DataFrame."""
        t0 = time.perf_counter()
        logger.info("[%s] Starting extraction", self.source_id)
        df = self.extract()
        elapsed = time.perf_counter() - t0
        logger.info(
            "[%s] Extracted %d rows in %.2fs", self.source_id, len(df), elapsed
        )
        output_path = self.load_to_bronze(df, bronze_dir)
        logger.info("[%s] Persisted Bronze data → %s", self.source_id, output_path)
        return df

    @abstractmethod
    def extract(self) -> pd.DataFrame:
        """Pull data from the remote source and return a raw DataFrame."""

    def load_to_bronze(self, df: pd.DataFrame, bronze_dir: Path) -> Path:
        """Persist *df* as a partitioned Parquet file under *bronze_dir*."""
        dest = bronze_dir / self.source_id
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / "data.parquet"
        df.to_parquet(out, index=False, compression="snappy")
        logger.info(
            "[%s] Bronze write: %d rows, %d columns → %s",
            self.source_id,
            len(df),
            len(df.columns),
            out,
        )
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _log_discard(reason: str, count: int, total: int) -> None:
        logger.warning(
            "DISCARD | reason=%r | count=%d | pct=%.1f%%",
            reason,
            count,
            100.0 * count / max(total, 1),
        )
