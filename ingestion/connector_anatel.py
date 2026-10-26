"""Anatel Open Data connector.

Datasets ingested
-----------------
1. SCM (Serviço de Comunicação Multimídia) — fixed broadband accesses
   → used to compute HHI per municipality
2. SMP (Serviço Móvel Pessoal) — mobile subscriptions
   → supplementary operator share validation
3. Reclamações — consumer complaints per service/municipality
   → used to compute vol_reclam per 1,000 accesses
4. Mosaico Estações Outorgadas — licensed base stations
   → used to derive n_erb (density of radio base stations per hexagon)

Auth   : None (open government data)
Format : CSV bulk download
Portal : https://informacoes.anatel.gov.br / https://dados.anatel.gov.br

LGPD   : All data is already municipality/station-level (no PII).
"""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from ingestion.base import BaseConnector
from processing.spatial import latlon_to_h3

logger = logging.getLogger(__name__)

# Configurable URLs — override via environment variables
_SCM_URL = os.getenv(
    "ANATEL_SCM_URL",
    "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/acessos/scm/SCM_Accesses.csv",
)
_SMP_URL = os.getenv(
    "ANATEL_SMP_URL",
    "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/acessos/smp/SMP_Accesses.csv",
)
_RECLAM_URL = os.getenv(
    "ANATEL_RECLAM_URL",
    "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/consumidor/Reclamacoes.csv",
)
_MOSAICO_URL = os.getenv(
    "ANATEL_MOSAICO_URL",
    "https://sistemas.anatel.gov.br/se/public/view/b/licenciamento.php?acao=csv",
)

_CSV_ENCODING = "latin-1"
_H3_RESOLUTIONS = [8, 9]


class AnatelConnector(BaseConnector):
    """Downloads and processes four Anatel open datasets.

    Feature outputs
    ---------------
    HHI         : Herfindahl-Hirschman Index per municipality
                  HHI = Σ(market_share_i² × 10000), range [0, 10000]
    vol_reclam  : Complaints per 1,000 accesses (SCM + SMP denominator)
    n_erb       : Count of licensed stations per H3 hexagon (Mosaico)
    """

    source_id = "anatel_dados"

    def __init__(self, h3_resolutions: list[int] | None = None) -> None:
        self.h3_resolutions = h3_resolutions or _H3_RESOLUTIONS

    # ------------------------------------------------------------------
    def extract(self) -> pd.DataFrame:
        scm = self._load_csv(_SCM_URL, label="SCM")
        smp = self._load_csv(_SMP_URL, label="SMP")
        reclam = self._load_csv(_RECLAM_URL, label="Reclamacoes")
        mosaico = self._load_csv(_MOSAICO_URL, label="Mosaico")

        hhi_df = self._compute_hhi(scm)
        reclam_df = self._compute_vol_reclam(reclam, scm, smp)
        erb_df = self._compute_n_erb(mosaico)

        # Merge into a single result keyed by (municipio, uf) + H3 hex
        result = hhi_df.merge(
            reclam_df, on=["municipio", "uf"], how="outer"
        )
        # n_erb is at hexagon level; persist separately and merge via spatial join
        # in the Silver layer.  Here we expose both the municipality table
        # and the hexagon-level ERB table as separate DataFrames bundled via
        # a dict-like column sentinel so load_to_bronze can split them.
        self._erb_df = erb_df  # stash for custom bronze write
        logger.info(
            "[anatel] HHI records: %d | vol_reclam records: %d | ERB hexagons: %d",
            len(hhi_df),
            len(reclam_df),
            len(erb_df),
        )
        return result

    def load_to_bronze(self, df: pd.DataFrame, bronze_dir: Path) -> Path:
        dest = bronze_dir / self.source_id
        dest.mkdir(parents=True, exist_ok=True)

        muni_path = dest / "municipality_metrics.parquet"
        df.to_parquet(muni_path, index=False, compression="snappy")
        logger.info("[anatel] Bronze municipality metrics → %s", muni_path)

        if hasattr(self, "_erb_df") and not self._erb_df.empty:
            erb_path = dest / "erb_h3.parquet"
            self._erb_df.to_parquet(erb_path, index=False, compression="snappy")
            logger.info("[anatel] Bronze ERB hexagon table → %s", erb_path)

        return muni_path

    # ------------------------------------------------------------------
    # HHI computation
    # ------------------------------------------------------------------
    def _compute_hhi(self, scm: pd.DataFrame) -> pd.DataFrame:
        """Compute Herfindahl-Hirschman Index per municipality from SCM data."""
        if scm.empty:
            return pd.DataFrame(columns=["municipio", "uf", "HHI"])

        # Normalise column names (Anatel CSV headers may vary)
        scm.columns = [c.strip().lower() for c in scm.columns]
        mun_col = _find_col(scm, ["municipio", "municipio_setor", "cod_municipio"])
        uf_col = _find_col(scm, ["uf", "estado", "sg_uf"])
        prest_col = _find_col(scm, ["prestadora", "empresa", "razao_social"])
        acess_col = _find_col(scm, ["acessos", "quantidade_acessos", "total_acessos"])

        if not all([mun_col, uf_col, prest_col, acess_col]):
            logger.warning(
                "[anatel] Required SCM columns not found; HHI will be null. "
                "Available: %s", list(scm.columns)
            )
            return pd.DataFrame(columns=["municipio", "uf", "HHI"])

        scm = scm[[mun_col, uf_col, prest_col, acess_col]].copy()
        scm.columns = ["municipio", "uf", "prestadora", "acessos"]
        scm["acessos"] = pd.to_numeric(scm["acessos"], errors="coerce").fillna(0)

        total = scm.groupby(["municipio", "uf"])["acessos"].sum().rename("total")
        scm = scm.merge(total.reset_index(), on=["municipio", "uf"])
        scm = scm[scm["total"] > 0]
        scm["share"] = scm["acessos"] / scm["total"]
        scm["share_sq"] = scm["share"] ** 2

        hhi = (
            scm.groupby(["municipio", "uf"])["share_sq"]
            .sum()
            .mul(10000)
            .round(2)
            .rename("HHI")
            .reset_index()
        )
        logger.info("[anatel] HHI computed for %d municipalities.", len(hhi))
        return hhi

    # ------------------------------------------------------------------
    # vol_reclam computation
    # ------------------------------------------------------------------
    def _compute_vol_reclam(
        self,
        reclam: pd.DataFrame,
        scm: pd.DataFrame,
        smp: pd.DataFrame,
    ) -> pd.DataFrame:
        """Compute complaints per 1,000 accesses per municipality."""
        if reclam.empty:
            return pd.DataFrame(columns=["municipio", "uf", "vol_reclam"])

        reclam.columns = [c.strip().lower() for c in reclam.columns]
        mun_col = _find_col(reclam, ["municipio", "cod_municipio"])
        uf_col = _find_col(reclam, ["uf", "sg_uf"])

        if not all([mun_col, uf_col]):
            logger.warning("[anatel] Required Reclamações columns not found.")
            return pd.DataFrame(columns=["municipio", "uf", "vol_reclam"])

        complaint_counts = (
            reclam.groupby([mun_col, uf_col])
            .size()
            .rename("n_reclam")
            .reset_index()
        )
        complaint_counts.columns = ["municipio", "uf", "n_reclam"]

        # Total accesses (SCM + SMP)
        access_totals = []
        for src, label in [(scm, "SCM"), (smp, "SMP")]:
            if src.empty:
                continue
            src = src.copy()
            src.columns = [c.strip().lower() for c in src.columns]
            m = _find_col(src, ["municipio", "cod_municipio"])
            u = _find_col(src, ["uf", "sg_uf"])
            a = _find_col(src, ["acessos", "quantidade_acessos", "total_acessos"])
            if m and u and a:
                grp = (
                    src.groupby([m, u])[a]
                    .sum()
                    .reset_index()
                )
                grp.columns = ["municipio", "uf", "acessos"]
                access_totals.append(grp)

        if access_totals:
            all_access = pd.concat(access_totals).groupby(
                ["municipio", "uf"]
            )["acessos"].sum().reset_index()
        else:
            all_access = pd.DataFrame(columns=["municipio", "uf", "acessos"])

        merged = complaint_counts.merge(all_access, on=["municipio", "uf"], how="left")
        merged["vol_reclam"] = (
            merged["n_reclam"] / merged["acessos"].replace(0, float("nan")) * 1000
        ).round(4)

        null_vol = merged["vol_reclam"].isna().sum()
        if null_vol:
            logger.info(
                "[anatel] %d municipalities with null vol_reclam (no access denominator).",
                null_vol,
            )

        return merged[["municipio", "uf", "vol_reclam"]]

    # ------------------------------------------------------------------
    # n_erb computation
    # ------------------------------------------------------------------
    def _compute_n_erb(self, mosaico: pd.DataFrame) -> pd.DataFrame:
        """Count ERB stations per H3 hexagon from Mosaico Estações."""
        if mosaico.empty:
            return pd.DataFrame(columns=[f"h3_r{r}" for r in self.h3_resolutions] + ["n_erb"])

        mosaico.columns = [c.strip().lower() for c in mosaico.columns]
        lat_col = _find_col(mosaico, ["latitude", "lat"])
        lon_col = _find_col(mosaico, ["longitude", "lon", "lng"])

        if not lat_col or not lon_col:
            logger.warning(
                "[anatel] Lat/lon columns not found in Mosaico. n_erb will be empty."
            )
            return pd.DataFrame(columns=[f"h3_r{r}" for r in self.h3_resolutions] + ["n_erb"])

        mosaico[lat_col] = pd.to_numeric(mosaico[lat_col], errors="coerce")
        mosaico[lon_col] = pd.to_numeric(mosaico[lon_col], errors="coerce")
        mosaico = mosaico.dropna(subset=[lat_col, lon_col])
        logger.info("[anatel] Mosaico stations with valid coords: %d", len(mosaico))

        res_primary = self.h3_resolutions[0]
        col = f"h3_r{res_primary}"
        mosaico[col], failed = latlon_to_h3(mosaico[lat_col], mosaico[lon_col], res_primary)
        if failed:
            logger.warning("[anatel] %d stations failed H3 assignment.", failed)

        # Supplement with secondary resolution
        for res in self.h3_resolutions[1:]:
            c2 = f"h3_r{res}"
            mosaico[c2], _ = latlon_to_h3(mosaico[lat_col], mosaico[lon_col], res)

        erb_count = (
            mosaico.groupby(col)
            .size()
            .rename("n_erb")
            .reset_index()
        )
        logger.info("[anatel] ERB station counts per hexagon (res %d): %d", res_primary, len(erb_count))
        return erb_count

    # ------------------------------------------------------------------
    # CSV loader helper
    # ------------------------------------------------------------------
    @staticmethod
    def _load_csv(url: str, label: str) -> pd.DataFrame:
        logger.info("[anatel] Fetching %s from: %s", label, url)
        try:
            resp = requests.get(url, timeout=120, stream=True)
            resp.raise_for_status()
            df = pd.read_csv(
                io.BytesIO(resp.content),
                encoding=_CSV_ENCODING,
                sep=None,
                engine="python",
                on_bad_lines="skip",
            )
            logger.info("[anatel] %s loaded: %d rows", label, len(df))
            return df
        except Exception as exc:
            logger.warning(
                "[anatel] %s fetch failed (%s). Returning empty DataFrame.", label, exc
            )
            return pd.DataFrame()


# ------------------------------------------------------------------
# Column-name discovery helper
# ------------------------------------------------------------------
def _find_col(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    """Return the first candidate column name present in *df*, else None."""
    for c in candidates:
        if c in df.columns:
            return c
    return None
