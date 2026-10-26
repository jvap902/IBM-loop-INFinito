# Telecom AI Platform — Implementation Plan

## Top-Level Overview

**Goal:** Build an AI platform that autonomously identifies strategic opportunities for telecom infrastructure reform and expansion (5G coverage, fiber, micro-cells, antenna capacity) across Brazilian territory.

**Approach:**
1. Ingest and normalize six public/open data sources (already catalogued in `knowledge-api.json`) into a unified H3-hexagon feature store.
2. Run a short EDA + validation phase to confirm or adjust the algorithm choices described in `knowledge-api.json` before committing to production models.
3. Implement three analytical axes (anomaly detection, expansion opportunities, promotional targeting) as independently callable ML pipelines.
4. Expose every pipeline as a versioned internal API tool so an Operational Agent can invoke them autonomously via tool-calling.
5. Build a transparent, auditable Operational Agent (LangGraph-based, swappable via abstraction layer) that activates analyses, interprets clusters, and produces prescriptive reports.

**Authoritative references:**
- [`knowledge-api.json`](knowledge-api.json) — data source catalogue, H3 feature vector definition, per-axis model specification.
- [`prompts.md`](prompts.md) — original requirements document.

**LGPD compliance constraint:** All processing is performed on spatially aggregated data (H3 hexagons, census sectors). No individual-level records are stored or processed at any stage.

---

## Sub-Task 1 — Data Ingestion & Feature Store

**Status:** `[x] complete`

### Intent
Establish the ETL pipelines that pull from every external source defined in `knowledge-api.json`, apply LGPD-safe aggregation rules, and materialise a unified H3-resolution-8/9 feature store ready for ML consumption.

### Expected Outcomes
- Six source-specific ingestion connectors are operational and tested.
- Raw data is stored in a partitioned, versioned data lake (Bronze layer).
- A sanitised, spatially joined Silver layer exists, keyed on H3 hexagon ID.
- A Gold feature table with the 10-dimensional vector `x_hi = [d_down, d_up, lat, vol_test, n_dom, n_com, ren_med, n_erb, HHI, vol_reclam]` is available for ML pipelines.
- No individual-level records exist anywhere in the pipeline.

### Todo List
1. Scaffold project repository structure: `ingestion/`, `processing/`, `ml/`, `api/`, `agent/`, `audit/`.
2. Implement connector for **Ookla Speedtest Open Data** (S3 Parquet, fixed + mobile, `--no-sign-request`). Quadkey → H3 spatial join.
3. Implement connector for **IBGE CNEFE + SIDRA** (bulk Parquet download + REST API). Sector polygon → H3 weighted aggregation for `n_dom`, `n_com`, `ren_med`.
4. Implement connector for **Anatel Open Data** (CSV bulk for SCM + SMP + Reclamações + Mosaico Estações). Compute `HHI` per municipality, `vol_reclam` per 1,000 accesses, join `n_erb` from Mosaico.
5. Implement connector for **OpenCelliD** (daily gzip CSV dump via API key). Filter `mcc=724` (Brazil). H3 density count for `n_erb` (supplement to Anatel Mosaico).
6. Implement connector for **M-Lab NDT** (BigQuery `measurement-lab.ndt.unified_downloads/uploads`). Aggregate `MinRTT`, `LossRate`, `MeanThroughputMbps` per H3.
7. Implement connector for **Cloudflare Radar API** (REST, Bearer Token). Store outage + traffic anomaly annotations as a time-series reference table (used for cross-validation in Axis 1, not in the static feature vector).
8. Build spatial join layer: convert all coordinate-based records to H3 index using `h3-py`. Resolutions 8 and 9 both materialised.
9. Implement sanitisation rules: clip outliers (IQR × 3), impute missing cells via spatial median from ring-1 neighbours, flag hexagons with < 3 Ookla tests as low-confidence.
10. Build Silver → Gold aggregation: compute final `x_hi` vector per hexagon, persist as Apache Parquet partitioned by `(year, month, h3_res)`.
11. Write data quality checks (Great Expectations or Pydantic validators) asserting no null in required fields, H3 coverage > 80% of populated municipalities, `HHI` in `[0, 10000]`.
12. Schedule ingestion DAGs (Apache Airflow or Prefect) with update cadences matching source frequencies (Ookla: quarterly, IBGE: static, Anatel: monthly, OpenCelliD: daily, M-Lab: daily, Cloudflare: near-real-time).

### Relevant Context
- `knowledge-api.json` → `sources[]` — complete API contracts, auth methods, schema fields, and update frequencies for all six sources.
- `knowledge-api.json` → `agent_pipeline_specification.h3_feature_vector` — canonical definition of `x_hi` and each component's source.
- Spatial standard: `spatial_index_standard = "Uber H3"`, `recommended_resolutions = [8, 9]`.

### Stack
| Layer | Technology |
|---|---|
| Orchestration | Apache Airflow 2.x (or Prefect 2) |
| Storage - Bronze | AWS S3 / MinIO (Parquet, partitioned) |
| Storage - Gold | DuckDB (local dev) / Apache Iceberg on S3 (prod) |
| Spatial ops | `h3-py`, `geopandas`, `shapely` |
| Data quality | Great Expectations or Pydantic v2 |
| BigQuery access | `google-cloud-bigquery` Python SDK |

---

## Sub-Task 2 — Exploratory Data Analysis & Algorithm Validation

**Status:** `[ ] pending`

### Intent
Before committing to the production model architecture, perform a structured EDA and baseline comparison to confirm (or adjust) the algorithm choices in `knowledge-api.json`. This is a time-boxed discovery phase — its output is a brief findings document that either validates the spec or proposes amendments.

### Expected Outcomes
- Correlation matrix and VIF check for all 10 `x_hi` features is documented.
- One baseline pass per axis (IsolationForest, HDBSCAN, K-Means++ k=3) is executed and scored.
- A single `eda-findings.md` decision table records each algorithm's metric score, accept/adjust decision, and rationale.

### Todo List
1. Build an EDA notebook (`notebooks/01_eda_feature_store.ipynb`): Pearson + Spearman correlation matrix and VIF check (> 10 flags multicollinearity) for all `x_hi` features.
2. **Axis 1 baseline:** run `IsolationForest` with default hyperparameters; measure agreement rate against Cloudflare Radar outage annotations (ground-truth proxy). Accept if agreement ≥ 60%, otherwise note adjustment needed.
3. **Axis 2 baseline:** run HDBSCAN with default `min_cluster_size`; evaluate with Silhouette Score; verify high-density / low-speed hexagons concentrate in the same clusters.
4. **Axis 3 baseline:** run K-Means++ with k=3 (matching the three named profiles); check Silhouette Score. Accept if score > 0.3, otherwise sweep k ∈ [3, 6].
5. Document findings in `eda-findings.md` — a single decision table: algorithm, metric score, decision (confirm / adjust), and rationale.
6. If any algorithm is adjusted, update `knowledge-api.json` accordingly (single source of truth for pipeline spec).

### Relevant Context
- `knowledge-api.json` → `agent_pipeline_specification.analytical_modules[]` — current algorithm choices and their `input_features` per axis.
- Axis 1 anomaly threshold: `s(x, n) >= 0.65` (Isolation Forest scoring convention).
- HDBSCAN `clustering_criteria` hint: `n_dom + n_com` high, `d_down < 30 Mbps`, `HHI > 3500`.

### Stack
| Layer | Technology |
|---|---|
| EDA | Jupyter Lab, `pandas`, `plotly`, `seaborn` |
| Clustering | `scikit-learn`, `hdbscan` |
| Metrics | `scikit-learn.metrics` (Silhouette Score) |

---

## Sub-Task 3 — ML Pipeline Implementation (Three Analytical Axes)

**Status:** `[ ] pending`

### Intent
Implement the three production ML pipelines confirmed by Sub-Task 2. Each pipeline is self-contained, versioned, and produces a structured output artefact (scored hexagon table) consumable by downstream agents and APIs.

### Expected Outcomes
- **Axis 1 pipeline** (`axis_maintenance_criticality`): scores every hexagon with an anomaly score; hexagons with score ≥ threshold are flagged as critical; enriched with Cloudflare Radar cross-validation signal.
- **Axis 2 pipeline** (`axis_expansion_opportunities`): produces labelled cluster assignments for expansion candidate hexagons; noise points (-1) explicitly handled.
- **Axis 3 pipeline** (`axis_promotional_targeting`): assigns every hexagon to one of k promotional segments with a named profile (Premium, High Churn Risk, Essential Connectivity).
- Each pipeline writes its output to the Gold layer as a Parquet table and logs run metadata (model version, hyperparameters, run timestamp, metrics) to an MLflow experiment.
- Re-training trigger is defined per axis (schedule-based + drift-based).

### Todo List
1. Implement `pipeline_axis1.py`: StandardScaler → (optional UMAP) → IsolationForest + LOF ensemble; output columns `[h3_id, anomaly_score, is_critical, lof_score, cloudflare_outage_overlap]`.
2. Implement `pipeline_axis2.py`: StandardScaler → UMAP (if confirmed) → HDBSCAN; output columns `[h3_id, cluster_id, cluster_size, avg_d_down, avg_n_dom, avg_HHI, is_noise]`.
3. Implement `pipeline_axis3.py`: StandardScaler → K-Means++ (k from EDA); output columns `[h3_id, segment_id, segment_name, centroid_distance, silhouette_score_local]`.
4. For each pipeline, implement a `validate_output()` function: assert no nulls in key fields, cluster count within expected range, anomaly rate between 1–15% (Axis 1), noise rate < 25% (Axis 2).
5. Integrate MLflow tracking: log `params`, `metrics`, and the serialised model artifact (`.pkl`) per run.
6. Implement `drift_detector.py`: compute Population Stability Index (PSI) on the Gold feature table monthly; if PSI > 0.2 for any feature, trigger a pipeline re-run via Airflow.
7. Write unit tests for each pipeline covering: valid input, missing H3 cells, all-NaN feature column, single-cluster degenerate case.

### Relevant Context
- `knowledge-api.json` → `agent_pipeline_specification.analytical_modules[]` — per-axis `input_features`, `primary_model`, `secondary_model`, thresholds, and `llm_action` descriptions.
- EDA findings from Sub-Task 2 determine final dimensionality reduction and hyperparameters.
- Anomaly threshold for Axis 1: `s(x, n) >= 0.65`.

### Stack
| Layer | Technology |
|---|---|
| ML | `scikit-learn`, `hdbscan`, `umap-learn` |
| Experiment tracking | MLflow (self-hosted or Databricks) |
| Serialisation | `joblib` |
| Drift detection | `nannyml` or custom PSI |
| Testing | `pytest` + `pytest-mock` |

---

## Sub-Task 4 — Internal Tool API Layer (Tool-Calling Interface)

**Status:** `[ ] pending`

### Intent
Wrap each ML pipeline behind a versioned REST API so that the Operational Agent can invoke them programmatically via tool-calling. Define strict input/output contracts, configurable parameters, and an OpenAPI schema that the agent's tool registry can consume. The API is designed to also serve a future BI dashboard as an additional consumer.

### Expected Outcomes
- Three tool endpoints are live and documented: `POST /tools/axis1/run`, `POST /tools/axis2/run`, `POST /tools/axis3/run`.
- Each endpoint accepts a JSON body with configurable parameters (filter region, model hyperparameters, feature weights) and returns a structured JSON result.
- An OpenAPI 3.1 schema (`openapi.yaml`) exists and is the single source of truth for all tool contracts.
- A health check endpoint (`GET /health`) and a capability discovery endpoint (`GET /tools`) exist.
- Authentication is enforced (API key header) for all write/run endpoints.
- Response payloads include GeoJSON-compatible geometry fields (`h3_id`, `lat_centroid`, `lon_centroid`) so a future dashboard layer can render hexagon results without additional transformation.

### Todo List
1. Scaffold FastAPI application (`api/main.py`). Configure structured logging (JSON format, including `run_id`, `axis`, `region_filter`, `timestamp`).
2. Define Pydantic request/response models for each axis. Common request fields:

   | Field | Type | Description |
   |---|---|---|
   | `region_filter` | `H3RegionFilter` | Optional: list of H3 parent cells at res-5/6 to restrict analysis |
   | `h3_resolution` | `int` (8 or 9) | Target resolution |
   | `feature_weights` | `dict[str, float]` | Optional override of equal feature weights |
   | `min_cluster_size` | `int` | Axis 2 only: HDBSCAN `min_cluster_size` |
   | `n_clusters` | `int` | Axis 3 only: K-Means k override |
   | `anomaly_threshold` | `float` | Axis 1 only: override of 0.65 default |

3. Implement `POST /tools/axis1/run`: validates request → loads Gold Parquet → runs `pipeline_axis1` → returns scored hexagon list (top-N anomalies, default 50).
4. Implement `POST /tools/axis2/run`: runs `pipeline_axis2` → returns cluster summary (cluster_id, size, centroid coordinates, avg feature values, TAM estimate).
5. Implement `POST /tools/axis3/run`: runs `pipeline_axis3` → returns segment assignment table with segment profile metadata.
6. Implement `GET /tools`: returns a machine-readable catalogue of available tools, their parameters, and descriptions — this is the agent's tool registry source.
7. Generate and validate `openapi.yaml` via `fastapi` built-in schema export. Keep it committed to the repo as the contract artefact.
8. Add API key middleware (`api/auth.py`). Keys stored in environment variables or a secrets manager, never hardcoded.
9. Write integration tests for each endpoint: valid request, invalid region filter, resolution out of range, empty result set.
10. Add `POST /tools/axis1/crossvalidate` endpoint that accepts a date range and calls Cloudflare Radar `/annotations/outages` to overlay anomaly flags with known outage events — returns an overlap summary for audit purposes.

### Relevant Context
- `knowledge-api.json` → `agent_pipeline_specification.analytical_modules[].llm_action` — describes how the agent is expected to use each tool's output.
- The OpenAPI schema will be directly consumed by the LangGraph tool-calling layer in Sub-Task 5.

### Stack
| Layer | Technology |
|---|---|
| API framework | FastAPI + Uvicorn |
| Validation | Pydantic v2 |
| Schema | OpenAPI 3.1 (auto-generated by FastAPI) |
| Auth | API Key header middleware |
| Testing | `pytest` + `httpx` (async test client) |
| Containerisation | Docker + Docker Compose |

---

## Sub-Task 5 — Transparency & Auditability Layer

**Status:** `[ ] pending`

### Intent
Implement cross-cutting transparency mechanisms that apply to both the Planner Agent (this planning artefact) and the Operational Agent. Every decision, tool call, and model output must be traceable by human reviewers.

### Expected Outcomes
- A structured audit log schema is defined and implemented.
- Every agent action (tool invocation, reasoning step, report generation) is persisted as an auditable event.
- ML model outputs are enriched with local explainability scores (SHAP values).
- An audit query API allows human reviewers to retrieve the full decision chain for any report or cluster run.
- The planning artefact itself (this file) is versioned in git and treated as the Planner Agent's chain-of-thought record.

### Todo List
1. Define `AuditEvent` schema (`audit/schema.py`):
   ```
   {
     "event_id": uuid,
     "timestamp": ISO-8601,
     "agent_id": str,        # "planner" | "operational"
     "event_type": str,      # "tool_call" | "reasoning_step" | "report_generated" | "model_run"
     "tool_name": str | null,
     "tool_input": dict | null,
     "tool_output_summary": str | null,
     "reasoning_text": str | null,
     "run_id": str | null,
     "model_version": str | null
   }
   ```
2. Implement `AuditLogger` class with methods `log_tool_call()`, `log_reasoning()`, `log_model_run()`. Persist to append-only JSONL file and/or PostgreSQL `audit_events` table.
3. Integrate `AuditLogger` into every FastAPI tool endpoint: log request, run metadata, and output summary on each invocation.
4. Integrate `AuditLogger` into the LangGraph agent (Sub-Task 6): wrap every node execution with an audit event.
5. Implement SHAP explainability for each axis:
   - Axis 1 (IsolationForest): use `shap.TreeExplainer`; include top-3 contributing features per anomalous hexagon in the tool API response.
   - Axis 2 (HDBSCAN): SHAP is not directly applicable; instead, compute per-cluster feature means and Z-scores relative to the global distribution as a proxy explanation.
   - Axis 3 (K-Means++): use `shap.KernelExplainer` on centroid distances; include top-3 features per segment in the report.
6. Add a `GET /audit/events` endpoint with filters `(agent_id, event_type, date_range, run_id)` for human reviewer access.
7. Document the auditability model in `audit/README.md`: what is logged, retention policy, access control.

### Relevant Context
- Etapa 4 requirement: Chain-of-Thought logging, action logs, and tool-call justification for both Planning and Operational agents.
- The Planner Agent's chain-of-thought is this plan file, versioned in git.

### Stack
| Layer | Technology |
|---|---|
| Explainability | `shap` |
| Audit storage | JSONL (dev) / PostgreSQL `audit_events` (prod) |
| API | FastAPI (same service as Tool API, `/audit` prefix) |

---

## Sub-Task 6 — Operational Agent Implementation

**Status:** `[ ] pending`

### Intent
Build the autonomous Operational Agent that orchestrates the three analytical axes, interprets the results, and produces prescriptive infrastructure expansion reports. The agent is implemented in LangGraph with a swappable LLM backend and a clean abstraction boundary over the tool layer.

### Expected Outcomes
- An end-to-end agent workflow is implemented: trigger → gap detection → tool activation → interpretation → report generation.
- The agent can be invoked on-demand or on schedule.
- Every agent run produces a structured Markdown + JSON prescriptive report.
- The agent framework is swappable (LangGraph is default; the tool abstraction layer allows migration to CrewAI or other frameworks without rewriting tools).
- All agent actions are persisted to the audit log (Sub-Task 5).

### Architecture

The agent is implemented as a **LangGraph StateGraph** with the following nodes:

```
[START]
   │
   ▼
[gap_detector]          ← Checks Gold feature store for unanalysed regions / stale runs
   │
   ▼
[tool_selector]         ← Decides which axis/axes to invoke based on gap + user directive
   │
   ├──► [axis1_runner]  ← Calls POST /tools/axis1/run
   ├──► [axis2_runner]  ← Calls POST /tools/axis2/run
   └──► [axis3_runner]  ← Calls POST /tools/axis3/run
          │
          ▼
   [result_interpreter] ← Merges outputs, cross-references axes, derives investment hypotheses
          │
          ▼
   [report_writer]      ← Generates prescriptive Markdown report (see report schema below)
          │
          ▼
        [END]
```

### Todo List
1. Define `AgentState` TypedDict (`agent/state.py`): `region_scope`, `axes_requested`, `axis1_result`, `axis2_result`, `axis3_result`, `investment_hypotheses`, `report_markdown`, `audit_trail`.
2. Implement `gap_detector` node: query Gold feature store for hexagons not analysed in the last N days; if coverage is full, proceed anyway if invoked with explicit `force=True`.
3. Implement `tool_selector` node: LLM-driven reasoning step — given the gap report and optional user directive (e.g. "focus on São Paulo metro for 5G"), decide which combination of axes to run and with what parameters. Log this reasoning step to audit.
4. Implement `axis1_runner`, `axis2_runner`, `axis3_runner` nodes: each calls the corresponding FastAPI tool endpoint via HTTP; handles errors with retry (max 3, exponential backoff); appends `AuditEvent` for each call.
5. Implement `result_interpreter` node:
   - Cross-reference Axis 1 anomaly hexagons with Axis 2 expansion clusters: hexagons that are both critical AND in an expansion cluster are the highest-priority investment targets.
   - Cross-reference Axis 3 segments with Axis 2 clusters: identify clusters dominated by "Alta Vulnerabilidade Concorrência" → churn-risk expansion zones.
   - Compute TAM estimate: `n_dom × estimated_ARPU × (1 - current_penetration_rate)` per cluster.
   - Log all cross-reference logic as a reasoning step to audit.
6. Implement `report_writer` node: use an LLM to produce a structured Markdown report with the following mandatory sections:
   ```
   # Relatório Prescritivo de Expansão de Infraestrutura — {region} — {date}
   ## 1. Sumário Executivo
   ## 2. Situação Atual da Infraestrutura (Axis 1 findings)
   ## 3. Oportunidades de Expansão Identificadas (Axis 2 clusters)
   ## 4. Segmentação de Mercado para Promoções (Axis 3 segments)
   ## 5. Priorização de Investimentos (cross-reference matrix)
   ## 6. Estimativa de Retorno (TAM / ARPU / CAPEX proxy)
   ## 7. Próximas Ações Recomendadas
   ## Apêndice: Metodologia e Auditabilidade
   ```
7. Implement LLM abstraction layer (`agent/llm_provider.py`): a `BaseLLMProvider` protocol with `chat()` and `tool_call()` methods. Implement `WatsonxProvider` (default) and `OpenAIProvider` as concrete classes. Active provider is selected via environment variable `LLM_PROVIDER` (default: `"watsonx"`).
8. Implement tool abstraction layer (`agent/tool_registry.py`): loads tool definitions from `GET /tools` endpoint at startup; provides `invoke_tool(name, params)` method. Allows dropping in any new tool endpoint without agent code changes.
9. Implement agent entrypoint (`agent/run.py`): accepts `--region`, `--axes`, `--force` CLI arguments; builds `AgentState`; runs LangGraph workflow; writes report to `reports/{region}_{date}.md` and `reports/{region}_{date}.json`.
10. Write end-to-end integration test: mock all three tool endpoints, run full agent workflow, assert report contains all 7 mandatory sections and `audit_trail` has ≥ 5 events.

### Relevant Context
- `knowledge-api.json` → `agent_pipeline_specification.analytical_modules[].llm_action` — the intended LLM reasoning action for each axis result.
- Sub-Task 4 `GET /tools` endpoint provides the machine-readable tool registry.
- Sub-Task 5 `AuditLogger` must be injected into every node.

### Stack
| Layer | Technology |
|---|---|
| Agent framework | LangGraph (default), abstracted for CrewAI swap |
| LLM backend | IBM watsonx.ai (default) / OpenAI GPT-4o (alternate) |
| HTTP client | `httpx` (async) |
| CLI | `typer` |
| Testing | `pytest` + `respx` (HTTP mock) |

---

## Cross-Cutting Decisions

### LGPD Compliance
- All ingestion connectors operate exclusively on spatially aggregated outputs (H3 hexagons, census sectors). No individual address records, device IDs, or personally identifiable information is retained.
- CNEFE coordinates are consumed to compute `n_dom`/`n_com` counts per hexagon, then immediately discarded — raw CNEFE files are not persisted in the data lake.
- Ookla data is already anonymised at tile level (Quadkey zoom 16 ≈ 610 m) — no de-anonymisation is attempted.
- Data retention policy: Bronze layer 12 months rolling; Gold layer indefinite (it is derived, aggregated, non-personal).

### Swappable Orchestration
The `tool_registry.py` abstraction means that replacing LangGraph with CrewAI or AutoGen requires only re-implementing the graph/crew definition file — the tool layer, audit layer, and ML pipelines are untouched.

### Configuration Management
All secrets (API keys, LLM keys, DB credentials) are managed via environment variables. A `.env.example` file documents all required variables. Never hardcoded.

### Versioning
- ML models: versioned in MLflow Model Registry.
- Tool API: versioned via URL prefix (`/v1/tools/...`).
- Feature store: versioned via Parquet partition `(year, month)`.
- This plan file: versioned in git.

---

## Milestone Summary

| Milestone | Sub-Tasks | Deliverable |
|---|---|---|
| M1 — Data Foundation | Sub-Task 1 | Gold feature store live, data quality checks passing |
| M2 — Algorithm Validation | Sub-Task 2 | `eda-findings.md`, confirmed algorithm choices |
| M3 — ML Pipelines | Sub-Task 3 | Three production pipelines, MLflow experiments tracked |
| M4 — Tool API | Sub-Task 4 | `openapi.yaml`, three live endpoints, integration tests green |
| M5 — Auditability | Sub-Task 5 | Audit log live, SHAP explainability integrated |
| M6 — Operational Agent | Sub-Task 6 | End-to-end agent workflow, sample prescriptive report generated |
