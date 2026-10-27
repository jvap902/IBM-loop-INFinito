# Telecom AI Platform — Web UI

React + Vite single-page application for the Telecom AI Platform.

## Prerequisites

| Tool | Version |
|------|---------|
| Node.js | 18+ |
| npm | 9+ |

## Setup

```bash
npm install
```

## Development

Requires the FastAPI backend running on `http://localhost:8000` and `CORS_ORIGINS=http://localhost:5173` set in `.env`.

```bash
npm run dev        # starts Vite dev server on http://localhost:5173
```

All `/v1/*` and `/health` requests are proxied to `http://localhost:8000`.

## Build

```bash
npm run build      # outputs to frontend/dist/
npm run preview    # preview the production build locally
```

## Project Structure

```
frontend/
├── index.html
├── package.json
├── vite.config.ts         — Vite config + proxy
├── tailwind.config.js     — Industrial dark palette
├── tsconfig.json
└── src/
    ├── main.tsx           — React entry, Router, QueryClient
    ├── App.tsx            — Shell layout (Sidebar + Outlet)
    ├── index.css          — Tailwind base + Leaflet CSS import
    ├── types.ts           — TypeScript interfaces mirroring api/schemas.py
    ├── api/
    │   ├── client.ts      — Axios instance + X-API-Key interceptor
    │   ├── agentApi.ts    — runAgent() → POST /v1/agent/run
    │   ├── axisApi.ts     — runAxis1/2/3() → POST /v1/tools/axis*/run
    │   └── auditApi.ts    — queryAuditEvents() → GET /v1/audit/events
    ├── stores/
    │   └── reportStore.ts — Zustand store holding the latest AgentRunResponse
    ├── components/
    │   ├── Sidebar.tsx        — Navigation sidebar
    │   ├── KpiCard.tsx        — Metric card
    │   ├── HexMap.tsx         — React Leaflet map (axis 1/2/3 overlays)
    │   ├── TamBarChart.tsx    — Recharts bar chart (TAM per cluster)
    │   ├── SegmentPieChart.tsx — Recharts donut chart (segment distribution)
    │   ├── InvestmentTable.tsx — Sortable investment hypothesis table
    │   └── AxisForm.tsx       — Form shell + reusable form primitives
    └── pages/
        ├── Dashboard.tsx   — /     Result viewer
        ├── RunPage.tsx     — /run  Full agent runner
        ├── Axis1Page.tsx   — /axis1
        ├── Axis2Page.tsx   — /axis2
        ├── Axis3Page.tsx   — /axis3
        └── AuditPage.tsx   — /audit
```

## Industrial Palette

| Token | Hex | Usage |
|-------|-----|-------|
| `ind-bg` | `#0f172a` | Page background |
| `ind-surface` | `#1e293b` | Cards, panels |
| `ind-border` | `#334155` | Borders |
| `ind-text` | `#e2e8f0` | Primary text |
| `ind-muted` | `#94a3b8` | Secondary text |
| `ind-accent` | `#f59e0b` | Amber — primary accent, buttons |
| `ind-danger` | `#ef4444` | Red — Axis 1 critical |
| `ind-cluster` | `#3b82f6` | Blue — Axis 2 clusters |
| `ind-segment` | `#22c55e` | Green — Axis 3 segments |
