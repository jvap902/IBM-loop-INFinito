# Plan: Axis 1 UX Improvements — Resolution Feedback & Informative Results Panel

## Overview

Two UX issues remain in the "Manutenção Necessária" tab:

1. **Resolution selector appears to do nothing** — "Detalhado (res 9)" and "Padrão (res 8)" produce identical results. The code path is correct: `h3_resolution` reaches `_load_gold()` and filters the parquet by `h3_res`. The silent failure occurs when the gold parquet only contains one resolution (e.g. only res 8), which is likely the case in the current dataset. The fix has two parts: the backend detects whether the requested resolution exists in the data and includes a `resolution_warning` in the response; the frontend displays it so users understand why results look the same.

2. **Results panel below the map is not informative enough** — The `CriticalTable` currently shows 6 columns: raw H3 hex ID (meaningless to humans), separate Lat and Lon (not actionable), a plain anomaly score float, a cryptic LOF float, and a plain "Sim/Não" Cloudflare flag. Several improvements are planned: replacing H3 IDs with reverse-geocoded place names, collapsing Lat/Lon into the location cell, adding a severity badge (Crítico/Alto/Médio) derived from the anomaly score, renaming cryptic column headers, and visually emphasising the Cloudflare confirmation. The KPI cards above the table also replace the "Duração" developer metric with a "Confirmados Cloudflare" business metric — the count of critical hexagons with confirmed outage overlap.

---

## Sub-Task 1 — Backend: detect missing resolution and expose warning in response

**Status:** `[x] done`

### Intent
When the gold parquet does not contain the requested `h3_resolution`, the user silently gets results from a different resolution (or an error). This sub-task makes the backend transparent: it checks whether the requested resolution exists, falls back gracefully, and signals the mismatch through a new `resolution_warning` field on the response.

### Expected Outcomes
- `Axis1RunResponse` gains an optional `resolution_warning: Optional[str]` field (default `None`).
- In `_load_gold()` (or in `run_axis1`), after filtering by `h3_res`, if the result is empty because the resolution was not found in the data, the handler falls back to whatever rows are present and sets `resolution_warning` to an explanatory string (e.g. `"Resolução 9 não disponível nos dados; usando resolução 8."`).
- If the requested resolution exists, `resolution_warning` is `None`.
- The TypeScript `Axis1RunResponse` interface gains `resolution_warning?: string | null`.

### Todo List
1. Open `api/schemas.py`.
2. Add `resolution_warning: Optional[str] = None` to `Axis1RunResponse`.
3. Open `api/routes/tools.py`.
4. In `_load_gold()`, after `df = df[df["h3_res"] == h3_resolution]`, check if the filtered df is empty but the unfiltered df was not. If so, instead of raising HTTP 400, return the unfiltered df along with a warning string. Refactor `_load_gold` to return a tuple `(pd.DataFrame, Optional[str])` where the second element is the resolution warning.
5. In `run_axis1`, unpack the tuple from `_load_gold`, store the warning, and pass it into `Axis1RunResponse(resolution_warning=...)`.
6. Open `frontend/src/types.ts`.
7. Add `resolution_warning?: string | null` to `Axis1RunResponse`.

### Relevant Context
- **Schema file:** `api/schemas.py` — `Axis1RunResponse` (lines 114–123)
- **`_load_gold` function:** `api/routes/tools.py` lines 67–119 — currently returns `pd.DataFrame`; needs to return `tuple[pd.DataFrame, Optional[str]]`
- **`run_axis1` handler:** `api/routes/tools.py` lines 267–377 — calls `_load_gold` at line 281
- **TypeScript types:** `frontend/src/types.ts` lines 71–79 (`Axis1RunResponse`)
- **Note:** `_load_gold` is also called by `run_axis2` and `run_axis3` — their call sites must be updated to unpack the tuple too, but since they don't use the warning, they can just discard it.

---

## Sub-Task 2 — Frontend: display resolution warning banner in results panel

**Status:** `[x] done`

### Intent
After Sub-Task 1, the API can signal a resolution mismatch. This sub-task makes `Axis1Page.tsx` show that warning to the user in the results panel — a non-blocking info banner explaining why the selected resolution had no effect.

### Expected Outcomes
- When `data.resolution_warning` is present, a visible info/warning banner appears above the KPI cards in the results panel.
- When `data.resolution_warning` is null, no banner is shown.

### Todo List
1. Open `frontend/src/pages/Axis1Page.tsx`.
2. In the results panel (inside `{data ? (...)}`), before the KPI cards grid, add a conditional block: if `data.resolution_warning` is truthy, render an info banner with the warning message.
3. Reuse or inline a simple banner style consistent with the existing `ErrorBanner` component (a yellow/amber info variant).

### Relevant Context
- **Page file:** `frontend/src/pages/Axis1Page.tsx` lines 95–101 (results panel start)
- **`ErrorBanner` component:** `frontend/src/components/AxisForm.tsx` — inspect its props/style to create a matching info variant

---

## Sub-Task 3 — Backend: add `place_name` to Axis 1 results via reverse geocoding

**Status:** `[x] done`

### Intent
Each critical hexagon has `lat_centroid` and `lon_centroid`. The `_reverse_geocode()` utility in `tools.py` is already used by Axis 2 to produce human-readable "City, State, CC" strings. This sub-task wires it into the Axis 1 result-building loop so every `Axis1HexagonResult` gains a `place_name` field.

### Expected Outcomes
- `Axis1HexagonResult` in `api/schemas.py` gains `place_name: Optional[str] = None`.
- In `run_axis1`, the loop that builds `Axis1HexagonResult` objects calls `_reverse_geocode(lat, lon)` and sets `place_name`.
- The TypeScript `Axis1HexagonResult` interface gains `place_name?: string | null`.

### Todo List
1. Open `api/schemas.py`.
2. Add `place_name: Optional[str] = None` to `Axis1HexagonResult`.
3. Open `api/routes/tools.py`.
4. In the `run_axis1` result-building loop (around line 321), compute `place = _reverse_geocode(lat, lon)` and pass `place_name=place` to the `Axis1HexagonResult` constructor.
5. Open `frontend/src/types.ts`.
6. Add `place_name?: string | null` to `Axis1HexagonResult`.

### Relevant Context
- **`Axis1HexagonResult` schema:** `api/schemas.py` lines 102–111
- **Result loop:** `api/routes/tools.py` lines 320–331
- **`_reverse_geocode` function:** `api/routes/tools.py` lines 136–146 — returns `Optional[str]`, already used by Axis 2 at line 584
- **TypeScript type:** `frontend/src/types.ts` lines 61–69

---

## Sub-Task 4 — Frontend: redesign the critical hexagons table for clarity and actionability

**Status:** `[x] done`

### Intent
The current table is hard to act on: raw H3 IDs, separate meaningless Lat/Lon columns, plain floats with no visual weight, and a cryptic "Cloudflare" column that doesn't explain what it means. This sub-task redesigns the table with five focused columns — location, severity tier, anomaly score, LOF score, and outage confirmation — using visual styling to communicate priority at a glance.

### Expected Outcomes
The redesigned `CriticalTable` has these 5 columns (replacing the current 6):

| Column | What it shows | Notes |
|---|---|---|
| **Localização** | `place_name` (primary) + H3 ID below in monospace | Falls back to H3 ID only when `place_name` is null |
| **Prioridade** | Severity badge derived from `anomaly_score` | `≥ 0.80` → "Crítico" (red), `≥ 0.65` → "Alto" (orange/amber), `< 0.65` → "Médio" (yellow) |
| **Score Anomalia** | Raw float, right-aligned | Colour-coded: red for ≥ 0.80, amber for ≥ 0.65, default otherwise |
| **Fator LOF** | Raw float | Renamed from plain "LOF" for clarity |
| **Ocorrência Cloudflare** | "⚠ Confirmado" (amber, bold) or "—" (muted grey) | Renamed and styled to be immediately visible |

The standalone Lat and Lon columns are removed; coordinates are folded into the Localização cell as a secondary line when `place_name` is present, or kept as the primary display when it is not.

### Todo List
1. Open `frontend/src/pages/Axis1Page.tsx`.
2. Replace the column headers array with: `['Localização', 'Prioridade', 'Score Anomalia', 'Fator LOF', 'Ocorrência Cloudflare']`.
3. Rewrite the row rendering to:
   - **Localização cell:** `place_name` as primary text; H3 ID as `font-mono text-[10px] text-ind-muted` below; if no `place_name`, show coordinates as secondary.
   - **Prioridade cell:** compute severity from `anomaly_score`, render a small badge with appropriate colour class.
   - **Score Anomalia cell:** display float with colour class based on score range.
   - **Fator LOF cell:** display float as before.
   - **Ocorrência Cloudflare cell:** "⚠ Confirmado" styled in `text-orange-400 font-semibold`, or `—` in `text-ind-muted`.

### Relevant Context
- **`CriticalTable` component:** `frontend/src/pages/Axis1Page.tsx` lines 9–37
- **`place_name` field:** added by Sub-Task 3; available as `r.place_name`
- **Axis 2 pattern for place_name:** `Axis2Page.tsx` line 30 — `{c.place_name && <div className="text-[10px] text-ind-muted mt-0.5">{c.place_name}</div>}`

---

## Sub-Task 5 — Frontend: replace "Duração" KPI card with "Confirmados Cloudflare"

**Status:** `[x] done`

### Intent
The three KPI cards above the table show "Hexágonos Analisados", "Anomalias Críticas", and "Duração". Duration is a developer metric, not a business metric. The most actionable number for an operator is how many of the critical hexagons were **also confirmed by a Cloudflare outage** — these are the highest-certainty maintenance targets. This sub-task replaces the Duração card with a "Confirmados Cloudflare" card computed from `data.results`.

### Expected Outcomes
- The third KPI card label is "Confirmados Cloudflare".
- Its value is the count of results where `cloudflare_outage_overlap === 1`.
- Its `sub` line shows the percentage of critical hexagons confirmed (e.g. "23% dos críticos").
- Its `valueColor` is `"text-orange-400"` to distinguish from the red critical count.
- The run ID / duration are no longer shown in the KPI cards (they are available in the audit log).

### Todo List
1. Open `frontend/src/pages/Axis1Page.tsx`.
2. In the KPI cards grid, compute `const nCloudflare = data.results.filter(r => r.cloudflare_outage_overlap === 1).length` before the JSX.
3. Replace the third `<KpiCard>` (currently "Duração") with one that shows `nCloudflare`, with `sub` showing the percentage of critical hexagons it represents, and `valueColor="text-orange-400"`.

### Relevant Context
- **KPI cards block:** `frontend/src/pages/Axis1Page.tsx` lines 97–101
- **`KpiCard` props:** `label`, `value`, `sub?`, `valueColor?` — defined in `frontend/src/components/KpiCard.tsx`
- **`cloudflare_outage_overlap`:** available on every `Axis1HexagonResult` as `0` or `1`

---

## Execution Order

Sub-Tasks 1 and 3 both touch backend files and can be done in the same pass.
Sub-Task 2 depends on Sub-Task 1 (needs the new response field).
Sub-Tasks 4 and 5 depend on Sub-Task 3 (need the new result fields), but can be done together since they are both in `Axis1Page.tsx`.
