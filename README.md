# Telecom AI Platform

> **Part of the IBM SkillsBUILD Program**
> An autonomous AI platform for accelerating telecom infrastructure decisions in Brazil.

---

## Overview

Telecom AI Platform is an AI-driven decision support system built to help telecommunications companies **make faster, evidence-based decisions** about infrastructure expansion, maintenance prioritization, and market targeting across Brazilian territory.

Instead of weeks of manual analysis, the platform's autonomous agent can ingest public network data, run three analytical axes in parallel, and deliver a full prescriptive report — complete with investment estimates, cluster maps, and explainable reasoning — in a single orchestrated run.

The system was developed as part of the **IBM SkillsBUILD** program, combining IBM watsonx.ai with modern MLOps, agentic AI patterns, and responsible AI principles (LGPD compliance, SHAP explainability, and append-only audit trails).

---

## Why It Exists

Infrastructure decisions in telecom — where to deploy fiber, when to reform an antenna cluster, which regions to target with promotional offers — traditionally require cross-departmental analysis that takes weeks. This platform compresses that cycle by:

- **Continuously ingesting** six public open-data sources (Ookla, IBGE, Anatel, OpenCelliD, M-Lab NDT, Cloudflare Radar)
- **Running three ML analytical axes** on a unified H3-hexagon feature store
- **Exposing every pipeline as an API tool** so an autonomous agent can invoke and combine them
- **Generating a prescriptive Markdown + JSON report** with investment priorities, TAM estimates, and recommended next actions

---

## Key Capabilities

### 🔍 Axis 1 — Maintenance & Criticality Detection
Identifies hexagons with anomalous network behavior using an ensemble of **IsolationForest + LOF (Local Outlier Factor)**. Anomaly scores above 0.65 flag critical zones. Results are cross-validated against **Cloudflare Radar** outage annotations to isolate upstream causes from local infrastructure failures.

### 📡 Axis 2 — Expansion Opportunity Mapping
Discovers underserved high-demand regions using a **UMAP → HDBSCAN** clustering pipeline. Clusters are profiled (e.g., "High-Density Underserved", "Ultra-High Performance") and ranked by a **TAM (Total Addressable Market)** estimate calculated per cluster:

```
TAM = n_dom × ARPU × (1 − penetration_rate)
```

### 🎯 Axis 3 — Promotional Segment Targeting
Segments hexagons into commercial profiles (Premium, Core, Emerging) using **K-Means++** on income, household density, complaint volume, and upload speed features. Enables targeted promotional campaigns with quantified market potential per segment.

---

## Explainability First

Every decision made by the platform is explainable and auditable. This is not an afterthought — it is a core design requirement.

| Axis | Explainability Method |
|---|---|
| Axis 1 (Anomaly Detection) | **SHAP TreeExplainer** — top-3 features driving each anomaly score |
| Axis 2 (Expansion Clustering) | **Z-score cluster profiles** — feature means and standard deviations per cluster |
| Axis 3 (Promotional Segmentation) | **SHAP KernelExplainer** — top-3 variables explaining each segment assignment |

Every agent action, tool invocation, and model run is persisted to an **append-only audit log** (JSONL or PostgreSQL) via the `AuditEvent` schema, capturing:

- `event_id`, `timestamp`, `agent_id`, `event_type`
- `tool_name`, `tool_input`, `tool_output_summary`
- `reasoning_text` (LLM chain-of-thought)
- `run_id`, `model_version`

The audit trail is queryable via `GET /v1/audit/events` with filters by agent, event type, date range, and run ID.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Data Sources (6 open)                                      │
│  Ookla · IBGE · Anatel · OpenCelliD · M-Lab · Cloudflare   │
└─────────────────┬───────────────────────────────────────────┘
                  │ ETL — Bronze → Silver → Gold
                  ▼
┌─────────────────────────────────────────────────────────────┐
│  H3 Feature Store  (Uber H3 res 8/9)                        │
│  x_hi = [d_down, d_up, lat, vol_test, n_dom, n_com,        │
│           ren_med, n_erb, HHI, vol_reclam]                  │
└─────────────────┬───────────────────────────────────────────┘
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
   Axis 1      Axis 2    Axis 3
 IsoForest    UMAP +    K-Means++
   + LOF      HDBSCAN
        └─────────┼─────────┘
                  │ FastAPI Tool Layer (X-API-Key auth)
                  ▼
┌─────────────────────────────────────────────────────────────┐
│  Operational Agent  (LangGraph StateGraph, 7 nodes)         │
│  LLM: IBM watsonx.ai (default) · OpenAI · Gemini · Stub    │
└─────────────────┬───────────────────────────────────────────┘
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
 Prescriptive Report    Audit Trail
 (Markdown + JSON)      (JSONL / PG)
        +
   Web Dashboard
 (React + Leaflet)
```

---

## Repository Structure

```
.
├── agent/              # LangGraph Operational Agent
│   ├── graph.py        # 7-node StateGraph
│   ├── llm_provider.py # Watsonx / OpenAI / Gemini / Stub
│   ├── run.py          # CLI entrypoint
│   └── tool_registry.py
├── api/                # FastAPI Tool API (port 8000)
│   ├── main.py
│   ├── auth.py         # X-API-Key middleware
│   ├── routes/         # tools, audit, agent, reports
│   └── schemas.py      # Pydantic v2 contracts
├── audit/              # Transparency & Audit Layer
│   ├── logger.py       # Append-only AuditLogger
│   ├── explainability.py # SHAP per-axis explainers
│   └── schema.py       # AuditEvent model
├── data_ingestion/     # ETL connectors & processing
│   ├── connectors/     # ookla, ibge, anatel, opencellid, mlab, cloudflare
│   └── processing/     # spatial, sanitise, feature_store, quality
├── ml/                 # ML pipelines
│   └── pipelines/
│       ├── pipeline_axis1.py  # IsolationForest + LOF
│       ├── pipeline_axis2.py  # UMAP + HDBSCAN
│       └── pipeline_axis3.py  # K-Means++
├── frontend/           # React + Vite + Tailwind web UI
├── tests/              # pytest (234 tests, 100% passing)
├── knowledge-api.json  # Canonical data catalogue & ML spec
├── eda-findings.md     # EDA & algorithm validation report
├── openapi.yaml        # Auto-generated OpenAPI 3.1 schema
└── EXECUTION_GUIDE.md  # Step-by-step execution reference
```

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+ (frontend only)

### Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env — at minimum set TOOL_API_KEY and GOLD_PARQUET_PATH

# 3. Start the Tool API
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 4. Run the agent (separate terminal)
python -m agent.run --region BR-SP --axes axis1 --axes axis2 --axes axis3

# 5. (Optional) Start the web UI
cd frontend && npm install && npm run dev
```

### Run Tests

```bash
pytest tests/ -v
# 234 passed
```

### Docker

```bash
docker compose up
```

---

## Report Format

Every agent run produces a prescriptive Markdown report with the following mandatory sections:

1. **Executive Summary**
2. **Current Infrastructure Status** (Axis 1 — anomaly map)
3. **Identified Expansion Opportunities** (Axis 2 — cluster profiles)
4. **Market Segmentation for Promotions** (Axis 3 — segment breakdown)
5. **Investment Prioritization** (cross-axis opportunity matrix)
6. **Return Estimate** (TAM / ARPU / CAPEX proxy)
7. **Recommended Next Actions**
8. **Appendix: Methodology & Auditability** (model versions, run IDs, SHAP summaries)

Reports are saved to `reports/` as both `.md` and `.json`.

---

## LLM Providers

The agent's reasoning layer is fully swappable via the `LLM_PROVIDER` environment variable:

| Provider | Config key | Notes |
|---|---|---|
| **IBM watsonx.ai** | `watsonx` | Default for production. Requires `WATSONX_API_KEY` + `WATSONX_PROJECT_ID` |
| OpenAI GPT-4o | `openai` | Requires `OPENAI_API_KEY` |
| Google Gemini | `gemini` | Requires `GEMINI_API_KEY` |
| Stub (offline) | `stub` | No API key needed — for development and testing |

---

## LGPD Compliance

All processing operates exclusively on **spatially aggregated data** (H3 hexagons and IBGE census sectors). No individual subscriber records, personal identifiers, or sensitive data are stored or processed at any stage. The audit logger applies automatic PII redaction before persisting any event payload.

---

## IBM SkillsBUILD

This project was developed as part of the **IBM SkillsBUILD** program. It demonstrates the application of IBM watsonx.ai in a real-world agentic AI architecture, combining responsible AI practices (explainability, auditability, LGPD compliance) with modern MLOps and autonomous decision-making to accelerate infrastructure planning in the Brazilian telecommunications sector.

---

## License

This project is intended for educational and demonstration purposes within the IBM SkillsBUILD program.
