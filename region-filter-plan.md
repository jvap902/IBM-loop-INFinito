# Plan: Fix Region & State Filtering in Analysis

## Top-Level Overview

The Analysis tab allows users to type a region string (e.g. `BR-SP`) or an H3 parent ID
to scope the ML analysis. Currently, entering any value other than `all` or a raw H3 ID
has **no effect** — the analysis always runs on the full dataset.

**Root cause (two-part):**

1. **`graph.py` (`_make_axis_runner`)** – The region-to-filter conversion only passes the
   string through if it has length ≥ 7 AND is not `"all"`. A label like `"BR-SP"` (5 chars)
   is silently dropped. Even if it were long enough, a non-H3 string would be forwarded
   directly to `_load_gold()` as a filter item, where `h3.get_resolution("BR-SP")` throws
   inside the try/except, causing every row to be masked out and an HTTP 400 error.

2. **`tools.py` (`_load_gold`)** – The filter logic only understands H3 parent cell IDs.
   It has no concept of Brazilian regions (`Norte`, `Sudeste`, …) or states (`SP`, `RJ`, …).
   The Gold Parquet table itself has no `uf`/`estado`/`regiao` column, so even if the
   filter reached the data layer there would be nothing to match against.

**Goal:** Users must be able to type either:
- A **Brazilian macro-region name** (e.g. `Sudeste`, `Norte`) to scope the analysis to all
  H3 cells in that region.
- A **Brazilian state abbreviation or name** (e.g. `SP`, `São Paulo`) to scope the analysis
  to all H3 cells in that state.
- A raw **H3 parent cell ID** (existing behaviour, to be preserved).
- `all` (existing behaviour, to be preserved).

The fix must not require changes to the Gold Parquet schema or re-ingestion of data, and
must not alter the ML pipeline internals (Axis 1 / 2 / 3).

---

## Sub-Tasks

---

### Sub-Task 1 — Add a Brazil Region/State → H3 Resolver

**Intent**
Create a self-contained resolver that, given a free-text region string, returns a list of
H3 parent cell IDs (resolution 5) covering that geographic area. This allows the rest of
the pipeline to keep working with H3 IDs as filters — no downstream changes required.

The resolver must handle:
- State abbreviations: `SP`, `RJ`, `MG`, …
- State full names: `São Paulo`, `Rio de Janeiro`, …
- Macro-region names: `Sudeste`, `Norte`, `Nordeste`, `Centro-Oeste`, `Sul`
- Normalisation: accent-insensitive, case-insensitive

The H3 cells for each state are computed by running `h3.geo_to_cells(polygon, res=5)` on
each state's GeoJSON polygon. `geopandas` (v1.2.0), `shapely` (v2.2.0), and `pyproj`
(v3.8.0) are already project dependencies and will be used to load and transform the
boundaries. `reverse_geocoder` (already imported in `api/routes/tools.py`) works in the
reverse direction only (lat/lon → city name) and cannot provide polygons — it will be used
only to cross-reference `admin1` name spellings for the normalisation table.

The GeoJSON boundary file for Brazil's 27 states is not present in the repo and must be
downloaded (from IBGE/Natural Earth) and committed to `data/geo/brazil_states.geojson`.
If the file is absent at runtime, the resolver falls back to a bounding-box approximation
using hardcoded lat/lon extents for each state (reliable enough for res-5 coverage).

The output of this resolver is a `list[str]` of H3 res-5 IDs, or `None` if the input is
`"all"` / empty, or the raw list `[input]` if the input is already a valid H3 ID.

**Expected Outcomes**
- A new module (e.g. `agent/region_resolver.py`) with a single public function:
  `resolve_region(region_str: str) -> list[str] | None`
- Unit tests covering: state abbreviation, full name (with accents), macro-region name,
  raw H3 ID passthrough, `"all"` → `None`, and an unknown string raising a clear error.
- Static GeoJSON boundary file committed to the repo (e.g. `data/geo/brazil_states.geojson`).

**Todo List**
- [ ] Download the Brazil states GeoJSON from IBGE/Natural Earth and commit it to
      `data/geo/brazil_states.geojson`.
- [ ] Create `agent/region_resolver.py` with:
  - A normalisation lookup table covering:
    - State abbreviations in both formats: `SP` and `BR-SP`.
    - State full names (with and without accents): `São Paulo`, `Sao Paulo`.
    - Macro-region names: `Norte`, `Nordeste`, `Centro-Oeste`, `Sudeste`, `Sul`
      (each resolving to the list of constituent state abbreviations).
  - `resolve_region(region_str: str) -> list[str] | None` that:
    - Returns `None` for `"all"` or empty string.
    - Returns `[region_str]` unchanged if it's already a valid H3 ID (`h3.is_valid_cell`).
    - Normalises the input (strip, uppercase, remove accents) and looks it up in the table.
    - Loads `data/geo/brazil_states.geojson` via `geopandas`, filters to the matched
      state(s), runs `h3.geo_to_cells(polygon.__geo_interface__, res=5)` for each polygon,
      and returns the de-duplicated union as a `list[str]`.
    - Raises `ValueError("Região não reconhecida: '…'. Use 'all', um código de estado (SP, BR-SP), nome do estado ou nome da macro-região.")` for unrecognised inputs.
- [ ] Write unit tests in `tests/unit/test_region_resolver.py`.

**Relevant Context**
- `agent/graph.py:264–275` — current (broken) region → filter conversion; will be replaced
  with a call to `resolve_region`.
- `api/routes/tools.py:97–109` — H3 filter application; no changes needed here once the
  resolver produces valid H3 IDs.
- `h3` library is already a project dependency (used throughout `api/routes/tools.py`).

**Status** `[x] done`

---

### Sub-Task 2 — Wire the Resolver into the Agent Graph

**Intent**
Replace the ad-hoc length-check in `_make_axis_runner` with a call to the new
`resolve_region` function. The agent node becomes the single place where a human-readable
region string is translated into a list of H3 filter IDs.

**Expected Outcomes**
- `agent/graph.py` `_make_axis_runner` calls `resolve_region(region)` and passes the result
  as `region_filter` to the tool params.
- If `resolve_region` raises `ValueError` (unrecognised input), the node returns a
  structured error entry in `state["errors"]` — consistent with the existing error-handling
  pattern in that function — rather than crashing.
- Existing H3 ID passthrough behaviour is unchanged.
- Existing `"all"` behaviour (no filter) is unchanged.

**Todo List**
- [ ] Import `resolve_region` from `agent/region_resolver.py` in `agent/graph.py`.
- [ ] In `_make_axis_runner`, replace lines 265–271 (the length-check block) with:
  ```python
  try:
      region_filter = resolve_region(region)
  except ValueError as exc:
      # return structured error consistent with existing pattern
      ...
  ```
- [ ] Run existing agent tests to confirm no regression (`tests/test_agent.py`).

**Relevant Context**
- `agent/graph.py:251–319` — `_make_axis_runner` factory; the change is localised to
  lines 264–275.
- `agent/state.py:68` — `region_scope` type is `str | list[str]`; the resolver handles
  both.

**Status** `[x] done`

---

### Sub-Task 3 — Update the Frontend Region Input

**Intent**
Improve the UI region input so users clearly understand the accepted formats, and provide
immediate inline feedback when an unrecognised value is typed (rather than letting the
backend 422 be the first signal).

**Expected Outcomes**
- The placeholder in `RunPage.tsx` is updated (e.g. `all · SP · BR-SP · Sudeste · 855198c7fffffff`).
- The help text is updated to list all accepted formats.
- A `<datalist>` element is wired to the input for autocomplete (5 macro-region names +
  27 state abbreviations + 27 `BR-XX` forms + `all`). No extra libraries needed.
- The backend's 422 `detail` message is surfaced clearly in the error area already
  rendered by the form — the existing error display block handles this. No new UI
  components are needed for the error path.

**Todo List**
- [ ] Update `frontend/src/pages/RunPage.tsx`:
  - Change the `placeholder` of the region `<input>` to
    `all · SP · BR-SP · Sudeste · 855198c7fffffff`.
  - Update the `<p>` help text below the input to mention both `SP` and `BR-SP` formats.
  - Add a `<datalist id="region-suggestions">` with `all`, 5 macro-regions, 27 state
    abbreviations, and 27 `BR-XX` codes.
  - Add `list="region-suggestions"` to the `<input>`.
  - Confirm the existing error display block (which already renders
    `apiError.response.data.detail`) surfaces the 422 detail from Sub-Task 4.

**Relevant Context**
- `frontend/src/pages/RunPage.tsx:117–127` — the region input block to be updated.

**Status** `[x] done`

---

### Sub-Task 4 — Update Backend Schema & Validation

**Intent**
Update `AgentRunRequest` in `api/schemas.py` to reflect the expanded valid formats for the
`region` field. Add a Pydantic validator that rejects strings that are not `"all"`, not a
valid H3 ID, and not a known Brazil region/state — failing fast at the API boundary with a
clear 422 error rather than propagating silently into the agent.

**Expected Outcomes**
- `api/schemas.py` `AgentRunRequest.region` field description and `examples` list are
  updated.
- A `@field_validator("region")` is added that calls `resolve_region` and raises
  `ValueError` for unrecognised inputs (Pydantic will turn this into a 422).
- The validator should not pre-compute or store the H3 list — it only validates.
  Resolution happens in the agent graph (Sub-Task 2).
- Existing API tests pass without modification.

**Todo List**
- [ ] In `api/schemas.py`, update the `region` field description and examples.
- [ ] Add a `@field_validator("region", mode="before")` that:
  - Allows `"all"` and `""`.
  - Allows a string that is a valid H3 cell ID (`h3.is_valid_cell`).
  - Calls `resolve_region` and only checks that it does NOT raise.
  - Raises `ValueError` with the resolver's message for anything else.
- [ ] Import `resolve_region` and `h3` in `api/schemas.py`.
- [ ] Run `tests/test_api.py` to confirm no regression.

**Relevant Context**
- `api/schemas.py:309–337` — `AgentRunRequest` definition.
- The validator must import from `agent/region_resolver.py`; verify there are no circular
  import issues (the `api` package does not currently import from `agent`; consider placing
  the resolver in a shared location like `agent/region_resolver.py` and importing it in
  both places, or duplicating the validation logic in a tiny `api/region_resolver.py`
  wrapper that delegates to the same module).

**Status** `[x] done`

---

## Implementation Order

Sub-tasks must be completed in order:

```
Sub-Task 1  →  Sub-Task 2  →  Sub-Task 4  →  Sub-Task 3
(resolver)      (agent)        (schema)        (UI)
```

Sub-Task 3 (UI) is independent of Sub-Tasks 2 and 4 and can be done in parallel if
desired, but is lowest risk and should be done last.
