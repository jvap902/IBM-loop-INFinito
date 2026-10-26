"""Silver → Gold aggregation pipeline.

Builds the 10-dimensional feature vector:
    x_hi = [d_down, d_up, lat, vol_test, n_dom, n_com, ren_med, n_erb, HHI, vol_reclam]

Each dimension maps to a Bronze source as specified in knowledge-api.json:
    d_down     ← Ookla avg_d_kbps / 1000 (Mbps), weighted by test count
    d_up       ← Ookla avg_u_kbps / 1000 (Mbps), weighted by test count
    lat        ← Ookla avg_lat_ms (primary) / M-Lab MinRTT (fallback)
    vol_test   ← Ookla tests / devices (normalised test density)
    n_dom      ← IBGE CNEFE count of COD_ESPECI == 1
    n_com      ← IBGE CNEFE count of COD_ESPECI == 2
    ren_med    ← IBGE SIDRA table 9927, interpolated to hexagon
    n_erb      ← Anatel Mosaico + OpenCelliD (summed, deduplicated by radius)
    HHI        ← Anatel SCM Herfindahl-Hirschman Index, joined at municipality
    vol_reclam ← Anatel Reclamações per 1,000 accesses, joined at municipality

LGPD: no individual records exist at this stage.  All inputs are hexagon-level
or municipality-level aggregates.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from processing.sanitise import run_sanitisation

logger = logging.getLogger(__name__)

# Canonical feature vector columns (spec-ordered)
X_HI_COLUMNS = [
    "d_down",
    "d_up",
    "lat",
    "vol_test",
    "n_dom",
    "n_com",
    "ren_med",
    "n_erb",
    "HHI",
    "vol_reclam",
]

# Non-feature metadata columns kept in the Gold table
METADATA_COLUMNS = [
    "h3_r8",
    "h3_r9",
    "year",
    "month",
    "h3_res",
    "low_confidence",
]


def build_silver(
    ookla_df: pd.DataFrame,
    ibge_df: pd.DataFrame,
    anatel_muni_df: pd.DataFrame,
    anatel_erb_df: pd.DataFrame,
    opencellid_df: pd.DataFrame,
    mlab_df: pd.DataFrame,
    h3_resolution: int = 8,
) -> pd.DataFrame:
    """Join all Bronze-layer DataFrames into a unified Silver layer.

    Parameters
    ----------
    ookla_df       : Output of OoklaConnector.extract()
    ibge_df        : Output of IBGEConnector.extract()
    anatel_muni_df : Municipality-level HHI + vol_reclam (Anatel)
    anatel_erb_df  : Hexagon-level n_erb (Anatel Mosaico)
    opencellid_df  : Hexagon-level n_erb supplement (OpenCelliD)
    mlab_df        : Hexagon-level M-Lab NDT aggregates
    h3_resolution  : Primary H3 resolution to join on (8 or 9).

    Returns
    -------
    Silver DataFrame keyed on the primary H3 cell.
    """
    h3_col = f"h3_r{h3_resolution}"
    logger.info("[silver] Building Silver layer at H3 res %d …", h3_resolution)

    # ------------------------------------------------------------------
    # 1.  Ookla aggregate per hexagon
    # ------------------------------------------------------------------
    if not ookla_df.empty and h3_col in ookla_df.columns:
        ookla_agg = (
            ookla_df.groupby(h3_col)
            .apply(
                lambda g: pd.Series(
                    {
                        # Weighted average by test count
                        "d_down": (
                            (g["avg_d_mbps"] * g["tests"]).sum() / g["tests"].sum()
                            if g["tests"].sum() > 0
                            else None
                        ),
                        "d_up": (
                            (g["avg_u_mbps"] * g["tests"]).sum() / g["tests"].sum()
                            if g["tests"].sum() > 0
                            else None
                        ),
                        "lat": (
                            (g["avg_lat_ms"] * g["tests"]).sum() / g["tests"].sum()
                            if g["tests"].sum() > 0
                            else None
                        ),
                        "vol_test": (
                            g["tests"].sum() / g["devices"].sum()
                            if g["devices"].sum() > 0
                            else None
                        ),
                        "low_confidence": bool((g["tests"] < 3).all()),
                    }
                ),
                include_groups=False,
            )
            .reset_index()
        )
        logger.info("[silver] Ookla hexagons: %d", len(ookla_agg))
    else:
        logger.warning("[silver] Ookla DataFrame empty; d_down/d_up/lat/vol_test will be null.")
        ookla_agg = pd.DataFrame(columns=[h3_col, "d_down", "d_up", "lat", "vol_test", "low_confidence"])
        ookla_agg[h3_col] = ookla_agg[h3_col].astype(str)

    # ------------------------------------------------------------------
    # 2.  Start Silver as the union of all hexagon keys
    # ------------------------------------------------------------------
    all_h3_keys: set[str] = set()
    for src_df in [ookla_agg, ibge_df, anatel_erb_df, opencellid_df, mlab_df]:
        if not src_df.empty and h3_col in src_df.columns:
            all_h3_keys |= set(src_df[h3_col].dropna())

    if not all_h3_keys:
        logger.warning("[silver] All sources are empty; returning empty Silver DataFrame.")
        return pd.DataFrame(columns=[h3_col])

    silver = pd.DataFrame({h3_col: list(all_h3_keys)})
    logger.info("[silver] Total unique hexagons across all sources: %d", len(silver))

    # Ensure h3 key column is string dtype before any merge
    silver[h3_col] = silver[h3_col].astype(str)
    ookla_agg[h3_col] = ookla_agg[h3_col].astype(str)

    # ------------------------------------------------------------------
    # 3.  Merge Ookla features
    # ------------------------------------------------------------------
    silver = silver.merge(ookla_agg, on=h3_col, how="left")

    # ------------------------------------------------------------------
    # 4.  Merge M-Lab (fallback for lat when Ookla is missing)
    # ------------------------------------------------------------------
    if not mlab_df.empty and h3_col in mlab_df.columns:
        silver = silver.merge(
            mlab_df[[h3_col, "mlab_min_rtt_ms", "mlab_down_mbps"]],
            on=h3_col,
            how="left",
        )
        # Fallback: if lat is null, use M-Lab MinRTT
        silver["lat"] = silver["lat"].combine_first(silver["mlab_min_rtt_ms"])
        silver = silver.drop(columns=["mlab_min_rtt_ms", "mlab_down_mbps"], errors="ignore")
    else:
        logger.warning("[silver] M-Lab DataFrame empty; no lat fallback.")

    # ------------------------------------------------------------------
    # 5.  Merge IBGE features
    # ------------------------------------------------------------------
    if not ibge_df.empty and h3_col in ibge_df.columns:
        silver = silver.merge(
            ibge_df[[h3_col, "n_dom", "n_com", "ren_med"]],
            on=h3_col,
            how="left",
        )
    else:
        logger.warning("[silver] IBGE DataFrame empty; n_dom/n_com/ren_med will be null.")
        for col in ["n_dom", "n_com", "ren_med"]:
            silver[col] = None

    # ------------------------------------------------------------------
    # 6.  Merge Anatel ERB counts
    # ------------------------------------------------------------------
    if not anatel_erb_df.empty and h3_col in anatel_erb_df.columns:
        silver = silver.merge(
            anatel_erb_df[[h3_col, "n_erb"]],
            on=h3_col,
            how="left",
        )
    else:
        silver["n_erb"] = None

    # ------------------------------------------------------------------
    # 7.  Supplement n_erb with OpenCelliD (sum, floor at Anatel count)
    # ------------------------------------------------------------------
    if not opencellid_df.empty and h3_col in opencellid_df.columns:
        silver = silver.merge(
            opencellid_df[[h3_col, "n_erb"]].rename(columns={"n_erb": "n_erb_ocid"}),
            on=h3_col,
            how="left",
        )
        # Use the max of both sources as a conservative density estimate
        silver["n_erb"] = silver[["n_erb", "n_erb_ocid"]].max(axis=1)
        silver = silver.drop(columns=["n_erb_ocid"])
        logger.info(
            "[silver] n_erb supplemented with OpenCelliD for %d hexagons.",
            silver["n_erb"].notna().sum(),
        )

    # ------------------------------------------------------------------
    # 8.  Merge Anatel municipality-level HHI + vol_reclam
    #     Municipality → hexagon join via municipality code embedded in
    #     the IBGE sector hierarchy.  For cells without a direct match,
    #     the value is left null and will be imputed by spatial median.
    # ------------------------------------------------------------------
    if not anatel_muni_df.empty:
        # anatel_muni_df has columns [municipio, uf, HHI, vol_reclam]
        # The silver layer does not have a municipality column at this point;
        # if ibge_df carries a municipality code, use it — otherwise keep null.
        if "municipio" in silver.columns:
            silver = silver.merge(
                anatel_muni_df[["municipio", "uf", "HHI", "vol_reclam"]],
                on=["municipio", "uf"],
                how="left",
            )
        else:
            logger.warning(
                "[silver] No 'municipio' column in Silver; "
                "HHI and vol_reclam will be null (imputed in sanitisation)."
            )
            silver["HHI"] = None
            silver["vol_reclam"] = None
    else:
        silver["HHI"] = None
        silver["vol_reclam"] = None

    logger.info(
        "[silver] Silver layer built: %d rows × %d columns",
        len(silver),
        len(silver.columns),
    )
    return silver


def build_gold(
    silver: pd.DataFrame,
    h3_resolution: int = 8,
    year: int | None = None,
    month: int | None = None,
    output_dir: Path | None = None,
) -> pd.DataFrame:
    """Sanitise Silver → produce Gold feature table with x_hi vector.

    Steps
    -----
    1. Run sanitisation (clip outliers, spatial median imputation, low-confidence flag).
    2. Select and rename to canonical x_hi column names.
    3. Add metadata columns (h3_res, year, month).
    4. Persist as Parquet partitioned by (year, month, h3_res).

    Parameters
    ----------
    silver       : Output of :func:`build_silver`.
    h3_resolution: H3 resolution; written as the ``h3_res`` partition key.
    year, month  : Optional temporal partition values (defaults to current date).
    output_dir   : Directory to write Parquet output.  If None, no file is written.

    Returns
    -------
    Gold DataFrame with columns = METADATA_COLUMNS + X_HI_COLUMNS.
    """
    import datetime as _dt

    now = _dt.date.today()
    year = year or now.year
    month = month or now.month

    h3_col = f"h3_r{h3_resolution}"

    # Run full sanitisation
    silver_san = run_sanitisation(silver, h3_col=h3_col)

    # Ensure all x_hi columns exist (fill with NaN if missing)
    for col in X_HI_COLUMNS:
        if col not in silver_san.columns:
            logger.warning(
                "[gold] Required x_hi column %r missing from Silver; filled with NaN.",
                col,
            )
            silver_san[col] = float("nan")

    # Build Gold table
    gold = silver_san[[h3_col] + X_HI_COLUMNS + ["low_confidence"]].copy()

    # Add secondary H3 resolution column if available
    h3_col_alt = "h3_r9" if h3_resolution == 8 else "h3_r8"
    if h3_col_alt in silver_san.columns:
        gold[h3_col_alt] = silver_san[h3_col_alt]

    gold["year"] = year
    gold["month"] = month
    gold["h3_res"] = h3_resolution

    # Rename primary H3 col to generic "h3_id" for schema consistency
    gold = gold.rename(columns={h3_col: "h3_id"})

    # Feature fill-rate audit
    for col in X_HI_COLUMNS:
        null_pct = 100.0 * gold[col].isna().sum() / max(len(gold), 1)
        logger.info("[gold] feature=%r null_pct=%.1f%%", col, null_pct)

    coverage_ok = gold["h3_id"].notna().sum() / max(len(gold), 1)
    logger.info(
        "[gold] Gold table finalised: %d hexagons | H3 coverage=%.1f%%",
        len(gold),
        100.0 * coverage_ok,
    )

    # Persist to Parquet
    if output_dir is not None:
        partition_path = (
            Path(output_dir)
            / f"year={year}"
            / f"month={month:02d}"
            / f"h3_res={h3_resolution}"
        )
        partition_path.mkdir(parents=True, exist_ok=True)
        out_file = partition_path / "feature_store.parquet"
        gold.to_parquet(out_file, index=False, compression="snappy")
        logger.info("[gold] Persisted → %s (%d rows)", out_file, len(gold))

    return gold
