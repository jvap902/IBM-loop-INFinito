# Plan: Fix "Manutenção Necessária" Tab

## Overview

The "Manutenção Necessária" tab (Axis 1) has two distinct bugs:

1. **Sliders allow out-of-range values** — The `contamination` and `anomaly_threshold` sliders expose ranges that the ML pipeline's `validate_output()` will reject. The pipeline enforces that the resulting anomaly rate must be between 1% and 15%. `contamination` directly controls that rate (it tells IsolationForest what fraction to flag), so its safe UI range is [0.01, 0.15] — matching `ANOMALY_RATE_MIN`/`ANOMALY_RATE_MAX`. The Pydantic schema currently allows up to 0.5 and must be tightened too. `anomaly_threshold` is a secondary cutoff that can only reduce critical counts; its safe operational range is [0.30, 0.90]. The fix narrows both sliders and updates the Pydantic upper bound for `contamination`, and updates hint text to explain the constraint.

2. **Region filter only accepts raw H3 hex codes** — The UI placeholder and hint suggest hex IDs like `85283473fffffff`, and the backend passes the raw strings directly to `_load_gold()` which treats them as literal H3 cell IDs. The `resolve_region()` utility already exists in `agent/region_resolver.py` and can map state codes (`SP`, `BR-SP`), full state names (`São Paulo`), and macro-region names (`Sudeste`) to H3 cell lists — but it is never called in the Axis 1 handler. The fix wires this utility into the `run_axis1` route and updates the frontend hint and placeholder.

---

## Sub-Task 1 — Constrain slider ranges to safe operational values

**Status:** `[x] done`

### Intent
The `contamination` and `anomaly_threshold` sliders currently expose ranges that will cause the ML pipeline to reject the run with a HTTP 422 error. `contamination` directly maps to the anomaly rate, so its safe range is exactly [0.01, 0.15] (the pipeline's `ANOMALY_RATE_MIN`/`ANOMALY_RATE_MAX`). The Pydantic schema must also be tightened to match, so the API and the UI enforce the same constraint. `anomaly_threshold` is a secondary score cutoff; its safe operational range is [0.30, 0.90], covering the EDA-confirmed default of 0.65 and all realistic values. Hint text on both sliders should be updated to explain what the parameter does and why the range is bounded.

### Expected Outcomes
- The `contamination` slider in `Axis1Page.tsx` has `min=0.01`, `max=0.15` (was `max=0.5`).
- The `anomaly_threshold` slider has `min=0.30`, `max=0.90` (was `min=0`, `max=1`).
- The `contamination` field in `Axis1RunRequest` in `api/schemas.py` has `le=0.15` (was `le=0.5`).
- Hint text on both sliders clearly explains the operational constraint.
- Default values are unchanged (contamination=0.05, anomaly_threshold=0.65).

### Todo List
1. Open `frontend/src/pages/Axis1Page.tsx`.
2. Change the `contamination` `<Slider>` `max` prop from `0.5` to `0.15`.
3. Change the `anomaly_threshold` `<Slider>` `min` prop from `0` to `0.30`.
4. Change the `anomaly_threshold` `<Slider>` `max` prop from `1` to `0.90`.
5. Update the `hint` prop of the `contamination` `FormField` to explain the range: _"Fração esperada de anomalias pelo IsolationForest. Limitado a 15% para garantir que o modelo opere dentro do intervalo validado."_
6. Update the `hint` prop of the `anomaly_threshold` `FormField` to explain the range: _"Score ≥ threshold → hexágono crítico. Faixa operacional validada: 0.30–0.90. Padrão confirmado pela EDA: 0.65."_
7. Open `api/schemas.py`.
8. In `Axis1RunRequest`, change the `contamination` field's `le=0.5` to `le=0.15`.

### Relevant Context
- **Slider file:** `frontend/src/pages/Axis1Page.tsx` lines 78–83
- **Schema file:** `api/schemas.py` lines 92–99 (`contamination` field in `Axis1RunRequest`)
- **Pipeline constants:** `ANOMALY_RATE_MIN = 0.01`, `ANOMALY_RATE_MAX = 0.15` in `ml/pipelines/pipeline_axis1.py` lines 46–47
- **Error raised by:** `validate_output()` in `ml/pipelines/pipeline_axis1.py` lines 82–87
- **Pydantic also validates `contamination` on inbound requests:** `api/schemas.py` line 95 (`ge=0.01`) — the lower bound is already correct, only the upper bound (`le`) needs updating

---

## Sub-Task 2 — Wire `resolve_region()` into the Axis 1 backend handler

**Status:** `[x] done`

### Intent
The `run_axis1` handler currently passes `body.region_filter` (a raw `list[str]`) directly to `_load_gold()`, which expects H3 cell IDs. The `resolve_region()` function in `agent/region_resolver.py` already converts human-readable region strings (state codes, state names, macro-regions, or raw H3 IDs) to H3 res-5 cell lists. This sub-task inserts the translation step so the endpoint accepts any of those formats.

### Expected Outcomes
- `POST /tools/axis1/run` with `region_filter: ["SP"]` works correctly and filters to São Paulo.
- `POST /tools/axis1/run` with `region_filter: ["Sudeste"]` works correctly.
- Raw H3 IDs continue to work unchanged.
- An invalid string (e.g. `["XYZZY"]`) returns a clear HTTP 400 error instead of silently producing empty results.

### Todo List
1. Open `api/routes/tools.py`.
2. Import `resolve_region` from `agent.region_resolver` at the top of the file.
3. In the `run_axis1` handler, before the `_load_gold()` call, add a translation step:
   - For each string in `body.region_filter`, call `resolve_region(s)`.
   - Collect the resulting H3 cell lists, flatten and deduplicate them into a single `list[str]`.
   - If `resolve_region` raises a `ValueError` for any entry, catch it and re-raise as `HTTPException(status_code=400, detail=...)`.
   - Pass the resolved H3 list to `_load_gold()` instead of the raw `body.region_filter`.
4. If `body.region_filter` is `None`, skip the step and pass `None` to `_load_gold()` as before.

### Relevant Context
- **Handler file:** `api/routes/tools.py` lines 267–281 (the `run_axis1` function preamble and `_load_gold` call at line 281)
- **Resolver:** `agent/region_resolver.py` — `resolve_region(region_str: str) -> Optional[list[str]]`; returns `None` for `"all"` or empty, `[region_str]` for a valid H3 ID, or a sorted list of H3 res-5 cell IDs for named regions; raises `ValueError` for unknown inputs
- **`_load_gold` signature:** `_load_gold(region_filter: Optional[list[str]], h3_resolution: int)` — expects H3 cell IDs

---

## Sub-Task 3 — Update the frontend region filter UI

**Status:** `[x] done`

### Intent
The `TextInput` placeholder (`Ex.: 85283473fffffff`) and the form field hint for the region filter suggest only hex codes are accepted. After Sub-Task 2 enables human-readable input on the backend, this sub-task updates the UI copy to tell users what formats are supported.

### Expected Outcomes
- The placeholder shows a human-readable example (e.g. `Ex.: SP, Sudeste`).
- The hint text lists the accepted formats: state codes, full state names, macro-region names, and (for advanced users) raw H3 cell IDs.
- The `monospace` font styling on the `TextInput` is removed, since the field no longer primarily expects hex codes.

### Todo List
1. Open `frontend/src/pages/Axis1Page.tsx`.
2. Update the `hint` prop of the region filter `FormField` to explain the accepted formats:
   _"Use um código de estado (ex: SP), nome completo (ex: São Paulo), macro-região (ex: Sudeste) ou deixe em branco para o Brasil todo."_
3. Update the `placeholder` prop of `TextInput` from `"Ex.: 85283473fffffff"` to `"Ex.: SP, Sudeste"`.
4. Remove the `monospace` prop from the `TextInput` component call.

### Relevant Context
- **File:** `frontend/src/pages/Axis1Page.tsx` lines 72–73
- **`TextInput` component:** `frontend/src/components/AxisForm.tsx` — accepts `monospace?: boolean`
- **Accepted formats (from `resolve_region`):** UF codes (`SP`, `BR-SP`), full state names (`São Paulo`), macro-regions (`Sudeste`, `Norte`, `Nordeste`, `Centro-Oeste`, `Sul`), or raw H3 IDs

---

## Execution Order

Sub-Task 1 is fully independent and can be done at any time.
Sub-Task 2 must be completed before Sub-Task 3 is meaningful (the UI change should reflect working backend capability).
Sub-Task 3 follows Sub-Task 2.
