"""Tool API route handlers.

Endpoints
---------
GET  /tools                       — machine-readable tool catalogue
POST /tools/axis1/run             — Axis 1: Maintenance & Criticality
POST /tools/axis1/crossvalidate   — Axis 1: Cloudflare outage cross-validation
POST /tools/axis2/run             — Axis 2: Expansion Opportunities
POST /tools/axis3/run             — Axis 3: Promotional Targeting

All ``/run`` endpoints require a valid ``X-API-Key`` header.
The ``GET /tools`` endpoint is publicly accessible (no auth required) so
the Operational Agent can discover available tools at startup.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Optional

import h3
import httpx
import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import require_api_key
from api.schemas import (
    Axis1CrossValidateRequest,
    Axis1CrossValidateResponse,
    Axis1HexagonResult,
    Axis1RunRequest,
    Axis1RunResponse,
    Axis2ClusterSummary,
    Axis2RunRequest,
    Axis2RunResponse,
    Axis3HexagonResult,
    Axis3RunRequest,
    Axis3RunResponse,
    Axis3SegmentProfile,
    OutageOverlapEntry,
    ToolCatalogueResponse,
    ToolDefinition,
    ToolParameter,
)
from ml.pipelines import pipeline_axis1, pipeline_axis2, pipeline_axis3
from audit.logger import get_audit_logger
from audit import explainability as _xai

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Helpers ────────────────────────────────────────────────────────────────

_GOLD_PARQUET_PATH = os.getenv("GOLD_PARQUET_PATH", "data/gold/features.parquet")


def _load_gold(region_filter: Optional[list[str]], h3_resolution: int) -> pd.DataFrame:
    """Load the Gold Feature Store Parquet and apply optional region filter.

    Parameters
    ----------
    region_filter : Optional list of parent H3 cell IDs (res 5 or 6).
    h3_resolution : Target resolution to filter by (8 or 9).

    Raises
    ------
    HTTPException 404 if the Gold Parquet file is not found.
    HTTPException 400 if the region filter produces an empty dataset.
    """
    if not os.path.exists(_GOLD_PARQUET_PATH):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Gold Feature Store not found at '{_GOLD_PARQUET_PATH}'. "
                "Ensure GOLD_PARQUET_PATH points to a valid Parquet file and that "
                "Sub-Task 1 (data ingestion) has been completed."
            ),
        )

    df = pd.read_parquet(_GOLD_PARQUET_PATH)

    # Filter by H3 resolution column if present
    if "h3_res" in df.columns:
        df = df[df["h3_res"] == h3_resolution]

    # Apply spatial region filter
    if region_filter:
        def _in_region(h3_id: str) -> bool:
            try:
                for parent in region_filter:
                    parent_res = h3.get_resolution(parent)
                    if h3.cell_to_parent(h3_id, parent_res) == parent:
                        return True
                return False
            except Exception:
                return False

        mask = df["h3_id"].apply(_in_region)
        df = df[mask]

    if df.empty:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The applied region_filter produced an empty dataset. "
                   "Check that the provided H3 parent cell IDs are valid and "
                   "overlap with the Gold Feature Store.",
        )

    return df


def _h3_centroid(h3_id: str) -> tuple[float, float]:
    """Return (lat, lon) centroid for an H3 cell."""
    try:
        lat, lon = h3.cell_to_latlng(h3_id)
        return round(lat, 6), round(lon, 6)
    except Exception:
        return 0.0, 0.0


def _make_run_id() -> str:
    return str(uuid.uuid4())


# ── GET /tools ─────────────────────────────────────────────────────────────

_TOOL_CATALOGUE: list[ToolDefinition] = [
    ToolDefinition(
        tool_id="axis1_run",
        name="Axis 1 — Maintenance & Criticality Analyzer",
        description=(
            "Scores every H3 hexagon with an anomaly score using an IsolationForest + LOF "
            "ensemble. Hexagons with score ≥ anomaly_threshold are flagged as critical "
            "infrastructure maintenance targets. Returns the top-N anomalous hexagons with "
            "GeoJSON-compatible coordinates."
        ),
        endpoint="/v1/tools/axis1/run",
        method="POST",
        parameters=[
            ToolParameter(name="region_filter", type="list[str] | null", required=False, default="null", description="H3 parent cell IDs at res 5/6 to restrict the analysis."),
            ToolParameter(name="h3_resolution", type="int", required=False, default="8", description="Target H3 resolution (8 or 9)."),
            ToolParameter(name="feature_weights", type="dict[str, float] | null", required=False, default="null", description="Optional feature weight overrides."),
            ToolParameter(name="anomaly_threshold", type="float", required=False, default="0.65", description="IsolationForest score threshold for is_critical flag."),
            ToolParameter(name="top_n", type="int", required=False, default="50", description="Maximum number of critical hexagons to return."),
            ToolParameter(name="contamination", type="float", required=False, default="0.05", description="Expected anomaly fraction for IsolationForest."),
        ],
        output_schema_ref="#/components/schemas/Axis1RunResponse",
    ),
    ToolDefinition(
        tool_id="axis1_crossvalidate",
        name="Axis 1 — Cloudflare Outage Cross-Validator",
        description=(
            "Runs Axis 1 anomaly detection and cross-references the critical hexagons "
            "against Cloudflare Radar outage annotations for a given date range. "
            "Returns an agreement rate and per-event overlap summary for audit purposes."
        ),
        endpoint="/v1/tools/axis1/crossvalidate",
        method="POST",
        parameters=[
            ToolParameter(name="date_start", type="str", required=True, default=None, description="ISO-8601 start date, e.g. '2024-01-01'."),
            ToolParameter(name="date_end", type="str", required=True, default=None, description="ISO-8601 end date, e.g. '2024-01-31'."),
            ToolParameter(name="region_filter", type="list[str] | null", required=False, default="null", description="H3 parent cell IDs at res 5/6 to restrict the analysis."),
            ToolParameter(name="anomaly_threshold", type="float", required=False, default="0.65", description="Anomaly score threshold."),
            ToolParameter(name="top_n", type="int", required=False, default="50", description="Maximum number of critical hexagons."),
        ],
        output_schema_ref="#/components/schemas/Axis1CrossValidateResponse",
    ),
    ToolDefinition(
        tool_id="axis2_run",
        name="Axis 2 — Expansion Opportunity Clusterer",
        description=(
            "Identifies geographic clusters of high-demand, underserved hexagons using "
            "UMAP + HDBSCAN. Returns a cluster summary with centroid coordinates, mean "
            "feature values, and a TAM proxy estimate per cluster — ideal for prioritising "
            "new infrastructure deployment zones."
        ),
        endpoint="/v1/tools/axis2/run",
        method="POST",
        parameters=[
            ToolParameter(name="region_filter", type="list[str] | null", required=False, default="null", description="H3 parent cell IDs at res 5/6."),
            ToolParameter(name="h3_resolution", type="int", required=False, default="8", description="Target H3 resolution (8 or 9)."),
            ToolParameter(name="feature_weights", type="dict[str, float] | null", required=False, default="null", description="Optional feature weight overrides."),
            ToolParameter(name="min_cluster_size", type="int", required=False, default="50", description="HDBSCAN min_cluster_size parameter."),
            ToolParameter(name="skip_umap", type="bool", required=False, default="false", description="Skip UMAP pre-reduction."),
        ],
        output_schema_ref="#/components/schemas/Axis2RunResponse",
    ),
    ToolDefinition(
        tool_id="axis3_run",
        name="Axis 3 — Promotional Market Segmenter",
        description=(
            "Segments every H3 hexagon into promotional target groups using K-Means++. "
            "Assigns each hexagon to one of three named profiles (Premium, "
            "Conectividade Essencial, Alta Vulnerabilidade Concorrência) based on "
            "income, complaint volume, market concentration, and upload speed."
        ),
        endpoint="/v1/tools/axis3/run",
        method="POST",
        parameters=[
            ToolParameter(name="region_filter", type="list[str] | null", required=False, default="null", description="H3 parent cell IDs at res 5/6."),
            ToolParameter(name="h3_resolution", type="int", required=False, default="8", description="Target H3 resolution (8 or 9)."),
            ToolParameter(name="feature_weights", type="dict[str, float] | null", required=False, default="null", description="Optional feature weight overrides."),
            ToolParameter(name="n_clusters", type="int", required=False, default="3", description="Number of K-Means clusters (k)."),
            ToolParameter(name="sweep_if_low_silhouette", type="bool", required=False, default="true", description="Auto-sweep k if silhouette < 0.30."),
        ],
        output_schema_ref="#/components/schemas/Axis3RunResponse",
    ),
]


@router.get(
    "/tools",
    response_model=ToolCatalogueResponse,
    summary="Tool Catalogue — list all available analytical tools",
    description=(
        "Returns a machine-readable catalogue of every tool exposed by this API, "
        "including endpoint paths, HTTP methods, parameter types, and output schema "
        "references. This endpoint is the agent's tool registry source and does not "
        "require authentication."
    ),
    tags=["Discovery"],
)
async def get_tool_catalogue() -> ToolCatalogueResponse:
    return ToolCatalogueResponse(
        tool_count=len(_TOOL_CATALOGUE),
        tools=_TOOL_CATALOGUE,
    )


# ── POST /tools/axis1/run ──────────────────────────────────────────────────

@router.post(
    "/tools/axis1/run",
    response_model=Axis1RunResponse,
    summary="Axis 1 — Run Maintenance & Criticality pipeline",
    description=(
        "Loads the Gold Feature Store, executes the IsolationForest + LOF anomaly "
        "detection ensemble, and returns the top-N critical hexagons with their "
        "anomaly scores and GeoJSON-compatible coordinates. "
        "Requires ``X-API-Key`` header."
    ),
    tags=["Tools"],
)
async def run_axis1(
    body: Axis1RunRequest,
    _key: str = Depends(require_api_key),
) -> Axis1RunResponse:
    run_id = _make_run_id()
    t0 = time.perf_counter()
    logger.info(
        "run_id=%s axis=axis1 region_filter=%s h3_resolution=%s threshold=%s",
        run_id, body.region_filter, body.h3_resolution, body.anomaly_threshold,
    )

    audit = get_audit_logger()

    try:
        gold_df = _load_gold(body.region_filter, body.h3_resolution)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("run_id=%s axis=axis1 error loading gold: %s", run_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    # ── Run pipeline (re-fit scaler + iforest to capture artefacts for SHAP) ─
    from sklearn.preprocessing import StandardScaler
    from sklearn.ensemble import IsolationForest

    feature_cols = [c for c in pipeline_axis1.AXIS1_FEATURES if c in gold_df.columns]
    work_df = gold_df[["h3_id"] + feature_cols].dropna(subset=feature_cols).copy()
    scaler_ax1 = StandardScaler()
    X_scaled_ax1 = scaler_ax1.fit_transform(work_df[feature_cols].values.astype(float))
    iforest_ax1 = IsolationForest(
        contamination=body.contamination,
        random_state=42,
        n_estimators=200,
    )
    iforest_ax1.fit(X_scaled_ax1)

    try:
        result_df = pipeline_axis1.run(
            gold_df=gold_df,
            contamination=body.contamination,
            anomaly_score_threshold=body.anomaly_threshold,
            enable_mlflow=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("run_id=%s axis=axis1 pipeline error: %s", run_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    total_scored = len(result_df)
    critical_df = result_df[result_df["is_critical"] == 1].copy()
    critical_df = critical_df.sort_values("anomaly_score", ascending=False).head(body.top_n)

    rows: list[Axis1HexagonResult] = []
    for _, row in critical_df.iterrows():
        lat, lon = _h3_centroid(row["h3_id"])
        rows.append(Axis1HexagonResult(
            h3_id=row["h3_id"],
            lat_centroid=lat,
            lon_centroid=lon,
            anomaly_score=float(row["anomaly_score"]),
            is_critical=int(row["is_critical"]),
            lof_score=float(row["lof_score"]),
            cloudflare_outage_overlap=int(row["cloudflare_outage_overlap"]),
        ))

    duration = round(time.perf_counter() - t0, 3)
    n_critical = int(result_df["is_critical"].sum())
    logger.info(
        "run_id=%s axis=axis1 total=%d critical=%d duration=%.3fs",
        run_id, total_scored, n_critical, duration,
    )

    # ── SHAP explainability ────────────────────────────────────────────────
    is_critical_mask = result_df["is_critical"].values
    explanation = _xai.explain_axis1(
        X_scaled=X_scaled_ax1,
        feature_names=feature_cols,
        iforest=iforest_ax1,
        is_critical_mask=is_critical_mask,
    )

    # ── Audit log ─────────────────────────────────────────────────────────
    audit.log_tool_call(
        run_id=run_id,
        agent_id="operational",
        tool_name="axis1_run",
        tool_input={
            "region_filter": body.region_filter,
            "h3_resolution": body.h3_resolution,
            "anomaly_threshold": body.anomaly_threshold,
            "contamination": body.contamination,
            "top_n": body.top_n,
        },
        tool_output_summary={
            "total_hexagons_scored": total_scored,
            "n_critical": n_critical,
            "anomaly_rate": round(n_critical / total_scored, 6) if total_scored else 0.0,
            "duration_seconds": duration,
        },
        explanation=explanation,
    )

    return Axis1RunResponse(
        run_id=run_id,
        duration_seconds=duration,
        total_hexagons_scored=total_scored,
        n_critical=n_critical,
        anomaly_rate=round(n_critical / total_scored, 6) if total_scored else 0.0,
        results=rows,
    )


# ── POST /tools/axis1/crossvalidate ───────────────────────────────────────

@router.post(
    "/tools/axis1/crossvalidate",
    response_model=Axis1CrossValidateResponse,
    summary="Axis 1 — Cross-validate critical hexagons against Cloudflare outages",
    description=(
        "Runs Axis 1 anomaly detection then calls the Cloudflare Radar "
        "``/annotations/outages`` endpoint for the supplied date range. "
        "Returns an agreement rate and a per-event hexagon-overlap summary. "
        "Requires ``X-API-Key`` header."
    ),
    tags=["Tools"],
)
async def crossvalidate_axis1(
    body: Axis1CrossValidateRequest,
    _key: str = Depends(require_api_key),
) -> Axis1CrossValidateResponse:
    run_id = _make_run_id()
    t0 = time.perf_counter()
    logger.info(
        "run_id=%s axis=axis1_crossvalidate date_start=%s date_end=%s",
        run_id, body.date_start, body.date_end,
    )

    # ── 1. Run Axis 1 pipeline ─────────────────────────────────────────────
    try:
        gold_df = _load_gold(body.region_filter, 8)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    try:
        result_df = pipeline_axis1.run(
            gold_df=gold_df,
            anomaly_score_threshold=body.anomaly_threshold,
            enable_mlflow=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    critical_df = result_df[result_df["is_critical"] == 1].head(body.top_n)
    critical_h3_set = set(critical_df["h3_id"].tolist())

    # ── 2. Fetch Cloudflare outages ────────────────────────────────────────
    cf_token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    cf_outages: list[dict] = []
    if cf_token:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://api.cloudflare.com/client/v4/radar/annotations/outages",
                    headers={"Authorization": f"Bearer {cf_token}"},
                    params={"dateStart": body.date_start, "dateEnd": body.date_end, "limit": 100},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    cf_outages = data.get("result", {}).get("annotations", [])
        except Exception as exc:
            logger.warning("run_id=%s cloudflare fetch failed: %s", run_id, exc)
    else:
        logger.warning("run_id=%s CLOUDFLARE_API_TOKEN not set — skipping outage fetch.", run_id)

    # ── 3. Compute overlap ─────────────────────────────────────────────────
    overlap_events: list[OutageOverlapEntry] = []
    total_cf_cells_in_critical = 0

    for event in cf_outages:
        # Cloudflare annotations carry lat/lon or location string — best effort H3 mapping
        locations = event.get("locations", [])
        event_h3_cells: set[str] = set()
        for loc in locations:
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            if lat is not None and lon is not None:
                try:
                    cell = h3.latlng_to_cell(float(lat), float(lon), 8)
                    event_h3_cells.add(cell)
                except Exception:
                    pass

        overlap_count = len(event_h3_cells & critical_h3_set)
        total_cf_cells_in_critical += overlap_count

        overlap_events.append(OutageOverlapEntry(
            outage_id=str(event.get("id", "")),
            outage_description=event.get("description", ""),
            outage_start=event.get("startDate", ""),
            outage_end=event.get("endDate"),
            affected_location=event.get("linkedUrl") or event.get("eventStatus"),
            overlapping_critical_hexagons=overlap_count,
        ))

    n_cf = len(cf_outages)
    agreement_rate = (total_cf_cells_in_critical / len(critical_h3_set)) if critical_h3_set else 0.0

    duration = round(time.perf_counter() - t0, 3)
    logger.info(
        "run_id=%s axis=axis1_crossvalidate cf_outages=%d agreement=%.2f%% duration=%.3fs",
        run_id, n_cf, agreement_rate * 100, duration,
    )

    return Axis1CrossValidateResponse(
        run_id=run_id,
        duration_seconds=duration,
        date_range={"start": body.date_start, "end": body.date_end},
        n_critical_hexagons=len(critical_h3_set),
        n_cloudflare_outages_fetched=n_cf,
        agreement_rate=round(agreement_rate, 6),
        overlapping_events=overlap_events,
    )


# ── POST /tools/axis2/run ──────────────────────────────────────────────────

@router.post(
    "/tools/axis2/run",
    response_model=Axis2RunResponse,
    summary="Axis 2 — Run Expansion Opportunities pipeline",
    description=(
        "Executes the UMAP + HDBSCAN expansion clustering pipeline and returns "
        "a cluster summary with centroid coordinates, mean feature values, and a "
        "TAM estimate per cluster. Requires ``X-API-Key`` header."
    ),
    tags=["Tools"],
)
async def run_axis2(
    body: Axis2RunRequest,
    _key: str = Depends(require_api_key),
) -> Axis2RunResponse:
    run_id = _make_run_id()
    t0 = time.perf_counter()
    logger.info(
        "run_id=%s axis=axis2 region_filter=%s min_cluster_size=%s",
        run_id, body.region_filter, body.min_cluster_size,
    )

    audit = get_audit_logger()

    try:
        gold_df = _load_gold(body.region_filter, body.h3_resolution)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    try:
        result_df = pipeline_axis2.run(
            gold_df=gold_df,
            hdbscan_min_cluster_size=body.min_cluster_size,
            skip_umap=body.skip_umap,
            enable_mlflow=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("run_id=%s axis=axis2 pipeline error: %s", run_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    # Build per-cluster centroid coordinates using H3
    result_df = result_df.copy()
    result_df["lat_centroid"] = result_df["h3_id"].apply(lambda x: _h3_centroid(x)[0])
    result_df["lon_centroid"] = result_df["h3_id"].apply(lambda x: _h3_centroid(x)[1])

    non_noise = result_df[result_df["is_noise"] == 0]
    cluster_centroids = (
        non_noise.groupby("cluster_id")[["lat_centroid", "lon_centroid"]]
        .mean()
        .round(6)
    )

    unique_clusters = result_df.drop_duplicates("cluster_id")
    clusters: list[Axis2ClusterSummary] = []
    for _, row in unique_clusters.iterrows():
        cid = int(row["cluster_id"])
        is_noise_cluster = int(row["is_noise"])
        lat = float(cluster_centroids.loc[cid, "lat_centroid"]) if cid in cluster_centroids.index else 0.0
        lon = float(cluster_centroids.loc[cid, "lon_centroid"]) if cid in cluster_centroids.index else 0.0
        avg_n_dom = None if pd.isna(row.get("avg_n_dom")) else float(row["avg_n_dom"])
        avg_d_down = None if pd.isna(row.get("avg_d_down")) else float(row["avg_d_down"])
        avg_hhi = None if pd.isna(row.get("avg_HHI")) else float(row["avg_HHI"])
        cluster_size = int(row["cluster_size"])
        tam = round(avg_n_dom * cluster_size, 2) if avg_n_dom is not None else None

        clusters.append(Axis2ClusterSummary(
            cluster_id=cid,
            cluster_size=cluster_size,
            lat_centroid=lat,
            lon_centroid=lon,
            avg_d_down=avg_d_down,
            avg_n_dom=avg_n_dom,
            avg_HHI=avg_hhi,
            tam_estimate=tam,
            is_noise=is_noise_cluster,
        ))

    n_real_clusters = int((result_df[result_df["is_noise"] == 0]["cluster_id"].nunique()))
    noise_rate = float(result_df["is_noise"].mean())
    duration = round(time.perf_counter() - t0, 3)
    logger.info(
        "run_id=%s axis=axis2 clusters=%d noise_rate=%.2f%% duration=%.3fs",
        run_id, n_real_clusters, noise_rate * 100, duration,
    )

    # ── Z-score proxy explainability ──────────────────────────────────────
    feature_cols_ax2 = [c for c in pipeline_axis2.AXIS2_FEATURES if c in gold_df.columns]
    explanation_ax2 = _xai.explain_axis2_from_pipeline(
        gold_df=gold_df,
        result_df=result_df,
        feature_cols=feature_cols_ax2,
    )

    # ── Audit log ─────────────────────────────────────────────────────────
    audit.log_tool_call(
        run_id=run_id,
        agent_id="operational",
        tool_name="axis2_run",
        tool_input={
            "region_filter": body.region_filter,
            "h3_resolution": body.h3_resolution,
            "min_cluster_size": body.min_cluster_size,
            "skip_umap": body.skip_umap,
        },
        tool_output_summary={
            "total_hexagons_processed": len(result_df),
            "n_clusters": n_real_clusters,
            "noise_rate": round(noise_rate, 6),
            "duration_seconds": duration,
        },
        explanation=explanation_ax2,
    )

    return Axis2RunResponse(
        run_id=run_id,
        duration_seconds=duration,
        total_hexagons_processed=len(result_df),
        n_clusters=n_real_clusters,
        noise_rate=round(noise_rate, 6),
        clusters=clusters,
    )


# ── POST /tools/axis3/run ──────────────────────────────────────────────────

@router.post(
    "/tools/axis3/run",
    response_model=Axis3RunResponse,
    summary="Axis 3 — Run Promotional Targeting segmentation",
    description=(
        "Executes the K-Means++ promotional segmentation pipeline and returns "
        "the full hexagon-level segment assignment table together with segment "
        "profile metadata. Requires ``X-API-Key`` header."
    ),
    tags=["Tools"],
)
async def run_axis3(
    body: Axis3RunRequest,
    _key: str = Depends(require_api_key),
) -> Axis3RunResponse:
    run_id = _make_run_id()
    t0 = time.perf_counter()
    logger.info(
        "run_id=%s axis=axis3 region_filter=%s n_clusters=%s",
        run_id, body.region_filter, body.n_clusters,
    )

    audit = get_audit_logger()

    try:
        gold_df = _load_gold(body.region_filter, body.h3_resolution)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    # ── Fit scaler + KMeans to retain centroids for SHAP ─────────────────
    from sklearn.preprocessing import StandardScaler
    from sklearn.cluster import KMeans

    feature_cols_ax3 = [c for c in pipeline_axis3.AXIS3_FEATURES if c in gold_df.columns]
    work_ax3 = gold_df[["h3_id"] + feature_cols_ax3].dropna(subset=feature_cols_ax3).copy()
    scaler_ax3 = StandardScaler()
    X_scaled_ax3 = scaler_ax3.fit_transform(work_ax3[feature_cols_ax3].values.astype(float))
    km_ax3 = KMeans(n_clusters=body.n_clusters, init="k-means++", n_init=10, random_state=42)
    km_ax3.fit(X_scaled_ax3)

    try:
        result_df = pipeline_axis3.run(
            gold_df=gold_df,
            k=body.n_clusters,
            sweep_if_low_silhouette=body.sweep_if_low_silhouette,
            enable_mlflow=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("run_id=%s axis=axis3 pipeline error: %s", run_id, exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    n_total = len(result_df)
    sil_global: Optional[float] = None
    if "silhouette_score_local" in result_df.columns:
        sil_vals = result_df["silhouette_score_local"].dropna()
        if not sil_vals.empty:
            sil_global = round(float(sil_vals.mean()), 6)

    # Build segment profiles
    profiles: list[Axis3SegmentProfile] = []
    for seg_id in result_df["segment_id"].unique():
        seg_df = result_df[result_df["segment_id"] == seg_id]
        seg_name = str(seg_df["segment_name"].iloc[0])
        count = len(seg_df)
        avg_cd = float(seg_df["centroid_distance"].mean()) if "centroid_distance" in seg_df else 0.0
        avg_sil = None
        if "silhouette_score_local" in seg_df.columns:
            vals = seg_df["silhouette_score_local"].dropna()
            if not vals.empty:
                avg_sil = round(float(vals.mean()), 6)

        profiles.append(Axis3SegmentProfile(
            segment_id=int(seg_id),
            segment_name=seg_name,
            hexagon_count=count,
            hexagon_fraction=round(count / n_total, 6),
            avg_centroid_distance=round(avg_cd, 6),
            avg_silhouette=avg_sil,
        ))

    # Build hexagon-level result rows
    rows: list[Axis3HexagonResult] = []
    for _, row in result_df.iterrows():
        lat, lon = _h3_centroid(row["h3_id"])
        sil_local = None
        if "silhouette_score_local" in row and not pd.isna(row["silhouette_score_local"]):
            sil_local = float(row["silhouette_score_local"])
        rows.append(Axis3HexagonResult(
            h3_id=row["h3_id"],
            lat_centroid=lat,
            lon_centroid=lon,
            segment_id=int(row["segment_id"]),
            segment_name=str(row["segment_name"]),
            centroid_distance=float(row["centroid_distance"]),
            silhouette_score_local=sil_local,
        ))

    duration = round(time.perf_counter() - t0, 3)
    n_segments = result_df["segment_id"].nunique()
    logger.info(
        "run_id=%s axis=axis3 segments=%d hexagons=%d sil_global=%s duration=%.3fs",
        run_id, n_segments, n_total, sil_global, duration,
    )

    # ── KernelExplainer explainability (run in thread to avoid event loop conflict) ─
    import asyncio as _asyncio
    label_map_ax3 = result_df.set_index("h3_id")["segment_id"].to_dict()
    work_ax3_aligned = work_ax3[work_ax3["h3_id"].isin(result_df["h3_id"])].copy()
    X_for_shap = scaler_ax3.transform(
        work_ax3_aligned[feature_cols_ax3].values.astype(float)
    )
    labels_for_shap = np.array([
        label_map_ax3.get(h3, 0) for h3 in work_ax3_aligned["h3_id"]
    ])
    explanation_ax3 = await _asyncio.to_thread(
        _xai.explain_axis3,
        X_for_shap,
        feature_cols_ax3,
        km_ax3.cluster_centers_,
        labels_for_shap,
    )

    # ── Audit log ─────────────────────────────────────────────────────────
    audit.log_tool_call(
        run_id=run_id,
        agent_id="operational",
        tool_name="axis3_run",
        tool_input={
            "region_filter": body.region_filter,
            "h3_resolution": body.h3_resolution,
            "n_clusters": body.n_clusters,
            "sweep_if_low_silhouette": body.sweep_if_low_silhouette,
        },
        tool_output_summary={
            "total_hexagons_segmented": n_total,
            "n_segments": int(n_segments),
            "silhouette_score_global": sil_global,
            "duration_seconds": duration,
        },
        explanation=explanation_ax3,
    )

    return Axis3RunResponse(
        run_id=run_id,
        duration_seconds=duration,
        total_hexagons_segmented=n_total,
        n_segments=int(n_segments),
        silhouette_score_global=sil_global,
        segment_profiles=profiles,
        results=rows,
    )
