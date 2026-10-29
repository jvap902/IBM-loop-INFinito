"""
region_resolver.py
------------------
Converts a free-text Brazil region string to a list of H3 res-5 cell IDs.

Public API
----------
resolve_region(region_str: str) -> list[str] | None
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path
from typing import Optional

import h3

# ---------------------------------------------------------------------------
# Macro-region membership
# ---------------------------------------------------------------------------

_MACRO_REGIONS: dict[str, list[str]] = {
    "NORTE":        ["AC", "AM", "AP", "PA", "RO", "RR", "TO"],
    "NORDESTE":     ["AL", "BA", "CE", "MA", "PB", "PE", "PI", "RN", "SE"],
    "CENTRO-OESTE": ["DF", "GO", "MS", "MT"],
    "SUDESTE":      ["ES", "MG", "RJ", "SP"],
    "SUL":          ["PR", "RS", "SC"],
}

# ---------------------------------------------------------------------------
# All valid UF codes and their canonical full names (as they appear in the
# GeoJSON  name  field)
# ---------------------------------------------------------------------------

_UF_NAMES: dict[str, str] = {
    "AC": "Acre",
    "AL": "Alagoas",
    "AM": "Amazonas",
    "AP": "Amapá",
    "BA": "Bahia",
    "CE": "Ceará",
    "DF": "Distrito Federal",
    "ES": "Espírito Santo",
    "GO": "Goiás",
    "MA": "Maranhão",
    "MG": "Minas Gerais",
    "MS": "Mato Grosso do Sul",
    "MT": "Mato Grosso",
    "PA": "Pará",
    "PB": "Paraíba",
    "PE": "Pernambuco",
    "PI": "Piauí",
    "PR": "Paraná",
    "RJ": "Rio de Janeiro",
    "RN": "Rio Grande do Norte",
    "RO": "Rondônia",
    "RR": "Roraima",
    "RS": "Rio Grande do Sul",
    "SC": "Santa Catarina",
    "SE": "Sergipe",
    "SP": "São Paulo",
    "TO": "Tocantins",
}

# ---------------------------------------------------------------------------
# Bounding-box fallback (lat_min, lat_max, lng_min, lng_max) per UF
# Used when the GeoJSON file is absent at runtime.
# ---------------------------------------------------------------------------

_UF_BBOX: dict[str, tuple[float, float, float, float]] = {
    "AC": (-11.14,  -7.12, -73.98, -66.62),
    "AL": ( -9.96,  -8.81, -38.24, -35.15),
    "AM": ( -9.82,   2.24, -73.79, -56.10),
    "AP": ( -1.24,   4.44, -52.37, -49.87),
    "BA": (-17.99,  -8.53, -46.62, -37.35),
    "CE": ( -7.86,  -2.78, -41.43, -37.26),
    "DF": (-16.05, -15.50, -48.28, -47.31),
    "ES": (-21.32, -17.88, -41.87, -39.67),
    "GO": (-19.49, -12.41, -53.25, -45.93),
    "MA": ( -9.98,  -1.01, -48.20, -41.82),
    "MG": (-22.92, -14.24, -51.04, -39.86),
    "MS": (-24.07, -17.16, -58.16, -50.93),
    "MT": (-18.04,  -7.35, -61.61, -50.23),
    "PA": ( -9.84,   2.59, -58.90, -46.03),
    "PB": ( -8.28,  -6.03, -38.80, -34.79),
    "PE": ( -9.48,  -7.29, -41.35, -34.87),
    "PI": (-10.93,  -2.74, -45.98, -40.37),
    "PR": (-26.72, -22.52, -54.62, -48.02),
    "RJ": (-23.37, -20.76, -44.90, -40.96),
    "RN": ( -6.98,  -4.83, -38.59, -35.01),
    "RO": (-13.69,  -7.97, -66.80, -59.76),
    "RR": (  1.18,   5.27, -64.82, -58.89),
    "RS": (-33.75, -27.10, -57.65, -49.70),
    "SC": (-29.36, -25.96, -53.84, -48.37),
    "SE": (-11.57,  -9.52, -38.24, -36.39),
    "SP": (-25.31, -19.78, -53.11, -44.16),
    "TO": (-13.46,  -5.17, -50.74, -45.71),
}

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _strip_accents(s: str) -> str:
    """Return *s* with all combining diacritics removed."""
    return (
        unicodedata.normalize("NFD", s)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def _normalise(s: str) -> str:
    """Strip whitespace, uppercase, remove accents."""
    return _strip_accents(s.strip()).upper()


# ---------------------------------------------------------------------------
# Build the lookup table: normalised key → list[UF]
# ---------------------------------------------------------------------------

def _build_lookup() -> dict[str, list[str]]:
    table: dict[str, list[str]] = {}

    # UF code direct (e.g. "SP")
    for uf in _UF_NAMES:
        table[uf] = [uf]
        # BR-prefixed form (e.g. "BR-SP")
        table[f"BR-{uf}"] = [uf]

    # Full state names — with and without accents
    for uf, name in _UF_NAMES.items():
        key_accented = _normalise(name)
        key_plain = _strip_accents(key_accented)  # already upper, just ensure
        table[key_accented] = [uf]
        table[key_plain] = [uf]

    # Macro-region names — with and without accents
    for region, ufs in _MACRO_REGIONS.items():
        key_accented = _normalise(region)
        key_plain = _strip_accents(key_accented)
        table[key_accented] = ufs
        table[key_plain] = ufs

    return table


_LOOKUP: dict[str, list[str]] = _build_lookup()

# ---------------------------------------------------------------------------
# GeoJSON loading (cached at module level)
# ---------------------------------------------------------------------------

_GEOJSON_PATH = Path(__file__).parent.parent / "data" / "geo" / "brazil_states.geojson"

_gdf = None  # lazily loaded


def _load_gdf():
    global _gdf
    if _gdf is None:
        import geopandas as gpd  # lazy import — optional at module load
        _gdf = gpd.read_file(_GEOJSON_PATH)
    return _gdf


def _cells_from_bbox(uf: str) -> list[str]:
    """Fallback: cover the UF bounding box with H3 res-5 cells."""
    lat_min, lat_max, lng_min, lng_max = _UF_BBOX[uf]
    bbox_poly = {
        "type": "Polygon",
        "coordinates": [[
            [lng_min, lat_min],
            [lng_max, lat_min],
            [lng_max, lat_max],
            [lng_min, lat_max],
            [lng_min, lat_min],
        ]],
    }
    return list(h3.geo_to_cells(bbox_poly, res=5))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_region(region_str: str) -> Optional[list[str]]:
    """Convert a free-text region string to H3 res-5 cell IDs.

    Returns
    -------
    None
        When *region_str* is ``"all"`` or empty — meaning no spatial filter.
    list[str]
        Sorted, de-duplicated H3 res-5 cell IDs covering the requested area.
        If *region_str* is already a valid H3 cell ID, ``[region_str]`` is
        returned unchanged.

    Raises
    ------
    ValueError
        For any input that cannot be resolved.
    """
    # "all" / empty / whitespace-only → no filter
    stripped = region_str.strip()
    if not stripped or stripped.lower() == "all":
        return None

    # Already a valid H3 ID → pass through unchanged
    if h3.is_valid_cell(region_str):
        return [region_str]

    # Normalise and look up
    key = _normalise(region_str)
    ufs = _LOOKUP.get(key)
    if ufs is None:
        raise ValueError(
            f"Região não reconhecida: '{region_str}'. "
            "Use 'all', um código de estado (ex: SP, BR-SP), "
            "nome do estado ou nome da macro-região (ex: Sudeste)."
        )

    # Resolve each UF to H3 cells
    cells: set[str] = set()

    geojson_available = _GEOJSON_PATH.exists()

    if geojson_available:
        try:
            gdf = _load_gdf()
            subset = gdf[gdf["sigla"].isin(ufs)]
            for geom in subset.geometry:
                cells.update(h3.geo_to_cells(geom.__geo_interface__, res=5))
        except Exception:
            geojson_available = False  # fall through to bbox fallback

    if not geojson_available:
        for uf in ufs:
            cells.update(_cells_from_bbox(uf))

    return sorted(cells)
