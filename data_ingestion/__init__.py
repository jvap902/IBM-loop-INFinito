"""data_ingestion — Sub-Task 1: Data Ingestion & Feature Store.

Public API
----------
Connectors (one per source):
    OoklaConnector, IBGEConnector, AnatelConnector,
    OpenCelliDConnector, MLABConnector, CloudflareRadarConnector

Processing utilities:
    spatial   — latlon_to_h3, quadkey_to_h3, h3_disk_neighbours
    sanitise  — run_sanitisation, clip_outliers, impute_spatial_median
    feature_store — build_silver, build_gold, X_HI_COLUMNS
    quality   — validate_gold, FeatureRow, QualityReport

Usage example
-------------
    from data_ingestion.connectors.ookla import OoklaConnector
    from data_ingestion.processing.feature_store import build_silver, build_gold
    from data_ingestion.processing.quality import validate_gold
"""
from data_ingestion.connectors.ookla import OoklaConnector
from data_ingestion.connectors.ibge import IBGEConnector
from data_ingestion.connectors.anatel import AnatelConnector
from data_ingestion.connectors.opencellid import OpenCelliDConnector
from data_ingestion.connectors.mlab import MLABConnector
from data_ingestion.connectors.cloudflare import CloudflareRadarConnector

from data_ingestion.processing.spatial import (
    latlon_to_h3,
    quadkey_to_h3,
    h3_disk_neighbours,
    h3_parent,
)
from data_ingestion.processing.sanitise import (
    run_sanitisation,
    clip_outliers,
    impute_spatial_median,
    flag_low_confidence,
)
from data_ingestion.processing.feature_store import build_silver, build_gold, X_HI_COLUMNS
from data_ingestion.processing.quality import validate_gold, QualityReport

__all__ = [
    "OoklaConnector", "IBGEConnector", "AnatelConnector",
    "OpenCelliDConnector", "MLABConnector", "CloudflareRadarConnector",
    "latlon_to_h3", "quadkey_to_h3", "h3_disk_neighbours", "h3_parent",
    "run_sanitisation", "clip_outliers", "impute_spatial_median", "flag_low_confidence",
    "build_silver", "build_gold", "X_HI_COLUMNS",
    "validate_gold", "QualityReport",
]
