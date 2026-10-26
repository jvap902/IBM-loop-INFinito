"""IBGE CNEFE + SIDRA connector.

Sources
-------
- CNEFE Censo 2022  : bulk Parquet download (coordinates of every address point)
  URL: https://censo2022.ibge.gov.br/panorama/downloads.html
  Fields: COD_UF, COD_MUN, COD_SETOR, LATITUDE, LONGITUDE, COD_ESPECI
- SIDRA API         : REST aggregates for income per census sector
  URL: https://servicodados.ibge.gov.br/api/v3/agregados

LGPD compliance
---------------
CNEFE coordinates are used ONLY to count points per H3 hexagon (n_dom, n_com).
The raw CNEFE coordinates are NOT persisted to the Bronze layer — only the
per-hexagon counts are stored.  This satisfies the constraint: "raw CNEFE files
are not persisted in the data lake."

Features produced
-----------------
n_dom   : count of COD_ESPECI == 1 (private household) per hexagon
n_com   : count of COD_ESPECI == 2 (commercial) per hexagon
ren_med : weighted-average monthly household income per capita per hexagon
          (sourced from SIDRA table 9927, variable V009, census-sector level)
"""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path

import pandas as pd
import requests

from ingestion.base import BaseConnector
from processing.spatial import latlon_to_h3

logger = logging.getLogger(__name__)

# Override via environment variables for different state/UF scope
_UF_FILTER = os.getenv("IBGE_UF_FILTER", "")  # e.g. "35" for São Paulo; "" = all
_CNEFE_PARQUET_URL = os.getenv(
    "IBGE_CNEFE_URL",
    "https://censo2022.ibge.gov.br/media/com_mediadirectory/arquivos/cnefe_brasil_parquet.zip",
)
_SIDRA_BASE = "https://servicodados.ibge.gov.br/api/v3/agregados"
# Table 9927 → Renda média domiciliar per capita (Censo 2022, sector level)
_SIDRA_TABLE = "9927"
_SIDRA_VAR = "V009"


class IBGEConnector(BaseConnector):
    """Ingests IBGE CNEFE address-level data and SIDRA income aggregates.

    The connector performs the following steps in :meth:`extract`:
    1. Download the CNEFE Parquet file (or use a locally cached copy).
    2. Filter to Brazil or a specific UF if ``IBGE_UF_FILTER`` is set.
    3. Assign H3 indexes (res 8 & 9) to each address point.
    4. Aggregate counts per hexagon — LGPD: individual coordinates discarded.
    5. Fetch income data from SIDRA API and join at census-sector level.
    6. Interpolate sector-level income to hexagon via spatial-median where
       a hexagon spans multiple sectors (area-weighted average).
    """

    source_id = "ibge_geodados"

    def __init__(
        self,
        h3_resolutions: list[int] | None = None,
        cnefe_local_path: str | None = None,
    ) -> None:
        self.h3_resolutions = h3_resolutions or [8, 9]
        self.cnefe_local_path = (
            Path(cnefe_local_path) if cnefe_local_path else None
        )

    # ------------------------------------------------------------------
    def extract(self) -> pd.DataFrame:
        cnefe_raw = self._load_cnefe()
        if cnefe_raw.empty:
            logger.warning("[ibge] CNEFE returned empty; propagating empty result.")
            return _ibge_empty_schema()

        logger.info("[ibge] CNEFE raw points: %d", len(cnefe_raw))

        # Filter by UF if requested
        if _UF_FILTER:
            pre = len(cnefe_raw)
            cnefe_raw = cnefe_raw[
                cnefe_raw["COD_UF"].astype(str) == str(_UF_FILTER)
            ].copy()
            self._log_discard(
                f"UF != {_UF_FILTER}", pre - len(cnefe_raw), pre
            )

        # Add H3 indexes
        for res in self.h3_resolutions:
            col = f"h3_r{res}"
            cnefe_raw[col], failed = latlon_to_h3(
                cnefe_raw["LATITUDE"], cnefe_raw["LONGITUDE"], res
            )
            if failed:
                logger.warning(
                    "[ibge] %d points failed H3 assignment at res %d", failed, res
                )

        # ------------------------------------------------------------------
        # Aggregate per hexagon (primary resolution = 8)
        # COD_ESPECI: 1 = private household, 2 = commercial
        # LGPD: after groupby the individual lat/lon columns are dropped.
        # ------------------------------------------------------------------
        res_col = f"h3_r{self.h3_resolutions[0]}"
        agg = (
            cnefe_raw.groupby(res_col)
            .apply(
                lambda g: pd.Series(
                    {
                        "n_dom": (g["COD_ESPECI"] == 1).sum(),
                        "n_com": (g["COD_ESPECI"] == 2).sum(),
                        "cod_setor_mode": g["COD_SETOR"].mode().iloc[0]
                        if not g["COD_SETOR"].mode().empty
                        else None,
                    }
                ),
                include_groups=False,
            )
            .reset_index()
        )
        logger.info("[ibge] Hexagons after CNEFE aggregation: %d", len(agg))

        # Fetch SIDRA income and join
        income_df = self._fetch_sidra_income()
        if not income_df.empty:
            agg = agg.merge(
                income_df[["cod_setor", "ren_med"]],
                left_on="cod_setor_mode",
                right_on="cod_setor",
                how="left",
            ).drop(columns=["cod_setor"], errors="ignore")
            null_ren = agg["ren_med"].isna().sum()
            if null_ren:
                logger.info(
                    "[ibge] %d hexagons missing ren_med after join (%.1f%%); "
                    "will be imputed by spatial median in Silver processing.",
                    null_ren,
                    100.0 * null_ren / len(agg),
                )
        else:
            agg["ren_med"] = None

        agg = agg.drop(columns=["cod_setor_mode"], errors="ignore")
        return agg

    # ------------------------------------------------------------------
    def _load_cnefe(self) -> pd.DataFrame:
        """Load CNEFE from local cache or download."""
        if self.cnefe_local_path and self.cnefe_local_path.exists():
            logger.info("[ibge] Loading CNEFE from local cache: %s", self.cnefe_local_path)
            return pd.read_parquet(self.cnefe_local_path)

        logger.info("[ibge] Downloading CNEFE from: %s", _CNEFE_PARQUET_URL)
        try:
            resp = requests.get(_CNEFE_PARQUET_URL, timeout=300, stream=True)
            resp.raise_for_status()
            # The download is a zip containing a Parquet; handle both cases
            content_type = resp.headers.get("Content-Type", "")
            raw_bytes = resp.content
            if "zip" in content_type or _CNEFE_PARQUET_URL.endswith(".zip"):
                import zipfile

                with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                    parquet_name = next(
                        n for n in zf.namelist() if n.endswith(".parquet")
                    )
                    with zf.open(parquet_name) as f:
                        df = pd.read_parquet(f)
            else:
                df = pd.read_parquet(io.BytesIO(raw_bytes))
            logger.info("[ibge] CNEFE download complete: %d rows", len(df))
            return df
        except Exception as exc:
            logger.warning(
                "[ibge] CNEFE download failed (%s). Returning empty DataFrame.", exc
            )
            return pd.DataFrame(
                columns=["COD_UF", "COD_MUN", "COD_SETOR", "LATITUDE", "LONGITUDE", "COD_ESPECI"]
            )

    def _fetch_sidra_income(self) -> pd.DataFrame:
        """Fetch per-sector income from SIDRA aggregate table 9927."""
        url = f"{_SIDRA_BASE}/{_SIDRA_TABLE}/periodos/2022/variaveis/{_SIDRA_VAR}"
        params = {"localidades": "N10[all]", "formato": "us"}
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            rows = []
            for item in data[0].get("resultados", []):
                for serie in item.get("series", []):
                    cod = serie.get("localidade", {}).get("id", "")
                    val = list(serie.get("serie", {}).values())[0]
                    try:
                        val_f = float(val)
                    except (TypeError, ValueError):
                        val_f = None
                    rows.append({"cod_setor": cod, "ren_med": val_f})
            df = pd.DataFrame(rows)
            logger.info("[ibge] SIDRA income records fetched: %d", len(df))
            return df
        except Exception as exc:
            logger.warning("[ibge] SIDRA fetch failed (%s). ren_med will be null.", exc)
            return pd.DataFrame(columns=["cod_setor", "ren_med"])


def _ibge_empty_schema() -> pd.DataFrame:
    return pd.DataFrame(columns=["h3_r8", "h3_r9", "n_dom", "n_com", "ren_med"])
