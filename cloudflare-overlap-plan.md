# Plan: Wire Live Cloudflare Outage Data into run_axis1

## Overview

The `cloudflare_outage_overlap` field on every `Axis1HexagonResult` is always `0` when called from the frontend, because `pipeline_axis1.run()` is invoked without `cloudflare_outage_h3_ids`. That argument defaults to `None` → empty set → every hexagon scores `0`.

The Cloudflare fetch logic already exists in `crossvalidate_axis1` — it calls the Cloudflare Radar `/annotations/outages` API, maps outage lat/lon points to H3 cells, and produces a set of affected cells. This plan extracts that logic into a shared async helper and calls it from `run_axis1` before the pipeline runs, so the "Ocorrência Cloudflare" column is populated with real data on every normal run.

The response gains a `cloudflare_data_available` boolean so the frontend can clearly label the column as live data or as unavailable (token not configured / API error).

---

## Sub-Task 1 — Backend: extract Cloudflare fetch into a shared helper and wire into run_axis1

**Status:** `[x] done`

### Intent
The Cloudflare outage fetch is currently inlined inside `crossvalidate_axis1`. This sub-task extracts it into a standalone async helper `_fetch_cloudflare_outage_cells(h3_resolution)` and calls it from `run_axis1` before the pipeline executes. The helper reads `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_DATE_RANGE_DAYS` from the environment, fetches recent outage annotations, maps each outage's lat/lon to an H3 cell at the requested resolution, and returns a `set[str]`. If the token is absent or the API call fails, it returns an empty set and logs a warning.

### Expected Outcomes
- A new async function `_fetch_cloudflare_outage_cells(h3_resolution: int) -> tuple[set[str], bool]` exists in `tools.py`. It returns `(cell_set, data_available)` where `data_available` is `True` only when the API call succeeded and returned at least some annotations.
- `run_axis1` calls `_fetch_cloudflare_outage_cells(body.h3_resolution)` before calling `pipeline_axis1.run()`, passing the returned cell set as `cloudflare_outage_h3_ids`.
- `Axis1RunResponse` gains a `cloudflare_data_available: bool = False` field.
- `run_axis1` sets `cloudflare_data_available` from the helper's return value and includes it in the response.
- `crossvalidate_axis1` is updated to call `_fetch_cloudflare_outage_cells` instead of repeating the inline fetch logic.

### Todo List
1. Open `api/routes/tools.py`.
2. Add a new async helper `_fetch_cloudflare_outage_cells(h3_resolution: int) -> tuple[set[str], bool]`:
   - Read `CLOUDFLARE_API_TOKEN` from env; if empty, return `(set(), False)`.
   - Read `CLOUDFLARE_DATE_RANGE_DAYS` from env (default `30`).
   - Compute `date_end` as today's date (ISO-8601), `date_start` as `date_end - CLOUDFLARE_DATE_RANGE_DAYS`.
   - Call `GET https://api.cloudflare.com/client/v4/radar/annotations/outages` with the date range and `limit=100`.
   - For each annotation's `locations`, convert lat/lon to an H3 cell at `h3_resolution` using `h3.latlng_to_cell`.
   - Return `(cells, True)` on success, `(set(), False)` on any error.
3. In `run_axis1`, before the `pipeline_axis1.run()` call, `await _fetch_cloudflare_outage_cells(body.h3_resolution)` and unpack into `cf_cells, cf_available`.
4. Pass `cloudflare_outage_h3_ids=cf_cells` to `pipeline_axis1.run()`.
5. Open `api/schemas.py` and add `cloudflare_data_available: bool = False` to `Axis1RunResponse`.
6. In `run_axis1`, pass `cloudflare_data_available=cf_available` to `Axis1RunResponse(...)`.
7. In `crossvalidate_axis1`, replace the inline Cloudflare fetch block (lines 498–514) with a call to `_fetch_cloudflare_outage_cells(8)`, discarding the `data_available` return value (crossvalidate uses its own overlap logic).

### Relevant Context
- **Inline fetch to extract:** `api/routes/tools.py` lines 497–514 (inside `crossvalidate_axis1`)
- **`pipeline_axis1.run()` call in `run_axis1`:** lines 372–377 — add `cloudflare_outage_h3_ids=cf_cells`
- **`Axis1RunResponse`:** `api/schemas.py` lines 114–130
- **`CLOUDFLARE_DATE_RANGE_DAYS`:** already documented in `.env.example` line 61
- **Date computation:** use Python's `datetime.date.today()` and `timedelta` — no new imports needed

---

## Sub-Task 2 — Frontend: update types and display Cloudflare availability state

**Status:** `[x] done`

### Intent
After Sub-Task 1, the API response carries `cloudflare_data_available`. The frontend should use this to inform the user whether the "Ocorrência Cloudflare" column reflects real data or is unavailable (token not set). When unavailable, the column header should carry a visual indicator, and a subtle note should explain why.

### Expected Outcomes
- `Axis1RunResponse` TypeScript interface gains `cloudflare_data_available?: boolean`.
- In `CriticalTable`, the "Ocorrência Cloudflare" column header shows a `(sem token)` note in muted style when `cloudflare_data_available` is `false` or absent.
- When `cloudflare_data_available` is `true`, the column header is unchanged and the "⚠ Confirmado" / "—" values have their normal meaning.
- The "Confirmados Cloudflare" KPI card `sub` line shows `"token não configurado"` in muted style when `cloudflare_data_available` is `false`.

### Todo List
1. Open `frontend/src/types.ts`.
2. Add `cloudflare_data_available?: boolean` to `Axis1RunResponse`.
3. Open `frontend/src/pages/Axis1Page.tsx`.
4. Pass `cloudflare_data_available` from `data` as a prop into `CriticalTable`.
5. In `CriticalTable`, conditionally append `" (sem token)"` in muted style to the "Ocorrência Cloudflare" column header when `cloudflare_data_available` is falsy.
6. In the KPI cards block, conditionally set the `sub` of the "Confirmados Cloudflare" card to `"token não configurado"` (in place of the percentage) when `cloudflare_data_available` is falsy.

### Relevant Context
- **TypeScript type:** `frontend/src/types.ts` lines 71–81 (`Axis1RunResponse`)
- **`CriticalTable` component:** `frontend/src/pages/Axis1Page.tsx` lines 21–57 — currently receives only `results`
- **Column headers array:** line 28 — `['Localização', 'Prioridade', 'Score Anomalia', 'Fator LOF', 'Ocorrência Cloudflare']`
- **KPI cards block:** lines 122–129 — Confirmados Cloudflare card

---

## Execution Order

Sub-Task 1 must be completed first (backend provides the new field).
Sub-Task 2 follows and can be done immediately after.
