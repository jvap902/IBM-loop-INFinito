"""
Unit tests for agent.region_resolver.resolve_region()
"""

import pytest
import h3

from agent.region_resolver import resolve_region


# ---------------------------------------------------------------------------
# "all" and empty string → None
# ---------------------------------------------------------------------------

def test_all_returns_none():
    assert resolve_region("all") is None


def test_all_case_insensitive_returns_none():
    assert resolve_region("ALL") is None
    assert resolve_region("All") is None


def test_empty_string_returns_none():
    assert resolve_region("") is None


def test_whitespace_only_returns_none():
    assert resolve_region("   ") is None


# ---------------------------------------------------------------------------
# Valid H3 ID passthrough
# ---------------------------------------------------------------------------

def test_valid_h3_id_passthrough():
    h3_id = "855198c7fffffff"
    assert h3.is_valid_cell(h3_id), "pre-condition: must be a valid H3 cell"
    result = resolve_region(h3_id)
    assert result == [h3_id]


def test_valid_h3_id_passthrough_res5():
    # Pick a known res-5 cell covering São Paulo area
    h3_id = "855198c7fffffff"
    result = resolve_region(h3_id)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0] == h3_id


# ---------------------------------------------------------------------------
# State abbreviation
# ---------------------------------------------------------------------------

def test_state_abbreviation_sp():
    result = resolve_region("SP")
    assert isinstance(result, list)
    assert len(result) > 0
    # Every returned element must be a valid H3 cell
    for cell in result:
        assert h3.is_valid_cell(cell), f"{cell!r} is not a valid H3 cell"


def test_state_abbreviation_lowercase():
    result = resolve_region("sp")
    assert isinstance(result, list)
    assert len(result) > 0


def test_state_abbreviation_am():
    result = resolve_region("AM")
    assert isinstance(result, list)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# BR-prefixed form
# ---------------------------------------------------------------------------

def test_br_prefixed_rj():
    result = resolve_region("BR-RJ")
    assert isinstance(result, list)
    assert len(result) > 0
    for cell in result:
        assert h3.is_valid_cell(cell)


def test_br_prefixed_lowercase():
    result = resolve_region("br-rj")
    assert isinstance(result, list)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Full name with/without accents
# ---------------------------------------------------------------------------

def test_accented_full_name_sp():
    result = resolve_region("São Paulo")
    assert isinstance(result, list)
    assert len(result) > 0
    for cell in result:
        assert h3.is_valid_cell(cell)


def test_unaccented_full_name_sp():
    result = resolve_region("Sao Paulo")
    assert isinstance(result, list)
    assert len(result) > 0
    for cell in result:
        assert h3.is_valid_cell(cell)


def test_accented_and_unaccented_same_result():
    """Accent-stripped name should resolve identically to the accented form."""
    assert resolve_region("São Paulo") == resolve_region("Sao Paulo")


def test_abbreviation_and_full_name_same_result():
    """'SP' and 'São Paulo' must resolve to the same set of H3 cells."""
    assert resolve_region("SP") == resolve_region("São Paulo")


def test_full_name_ceara():
    result = resolve_region("Ceará")
    assert isinstance(result, list)
    assert len(result) > 0


def test_full_name_ceara_unaccented():
    result = resolve_region("Ceara")
    assert isinstance(result, list)
    assert len(result) > 0
    assert resolve_region("Ceará") == resolve_region("Ceara")


# ---------------------------------------------------------------------------
# Macro-region
# ---------------------------------------------------------------------------

def test_macro_region_sudeste():
    result = resolve_region("Sudeste")
    assert isinstance(result, list)
    assert len(result) > 0
    for cell in result:
        assert h3.is_valid_cell(cell)


def test_macro_region_sudeste_covers_all_four_states():
    """Sudeste cells must be a strict superset of each individual state."""
    sudeste = set(resolve_region("Sudeste"))
    for uf in ("SP", "RJ", "MG", "ES"):
        state_cells = set(resolve_region(uf))
        assert state_cells, f"{uf} should resolve to non-empty cells"
        assert state_cells.issubset(sudeste), (
            f"Sudeste result must contain all cells from {uf}"
        )


def test_macro_region_sul():
    result = resolve_region("Sul")
    assert isinstance(result, list)
    assert len(result) > 0


def test_macro_region_norte():
    result = resolve_region("Norte")
    assert isinstance(result, list)
    assert len(result) > 0


def test_macro_region_nordeste():
    result = resolve_region("Nordeste")
    assert isinstance(result, list)
    assert len(result) > 0


def test_macro_region_centro_oeste():
    result = resolve_region("Centro-Oeste")
    assert isinstance(result, list)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Unknown string → ValueError
# ---------------------------------------------------------------------------

def test_unknown_string_raises_value_error():
    with pytest.raises(ValueError, match="Região não reconhecida"):
        resolve_region("ZZZ")


def test_unknown_string_error_message_contains_input():
    with pytest.raises(ValueError, match="'XYZ'"):
        resolve_region("XYZ")


def test_unknown_string_error_message_contains_hint():
    with pytest.raises(ValueError, match="SP"):
        resolve_region("NOT_A_REGION")


def test_random_string_raises():
    with pytest.raises(ValueError):
        resolve_region("foobar")
