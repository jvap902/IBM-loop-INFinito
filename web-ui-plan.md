# Telecom AI Platform — Web UI Implementation Plan

## Top-Level Overview

**Goal:** Replace the current CLI-only usage model with a full-featured web interface that exposes all platform capabilities (axis-level runs, full-agent execution, audit log, result visualization) through an industrial-themed graphical UI.

**Scope:**
- A new `frontend/` directory: React + Vite SPA, served on port 5173 during development
- A thin **BFF endpoint** (`/v1/agent/run`) added to the existing FastAPI app (`api/`) that wraps the LangGraph agent call into a single synchronous HTTP request (since loading spinner is sufficient — no streaming required)
- A Leaflet map renders cluster/segment centroids as colored circles; no WebGL dependency
- All existing FastAPI endpoints remain untouched

**Non-Goals:**
- Real-time streaming / WebSocket log feed
- Authentication redesign (API key remains as-is)
- Replacing the CLI agent runner (`agent/run.py`)
- Mobile / responsive layout optimization

**Technology Choices:**
- Frontend: React 18 + Vite, TypeScript, Tailwind CSS (industrial palette: dark slate, amber accents), React Query for async state, React Leaflet for map, Recharts for charts
- Backend addition: one new FastAPI route (`api/routes/agent.py`)

---

## Sub-Tasks

---

### Sub-Task 1 — Backend BFF: Agent Run Endpoint

**Status:** `[ ] pending`

**Intent:**
The frontend needs a single HTTP call that triggers the full LangGraph agent and returns the complete report JSON. Currently the agent is only reachable from the CLI (`agent/run.py`). This sub-task adds a `/v1/agent/run` POST endpoint that wraps the agent programmatically (no subprocess).

**Expected Outcomes:**
- `POST /v1/agent/run` accepts `{region, axes, force, llm_provider}` and returns the full `report_json` dict plus `run_id`, `duration_seconds`, and `errors[]`
- Requires the same `X-API-Key` header as all other `/v1/tools/*` endpoints
- On error, returns HTTP 500 with `{detail, errors[]}`
- The existing `agent/run.py` CLI continues to work unchanged

**Todo List:**
1. Create `api/routes/agent.py` with a single `POST /v1/agent/run` route
2. Define `AgentRunRequest` Pydantic model in `api/schemas.py`: `{region: str = "all", axes: list[str] = ["axis1","axis2","axis3"], force: bool = False, llm_provider: str = "stub"}`
3. Define `AgentRunResponse` Pydantic model: `{run_id, region_scope, axes_executed, duration_seconds, summary, investment_hypotheses, axis1_summary, axis2_summary, axis3_summary, errors}`
4. In the route handler: import `agent.graph` and `agent.state`, instantiate the graph, inject `AgentState` from request fields, invoke the graph synchronously via `asyncio.to_thread()` (same pattern used for SHAP in `audit/explainability.py`), return the `report_json` from `AgentState`; wrap the call with `asyncio.wait_for()` using the timeout value
5. Register the new router in `api/main.py` with prefix `/v1`
6. Add `CORS_ORIGINS` support to `api/main.py` to allow `http://localhost:5173` (already has env var stub in `.env.example`)
7. Add `AGENT_RUN_TIMEOUT_SECONDS` env var (default `120`) read in `api/routes/agent.py`; used as the `asyncio.wait_for()` timeout; return HTTP 504 with a clear message on timeout
8. Update `.env.example` to document `AGENT_RUN_TIMEOUT_SECONDS=120`
9. Update `requirements.txt` if any new backend deps are needed (likely none)

**Relevant Context:**
- `agent/graph.py` — StateGraph with 7 nodes; must be invoked programmatically
- `agent/state.py` — `AgentState` TypedDict; `report_json` is the output field
- `agent/run.py` — Reference implementation showing how to set up and invoke the graph
- `api/main.py` — App factory; CORS middleware setup and router registration
- `api/auth.py` — `X-API-Key` middleware that protects all `/v1/*` routes
- `audit/explainability.py` — Pattern for `asyncio.to_thread()` usage
- `.env.example` — Reference for where to add `AGENT_RUN_TIMEOUT_SECONDS`

---

### Sub-Task 2 — Frontend Scaffold

**Status:** `[ ] pending`

**Intent:**
Bootstrap the React + Vite project with the correct folder structure, Tailwind CSS configured with the industrial palette, and a proxy to the FastAPI backend so the frontend can call `/v1/*` directly without CORS issues during development.

**Expected Outcomes:**
- `frontend/` directory with `package.json`, `vite.config.ts`, `tailwind.config.ts`, `tsconfig.json`
- `npm run dev` starts the Vite dev server on port 5173 and proxies `/v1/*` to `http://localhost:8000`
- A placeholder `App.tsx` renders the shell layout (sidebar + main area) with the industrial color scheme
- All required npm packages installed: `react`, `react-dom`, `react-router-dom`, `@tanstack/react-query`, `react-leaflet`, `leaflet`, `recharts`, `axios`
- `npm run build` produces a static bundle in `frontend/dist/`

**Todo List:**
1. Create `frontend/package.json` with all required dependencies and `dev`/`build`/`preview` scripts
2. Create `frontend/vite.config.ts` with server proxy: `"/v1" → "http://localhost:8000"` and `"/health" → "http://localhost:8000"`
3. Create `frontend/tailwind.config.ts` extending default colors with the industrial palette (custom colors: `industrial-bg`, `industrial-surface`, `industrial-accent`, `industrial-danger`, `industrial-warn`)
4. Create `frontend/src/main.tsx` — React entry, QueryClientProvider, RouterProvider
5. Create `frontend/src/App.tsx` — Shell with `<Sidebar>` and `<Outlet>` (react-router)
6. Create `frontend/src/components/Sidebar.tsx` — Navigation links: Dashboard, Análise Completa, Eixo 1, Eixo 2, Eixo 3, Auditoria
7. Create `frontend/index.html` Vite entry point
8. Add `frontend/` to `.gitignore` under `node_modules` exclusion (already partially handled)

**Relevant Context:**
- `.env.example` line 90: `CORS_ORIGINS=http://localhost:3000,https://dashboard.internal` — shows CORS already anticipated
- `reports/dashboard.html` — Existing static dashboard for visual reference on data structure (KPI cards, map, charts, investment table)
- Industrial palette reference: dark slate backgrounds (`#0f172a`, `#1e293b`), amber accents (`#f59e0b`), red danger (`#ef4444`), green success (`#22c55e`)

---

### Sub-Task 3 — Dashboard Page (Results Viewer)

**Status:** `[ ] pending`

**Intent:**
Build the main results page that reads the most recent agent run from the BFF or from a loaded JSON report and displays all KPIs, the Leaflet map, TAM charts, segmentation, and the investment hypothesis table — the interactive equivalent of `reports/dashboard.html`.

**Expected Outcomes:**
- Route `/` shows the Dashboard page
- If no run has been made yet, shows an empty state with a call-to-action button linking to the "Análise Completa" page
- If a run result is in React Query cache (or uploaded via JSON file), shows:
  - 5 KPI cards: Hexágonos Analisados, Anomalias Críticas, Clusters de Expansão, Segmentos de Mercado, TAM Total (R$)
  - Leaflet map centered on Brazil with colored circle markers (red = Axis 1 critical, blue = Axis 2 clusters, green = Axis 3 segments), popup on click showing h3_id + metrics
  - Recharts BarChart for TAM per cluster (Axis 2)
  - Recharts PieChart for segment distribution (Axis 3)
  - Sortable table of investment hypotheses (priority_class, TAM, avg_n_dom, avg_d_down, avg_HHI, rationale)
  - Run metadata footer: run_id, region, axes executed, duration, timestamp

**Todo List:**
1. Create `frontend/src/pages/Dashboard.tsx`
2. Create `frontend/src/components/KpiCard.tsx` — reusable metric card with label, value, subtext, optional color variant
3. Create `frontend/src/components/HexMap.tsx` — React Leaflet map; accepts `axis1Results`, `axis2Clusters`, `axis3Results`; renders circle markers; popup on click
4. Create `frontend/src/components/TamBarChart.tsx` — Recharts BarChart; x = cluster_id, y = tam_estimate
5. Create `frontend/src/components/SegmentPieChart.tsx` — Recharts PieChart; one slice per segment, labeled by segment_name
6. Create `frontend/src/components/InvestmentTable.tsx` — Sortable table; columns: Priority, Cluster, TAM (R$), Dom/Hex, Vel↓ (Mbps), HHI, Lat, Lon, Rationale
7. Create `frontend/src/stores/reportStore.ts` — Zustand or React Context to hold the latest `AgentRunResponse` result in memory across pages
8. Wire the empty state call-to-action button

**Relevant Context:**
- `api/schemas.py` — `AgentRunResponse` shape (to be created in Sub-Task 1) mirrors `report_json` in `agent/state.py`
- `reports/BR-SP_2026-10-26.json` — Real sample data to use during UI development
- `reports/dashboard.html` — Visual reference for all chart types and table structure
- Leaflet circle color legend: critical hexagons = `#ef4444`, expansion clusters = `#3b82f6`, segments = `#22c55e`

---

### Sub-Task 4 — "Análise Completa" Page (Full Agent Runner)

**Status:** `[ ] pending`

**Intent:**
Build the form page that collects all agent parameters (region, axes, force flag, LLM provider) and triggers `POST /v1/agent/run`. Shows a loading spinner while the agent runs, then navigates to the Dashboard with the result.

**Expected Outcomes:**
- Route `/run` shows the Análise Completa page
- Form fields:
  - **Região** — text input with placeholder `BR-SP` (accepts any region label or H3 parent ID)
  - **Eixos** — three checkboxes: Eixo 1 (Manutenção/Criticidade), Eixo 2 (Expansão), Eixo 3 (Segmentação); all checked by default
  - **LLM Provider** — radio group: stub / watsonx / openai
  - **Forçar re-execução** — toggle switch (maps to `force: true/false`)
  - **API Key** — password input (pre-filled from `localStorage` if previously saved, with a "salvar" checkbox)
- "Executar Análise" button: disabled while running; shows spinner + "Analisando..." label
- On success: stores result in the report store, navigates to `/`
- On error: shows an inline error banner with the `errors[]` array from the response

**Todo List:**
1. Create `frontend/src/pages/RunPage.tsx`
2. Create `frontend/src/components/RunForm.tsx` — controlled form component with the fields above; uses `@tanstack/react-query` `useMutation` for the POST
3. Create `frontend/src/api/client.ts` — axios instance with base URL `/v1` and `X-API-Key` header injected from state/localStorage
4. Create `frontend/src/api/agentApi.ts` — `runAgent(params): Promise<AgentRunResponse>` function
5. Implement loading state: full-page overlay spinner with label "O agente está processando — isso pode levar alguns segundos..."
6. On success: call `setReport(result)` from the report store, then `navigate("/")`
7. On error: display `{detail}` + iterate `errors[]` in a red banner
8. Add `localStorage` persistence for API key (opt-in with checkbox)

**Relevant Context:**
- `agent/run.py` — All CLI flags correspond 1:1 to the form fields
- Sub-Task 1 `AgentRunRequest` schema: `{region, axes[], force, llm_provider}`
- `api/auth.py` — `X-API-Key` header requirement

---

### Sub-Task 5 — Individual Axis Pages

**Status:** `[ ] pending`

**Intent:**
Build three dedicated pages (one per axis) that let the user set axis-specific parameters and call the individual axis API endpoints directly — without triggering the full LangGraph agent.

**Expected Outcomes:**
- Routes `/axis1`, `/axis2`, `/axis3`, each with:
  - A parameter form panel on the left (all axis-specific fields)
  - A results panel on the right that renders after submission
- **Axis 1 (`/axis1`):** form fields: region_filter (text), h3_resolution (8|9 select), anomaly_threshold (slider 0.0–1.0), contamination (slider 0.01–0.5), top_n (number input 1–5000); results: KPIs (total_hexagons_scored, n_critical, anomaly_rate) + sortable table of critical hexagons + mini Leaflet map
- **Axis 2 (`/axis2`):** form fields: region_filter, h3_resolution, min_cluster_size (slider 2–2000), skip_umap (toggle); results: KPIs (n_clusters, noise_rate) + sortable cluster table (cluster_id, size, avg_d_down, avg_HHI, tam_estimate) + mini Leaflet map
- **Axis 3 (`/axis3`):** form fields: region_filter, h3_resolution, n_clusters (slider 2–10), sweep_if_low_silhouette (toggle); results: KPIs (n_segments, silhouette_score_global) + donut chart (segment distribution) + sortable hexagon table

**Todo List:**
1. Create `frontend/src/pages/Axis1Page.tsx`, `Axis2Page.tsx`, `Axis3Page.tsx`
2. Create `frontend/src/api/axisApi.ts` — three typed functions: `runAxis1(params)`, `runAxis2(params)`, `runAxis3(params)` calling the respective `/v1/tools/axis{1,2,3}/run` endpoints
3. Create `frontend/src/components/AxisForm.tsx` — generic left-panel form shell with title, description, and slot for axis-specific fields
4. Create `frontend/src/components/ResultsPanel.tsx` — generic right-panel wrapper that handles loading/error/empty states
5. For Axis 1: create `Axis1ResultsView.tsx` with KPI row + `HexMap` (critical hexagons only) + critical hexagon table
6. For Axis 2: create `Axis2ResultsView.tsx` with KPI row + `HexMap` (cluster centroids) + cluster table + `TamBarChart`
7. For Axis 3: create `Axis3ResultsView.tsx` with KPI row + `SegmentPieChart` + segment + hexagon tables
8. Register routes in `App.tsx`

**Relevant Context:**
- `api/schemas.py` — All `Axis{1,2,3}RunRequest` and `RunResponse` schemas
- `api/routes/tools.py` — Endpoints `/v1/tools/axis{1,2,3}/run`
- Sub-Task 3 reuses `HexMap`, `TamBarChart`, `SegmentPieChart` components — these must be built before or in parallel with this sub-task

---

### Sub-Task 6 — Audit Log Page

**Status:** `[ ] pending`

**Intent:**
Build the audit log viewer page that calls `GET /v1/audit/events` with filter controls and displays results in a filterable, paginated table — giving visibility into every tool call, reasoning step, and report event.

**Expected Outcomes:**
- Route `/audit` shows the Audit Log page
- Filter bar: agent_id (multi-select: planner|operational|system), event_type (multi-select: tool_call|reasoning_step|report_generated|model_run), date_start + date_end (date pickers), run_id (text input), limit (number input, default 100)
- "Buscar" button triggers `GET /v1/audit/events` with selected filters
- Results table: timestamp, run_id (truncated, copyable), agent_id, event_type, summary (expandable row for full JSON payload)
- Row expansion shows a formatted JSON viewer for the event payload
- Empty state for no results, error state for API failures

**Todo List:**
1. Create `frontend/src/pages/AuditPage.tsx`
2. Create `frontend/src/api/auditApi.ts` — `queryAuditEvents(filters): Promise<AuditQueryResponse>`
3. Create `frontend/src/components/AuditFilterBar.tsx` — controlled filter form
4. Create `frontend/src/components/AuditTable.tsx` — table with expandable rows; copy-to-clipboard for run_id
5. Create `frontend/src/components/JsonViewer.tsx` — simple pre-formatted JSON display with syntax highlighting using inline CSS (no extra lib)
6. Use `@tanstack/react-query` `useQuery` with `enabled: false` (manual trigger on "Buscar" click)

**Relevant Context:**
- `api/routes/audit.py` — `GET /v1/audit/events` with all filter query params
- `api/schemas.py` — `AuditQueryResponse` and `AuditEvent` shapes

---

### Sub-Task 7 — Documentation & Dev Setup

**Status:** `[ ] pending`

**Intent:**
Update `EXECUTION_GUIDE.md` and `README` to reflect the new web UI, and add a `frontend/README.md` with setup instructions. Ensure the new BFF endpoint is documented in the OpenAPI spec.

**Expected Outcomes:**
- `EXECUTION_GUIDE.md` has a new Section 11 "Web Interface" with: prerequisites (Node.js 18+), install steps (`npm install`), dev start command, build command, URL reference
- `api/routes/agent.py` is included when `export_openapi.py` is run, regenerating `openapi.yaml`
- `frontend/README.md` explains the folder structure, available scripts, and proxy config
- `.env.example` updated to document `CORS_ORIGINS` as required (not just commented) when using the web UI

**Todo List:**
1. Add Section 11 to `EXECUTION_GUIDE.md` covering Node.js prerequisite, `cd frontend && npm install`, `npm run dev`, `npm run build`
2. Update `.env.example` to uncomment and document `CORS_ORIGINS=http://localhost:5173`
3. Create `frontend/README.md` with folder structure and scripts table
4. Verify `export_openapi.py` picks up the new `api/routes/agent.py` router and regenerate `openapi.yaml`

**Relevant Context:**
- `EXECUTION_GUIDE.md` — Section 2 (Prerequisites table) needs Node.js row added
- `export_openapi.py` — Imports `api/main.py`; if the new router is registered there, it will be auto-included
- `.env.example` line 90 — `CORS_ORIGINS` already stubbed out

---

## Implementation Order

```
Sub-Task 1 (BFF endpoint)
    → Sub-Task 2 (Frontend scaffold)
        → Sub-Task 3 (Dashboard — reusable components)
        → Sub-Task 4 (Full agent runner form)
        → Sub-Task 5 (Individual axis pages — reuses components from ST3)
        → Sub-Task 6 (Audit log page)
            → Sub-Task 7 (Docs update)
```

Sub-Tasks 3, 4, 5 can be parallelized after Sub-Task 2 is complete, since they share components that will be built in Sub-Task 3.
