# Transparency & Auditability Layer — Governance Documentation

> **Sub-Task 5 | Telecom AI Platform**

---

## 1. Purpose and Scope

The Transparency & Auditability Layer provides a complete, tamper-evident audit
trail for every decision made by the Telecom AI Platform's analytical engines
and autonomous agents.  It is designed to satisfy the following governance
requirements:

| Requirement | How it is met |
|---|---|
| Traceability of AI decisions | Every `tool_call`, `model_run` and `reasoning_step` is written to an append-only log before the HTTP response is returned. |
| Explainability of ML outcomes | SHAP or proxy Z-score explanations are attached to each `model_run` event (see §4). |
| Human oversight | The `GET /v1/audit/events` REST endpoint enables compliance officers and auditors to query events without direct log-file access. |
| LGPD compliance | PII is blocked at write time (§3). No subscriber-level data enters the log. |
| Data minimisation | Only high-level output summaries (counts, rates, durations) are stored — never raw result payloads. |

---

## 2. Module Structure

```
audit/
├── __init__.py          Package marker + module docstring
├── schema.py            AuditEvent Pydantic model (canonical event structure)
├── logger.py            AuditLogger class (JSONL and PostgreSQL backends)
├── explainability.py    SHAP and proxy explainability for Axes 1, 2, 3
└── README.md            This file
```

---

## 3. AuditEvent Schema

Every event is serialised as a single JSON object (one per line in JSONL mode):

```json
{
  "event_id":             "f3c2a1b0-...",      // UUID v4, unique per event
  "timestamp":            "2024-03-15T14:22:01.123456+00:00",  // ISO-8601 UTC
  "agent_id":             "operational",        // planner | operational | system
  "event_type":           "tool_call",          // see §3.1
  "run_id":               "9e8d7c6b-...",        // links events within one run
  "model_version":        "1.0.0",              // optional
  "tool_name":            "axis1_run",          // endpoint/model identifier
  "tool_input":           { "contamination": 0.05, "h3_resolution": 8 },
  "tool_output_summary":  { "n_critical": 17, "duration_seconds": 1.23 },
  "reasoning_text":       null,                 // populated for reasoning_step
  "explanation":          { "status": "ok", "method": "TreeExplainer", ... }
}
```

### 3.1 Event Types

| `event_type` | When recorded |
|---|---|
| `tool_call` | Agent (or API client) calls a `/tools/axis*/run` endpoint. |
| `model_run` | Direct ML pipeline execution (e.g. batch jobs outside the API). |
| `reasoning_step` | Agent Chain-of-Thought step (Planner or Operational Agent). |
| `report_generated` | Final analytical report assembled and delivered to stakeholders. |

### 3.2 PII Guardrails

The logger automatically removes any key matching the blocklist below (case-insensitive)
from `tool_input` before persisting.  This is a defence-in-depth measure; the primary
control is that the API layer must never route subscriber-level data to these endpoints.

**Blocked keys:** `cpf`, `cnpj`, `nome`, `name`, `email`, `phone`, `telefone`,
`celular`, `subscriber_id`, `customer_id`, `msisdn`, `imsi`, `password`, `senha`,
`token`, `secret`, `api_key`.

Spatial identifiers (`h3_id`) are **safe to record** — they represent geographic
aggregates at H3 resolution 8 or 9, not individual subscribers.

---

## 4. Explainability Model

### 4.1 Axis 1 — IsolationForest (TreeExplainer)

**Method:** `shap.TreeExplainer` computes exact Shapley values for the
IsolationForest by traversing its ensemble of isolation trees.

**Output attached to the audit event:**

```json
{
  "status": "ok",
  "method": "TreeExplainer",
  "n_explained": 17,
  "top_features": [
    { "feature": "vol_reclam", "shap_value": 0.142 },
    { "feature": "d_down",     "shap_value": -0.089 },
    { "feature": "lat",        "shap_value": 0.031 }
  ],
  "global_importance": { "vol_reclam": 0.142, "d_down": 0.089, "lat": 0.031 }
}
```

**Interpretation:** Features with large positive SHAP values pushed the
anomaly score upward (toward "critical"); negative values indicate the feature
pulled the score downward (toward "normal").  The top-3 list covers the
hexagons actually flagged as critical so the explanation is local and actionable.

### 4.2 Axis 2 — HDBSCAN (Z-score Proxy)

**Method:** HDBSCAN is a density estimator with no tree structure amenable to
exact SHAP.  A Z-score proxy compares each cluster's feature means to the
global distribution.  Features with the largest |Z| are the most "discriminating"
for that cluster.

**Output:**

```json
{
  "status": "ok",
  "method": "cluster_zscore_proxy",
  "n_clusters_explained": 5,
  "clusters": {
    "0": {
      "cluster_id": 0,
      "n_hexagons": 312,
      "top_features": [
        { "feature": "d_down", "z_score": 2.41, "cluster_mean": 87.3, "global_mean": 43.1 },
        { "feature": "n_dom",  "z_score": 1.98, "cluster_mean": 195.2, "global_mean": 101.4 },
        { "feature": "HHI",    "z_score": -1.74, "cluster_mean": 2200.0, "global_mean": 4100.0 }
      ]
    }
  }
}
```

**Interpretation:** A cluster with high positive Z-score on `d_down` has
well-above-average download speeds, making it a high-quality expansion zone.
A negative Z-score on `HHI` indicates lower market concentration (more competition).

### 4.3 Axis 3 — K-Means++ (KernelExplainer)

**Method:** `shap.KernelExplainer` approximates Shapley values using a
model-agnostic perturbation approach.  The predict function is defined as the
softmax probability of cluster assignment based on centroid distance.  To bound
latency, at most 200 rows are explained per run (configurable via
`MAX_KERNEL_ROWS` in `audit/explainability.py`).

**Output:**

```json
{
  "status": "ok",
  "method": "KernelExplainer",
  "n_explained": 200,
  "segments": {
    "0": {
      "segment_id": 0,
      "n_samples_explained": 72,
      "top_features": [
        { "feature": "ren_med",    "shap_value": 0.312 },
        { "feature": "HHI",        "shap_value": 0.215 },
        { "feature": "vol_reclam", "shap_value": 0.187 }
      ],
      "mean_abs_shap": { "ren_med": 0.312, "HHI": 0.215, "vol_reclam": 0.187, ... }
    }
  }
}
```

**Interpretation:** Large `ren_med` SHAP value confirms that income is the
primary driver assigning hexagons to the "Premium" segment.

### 4.4 Graceful Degradation

If `shap` is not installed the explanation payload is:

```json
{ "status": "shap_unavailable", "reason": "shap not installed (pip install shap)", "top_features": [] }
```

This ensures the API always returns a response even when the XAI library is
absent.  The audit log still records all other event fields.

---

## 5. Backend Configuration

| Environment variable | Default | Description |
|---|---|---|
| `AUDIT_BACKEND` | `jsonl` | Storage backend (`jsonl` or `postgres`). |
| `AUDIT_JSONL_PATH` | `logs/audit.jsonl` | Path to the JSONL log file (jsonl backend). |
| `AUDIT_DB_DSN` | _(empty)_ | PostgreSQL connection string (postgres backend). |

### 5.1 JSONL Backend (Development)

Events are appended as newline-delimited JSON to a local file.  Concurrent
writes are protected by a `threading.Lock`.  The file is created (along with
parent directories) on first write.

**Rotation:** The JSONL backend does not rotate files automatically.  Use
logrotate or a scheduled job to archive `audit.jsonl` periodically.

### 5.2 PostgreSQL Backend (Production)

The logger INSERTs one row per event into the `audit_events` table (created
automatically on first connection):

```sql
CREATE TABLE audit_events (
    event_id            TEXT PRIMARY KEY,
    timestamp           TIMESTAMPTZ NOT NULL,
    agent_id            TEXT,
    event_type          TEXT NOT NULL,
    tool_name           TEXT,
    tool_input          JSONB,
    tool_output_summary JSONB,
    reasoning_text      TEXT,
    run_id              TEXT,
    model_version       TEXT,
    explanation         JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
```

Indexes on `agent_id`, `event_type`, `run_id` and `timestamp` are created
automatically to support the query patterns of `GET /audit/events`.

**Connection model:** One connection per write (psycopg2 context manager).
For high write throughput, replace with `psycopg2.pool.ThreadedConnectionPool`
or migrate to `asyncpg`.

---

## 6. Query API

### `GET /v1/audit/events`

**Authentication:** `X-API-Key` header (same key used for tool endpoints).

**Query parameters:**

| Parameter | Type | Description |
|---|---|---|
| `agent_id` | string | Filter by agent (`planner`, `operational`, `system`). |
| `event_type` | string | Filter by type (`tool_call`, `reasoning_step`, …). |
| `run_id` | string | Trace all events belonging to one pipeline run. |
| `date_start` | ISO-8601 datetime | Earliest timestamp (inclusive). |
| `date_end` | ISO-8601 datetime | Latest timestamp (inclusive). |
| `limit` | integer (1–1000) | Maximum events to return (newest first). Default 100. |

**Example:**

```bash
curl -H "X-API-Key: $TOOL_API_KEY" \
  "http://localhost:8000/v1/audit/events?event_type=tool_call&limit=20"
```

---

## 7. Data Retention and LGPD Compliance

### 7.1 Retention Policy

| Storage tier | Retention period | Disposal method |
|---|---|---|
| Hot (JSONL / PostgreSQL) | 90 days | Automated deletion / archival script |
| Cold (compressed archive) | 5 years | Encrypted S3-compatible object storage |
| Permanent deletion | After 5 years | Secure erasure per ABNT NBR ISO/IEC 27001 |

### 7.2 LGPD Obligations (Lei 13.709/2018)

1. **Minimisation:** Only operational metadata (scores, counts, durations,
   spatial H3 IDs) enters the audit log.  No subscriber names, CPF/CNPJ,
   contact details, or individual usage records are logged.

2. **Transparency:** This document constitutes the processing register required
   by Art. 37 LGPD for the AI system's automated processing activities.

3. **Access and correction:** Requests from data subjects must be routed through
   the Data Protection Officer (DPO).  The audit log itself is a compliance
   artefact — it does not contain personal data that would trigger Art. 18
   rights (access, correction, deletion) for data subjects.

4. **Security:** In production, the PostgreSQL backend should use TLS for the
   connection (`sslmode=require` in the DSN) and the JSONL file should reside
   on an encrypted volume.  API access is protected by the `X-API-Key`
   authentication layer.

5. **International transfers:** If the PostgreSQL instance is hosted outside
   Brazil, ensure the cloud provider satisfies the adequacy conditions of
   Art. 33 LGPD.

### 7.3 Auditor Access

Auditors should use the `GET /v1/audit/events` endpoint rather than direct
file/database access.  For forensic investigations requiring full log dumps,
access to the underlying storage must be approved by the DPO and logged
separately in the access management system.

---

## 8. Installing the `shap` Library

SHAP is listed as an optional dependency in `requirements.txt`.  To enable
full XAI functionality:

```bash
pip install shap>=0.44.0
```

For Axis 3 `KernelExplainer`, the `shap` package must be installed.  Axis 2
(Z-score proxy) has no additional dependencies.

---

_Last updated: Sub-Task 5 implementation — Telecom AI Platform_
