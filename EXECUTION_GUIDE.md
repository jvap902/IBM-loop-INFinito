# Telecom AI Platform — Execution Guide

> **Purpose:** This file is the authoritative step-by-step execution reference for running the
> Telecom AI Platform end-to-end. Hand it to any new agent instance or team member to resume
> or re-run the system from scratch.

---

## 1. Repository Structure

```
.
├── agent/                  # LangGraph Operational Agent (Sub-Task 6)
│   ├── graph.py            # StateGraph definition (7 nodes)
│   ├── llm_provider.py     # WatsonxProvider / OpenAIProvider / StubProvider
│   ├── run.py              # CLI entrypoint (typer)
│   ├── state.py            # AgentState TypedDict
│   └── tool_registry.py    # Dynamic tool discovery + HTTP invocation
├── api/                    # FastAPI Tool API (Sub-Task 4)
│   ├── auth.py             # X-API-Key middleware
│   ├── main.py             # App factory, port 8000
│   ├── routes/
│   │   ├── audit.py        # GET /v1/audit/events
│   │   └── tools.py        # POST /v1/tools/axis{1,2,3}/run + crossvalidate
│   └── schemas.py          # Pydantic request/response contracts
├── audit/                  # Transparency & Auditability Layer (Sub-Task 5)
│   ├── explainability.py   # SHAP explainers (Tree / Z-score proxy / Kernel)
│   ├── logger.py           # AuditLogger (JSONL / PostgreSQL)
│   ├── schema.py           # AuditEvent Pydantic model
│   └── README.md           # Governance documentation
├── data/
│   └── gold/
│       └── features.parquet  # Gold Feature Store (2 000 synthetic H3 hexagons)
├── data_ingestion/         # ETL connectors (Sub-Task 1)
│   ├── connectors/         # ookla, ibge, anatel, opencellid, cloudflare
│   └── processing/         # spatial, sanitise, feature_store, quality
├── logs/
│   └── audit.jsonl         # Append-only audit event log
├── ml/                     # ML utilities (Sub-Task 2 + 3)
│   ├── baseline_runners.py
│   ├── drift_detector.py
│   ├── eda_utils.py
│   └── pipelines/
│       ├── pipeline_axis1.py  # IsolationForest + LOF
│       ├── pipeline_axis2.py  # UMAP + HDBSCAN
│       └── pipeline_axis3.py  # K-Means++
├── reports/                # Agent output (Markdown + JSON per run)
├── tests/                  # pytest test suites
├── .env.example            # Template for all environment variables
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── export_openapi.py
├── knowledge-api.json      # Canonical data source catalogue + ML spec
├── openapi.yaml            # Auto-generated OpenAPI 3.1 schema
├── requirements.txt
└── telecom-ai-platform-plan.md  # Implementation plan (sub-task status)
```

---

## 2. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10 – 3.13 | Miniconda recommended on Windows |
| pip | latest | `pip install --upgrade pip` |
| PowerShell | 5.1+ | Windows execution environment |
| Node.js | 18+ | Required for the Web UI only. Download at https://nodejs.org |
| npm | 9+ | Bundled with Node.js |

---

## 3. First-Time Setup

### 3.1 Install Dependencies

```powershell
pip install -r requirements.txt
```

> `ibm-watsonx-ai` is **not** in `requirements.txt` (commented out). Install it separately
> only if you intend to use `LLM_PROVIDER=watsonx`:
>
> ```powershell
> pip install ibm-watsonx-ai
> ```

### 3.2 Create the `.env` File

```powershell
Copy-Item .env.example .env
```

Then open `.env` and set **at minimum** these three variables (uncomment and fill in):

```dotenv
TOOL_API_KEY=telecom-dev-key-2024
GOLD_PARQUET_PATH=data/gold/features.parquet
TOOL_API_BASE_URL=http://localhost:8000
```

For LLM mode (optional — defaults to `stub` which needs no credentials):

```dotenv
LLM_PROVIDER=stub           # or watsonx / openai

# If LLM_PROVIDER=watsonx:
# WATSONX_API_KEY=<your key>
# WATSONX_PROJECT_ID=<your project id>
# WATSONX_URL=https://us-south.ml.cloud.ibm.com
# WATSONX_MODEL_ID=ibm/granite-13b-chat-v2

# If LLM_PROVIDER=openai:
# OPENAI_API_KEY=<your key>
# OPENAI_MODEL_ID=gpt-4o
```

### 3.3 Generate Synthetic Gold Feature Store (if missing)

If `data/gold/features.parquet` does not exist, generate it:

```powershell
python -c "
import numpy as np, pandas as pd, h3, pathlib, json
rng = np.random.default_rng(42)
n = 2000
hex_ids = list({h3.geo_to_h3(rng.uniform(-33, 5), rng.uniform(-74, -34), 8) for _ in range(n*2)})[:n]
df = pd.DataFrame({'h3_id': hex_ids})
df['d_down']    = rng.uniform(5, 150, n)
df['d_up']      = rng.uniform(2, 50, n)
df['lat']       = rng.uniform(0, 150, n)
df['vol_test']  = rng.integers(10, 500, n).astype(float)
df['n_dom']     = rng.integers(50, 5000, n).astype(float)
df['n_com']     = rng.integers(5, 500, n).astype(float)
df['ren_med']   = rng.uniform(1000, 8000, n)
df['n_erb']     = rng.integers(1, 20, n).astype(float)
df['HHI']       = rng.uniform(1000, 9000, n)
df['vol_reclam']= rng.uniform(0, 50, n)
df['x_hi']      = df[['d_down','d_up','lat','vol_test','n_dom','n_com','ren_med','n_erb','HHI','vol_reclam']].values.tolist()
pathlib.Path('data/gold').mkdir(parents=True, exist_ok=True)
df.to_parquet('data/gold/features.parquet', index=False)
print(f'Generated {len(df)} hexagons -> data/gold/features.parquet')
"
```

---

## 4. Running the System

The platform has **two components** that must run concurrently:
1. **Tool API** (FastAPI server) — Terminal 1
2. **Operational Agent** (LangGraph CLI) — Terminal 2

### 4.1 Load Environment Variables into PowerShell

Run this in **each terminal** before starting anything:

```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^#=][^=]*)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable(
            $matches[1].Trim(), $matches[2].Trim(), 'Process'
        )
    }
}
```

### 4.2 Terminal 1 — Start the Tool API

```powershell
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify the API is healthy:

```powershell
Invoke-RestMethod http://localhost:8000/health
# Expected: {"status":"ok", ...}

Invoke-RestMethod http://localhost:8000/v1/tools
# Expected: list of 4 tools (axis1/run, axis2/run, axis3/run, axis1/crossvalidate)
```

Interactive docs are available at: `http://localhost:8000/v1/docs`

### 4.3 Terminal 2 — Run the Operational Agent

```powershell
python -m agent.run --region BR-SP --axes axis1 --axes axis2 --axes axis3 --force
```

> **PowerShell Note:** `--axes` must be repeated for each axis. Passing them as a
> comma-separated list (`--axes axis1,axis2,axis3`) does **not** work with typer on Windows.

**Available CLI flags:**

| Flag | Default | Description |
|---|---|---|
| `--region` | `all` | Region label or H3 parent cell ID |
| `--axes` | all three | Repeat for each axis: `--axes axis1 --axes axis2 --axes axis3` |
| `--force` | `false` | Skip freshness checks |
| `--output-dir` | `reports/` | Output directory for reports |
| `--api-base` | env `TOOL_API_BASE_URL` | Override API base URL |
| `--api-key` | env `TOOL_API_KEY` | Override API key |
| `--llm` | env `LLM_PROVIDER` | Override LLM provider (`watsonx` / `openai` / `stub`) |

### 4.4 Expected Output

A successful run prints:

```
Telecom Operational Agent
   Region  : BR-SP
   Axes    : ['axis1', 'axis2', 'axis3']
   Force   : True
   Run ID  : <uuid>
   API Base: http://localhost:8000
   LLM     : stub

Running agent graph...

Report saved:
   MD  : reports/BR-SP_<YYYY-MM-DD>.md
   JSON: reports/BR-SP_<YYYY-MM-DD>.json

Audit trail: 7 events recorded (run_id=<uuid>)

Summary:
   Critical hexagons (Axis 1) : 66
   Expansion clusters (Axis 2): 14
   Market segments  (Axis 3)  : 6
   Investment hypotheses      : 14
   Total TAM estimate         : R$ 102,511,293.74
```

Reports are saved to:
- `reports/<region>_<YYYY-MM-DD>.md` — Prescriptive Markdown report (7 mandatory sections)
- `reports/<region>_<YYYY-MM-DD>.json` — Machine-readable structured JSON
- `logs/audit.jsonl` — Appended audit events (7 events per full run)

---

## 5. Individual Axis Calls (Manual API Testing)

You can call each axis directly via the REST API without running the full agent:

```powershell
# Axis 1 — Anomaly Detection
Invoke-RestMethod -Method Post `
    -Uri http://localhost:8000/v1/tools/axis1/run `
    -Headers @{"X-API-Key"="telecom-dev-key-2024"; "Content-Type"="application/json"} `
    -Body '{"h3_resolution": 8}'

# Axis 2 — Expansion Opportunities
Invoke-RestMethod -Method Post `
    -Uri http://localhost:8000/v1/tools/axis2/run `
    -Headers @{"X-API-Key"="telecom-dev-key-2024"; "Content-Type"="application/json"} `
    -Body '{"h3_resolution": 8}'

# Axis 3 — Promotional Segmentation
Invoke-RestMethod -Method Post `
    -Uri http://localhost:8000/v1/tools/axis3/run `
    -Headers @{"X-API-Key"="telecom-dev-key-2024"; "Content-Type"="application/json"} `
    -Body '{"h3_resolution": 8}'

# Audit log query
Invoke-RestMethod -Uri http://localhost:8000/v1/audit/events `
    -Headers @{"X-API-Key"="telecom-dev-key-2024"}
```

---

## 6. Docker (Optional)

```powershell
docker compose up --build
```

The `docker-compose.yml` starts the FastAPI service. The agent CLI must still be run
separately (see Section 4.3) pointing at the container's exposed port.

---

## 7. Running Tests

```powershell
pytest tests/ -v
```

Test files:
- `tests/test_api.py` — API endpoint integration tests
- `tests/test_audit.py` — AuditLogger + SHAP tests
- `tests/test_agent.py` — End-to-end agent workflow tests (mocked HTTP)

---

## 8. Known Constraints & Caveats

| Item | Details |
|---|---|
| **Gold Feature Store** | Currently synthetic (2,000 H3 hexagons, random data). Real data requires running the ingestion connectors in `data_ingestion/connectors/`. |
| **M-Lab connector excluded** | The M-Lab/BigQuery connector was explicitly excluded — no GCP credentials needed. |
| **LLM provider** | `LLM_PROVIDER=stub` is the default and requires no credentials. `StubProvider` automatically selects all three axes. To use real LLM reasoning, switch to `watsonx` or `openai` and provide the corresponding credentials in `.env`. |
| **Windows PowerShell** | Emoji characters in terminal output can cause `UnicodeEncodeError` on cp1252 systems. All emojis have been removed from `agent/run.py`. |
| **`--axes` syntax** | In PowerShell + typer, axes must be passed as repeated flags: `--axes axis1 --axes axis2 --axes axis3`. Do **not** use commas or spaces. |
| **SHAP + async** | `shap.KernelExplainer` (Axis 3) runs in a thread via `asyncio.to_thread()` to avoid event loop conflicts with FastAPI. |
| **Sub-task plan markers** | `telecom-ai-platform-plan.md` still shows Sub-tasks 3, 5, 6 as `[ ] pending` but all are fully implemented in code. |

---

## 9. LLM Provider Reference

| Provider | `LLM_PROVIDER` value | Required env vars |
|---|---|---|
| IBM watsonx.ai | `watsonx` | `WATSONX_API_KEY`, `WATSONX_PROJECT_ID`, `WATSONX_URL`, `WATSONX_MODEL_ID` |
| OpenAI GPT-4o | `openai` | `OPENAI_API_KEY`, `OPENAI_MODEL_ID` |
| Stub (no LLM) | `stub` | none — selects all three axes automatically |

---

## 10. Sub-Task Implementation Status

| Sub-Task | Description | Status |
|---|---|---|
| 1 | Data Ingestion & Feature Store | `[x] complete` (synthetic Parquet; real connectors in `data_ingestion/`) |
| 2 | Exploratory Data Analysis & Algorithm Validation | `[x] complete` (`eda-findings.md`, `notebooks/`) |
| 3 | ML Pipeline Implementation (Three Analytical Axes) | `[x] complete` (`ml/pipelines/`) |
| 4 | Internal Tool API Layer | `[x] complete` (`api/`, `openapi.yaml`) |
| 5 | Transparency & Auditability Layer | `[x] complete` (`audit/`, `logs/audit.jsonl`) |
| 6 | Operational Agent Implementation | `[x] complete` (`agent/`, `reports/`) |

> **Note:** The `telecom-ai-platform-plan.md` file still shows Sub-tasks 3, 5, and 6 as
> `[ ] pending` — this is a documentation inconsistency; all six sub-tasks are implemented.

---

## 11. Web Interface

The platform ships with a React + Vite single-page application that exposes all capabilities through a graphical interface.

### 11.1 Prerequisites

Node.js 18+ must be installed. Verify with:

```powershell
node --version   # should print v18.x or higher
npm --version    # should print 9.x or higher
```

### 11.2 Install Frontend Dependencies

```powershell
cd frontend
npm install
```

### 11.3 Configure CORS (Backend)

Before starting both servers, ensure `.env` has the Vite dev server origin in `CORS_ORIGINS`:

```dotenv
CORS_ORIGINS=http://localhost:5173
```

Then reload the environment in both terminals (see Section 4.1).

### 11.4 Start the Web UI (Development)

With the Tool API already running on port 8000 (Section 4.2), open a third terminal:

```powershell
cd frontend
npm run dev
```

The UI is now available at: **http://localhost:5173**

The Vite dev server proxies all `/v1/*` requests to `http://localhost:8000` automatically — no CORS issues during development.

### 11.5 Pages & Features

| URL | Description |
|---|---|
| `/` | **Dashboard** — KPI cards, Leaflet map (H3 centroids), TAM bar chart, segmentation donut, investment hypothesis table. Shows empty state with CTA when no run has been made. |
| `/run` | **Análise Completa** — Form to trigger the full LangGraph agent (`POST /v1/agent/run`). Configure region, axes, LLM provider, force flag, and API key. Shows spinner overlay while running, navigates to Dashboard on success. |
| `/axis1` | **Eixo 1** — Direct call to `POST /v1/tools/axis1/run`. Sliders for anomaly threshold and contamination, map of critical hexagons, sortable results table. |
| `/axis2` | **Eixo 2** — Direct call to `POST /v1/tools/axis2/run`. Sliders for min cluster size, skip-UMAP toggle, TAM bar chart, cluster map. |
| `/axis3` | **Eixo 3** — Direct call to `POST /v1/tools/axis3/run`. Slider for k, auto-sweep toggle, segment donut chart, segment profile table. |
| `/audit` | **Auditoria** — Filter by agent_id, event_type, run_id, date range. Expandable rows show full JSON payload. Copy-to-clipboard for run_id. |

### 11.6 Production Build

```powershell
cd frontend
npm run build
```

The static bundle is output to `frontend/dist/`. Serve it with any static file server or configure FastAPI to serve it at `/` using `StaticFiles`.

### 11.7 Agent Run Timeout

The `/v1/agent/run` BFF endpoint has a configurable timeout. The default is 120 seconds. Increase it in `.env` if needed:

```dotenv
AGENT_RUN_TIMEOUT_SECONDS=180
```

HTTP 504 is returned if the agent does not complete within the configured time.
