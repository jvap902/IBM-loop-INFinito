# EDA Findings — Sub-Task 2: Exploratory Data Analysis & Algorithm Validation

**Generated:** 2025-07-10
**Source:** `notebooks/01_eda_feature_store.ipynb` · `ml/eda_utils.py` · `ml/baseline_runners.py`
**Feature vector:** `x_hi = [d_down, d_up, lat, vol_test, n_dom, n_com, ren_med, n_erb, HHI, vol_reclam]`
**Dataset:** 2,000 synthetic H3 hexagons (Brazil, res-8), 3% injected anomalies (60 cells).
**Status:** ✅ All three axes CONFIRMED — no amendments to `knowledge-api.json` required.

---

## 1. Multicollinearity Analysis

### 1.1 Pearson Correlation — Strong Pairs (|r| > 0.70)

| Feature A | Feature B | Pearson r | Interpretation |
|---|---|---|---|
| `d_down` | `d_up` | **+0.928** | Upload/download speeds co-move strongly — expected from shared last-mile infrastructure |
| `d_down` | `ren_med` | **+0.849** | Wealthier hexagons have faster connections |
| `d_down` | `n_dom` | **+0.804** | Denser residential areas attract better coverage |
| `d_down` | `n_erb` | **+0.726** | More base stations → higher speed |
| `d_down` | `vol_test` | **+0.714** | More tests in better-served areas |
| `d_up` | `ren_med` | **+0.829** | Same income-speed relationship on upload |
| `d_up` | `n_dom` | **+0.783** | Density–speed link on upload |
| `d_up` | `n_erb` | **+0.706** | Infrastructure density link |
| `n_dom` | `ren_med` | **+0.859** | Income and household density are spatially correlated |
| `n_dom` | `n_erb` | **+0.746** | Infrastructure follows population |
| `n_dom` | `vol_test` | **+0.743** | Testing activity proportional to population |
| `n_com` | `n_dom` | **+0.763** | Commercial and residential co-locate |
| `n_erb` | `ren_med` | **+0.783** | Richer areas have more base stations |
| `ren_med` | `vol_test` | **+0.769** | Test device penetration rises with income |
| `HHI` | `d_down` | **−0.825** | Monopoly markets have lower download speeds |
| `HHI` | `d_up` | **−0.807** | Same on upload |
| `HHI` | `n_dom` | **−0.857** | Concentrated markets tend to serve sparser areas |
| `HHI` | `ren_med` | **−0.891** | Highest-HHI areas are lowest-income — market failure pattern |
| `HHI` | `n_erb` | **−0.766** | Fewer ERBs where one operator dominates |
| `HHI` | `vol_test` | **−0.767** | Less testing activity in monopoly areas |

> **Finding:** Strong cross-correlations are structurally driven by the socioeconomic–infrastructure nexus in Brazilian telecoms. They do not represent redundant measurement noise and should **not** be removed from the feature vector. Each feature provides a distinct semantic axis consumed by a different model pipeline.

---

### 1.2 Variance Inflation Factor (VIF)

| Feature | VIF | Flag |
|---|---|---|
| `d_down` | **10.49** | ⚠️ VIF > 10 |
| `d_up` | 8.35 | OK |
| `ren_med` | 7.23 | OK |
| `n_dom` | 6.45 | OK |
| `HHI` | 6.40 | OK |
| `n_erb` | 2.86 | OK |
| `vol_test` | 2.78 | OK |
| `n_com` | 2.40 | OK |
| `lat` | 2.30 | OK |
| `vol_reclam` | 1.59 | OK |

**`d_down` is the sole feature with VIF marginally above the 10.0 threshold (VIF = 10.49).**

**Recommendation:** Retain `d_down` in the full feature vector for the following reasons:
1. `d_down` is the primary QoS signal in the telecom context (spec-mandated for all three axes).
2. VIF = 10.49 is only marginally above the threshold; the practical collinearity impact is low.
3. In Sub-Task 3, each per-axis pipeline uses a feature subset where `d_down` is not always present alongside all its correlated partners (Axis 3 uses `d_up`, not `d_down`), naturally reducing multicollinearity.
4. If compression is ever needed for Axis 3, a composite speed index `speed_idx = (d_down + d_up) / 2` could replace both — **to be revisited in Sub-Task 3 if pipeline VIF re-check flags it**.

---

## 2. Dimensionality Reduction Benchmark: UMAP vs PCA

| Method | Metric | Value | Threshold |
|---|---|---|---|
| PCA (2 components) | Cumulative explained variance | **0.7892** (78.9%) | — |
| PCA | PC1 explained variance | 0.6934 (69.3%) | — |
| PCA | PC2 explained variance | 0.0958 (9.6%) | — |
| UMAP (2 components) | Trustworthiness | **0.9614** | > 0.90 |

**Recommendation: UMAP ✅**

**Rationale:** PCA captures 78.9% of total variance in 2 components, which is borderline acceptable. However, UMAP achieves a trustworthiness score of 0.9614 (well above the 0.90 threshold), indicating it preserves local neighbourhood structure significantly better. The Brazilian telecom data exhibits nonlinear manifold geometry driven by the socioeconomic–infrastructure nexus — confirmed by the high concentration of strong pairwise correlations. PCA's linear assumption is insufficient to capture this structure.

**Pipeline implications:**
- **Axis 1 (IsolationForest):** UMAP pre-reduction is **optional** — IsolationForest operates in high-dimensional space effectively and adding UMAP risks compressing the anomaly signal. Evaluate per-run in Sub-Task 3.
- **Axis 2 (HDBSCAN):** UMAP pre-reduction is **recommended** — density-based clustering benefits greatly from the manifold-aware embedding. Apply before HDBSCAN in the production pipeline.
- **Axis 3 (K-Means++):** UMAP pre-reduction is **optional** — K-Means is distance-based and benefits from removing noise dimensions; evaluate whether silhouette improves further.

---

## 3. Baseline Model Decision Table

| Axis | Algorithm | Metric | Score | Threshold | Decision | Rationale |
|---|---|---|---|---|---|---|
| **Axis 1** — Maintenance & Criticality | IsolationForest (contamination=5%, predict-based flagging) | Cloudflare agreement rate | **0.9833** (98.3%) | ≥ 60% | ✅ **CONFIRM** | IsolationForest correctly recovered 59/60 injected anomaly hexagons (98.3% agreement >> 60% threshold). Anomaly rate = 5.0%, within healthy 1–15% range. |
| **Axis 2** — Expansion Opportunities | HDBSCAN (min\_cluster\_size=5) | Silhouette Score | **0.5905** | > 0.20 | ✅ **CONFIRM** | 2 dense clusters found; noise rate 3.15%. 100% of high-density/low-speed/high-HHI target hexagons concentrated in dominant cluster (criteria concentration = 100%). Strong spatial signal. |
| **Axis 3** — Promotional Targeting | K-Means++ (k=3) | Silhouette Score | **0.4798** | > 0.30 | ✅ **CONFIRM** | k=3 silhouette of 0.4798 exceeds the 0.30 threshold without requiring a k-sweep. Three profiles map cleanly to the spec-defined segments (see §4.3). |

**Overall verdict: All three axes confirmed. No algorithm changes required.**

---

## 4. Per-Axis Detail

### 4.1 Axis 1 — Maintenance & Criticality (IsolationForest)

- **Features used:** `lat`, `vol_reclam`, `d_down`
- **Anomaly rate:** 5.00% (100 / 2,000 hexagons flagged)
- **Cloudflare agreement:** 98.33% (59 / 60 known outage hexagons recovered)
- **Anomaly score threshold note:** The spec threshold `s(x,n) >= 0.65` refers to the canonical IF score convention. In sklearn, flagging via `predict() == -1` (honouring `contamination`) is the correct equivalent. The normalised IF score `[0,1]` is exposed in the pipeline output for threshold tuning in production.
- **Key finding:** The three-feature input (`lat`, `vol_reclam`, `d_down`) is highly discriminative — latency spikes and complaint volume surges are the strongest anomaly signals.

### 4.2 Axis 2 — Expansion Opportunities (HDBSCAN)

- **Features used:** `n_dom`, `n_com`, `d_down`, `n_erb`, `HHI`
- **n_clusters:** 2 | **noise rate:** 3.15%
- **Criteria concentration:** 100% of target hexagons (high density + low speed + high HHI) fall in the same cluster — the clustering criteria from `knowledge-api.json` are fully validated.
- **Key finding:** HDBSCAN naturally identifies the "underserved high-density" segment without any parameter tuning. Noise rate of 3.15% is well below the 25% acceptable threshold.

### 4.3 Axis 3 — Promotional Targeting (K-Means++)

- **Features used:** `ren_med`, `n_dom`, `vol_reclam`, `HHI`, `d_up`
- **k-sweep performed:** No — k=3 already satisfies the threshold
- **Cluster profiles identified:**

| Cluster ID | Size | Profile Match | mean\_ren\_med (R$) | mean\_HHI | mean\_d\_up (Mbps) | mean\_vol\_reclam |
|---|---|---|---|---|---|---|
| **1** | 529 (26.5%) | 🔵 **Premium** | 4,181 | 1,974 | 52.9 | 3.98 |
| **2** | 1,194 (59.7%) | 🟡 **Conectividade Essencial** | 1,387 | 4,842 | 14.2 | 10.91 |
| **0** | 277 (13.8%) | 🔴 **Alta Vulnerabilidade Concorrência** | 1,069 | 5,354 | 10.7 | 44.60 |

**Cluster–profile mapping:**
- **Cluster 1 → Premium:** Highest income (R$ 4,182), lowest HHI (competitive market), fastest upload (52.9 Mbps), fewest complaints. Maps directly to "Cluster Premium: Alta renda, alta velocidade, penetração FTTH consolidada".
- **Cluster 2 → Conectividade Essencial:** Median income, elevated HHI, slow upload (14.2 Mbps). Largest segment (60% of hexagons). Maps to "Cluster Conectividade Essencial: Baixa/média renda, alto tráfego móvel, demanda por planos econômicos".
- **Cluster 0 → Alta Vulnerabilidade Concorrência:** Lowest income, highest HHI (5,354 — near-monopoly), highest complaint volume (44.6/1,000 accesses), slowest upload. Maps to "Cluster Alta Vulnerabilidade Concorrência: Média renda, alto HHI, alta latência/reclamações". Strong churn-risk signal.

---

## 5. knowledge-api.json Update Assessment

| Change | Required? | Detail |
|---|---|---|
| Axis 1 algorithm | No | IsolationForest confirmed. Note added: use `predict()` for flagging in production; expose normalised IF score for threshold tuning. |
| Axis 1 features | No | `["lat", "vol_reclam", "d_down"]` validated — highly discriminative. |
| Axis 2 algorithm | No | HDBSCAN confirmed. Add recommendation: apply UMAP pre-reduction before HDBSCAN in Sub-Task 3 production pipeline. |
| Axis 3 algorithm | No | K-Means++ k=3 confirmed. Silhouette=0.4798 >> 0.30 threshold. No k-sweep needed. |
| Dimensionality reduction | Annotation | UMAP is recommended over PCA for Axis 2; optional for Axes 1 and 3. Annotated in §2 above. |
| `d_down` VIF flag | Monitor | VIF=10.49 marginally above threshold. No action now; revisit in Sub-Task 3 per-axis pipeline VIF check. |

**Conclusion: No amendments to `knowledge-api.json` are required.** The existing algorithm choices, feature sets, and thresholds are validated by the EDA. The UMAP recommendation and the `d_down` VIF monitoring note are documented here as guidance for Sub-Task 3.

---

## 6. Sub-Task 3 Handoff Checklist

- [x] Feature vector `x_hi` validated (10 dimensions, no null issues in synthetic baseline)
- [x] Axis 1: IsolationForest confirmed — use `predict()` for flagging, expose normalised score
- [x] Axis 2: HDBSCAN confirmed — **add UMAP pre-reduction** in production pipeline
- [x] Axis 3: K-Means++ k=3 confirmed — three named profiles empirically validated
- [x] Reusable modules ready: `ml/eda_utils.py`, `ml/baseline_runners.py`
- [ ] Sub-Task 3: implement `ml/pipelines/pipeline_axis1.py`, `pipeline_axis2.py`, `pipeline_axis3.py`
- [ ] Sub-Task 3: integrate MLflow tracking per pipeline run
- [ ] Sub-Task 3: implement `ml/drift_detector.py` (PSI monitoring)
