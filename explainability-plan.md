# Explainability & Traceability Plan

## Top-Level Overview

**Goal:** Make the agent's decisions fully transparent to the user — showing where the data came from, which features drove each ML model's output, and the step-by-step reasoning the agent followed to reach its conclusions.

**Scope:** Three complementary improvements are delivered together:
1. **Sources Footer** — each chat message gains a collapsible "Fontes usadas" section listing which report sections and exact data values were included in the LLM context.
2. **SHAP Feature Explanations in Report & Chat** — SHAP/Z-score feature importance data (already computed and logged to the audit trail) is surfaced in the `AgentRunResponse`, stored in the frontend, and injected into the LLM chat context. A new `ShapBarChart` component renders it visually.
3. **Rastreabilidade Page** — a new dedicated sidebar page (`/rastreabilidade`) shows the full reasoning trail for the current run: agent reasoning steps, tool calls with their inputs/outputs, and SHAP explanations per axis.

**Approach:** Progressive disclosure — every piece of traceability data is collapsed by default; the user expands only what they want. The chat stays clean; the detail lives one click away.

**Constraint:** All new UI text must be in Portuguese.

---

## Architecture Summary

```
Backend Changes
├── api/schemas.py
│   └── Add ExplanationsBlock (SHAP payloads for all 3 axes)
│   └── Extend AgentRunResponse with explanations: ExplanationsBlock | None
│   └── Extend AgentChatResponse with sources: list[SourceItem]
│
├── api/routes/agent.py
│   └── After building response: fetch audit events for run_id
│   └── Extract explanation payloads from tool_call events
│   └── Populate ExplanationsBlock and attach to response
│
└── api/routes/chat.py
    └── Inject SHAP top-features into LLM context string
    └── Compute sources list from report_context
    └── Return sources in AgentChatResponse

Frontend Changes
├── frontend/src/types.ts
│   └── Add ExplanationsBlock, ShapFeature, SourceItem types
│   └── Extend AgentRunResponse with explanations
│   └── Extend AgentChatResponse with sources
│
├── frontend/src/stores/reportStore.ts
│   └── Store already holds full AgentRunResponse — no change needed
│
├── frontend/src/components/ShapBarChart.tsx  [NEW]
│   └── Recharts BarChart showing top features with SHAP values
│
├── frontend/src/components/AgentChatDrawer.tsx
│   └── Each assistant message gets a collapsible "Fontes usadas" footer
│
├── frontend/src/pages/RastreabilidadePage.tsx  [NEW]
│   └── Full reasoning trail: reasoning steps, tool calls, SHAP per axis
│   └── Reuses ShapBarChart for each axis
│   └── Link from AgentChatDrawer header
│
├── frontend/src/components/Sidebar.tsx
│   └── Add "/rastreabilidade" nav entry
│
└── frontend/src/main.tsx
    └── Register /rastreabilidade route
```

---

## Sub-Tasks

---

### Sub-Task 1 — Backend: Add `ExplanationsBlock` and extend `AgentRunResponse`

**Intent:**
The SHAP/Z-score explanation data is already computed per axis in `api/routes/tools.py` and logged to the audit trail (`logs/audit.jsonl`). Currently it never reaches the frontend. This sub-task makes `AgentRunResponse` carry the explanation payloads so the frontend can display them without making a separate audit query per page load.

**Expected Outcomes:**
- `api/schemas.py` has a new `ExplanationsBlock` Pydantic model with fields `axis1`, `axis2`, `axis3`, each holding the raw explanation dict (typed as `dict | None`).
- `AgentRunResponse` has a new optional field `explanations: ExplanationsBlock | None = None`.
- `api/routes/agent.py` after building the run response: reads the audit log for the current `run_id`, finds the three `tool_call` events for `axis1_run`, `axis2_run`, `axis3_run`, extracts their `explanation` fields, and populates `ExplanationsBlock`.
- Running a full agent analysis and calling `POST /v1/agent/run` returns the response with `explanations.axis1`, `explanations.axis2`, `explanations.axis3` populated.
- No change to the tools pipeline — explanations are already computed; this is a read-and-forward operation.

**Todo List:**
1. In `api/schemas.py`: define `ExplanationsBlock(BaseModel)` with fields `axis1: dict | None`, `axis2: dict | None`, `axis3: dict | None`.
2. In `api/schemas.py`: add `explanations: ExplanationsBlock | None = None` to `AgentRunResponse`.
3. In `api/routes/agent.py`: after `final_state` is obtained, call `get_audit_logger().read_events(run_id=run_id, event_type="tool_call", limit=10)`.
4. In `api/routes/agent.py`: iterate the events, match `tool_name` to `axis1_run`, `axis2_run`, `axis3_run`, and extract the `explanation` field from each.
5. In `api/routes/agent.py`: construct `ExplanationsBlock` and set `response.explanations = block`.
6. Verify the response JSON includes the `explanations` key with SHAP data by running a test analysis.

**Relevant Context:**
- `api/schemas.py` — `AgentRunResponse` at line ~200, `InterpretationsBlock` at lines 291-309 (use as structural reference).
- `api/routes/agent.py` — response construction at lines 201-213.
- `audit/logger.py` — `read_events()` method at lines 283-355; filter by `run_id` and `event_type="tool_call"`.
- `audit/schema.py` — `AuditEvent.explanation` field at line 106.
- `logs/audit.jsonl` — sample explanation payload structure: `{ status, method, top_features: [{feature, shap_value}], global_importance }` for axes 1/3; `{ status, method, clusters: { "0": { top_features: [{feature, z_score, cluster_mean, global_mean}] } } }` for axis 2.

**Status:** [x] done

---

### Sub-Task 2 — Backend: Extend `AgentChatResponse` with `sources` and inject SHAP into LLM context

**Intent:**
Each chat answer the LLM generates is based on a subset of the report context. This sub-task makes the backend (a) tell the frontend exactly which sections and data values were included in the prompt, and (b) inject the SHAP top-features into that context so the LLM can reference them when explaining model decisions.

**Expected Outcomes:**
- `api/schemas.py` has a new `SourceItem` model with fields `section: str` (label like "Eixo 2 — Expansão") and `values: list[str]` (key data points like "13 clusters, TAM total R$ 4.2M").
- `AgentChatResponse` has a new field `sources: list[SourceItem] = []`.
- `api/routes/chat.py` `_build_context()` is extended to also inject SHAP top-features per axis from `report_context` (which now includes the `explanations` block from Sub-Task 1).
- `api/routes/chat.py` route handler computes a `sources` list from the same report data and returns it in the response.
- Calling `POST /v1/agent/chat` returns `{ answer, is_stub, sources: [...] }`.

**Todo List:**
1. In `api/schemas.py`: define `SourceItem(BaseModel)` with `section: str` and `values: list[str]`.
2. In `api/schemas.py`: add `sources: list[SourceItem] = []` to `AgentChatResponse`.
3. In `api/routes/chat.py`: extend `_build_context()` to read `report_context.get("explanations")` and, for each axis with a valid explanation, append a section like `"=== SHAP — EIXO 1 (features que mais contribuíram para anomalias) ==="` followed by the top 3 features.
4. In `api/routes/chat.py`: define a `_build_sources(report: dict) -> list[SourceItem]` helper that inspects the same report dict and returns one `SourceItem` per non-empty section used (region, axes, axis 1 summary, axis 2 clusters, axis 3 segments, hypotheses, SHAP features). Each item carries 2-3 key data values as strings.
5. In `api/routes/chat.py`: call `_build_sources()` and attach result to `AgentChatResponse`.
6. Verify the response includes `sources` with correct section labels and values for a real run.

**Relevant Context:**
- `api/schemas.py` — `AgentChatResponse` currently at lines 59-65; add `sources` field.
- `api/routes/chat.py` — `_build_context()` at lines 103-190; `agent_chat` route at lines 195-259.
- `frontend/src/api/chatApi.ts` — `AgentChatResponse` interface (line 9-12) must be updated in Sub-Task 4 to add `sources`.
- The `report_context` dict sent from the frontend (`AgentChatDrawer.tsx` lines 97-108) already includes `axis1_summary`, `axis2_summary`, `axis3_summary` — add `explanations` to that list in Sub-Task 4.

**Status:** [x] done

---

### Sub-Task 3 — Frontend: Add TypeScript types for `ExplanationsBlock`, `SourceItem`, and updated responses

**Intent:**
Before building any UI components, all new shapes returned by the backend must be typed in `frontend/src/types.ts` and `frontend/src/api/chatApi.ts`. This sub-task has no visual output but is the foundation every subsequent sub-task depends on.

**Expected Outcomes:**
- `frontend/src/types.ts` has `ShapFeature`, `ShapAxis1Explanation`, `ShapAxis2Explanation`, `ShapAxis3Explanation`, and `ExplanationsBlock` interfaces.
- `AgentRunResponse` in `types.ts` has `explanations?: ExplanationsBlock | null`.
- `frontend/src/api/chatApi.ts` has a `SourceItem` interface and `AgentChatResponse` is extended with `sources?: SourceItem[]`.
- The `ChatMessage` interface in `chatApi.ts` gains an optional `sources?: SourceItem[]` field so the drawer can store sources per assistant message.

**Todo List:**
1. In `frontend/src/types.ts`: add `ShapFeature` interface: `{ feature: string; shap_value: number }`.
2. In `frontend/src/types.ts`: add `ShapClusterFeature` interface: `{ feature: string; z_score: number; cluster_mean: number; global_mean: number }`.
3. In `frontend/src/types.ts`: add `ShapAxis1Explanation`: `{ status: string; method: string; n_explained: number; top_features: ShapFeature[]; global_importance: Record<string, number> }`.
4. In `frontend/src/types.ts`: add `ShapAxis2Explanation`: `{ status: string; method: string; n_clusters_explained: number; clusters: Record<string, { cluster_id: number; n_hexagons: number; top_features: ShapClusterFeature[] }> }`.
5. In `frontend/src/types.ts`: add `ShapAxis3Explanation`: `{ status: string; method: string; n_explained: number; segments: Record<string, { segment_id: number; n_samples_explained: number; top_features: ShapFeature[] }> }`.
6. In `frontend/src/types.ts`: add `ExplanationsBlock`: `{ axis1?: ShapAxis1Explanation | null; axis2?: ShapAxis2Explanation | null; axis3?: ShapAxis3Explanation | null }`.
7. In `frontend/src/types.ts`: add `explanations?: ExplanationsBlock | null` to `AgentRunResponse`.
8. In `frontend/src/api/chatApi.ts`: add `SourceItem` interface: `{ section: string; values: string[] }`.
9. In `frontend/src/api/chatApi.ts`: add `sources?: SourceItem[]` to `AgentChatResponse`.
10. In `frontend/src/api/chatApi.ts`: add `sources?: SourceItem[]` to `ChatMessage`.

**Relevant Context:**
- `frontend/src/types.ts` — full file; `AgentRunResponse` at lines 45-57.
- `frontend/src/api/chatApi.ts` — `ChatMessage` at lines 3-7, `AgentChatResponse` at lines 9-12.
- `logs/audit.jsonl` — actual SHAP payload shapes confirmed in exploration: Axis 1/3 use `shap_value` float; Axis 2 uses `z_score`, `cluster_mean`, `global_mean`.

**Status:** [x] done

---

### Sub-Task 4 — Frontend: Update `AgentChatDrawer` to pass `explanations` in context and store `sources` per message

**Intent:**
The chat drawer sends `report_context` to the backend but currently omits the `explanations` block (it doesn't exist yet until Sub-Task 1 runs). This sub-task updates the drawer to (a) include `explanations` in the context payload and (b) store the returned `sources` alongside each assistant message so the UI can render the footer.

**Expected Outcomes:**
- The `report_context` object built in `AgentChatDrawer.tsx` includes `explanations: report.explanations`.
- The `onSuccess` handler stores the `sources` from the response alongside the assistant message in `history`.
- The `ChatMessage` type now carries `sources?: SourceItem[]`.
- No visual change yet — this is the data-plumbing step before the footer UI in Sub-Task 5.

**Todo List:**
1. In `frontend/src/components/AgentChatDrawer.tsx`: add `explanations: report.explanations` to the `ctx` object (around line 97-108).
2. In `frontend/src/components/AgentChatDrawer.tsx`: in `onSuccess`, update the assistant message push to include `sources: data.sources ?? []`.
3. Confirm the context now reaches the backend by checking that `_build_context()` in `chat.py` receives the `explanations` key.

**Relevant Context:**
- `frontend/src/components/AgentChatDrawer.tsx` — `ctx` object at lines 97-108; `onSuccess` at lines 111-117.
- `frontend/src/api/chatApi.ts` — `ChatMessage` will have `sources` after Sub-Task 3.
- `frontend/src/stores/reportStore.ts` — `report` object comes from `useReportStore(s => s.report)`; after Sub-Task 1 it will have `report.explanations`.

**Status:** [x] done

---

### Sub-Task 5 — Frontend: Add collapsible "Fontes usadas" footer to each chat message

**Intent:**
Each assistant message in the drawer gains a subtle, collapsible "Fontes usadas" section below the answer bubble. It lists each section the LLM used as context (e.g. "Eixo 2 — Expansão") with 2-3 key values. Collapsed by default; expands on click. This matches the `InterpretationCard` collapsible pattern already in the codebase.

**Expected Outcomes:**
- Each non-stub assistant message that has `sources.length > 0` shows a "▾ Fontes usadas" toggle below the message bubble.
- Clicking it reveals a compact list of `SourceItem` entries: section name + values as small badges or bullet lines.
- The toggle is styled in the existing `ind-muted` / `ind-surface` palette — visually subordinate to the answer.
- User messages are not affected.
- Messages with `is_stub=true` are not affected.
- Empty `sources` array silently renders nothing.

**Todo List:**
1. In `frontend/src/components/AgentChatDrawer.tsx`: add per-message collapsed state (use a `Set<number>` of expanded indices or a local `useState` inside a sub-component).
2. Extract a `SourcesFooter` sub-component inside the file: accepts `sources: SourceItem[]`, renders collapsed by default, expands on toggle.
3. `SourcesFooter` renders a "▾ Fontes usadas (N seções)" toggle line in `text-[10px] text-ind-muted` style.
4. Expanded state shows each `SourceItem` as: section label in `text-ind-accent` + values as a comma-separated or pill-style list in `text-ind-muted`.
5. Integrate `SourcesFooter` below each non-stub assistant `MessageBubble`.
6. Verify that collapsing one message's footer does not affect others.

**Relevant Context:**
- `frontend/src/components/AgentChatDrawer.tsx` — `MessageBubble` at lines 9-38; existing drawer at lines 74-293.
- `frontend/src/components/InterpretationCard.tsx` — collapsible pattern with `collapsed` state and `▼ expandir` / `▲ recolher` toggle (lines 55-94) — follow the same UX pattern.
- Color tokens: `ind-accent`, `ind-muted`, `ind-surface`, `ind-border`, `ind-text`, `ind-bg` (defined in Tailwind config).

**Status:** [x] done

---

### Sub-Task 6 — Frontend: Build `ShapBarChart` component

**Intent:**
A reusable recharts-based horizontal bar chart that renders SHAP feature importance values. Used in the `RastreabilidadePage` for all three axes. Must handle both Axis 1/3 format (`shap_value` float) and Axis 2 format (`z_score` float). Follows the same recharts pattern as `TamBarChart`.

**Expected Outcomes:**
- `frontend/src/components/ShapBarChart.tsx` exists and renders a horizontal `BarChart` from recharts.
- Props: `features: Array<{ feature: string; value: number }>`, `title: string`, `colorPositive?: string`, `colorNegative?: string`.
- Bars are colored based on sign: positive values get one color (e.g. amber `#f59e0b`), negative get another (e.g. slate `#64748b`).
- Feature names on the Y-axis; values on the X-axis with one decimal place.
- Tooltip shows feature name + formatted value.
- Component handles empty `features` gracefully (renders nothing or a "sem dados" message).
- The component is exported and importable from the pages that need it.

**Todo List:**
1. Create `frontend/src/components/ShapBarChart.tsx`.
2. Import `BarChart`, `Bar`, `XAxis`, `YAxis`, `Tooltip`, `ResponsiveContainer`, `Cell` from `recharts` (same as `TamBarChart`).
3. Define props interface: `{ features: { feature: string; value: number }[]; title: string; colorPositive?: string; colorNegative?: string }`.
4. Render a `ResponsiveContainer` wrapping a horizontal `BarChart` (use `layout="vertical"` so feature names appear on the Y-axis).
5. Use `Cell` to color each bar by sign of value.
6. Add a `Tooltip` formatter that shows `feature: value.toFixed(4)`.
7. Add guard: if `features.length === 0` return a `<p className="text-ind-muted text-xs">Dados SHAP não disponíveis</p>`.

**Relevant Context:**
- `frontend/src/components/TamBarChart.tsx` — full file; recharts import pattern and `ResponsiveContainer` / `Cell` usage.
- `frontend/src/types.ts` — `ShapFeature` (added in Sub-Task 3): `{ feature: string; shap_value: number }`.
- Axis 2 uses `z_score` instead of `shap_value`; the caller in `RastreabilidadePage` will normalize both into `{ feature, value }` before passing to this component.

**Status:** [x] done

---

### Sub-Task 7 — Frontend: Build `RastreabilidadePage` and register route + nav entry

**Intent:**
A dedicated page accessible from the sidebar at `/rastreabilidade` and linked from the chat drawer header. It shows the full traceability picture for the currently loaded run: the agent's reasoning chain, tool calls with inputs/outputs, and SHAP feature importance charts for each axis. This is the "drill-down" view — the user comes here when they want to understand a run deeply.

**Expected Outcomes:**
- `/rastreabilidade` route exists and renders `RastreabilidadePage`.
- The sidebar shows a new entry "Rastreabilidade" with icon `🔍` between "Relatórios" and "Auditoria".
- The chat drawer header shows a small "ver rastreabilidade →" link next to the run_id subtitle.
- When no report is loaded, the page shows an empty-state message prompting the user to run an analysis.
- When a report is loaded, the page shows:
  1. **Header card** — run_id, region, axes executed, timestamp.
  2. **Eixo 1 — SHAP Features** section — `ShapBarChart` using `report.explanations.axis1.top_features` (mapped to `{ feature, value: shap_value }`). Shows method name ("TreeExplainer") and n_explained.
  3. **Eixo 2 — Features por Cluster (Top 3)** section — top 3 clusters by TAM from `report.axis2_summary.clusters` (sort by `tam_estimate` descending, filter `is_noise === 0`, take first 3), matched by cluster_id to `report.explanations.axis2.clusters`, using `z_score` as value. Each cluster is a collapsible accordion (first expanded, rest collapsed).
  4. **Eixo 3 — SHAP por Segmento** section — one `ShapBarChart` per segment in `report.explanations.axis3.segments`, using `shap_value` as value. All 3 K-Means segments always shown.
  5. **Interpretações** section — the 4 interpretation strings from `report.interpretations` (executive summary, axis 1, axis 2, axis 3) rendered using the existing `InterpretationCard` component.
- All sections are individually collapsible (follow `InterpretationCard` pattern).
- Sections whose data is `null` or `status !== "ok"` render a graceful "não disponível" message.

**Todo List:**
1. Create `frontend/src/pages/RastreabilidadePage.tsx`.
2. Read `report` from `useReportStore`.
3. Render empty-state when `report === null`.
4. Build the Header card using `report.run_id`, `report.region_scope`, `report.axes_executed`, `report.duration_seconds`.
5. Build the SHAP sections for Axis 1: check `report.explanations?.axis1?.status === "ok"`, map `top_features` to `{ feature, value: shap_value }`, render `<ShapBarChart>`.
6. Build the SHAP sections for Axis 2: check `report.explanations?.axis2?.status === "ok"`. Sort `report.axis2_summary.clusters` by `tam_estimate` descending, filter `is_noise === 0`, take first 3. For each, look up the matching entry in `report.explanations.axis2.clusters` by cluster_id (string key). Render a collapsible section per cluster with `<ShapBarChart features={cluster.top_features.map(f => ({ feature: f.feature, value: f.z_score }))} title={`Cluster ${id}`} />`. First cluster starts expanded, rest collapsed.
7. Build the SHAP sections for Axis 3: check `report.explanations?.axis3?.status === "ok"`, iterate `segments` dict entries, for each render `<ShapBarChart features={segment.top_features.map(f => ({ feature: f.feature, value: f.shap_value }))} title={segmentName} />`. Segment name can be looked up from `report.axis3_summary.segment_profiles[segment_id].segment_name`.
8. Build the Interpretações section using `InterpretationCard` for each interpretation string (reuse the existing component with `collapsible={true}`).
9. In `frontend/src/components/Sidebar.tsx`: add `{ to: '/rastreabilidade', label: 'Rastreabilidade', icon: '🔍' }` to the `links` array between `/reports` and `/audit`.
10. In `frontend/src/main.tsx`: import `RastreabilidadePage` and add `{ path: 'rastreabilidade', element: <RastreabilidadePage /> }` to the router children.
11. In `frontend/src/components/AgentChatDrawer.tsx`: in the drawer header subtitle area, add a `<Link to="/rastreabilidade">` link "ver rastreabilidade →" after the run_id display (visible only when `report` is not null).

**Relevant Context:**
- `frontend/src/pages/Dashboard.tsx` — use as structural reference for a page that reads from `useReportStore` and renders multiple sections.
- `frontend/src/components/InterpretationCard.tsx` — reuse for interpretation sections and as the collapsible pattern for Axis 2 cluster accordion.
- `frontend/src/components/ShapBarChart.tsx` — built in Sub-Task 6.
- `frontend/src/components/Sidebar.tsx` — `links` array at lines 3-12.
- `frontend/src/main.tsx` — router children at lines 39-48.
- `frontend/src/components/AgentChatDrawer.tsx` — header at lines 196-214; use `react-router-dom` `Link` component.
- `frontend/src/stores/reportStore.ts` — `useReportStore(s => s.report)`.
- Note: `tool_selector_rationale` is not currently in `AgentRunResponse` — if unavailable, skip that sub-section or display a note that it is only available in the audit log.

**Status:** [x] done

---

## Implementation Order

Sub-tasks must be executed in this order (each depends on the previous):

```
Sub-Task 1 (backend schemas + agent.py) 
  → Sub-Task 2 (backend chat.py) 
    → Sub-Task 3 (TS types) 
      → Sub-Task 4 (drawer context plumbing) 
        → Sub-Task 5 (sources footer UI) 
          → Sub-Task 6 (ShapBarChart component) 
            → Sub-Task 7 (RastreabilidadePage + routing)
```

Sub-Tasks 5, 6, and 7 are frontend-only and can be reviewed independently after Sub-Tasks 1-4 are confirmed working end-to-end.
