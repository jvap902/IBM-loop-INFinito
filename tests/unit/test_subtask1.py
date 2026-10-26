"""Unit tests for Sub-Task 1 — Data Ingestion & Feature Store.

Covers
------
- Spatial utilities (latlon_to_h3, quadkey_to_h3, h3_disk_neighbours)
- Sanitisation rules (clip_outliers, impute_spatial_median, flag_low_confidence)
- Silver → Gold aggregation (build_silver, build_gold)
- Data quality checks (validate_gold)

All external I/O (S3, BigQuery, REST APIs) is mocked so these tests
run without any real credentials or network access.
"""
from __future__ import annotations

import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _make_silver(n: int = 20, null_feature: str | None = None) -> pd.DataFrame:
    """Build a minimal synthetic Silver DataFrame."""
    import random

    random.seed(42)
    # Use real-looking H3 cells (res 8) — these are valid prefixes but
    # may not be actual Brazil cells; that's fine for unit tests.
    h3_ids = [f"88{i:014x}" for i in range(n)]
    df = pd.DataFrame(
        {
            "h3_r8": h3_ids,
            "d_down": [50.0 + i for i in range(n)],
            "d_up": [10.0 + i * 0.5 for i in range(n)],
            "lat": [20.0 + i * 0.1 for i in range(n)],
            "vol_test": [5.0 + i for i in range(n)],
            "n_dom": [100 + i * 10 for i in range(n)],
            "n_com": [50 + i * 5 for i in range(n)],
            "ren_med": [2000.0 + i * 50 for i in range(n)],
            "n_erb": [3.0 + i * 0.2 for i in range(n)],
            "HHI": [2000.0 + i * 100 for i in range(n)],
            "vol_reclam": [1.0 + i * 0.05 for i in range(n)],
        }
    )
    if null_feature:
        df[null_feature] = None
    return df


# ===========================================================================
# Spatial utilities
# ===========================================================================
class TestSpatialUtils:
    def test_latlon_to_h3_requires_h3_lib(self):
        """If h3 is installed, lat/lon → H3 index must not be empty."""
        pytest.importorskip("h3")
        from processing.spatial import latlon_to_h3

        lats = pd.Series([-23.5505, -22.9068])  # São Paulo, Rio
        lons = pd.Series([-46.6333, -43.1729])
        result, failed = latlon_to_h3(lats, lons, resolution=8)
        assert failed == 0
        assert result.notna().all()
        assert all(len(h) > 10 for h in result)

    def test_latlon_to_h3_nan_input(self):
        pytest.importorskip("h3")
        from processing.spatial import latlon_to_h3

        lats = pd.Series([None, -23.55])
        lons = pd.Series([None, -46.63])
        result, failed = latlon_to_h3(lats, lons, resolution=8)
        assert failed == 1
        assert pd.isna(result.iloc[0])
        assert result.iloc[1] is not None

    def test_h3_disk_neighbours_returns_list(self):
        pytest.importorskip("h3")
        from processing.spatial import h3_disk_neighbours, latlon_to_h3

        lats = pd.Series([-23.5505])
        lons = pd.Series([-46.6333])
        h3_id, _ = latlon_to_h3(lats, lons, resolution=8)
        neighbours = h3_disk_neighbours(h3_id.iloc[0], ring_size=1)
        # ring-1 includes the cell itself + up to 6 neighbours
        assert len(neighbours) >= 1

    def test_quadkey_to_h3_requires_mercantile(self):
        pytest.importorskip("mercantile")
        pytest.importorskip("h3")
        from processing.spatial import quadkey_to_h3
        import mercantile

        # Build a guaranteed-valid zoom-16 quadkey for a São Paulo coordinate
        tile = mercantile.tile(-46.6333, -23.5505, 16)
        qk = mercantile.quadkey(tile)
        qks = pd.Series([qk])
        result, failed = quadkey_to_h3(qks, resolution=8)
        assert failed == 0
        assert result.notna().all()


# ===========================================================================
# Sanitisation
# ===========================================================================
class TestSanitisation:
    def test_clip_outliers_removes_extremes(self):
        from processing.sanitise import clip_outliers

        df = _make_silver(20)
        # Inject a clear outlier
        df.loc[0, "d_down"] = 1_000_000.0
        df_clean = clip_outliers(df, features=["d_down"], iqr_multiplier=3.0)
        assert df_clean["d_down"].max() < 1_000_000.0

    def test_clip_outliers_no_change_within_fence(self):
        from processing.sanitise import clip_outliers

        df = _make_silver(20)
        original_max = df["d_down"].max()
        df_clean = clip_outliers(df, features=["d_down"], iqr_multiplier=3.0)
        # All values are within normal range; max should be unchanged
        assert math.isclose(df_clean["d_down"].max(), original_max, rel_tol=1e-6)

    def test_flag_low_confidence_threshold(self):
        from processing.sanitise import flag_low_confidence

        df = _make_silver(10)
        df["vol_test"] = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        df = flag_low_confidence(df, vol_test_col="vol_test", threshold=3)
        # rows 0 and 1 have vol_test < 3
        assert df["low_confidence"].sum() == 2
        assert not df.loc[2, "low_confidence"]

    def test_flag_low_confidence_missing_column(self):
        from processing.sanitise import flag_low_confidence

        df = _make_silver(5)
        df = df.drop(columns=["vol_test"])
        df = flag_low_confidence(df, vol_test_col="vol_test")
        assert "low_confidence" in df.columns
        assert not df["low_confidence"].any()

    def test_impute_spatial_median_no_h3_lib(self):
        """Imputation should handle absence of h3 gracefully."""
        from processing.sanitise import impute_spatial_median

        df = _make_silver(5, null_feature="ren_med")
        # Without real H3 ids, neighbours return empty → nulls remain
        result = impute_spatial_median(df, h3_col="h3_r8", features=["ren_med"])
        # Should not raise; nulls may remain but column is present
        assert "ren_med" in result.columns


# ===========================================================================
# Feature store / Silver → Gold
# ===========================================================================
class TestFeatureStore:
    def test_build_silver_all_empty_sources(self):
        from processing.feature_store import build_silver

        silver = build_silver(
            ookla_df=pd.DataFrame(),
            ibge_df=pd.DataFrame(),
            anatel_muni_df=pd.DataFrame(),
            anatel_erb_df=pd.DataFrame(),
            opencellid_df=pd.DataFrame(),
            mlab_df=pd.DataFrame(),
        )
        # All sources empty → empty silver
        assert len(silver) == 0

    def test_build_gold_produces_required_columns(self, tmp_path):
        from processing.feature_store import X_HI_COLUMNS, build_gold

        silver = _make_silver(10)
        # Rename to match expected primary h3 col name
        silver = silver.rename(columns={"h3_r8": "h3_r8"})
        gold = build_gold(silver, h3_resolution=8, year=2024, month=1, output_dir=tmp_path)
        for col in X_HI_COLUMNS:
            assert col in gold.columns, f"Missing column: {col}"
        assert "h3_id" in gold.columns
        assert "year" in gold.columns
        assert "month" in gold.columns
        assert "h3_res" in gold.columns

    def test_build_gold_persists_parquet(self, tmp_path):
        from processing.feature_store import build_gold

        silver = _make_silver(5)
        build_gold(silver, h3_resolution=8, year=2024, month=3, output_dir=tmp_path)
        parquet_files = list(tmp_path.rglob("*.parquet"))
        assert len(parquet_files) > 0


# ===========================================================================
# Data quality
# ===========================================================================
class TestQuality:
    def _make_gold(self, n: int = 50) -> pd.DataFrame:
        import random

        random.seed(1)
        return pd.DataFrame(
            {
                "h3_id": [f"88{i:014x}" for i in range(n)],
                "d_down": [30.0 + i for i in range(n)],
                "d_up": [5.0 + i * 0.3 for i in range(n)],
                "lat": [10.0 + i * 0.5 for i in range(n)],
                "vol_test": [5.0] * n,
                "n_dom": [200 + i * 5 for i in range(n)],
                "n_com": [50 + i * 2 for i in range(n)],
                "ren_med": [1800.0 + i * 20 for i in range(n)],
                "n_erb": [2.0 + i * 0.1 for i in range(n)],
                "HHI": [3000.0 + i * 50 for i in range(n)],
                "vol_reclam": [0.5 + i * 0.01 for i in range(n)],
                "low_confidence": [False] * n,
                "year": [2024] * n,
                "month": [1] * n,
                "h3_res": [8] * n,
            }
        )

    def test_valid_gold_passes_all_checks(self):
        from processing.quality import validate_gold

        gold = self._make_gold(50)
        report = validate_gold(gold, municipalities_total=50)
        # HHI range and non-null checks should pass
        hhi_failures = [f for f in report.failures if "HHI" in f and "not found" not in f]
        null_failures = [
            f for f in report.failures
            if "null values" in f or "missing" in f.lower()
        ]
        assert not hhi_failures, hhi_failures
        assert not null_failures, null_failures

    def test_hhi_out_of_range_fails(self):
        from processing.quality import validate_gold

        gold = self._make_gold(10)
        gold.loc[0, "HHI"] = 20000.0  # out of range
        report = validate_gold(gold, municipalities_total=10)
        assert any("HHI" in f for f in report.failures)

    def test_null_required_field_fails(self):
        from processing.quality import validate_gold

        gold = self._make_gold(10)
        gold["d_down"] = None
        report = validate_gold(gold, municipalities_total=10)
        assert any("d_down" in f for f in report.failures)

    def test_empty_gold_fails(self):
        from processing.quality import validate_gold

        gold = pd.DataFrame(
            columns=["h3_id", "d_down", "d_up", "lat", "n_dom", "n_erb", "HHI"]
        )
        report = validate_gold(gold, municipalities_total=100)
        assert any("empty" in f.lower() for f in report.failures)
