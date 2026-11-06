# Plan: Axis 2 & Axis 3 UX Improvements — Parity with Axis 1 Enhancements

## Overview

Axis 1 received three classes of UX improvements (per `axis1-ux-improvements-plan.md`):
1. A **resolution warning banner** — the backend signals when the selected resolution is unavailable, and the frontend renders an info banner.
2. **KPI card business-focus** — the developer "Duração" KPI was replaced with a high-signal business metric.
3. **Informative results table** — columns were redesigned for actionability: place names, severity badges, color-coded scores, and visually prominent confirmation markers.

This plan applies the same three improvement classes to **Axis 2 (Oportunidades de Expansão)** and **Axis 3 (Segmentação de Mercado)**, adapting each to its own domain semantics. Additionally, Axis 3 gains a **HexMap** panel (it currently has none) mirroring the geographic visualization already present in Axis 1 and Axis 2.

No new features beyond the parity scope are introduced.

---

## Gap Analysis

### Axis 2 Current State vs Axis 1 Improvements

| Improvement Class | Axis 1 | Axis 2 |
|---|---|---|
| Resolution warning banner | ✅ done | ❌ missing |
| Business-focused third KPI card | ✅ "Confirmados Cloudflare" | ❌ still "Duração" |
| Informative results table | ✅ redesigned | ❌ headers are cryptic ("Vel↓ Mbps", "Domic.", "HHI"); no TAM quality tier; no fallback coords in location cell |

> Note: `place_name` is already wired into `Axis2ClusterSummary` (both backend and frontend), so Sub-Task 3 equivalent is already done for Axis 2.

### Axis 3 Current State vs Axis 1 Improvements

| Improvement Class | Axis 1 | Axis 3 |
|---|---|---|
| Resolution warning banner | ✅ done | ❌ missing |
| Business-focused third KPI card | ✅ metric that matters | ❌ third card shows `sub="Duração: Xs"` instead of a business metric |
| Informative results table | ✅ redesigned | ❌ `SegmentTable` lacks silhouette quality badge, segment size share bar, and domain feature columns |
| HexMap geographic panel | ✅ present | ❌ entirely absent |
| `place_name` in results | ✅ done | ❌ `Axis3SegmentProfile` and `Axis3HexagonResult` have no `place_name` |

---

## Sub-Task A1 — Axis 2 Frontend: resolution warning banner

**Status:** `[x] done`

### Intent
`Axis2RunResponse` does not currently include a `resolution_warning` field (Axis 1's Sub-Task 1 wired this only into `Axis1RunResponse`). The backend `run_axis2` call already uses `gold_df, _ = _load_gold(...)` and discards the warning. This sub-task exposes the warning through the Axis 2 response so the frontend can display it.

### Expected Outcomes
- `Axis2RunResponse` in `api/schemas.py` gains `resolution_warning: Optional[str] = None`.
- In `run_axis2` (`api/routes/tools.py`), the discarded `_` from `_load_gold` is captured and passed into `Axis2RunResponse(resolution_warning=...)`.
- `Axis2RunResponse` TypeScript interface in `frontend/src/types.ts` gains `resolution_warning?: string | null`.
- `Axis2Page.tsx` renders the same yellow info banner pattern as `Axis1Page.tsx` (lines 120–124) above the KPI cards when `data.resolution_warning` is truthy.

### Todo List
1. Open `api/schemas.py`. Add `resolution_warning: Optional[str] = None` to `Axis2RunResponse`.
2. Open `api/routes/tools.py`. In `run_axis2`, change `gold_df, _ = _load_gold(...)` to `gold_df, res_warning = _load_gold(...)`. Pass `resolution_warning=res_warning` to `Axis2RunResponse(...)`.
3. Open `frontend/src/types.ts`. Add `resolution_warning?: string | null` to `Axis2RunResponse`.
4. Open `frontend/src/pages/Axis2Page.tsx`. Inside the `{data ? (...)}` block, before the KPI cards grid, add the conditional yellow banner (copy the same pattern from `Axis1Page.tsx` lines 120–124).

### Relevant Context
- **Schema:** `api/schemas.py` lines 206–215 (`Axis2RunResponse`)
- **Route handler:** `api/routes/tools.py` line 652 (discards warning with `_`), line 746–753 (builds response)
- **TS types:** `frontend/src/types.ts` lines 103–111 (`Axis2RunResponse`)
- **Frontend page:** `frontend/src/pages/Axis2Page.tsx` lines 94–114 (results panel)
- **Reference banner pattern:** `frontend/src/pages/Axis1Page.tsx` lines 120–124

---

## Sub-Task A2 — Axis 2 Frontend: replace "Duração" KPI with a business metric

**Status:** `[x] done`

### Intent
The third KPI card on Axis 2 shows `label="Duração"` with run_id as `sub`. This is a developer metric. The most actionable business number for an expansion analyst is the **total TAM (Mercado Endereçável Total)** across all real clusters — the sum of `tam_estimate` values for non-noise clusters. This replaces the duration card and gives the analyst an immediate sense of the aggregate addressable market identified.

### Expected Outcomes
- The third KPI card label is `"TAM Total Estimado"`.
- Its value is the sum of `tam_estimate` across all non-noise clusters, formatted as `fmtBrl(total)`.
- Its `sub` shows the count of real clusters (e.g. `"3 clusters encontrados"`).
- Its `valueColor` is `"text-ind-accent"` (matches the per-cluster TAM color already used in the table).
- Duration / run_id are no longer shown in the KPI cards.

### Todo List
1. Open `frontend/src/pages/Axis2Page.tsx`.
2. Before the JSX in the results block, compute `const totalTam = data.clusters.filter(c => c.is_noise === 0).reduce((s, c) => s + (c.tam_estimate ?? 0), 0)`.
3. Replace the third `<KpiCard>` (currently "Duração") with one that shows `fmtBrl(totalTam)`, `sub` showing cluster count, and `valueColor="text-ind-accent"`.

### Relevant Context
- **KPI cards block:** `frontend/src/pages/Axis2Page.tsx` lines 96–100
- **`fmtBrl` helper:** `Axis2Page.tsx` lines 10–11 — already formats numbers as BRL currency
- **`is_noise` field:** available on every `Axis2ClusterSummary` as `0` or `1`
- **`tam_estimate` field:** `Axis2ClusterSummary.tam_estimate: number | null`
- **`KpiCard` props:** `label`, `value`, `sub?`, `valueColor?`

---

## Sub-Task A3 — Axis 2 Frontend: redesign ClusterTable for clarity

**Status:** `[x] done`

### Intent
The current `ClusterTable` has 6 columns: "Cluster" (good, has `place_name`), "Hexágonos" (clear), "Vel↓ Mbps" (cryptic — reversed arrow, no unit context), "Domic." (truncated), "HHI" (acronym, unexplained), "TAM" (acronym). Column headers should be self-explanatory for business users. The location cell should also fall back to coordinates when `place_name` is null (currently it just shows nothing if null). Additionally, a visual TAM tier badge should distinguish high-TAM clusters from low ones.

### Expected Outcomes
The redesigned `ClusterTable` has these 6 columns with renamed, self-explanatory headers:

| Old Header | New Header | Notes |
|---|---|---|
| Cluster | Cluster | Keep — already shows `place_name` + cluster ID |
| Hexágonos | Hexágonos | Keep |
| Vel↓ Mbps | Veloc. Download (Mbps) | Rename for clarity |
| Domic. | Domicílios | Expand abbreviation |
| HHI | Concentração (HHI) | Add context word |
| TAM | TAM Estimado | Expand abbreviation; add tier badge |

Location cell improvement: when `place_name` is null, fall back to showing coordinates as a secondary line (matching the `Axis1Page` Localização cell pattern).

TAM tier badge: `≥ 1 000 000` → "Alto" (green/accent), `≥ 100 000` → "Médio" (yellow), otherwise no badge.

### Todo List
1. Open `frontend/src/pages/Axis2Page.tsx`.
2. Replace the `headers` array: `['Cluster', 'Hexágonos', 'Veloc. Download (Mbps)', 'Domicílios', 'Concentração (HHI)', 'TAM Estimado']`.
3. In the location cell (currently the `<td>` for cluster): when `c.place_name` is null, render coordinates `c.lat_centroid.toFixed(4), c.lon_centroid.toFixed(4)` as a secondary muted line instead of showing nothing.
4. In the TAM cell: add a helper `tamBadge(v)` that returns a small badge span when `v >= 1_000_000` ("Alto", green) or `v >= 100_000` ("Médio", yellow), and `null` otherwise. Render it alongside the formatted TAM value.

### Relevant Context
- **`ClusterTable` component:** `frontend/src/pages/Axis2Page.tsx` lines 13–44
- **Location cell pattern for null `place_name`:** `frontend/src/pages/Axis1Page.tsx` lines 41–43
- **Existing `fmtBrl` helper:** `Axis2Page.tsx` lines 10–11

---

## Sub-Task B1 — Axis 3 Backend: add `place_name` to segment profiles and hexagon results

**Status:** `[x] done`

### Intent
Axis 3 segment profiles and hexagon-level results have no geographic anchor — no `place_name`. For segment profiles, the centroid of the segment (mean lat/lon across all member hexagons) can be reverse-geocoded to give the analyst a sense of which geography each segment represents. For hexagon results, each hexagon already has `lat_centroid`/`lon_centroid` from `_h3_centroid`, so `_reverse_geocode` can be called the same way as in Axis 1.

However, since Axis 3 can have thousands of hexagon results, calling `_reverse_geocode` per hexagon would be too slow. The practical approach is to add `place_name` only to `Axis3SegmentProfile` (one call per segment, negligible cost), not to every `Axis3HexagonResult`.

### Expected Outcomes
- `Axis3SegmentProfile` in `api/schemas.py` gains `place_name: Optional[str] = None`.
- In `run_axis3`, the segment-profile building loop computes the mean lat/lon for each segment from `result_df`, calls `_reverse_geocode(lat, lon)`, and sets `place_name`.
- `Axis3SegmentProfile` TypeScript interface gains `place_name?: string | null`.

### Todo List
1. Open `api/schemas.py`. Add `place_name: Optional[str] = None` to `Axis3SegmentProfile`.
2. Open `api/routes/tools.py`. In the segment-profile building loop (`run_axis3`, around lines 822–840):
   - For each `seg_id`, after computing `count`, compute `seg_lats = seg_df["h3_id"].apply(lambda x: _h3_centroid(x)[0])` and `seg_lons = seg_df["h3_id"].apply(lambda x: _h3_centroid(x)[1])`.
   - Call `place = _reverse_geocode(float(seg_lats.mean()), float(seg_lons.mean()))`.
   - Pass `place_name=place` to `Axis3SegmentProfile(...)`.
3. Open `frontend/src/types.ts`. Add `place_name?: string | null` to `Axis3SegmentProfile`.

### Relevant Context
- **`Axis3SegmentProfile` schema:** `api/schemas.py` lines 233–241
- **Segment profile loop:** `api/routes/tools.py` lines 821–840
- **`_h3_centroid` helper:** `api/routes/tools.py` lines 143–151
- **`_reverse_geocode` helper:** `api/routes/tools.py` lines 153–198 (already used by Axis 1 and Axis 2)
- **TypeScript type:** `frontend/src/types.ts` lines 119–126

---

## Sub-Task B2 — Axis 3 Frontend: add resolution warning banner

**Status:** `[x] done`

### Intent
Same as Sub-Task A1 but for Axis 3. The `run_axis3` handler already discards the warning from `_load_gold`. This sub-task exposes it and shows it in the UI.

### Expected Outcomes
- `Axis3RunResponse` in `api/schemas.py` gains `resolution_warning: Optional[str] = None`.
- In `run_axis3` (`api/routes/tools.py`), the discarded `_` from `_load_gold` is captured and passed into `Axis3RunResponse(resolution_warning=...)`.
- `Axis3RunResponse` TypeScript interface gains `resolution_warning?: string | null`.
- `Axis3Page.tsx` renders the same yellow banner above the KPI cards when `data.resolution_warning` is truthy.

### Todo List
1. Open `api/schemas.py`. Add `resolution_warning: Optional[str] = None` to `Axis3RunResponse`.
2. Open `api/routes/tools.py`. In `run_axis3`, change `gold_df, _ = _load_gold(...)` to `gold_df, res_warning = _load_gold(...)`. Pass `resolution_warning=res_warning` to `Axis3RunResponse(...)`.
3. Open `frontend/src/types.ts`. Add `resolution_warning?: string | null` to `Axis3RunResponse`.
4. Open `frontend/src/pages/Axis3Page.tsx`. Before the KPI cards grid, add the conditional yellow banner when `data.resolution_warning` is truthy (same pattern as Axis1Page).

### Relevant Context
- **Schema:** `api/schemas.py` lines 256–266 (`Axis3RunResponse`)
- **Route handler:** `api/routes/tools.py` line 783 (discards warning with `_`), lines 904–912 (builds response)
- **TS types:** `frontend/src/types.ts` lines 138–147 (`Axis3RunResponse`)
- **Frontend page:** `frontend/src/pages/Axis3Page.tsx` lines 84–101 (results panel)
- **Reference banner pattern:** `frontend/src/pages/Axis1Page.tsx` lines 120–124

---

## Sub-Task B3 — Axis 3 Frontend: replace "Duração" sub with a quality KPI and add HexMap

**Status:** `[x] done`

### Intent
The third KPI card on Axis 3 shows `label="Silhouette Global"` — which is useful, but its `sub` shows `"Duração: Xs"`. Replace the `sub` with a meaningful quality label: "Boa separação" when `≥ 0.50`, "Separação razoável" when `≥ 0.30`, or "Sobreposição detectada" when `< 0.30`. Duration is removed.

Additionally, Axis 3 has no HexMap panel. All hexagon-level results have lat/lon coordinates and a `segment_id`. A map panel should be added so the analyst can see the geographic distribution of market segments — matching the pattern already present in Axis 1 and Axis 2.

### Expected Outcomes
- The third KPI card `sub` shows a silhouette quality label instead of duration.
- A new `HexMap` panel appears below the pie chart with `axis3Results={data.results}` (or the appropriate prop — confirm with `HexMap` component props).
- Duration is no longer shown in the KPI cards.

### Todo List
1. Open `frontend/src/pages/Axis3Page.tsx`.
2. In the KPI cards block (lines 86–90), replace the third card's `sub` value: compute a quality string from `data.silhouette_score_global` and display it as the `sub` prop. Remove duration from `sub`.
3. Import `HexMap` from `'../components/HexMap'` (it is not currently imported in `Axis3Page.tsx`).
4. After the existing pie chart `<div>` block, add a new `<div>` panel (same `bg-ind-surface border border-ind-border rounded-lg p-4` container) with label `"Mapa — Segmentos de Mercado"` and `<HexMap axis3Results={data.results} height="260px" />`.

### Relevant Context
- **KPI cards block:** `frontend/src/pages/Axis3Page.tsx` lines 86–90
- **HexMap component:** `frontend/src/components/HexMap.tsx` — prop `axis3Results?: Axis3HexagonResult[]` confirmed at line 19; renders green markers per hexagon with segment name in popup (lines 92–107); legend entry at lines 125–130. No changes to `HexMap.tsx` are needed.
- **Axis 2 HexMap panel (reference pattern):** `frontend/src/pages/Axis2Page.tsx` lines 105–108
- **`Axis3HexagonResult` type:** `frontend/src/types.ts` lines 128–136

---

## Sub-Task B4 — Axis 3 Frontend: redesign SegmentTable for clarity and business value

**Status:** `[x] done`

### Intent
The current `SegmentTable` shows 5 columns: "Seg." (ID only), "Nome", "Hexágonos", "% Total", "Silhouette Médio". It lacks geographic context (no `place_name`), no visual quality tier for the silhouette score, and the raw silhouette float is not self-explanatory to a business user. This sub-task redesigns the table to show place name alongside the segment name, adds a silhouette quality badge, and makes the segment size visually clear.

### Expected Outcomes
The redesigned `SegmentTable` has 5 columns (same count, richer content):

| Column | What it shows | Notes |
|---|---|---|
| **Segmento** | Segment ID badge + segment name; `place_name` as secondary line | Falls back to coordinates when `place_name` is null |
| **Hexágonos** | Count, localised | Unchanged |
| **% do Total** | Fraction as percentage | Unchanged |
| **Qualidade (Silhouette)** | Float + quality badge | `≥ 0.50` → "Boa" (green), `≥ 0.30` → "Razoável" (yellow), `< 0.30` → "Fraca" (red) |
| **Distância ao Centróide** | `avg_centroid_distance.toFixed(3)` | Renamed from nothing (was not previously shown); replaces the raw float |

### Todo List
1. Open `frontend/src/pages/Axis3Page.tsx`.
2. Add a `silhouetteBadge(score: number | null)` helper function at the top of the file (similar to `severityBadge` in Axis 1) that returns a small coloured badge span.
3. Replace the column headers array with: `['Segmento', 'Hexágonos', '% do Total', 'Qualidade (Silhouette)', 'Distância ao Centróide']`.
4. Rewrite the row rendering:
   - **Segmento cell:** render a small `S{s.segment_id}` badge (styled with `text-ind-segment font-mono font-semibold`), the `segment_name` beside or below it, and `place_name` as a secondary muted line below both when present.
   - **Hexágonos cell:** unchanged.
   - **% do Total cell:** unchanged.
   - **Qualidade cell:** show `s.avg_silhouette?.toFixed(3) ?? '—'` followed by `silhouetteBadge(s.avg_silhouette)`.
   - **Distância cell:** show `s.avg_centroid_distance.toFixed(3)`.

### Relevant Context
- **`SegmentTable` component:** `frontend/src/pages/Axis3Page.tsx` lines 9–34
- **`place_name` field:** added by Sub-Task B1; available as `s.place_name`
- **Reference badge pattern:** `frontend/src/pages/Axis1Page.tsx` lines 9–13 (`severityBadge`)
- **`Axis3SegmentProfile` type:** `frontend/src/types.ts` lines 119–126

---

## Execution Order

```
Sub-Tasks A1, A2, A3 are independent frontend-only changes for Axis 2.
  A1 also touches the backend schema + route (minor — add field, capture variable).
  A2 and A3 are pure frontend changes.

Sub-Task B1 is a backend change (schema + route) that B4 depends on (place_name).
Sub-Tasks B2 and B3 are independent of B1.
Sub-Task B4 depends on B1 (needs place_name in segment profiles).

Recommended pass order:
  Pass 1: A1 + B1 + B2 (all backend schema/route changes, do together)
  Pass 2: A2 + A3 + B3 (all remaining frontend changes)
  Pass 3: B4 (depends on B1 being done)
```

### Dependency Map

```
A1 (backend field) ──► A1 (frontend banner)
B1 (backend field) ──► B4 (redesigned table with place_name)
B2 (backend field) ──► B2 (frontend banner)
A2, A3, B3 ──► no backend dependencies (pure frontend)
```
