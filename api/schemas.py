"""Pydantic v2 request and response schemas for all Tool API endpoints.

Design principles
-----------------
* Every request model inherits from ``BaseToolRequest`` which carries the
  common filtering / resolution / weight parameters.
* Every response model inherits from ``BaseToolResponse`` which carries
  the run metadata (``run_id``, ``axis``, ``duration_seconds``).
* Response row models include GeoJSON-compatible geometry fields
  (``h3_id``, ``lat_centroid``, ``lon_centroid``) so a future BI dashboard
  can render hexagon results without additional transformation.
* All types are annotated for full OpenAPI 3.1 schema generation.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# ── Shared / primitive types ───────────────────────────────────────────────

H3CellId = Annotated[str, Field(description="Uber H3 cell identifier (any resolution).")]

H3RegionFilter = Annotated[
    Optional[list[str]],
    Field(
        default=None,
        description=(
            "Optional list of H3 parent cell IDs at resolution 5 or 6 used to "
            "spatially restrict the analysis. Hexagons outside these parent cells "
            "are excluded before the pipeline runs."
        ),
        examples=[["85283473fffffff", "8528347bfffffff"]],
    ),
]

FeatureWeights = Annotated[
    Optional[dict[str, float]],
    Field(
        default=None,
        description=(
            "Optional override of equal feature weights. Keys must match feature "
            "names in the Gold Feature Store (e.g. 'd_down', 'vol_reclam'). "
            "Values are multiplied against the standardised feature vector."
        ),
        examples=[{"d_down": 1.5, "vol_reclam": 2.0}],
    ),
]


# ── Common request base ────────────────────────────────────────────────────

class BaseToolRequest(BaseModel):
    """Fields shared by every axis run request."""

    region_filter: H3RegionFilter = None
    h3_resolution: Annotated[int, Field(ge=8, le=9, description="Target H3 resolution (8 or 9).")] = 8
    feature_weights: FeatureWeights = None

    @field_validator("h3_resolution")
    @classmethod
    def _validate_resolution(cls, v: int) -> int:
        if v not in (8, 9):
            raise ValueError("h3_resolution must be 8 or 9.")
        return v


# ── Axis 1 ─────────────────────────────────────────────────────────────────

class Axis1RunRequest(BaseToolRequest):
    """Request body for ``POST /tools/axis1/run``."""

    anomaly_threshold: Annotated[
        float,
        Field(
            ge=0.0,
            le=1.0,
            description=(
                "IsolationForest normalised score threshold above which a hexagon "
                "is flagged as critical. Defaults to 0.65 (EDA-confirmed)."
            ),
        ),
    ] = 0.65
    top_n: Annotated[
        int,
        Field(ge=1, le=5000, description="Maximum number of anomalous hexagons to return."),
    ] = 50
    contamination: Annotated[
        float,
        Field(
            ge=0.01,
            le=0.5,
            description="IsolationForest contamination fraction (expected anomaly rate).",
        ),
    ] = 0.05


class Axis1HexagonResult(BaseModel):
    """Single hexagon row in the Axis 1 response."""

    h3_id: H3CellId
    lat_centroid: Annotated[float, Field(description="Latitude of the H3 cell centroid.")]
    lon_centroid: Annotated[float, Field(description="Longitude of the H3 cell centroid.")]
    anomaly_score: Annotated[float, Field(ge=0.0, le=1.0, description="Normalised anomaly score [0, 1]. Higher = more anomalous.")]
    is_critical: Annotated[int, Field(ge=0, le=1, description="1 if the hexagon is flagged as critical, 0 otherwise.")]
    lof_score: Annotated[float, Field(ge=0.0, le=1.0, description="Normalised Local Outlier Factor score [0, 1].")]
    cloudflare_outage_overlap: Annotated[int, Field(ge=0, le=1, description="1 if this hexagon overlaps a known Cloudflare outage event.")]


class Axis1RunResponse(BaseModel):
    """Response body for ``POST /tools/axis1/run``."""

    run_id: Annotated[str, Field(description="Unique identifier for this pipeline run.")]
    axis: Annotated[str, Field(description="Axis identifier.")] = "axis1"
    duration_seconds: Annotated[float, Field(description="Wall-clock execution time in seconds.")]
    total_hexagons_scored: Annotated[int, Field(description="Total number of hexagons processed.")]
    n_critical: Annotated[int, Field(description="Number of hexagons flagged as critical.")]
    anomaly_rate: Annotated[float, Field(description="Fraction of hexagons that are critical.")]
    results: list[Axis1HexagonResult]


# ── Axis 1 cross-validate ──────────────────────────────────────────────────

class Axis1CrossValidateRequest(BaseModel):
    """Request body for ``POST /tools/axis1/crossvalidate``."""

    date_start: Annotated[str, Field(description="ISO-8601 start date (inclusive), e.g. '2024-01-01'.")]
    date_end: Annotated[str, Field(description="ISO-8601 end date (inclusive), e.g. '2024-01-31'.")]
    region_filter: H3RegionFilter = None
    anomaly_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.65
    top_n: Annotated[int, Field(ge=1, le=5000)] = 50


class OutageOverlapEntry(BaseModel):
    """Single outage event with the count of overlapping critical hexagons."""

    outage_id: str
    outage_description: str
    outage_start: str
    outage_end: Optional[str]
    affected_location: Optional[str]
    overlapping_critical_hexagons: int


class Axis1CrossValidateResponse(BaseModel):
    """Response body for ``POST /tools/axis1/crossvalidate``."""

    run_id: str
    axis: str = "axis1_crossvalidate"
    duration_seconds: float
    date_range: dict[str, str]
    n_critical_hexagons: int
    n_cloudflare_outages_fetched: int
    agreement_rate: Annotated[float, Field(description="Fraction of Cloudflare outage cells also flagged as critical.")]
    overlapping_events: list[OutageOverlapEntry]


# ── Axis 2 ─────────────────────────────────────────────────────────────────

class Axis2RunRequest(BaseToolRequest):
    """Request body for ``POST /tools/axis2/run``."""

    min_cluster_size: Annotated[
        int,
        Field(ge=2, le=2000, description="HDBSCAN minimum cluster size parameter."),
    ] = 50
    skip_umap: Annotated[
        bool,
        Field(description="If True, skip UMAP pre-reduction and feed scaled features directly into HDBSCAN."),
    ] = False


class Axis2ClusterSummary(BaseModel):
    """Summary row for a single expansion cluster."""

    cluster_id: Annotated[int, Field(description="HDBSCAN cluster label (-1 for noise).")]
    cluster_size: Annotated[int, Field(description="Number of hexagons in the cluster.")]
    lat_centroid: Annotated[float, Field(description="Mean latitude of hexagons in this cluster.")]
    lon_centroid: Annotated[float, Field(description="Mean longitude of hexagons in this cluster.")]
    avg_d_down: Annotated[Optional[float], Field(description="Mean download speed (Mbps) in the cluster.")] = None
    avg_n_dom: Annotated[Optional[float], Field(description="Mean number of residential addresses in the cluster.")] = None
    avg_HHI: Annotated[Optional[float], Field(description="Mean Herfindahl–Hirschman Index (market concentration) in the cluster.")] = None
    tam_estimate: Annotated[Optional[float], Field(description="Estimated Total Addressable Market proxy (avg_n_dom × cluster_size).")] = None
    is_noise: Annotated[int, Field(ge=0, le=1, description="1 if this is the noise cluster (-1 label).")] = 0


class Axis2RunResponse(BaseModel):
    """Response body for ``POST /tools/axis2/run``."""

    run_id: str
    axis: str = "axis2"
    duration_seconds: float
    total_hexagons_processed: int
    n_clusters: int
    noise_rate: float
    clusters: list[Axis2ClusterSummary]


# ── Axis 3 ─────────────────────────────────────────────────────────────────

class Axis3RunRequest(BaseToolRequest):
    """Request body for ``POST /tools/axis3/run``."""

    n_clusters: Annotated[
        int,
        Field(ge=2, le=10, description="Number of K-Means clusters (k). Defaults to 3, EDA-confirmed."),
    ] = 3
    sweep_if_low_silhouette: Annotated[
        bool,
        Field(description="If True, sweep k ∈ [3, 6] when silhouette < 0.30 and pick the best k."),
    ] = True


class Axis3SegmentProfile(BaseModel):
    """Metadata about a single market segment."""

    segment_id: int
    segment_name: Annotated[str, Field(description="Human-readable segment label.")]
    hexagon_count: int
    hexagon_fraction: Annotated[float, Field(description="Fraction of all hexagons in this segment.")]
    avg_centroid_distance: Annotated[float, Field(description="Mean distance from segment centroid (scaled space).")]
    avg_silhouette: Annotated[Optional[float], Field(description="Mean per-point silhouette score for this segment.")] = None


class Axis3HexagonResult(BaseModel):
    """Single hexagon row in the Axis 3 response."""

    h3_id: H3CellId
    lat_centroid: float
    lon_centroid: float
    segment_id: int
    segment_name: str
    centroid_distance: float
    silhouette_score_local: Optional[float] = None


class Axis3RunResponse(BaseModel):
    """Response body for ``POST /tools/axis3/run``."""

    run_id: str
    axis: str = "axis3"
    duration_seconds: float
    total_hexagons_segmented: int
    n_segments: int
    silhouette_score_global: Optional[float]
    segment_profiles: list[Axis3SegmentProfile]
    results: list[Axis3HexagonResult]


# ── Tool catalogue ─────────────────────────────────────────────────────────

class ToolParameter(BaseModel):
    """Description of a single tool parameter for the catalogue endpoint."""

    name: str
    type: str
    required: bool
    default: Optional[str] = None
    description: str


class ToolDefinition(BaseModel):
    """Machine-readable description of a single tool for the agent registry."""

    tool_id: str
    name: str
    description: str
    endpoint: str
    method: str
    parameters: list[ToolParameter]
    output_schema_ref: str


class ToolCatalogueResponse(BaseModel):
    """Response body for ``GET /tools``."""

    api_version: str = "v1"
    tool_count: int
    tools: list[ToolDefinition]


# ── Health ─────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    """Response body for ``GET /health``."""

    status: str = "ok"
    version: str
