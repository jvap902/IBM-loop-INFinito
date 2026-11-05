// ── Shared API types mirroring api/schemas.py ─────────────────────────────

export interface AgentRunRequest {
  region: string
  axes: string[]
  force: boolean
  llm_provider: 'stub' | 'watsonx' | 'openai' | 'gemini'
}

export interface AgentRunSummary {
  n_critical_hexagons: number
  n_expansion_clusters: number
  n_market_segments: number
  n_investment_hypotheses: number
  total_tam_brl: number
  capex_proxy_brl: number
  p1_clusters: number
  p2_clusters: number
}

export interface InvestmentHypothesis {
  cluster_id: number
  priority_class: string
  tam_estimate_brl: number
  avg_n_dom: number
  avg_d_down_mbps: number
  avg_hhi: number
  cluster_size_hexagons: number
  arpu_assumed_brl: number
  penetration_rate_assumed: number
  rationale: string
  interpretation?: string
  place_name?: string | null
  lat_centroid: number
  lon_centroid: number
}

export interface InterpretationsBlock {
  executive_summary: string
  axis1_interpretation: string
  axis2_interpretation: string
  axis3_interpretation: string
}

export interface AgentRunResponse {
  run_id: string
  region_scope: string
  axes_executed: string[]
  duration_seconds: number
  summary: AgentRunSummary
  interpretations: InterpretationsBlock | null
  investment_hypotheses: InvestmentHypothesis[]
  axis1_summary: Axis1Summary | null
  axis2_summary: Axis2Summary | null
  axis3_summary: Axis3Summary | null
  errors: ErrorEntry[]
}

// ── Axis-level types ───────────────────────────────────────────────────────

export interface Axis1HexagonResult {
  h3_id: string
  lat_centroid: number
  lon_centroid: number
  anomaly_score: number
  is_critical: number
  lof_score: number
  cloudflare_outage_overlap: number
  place_name?: string | null
}

export interface Axis1RunResponse {
  run_id: string
  axis: string
  duration_seconds: number
  total_hexagons_scored: number
  n_critical: number
  anomaly_rate: number
  results: Axis1HexagonResult[]
  resolution_warning?: string | null
  cloudflare_data_available?: boolean
}

export interface Axis1Summary {
  n_critical: number
  anomaly_rate: number
  top_critical: Axis1HexagonResult[]
}

export interface Axis2ClusterSummary {
  cluster_id: number
  cluster_size: number
  lat_centroid: number
  lon_centroid: number
  avg_d_down: number | null
  avg_n_dom: number | null
  avg_HHI: number | null
  tam_estimate: number | null
  is_noise: number
  place_name?: string | null
}

export interface Axis2RunResponse {
  run_id: string
  axis: string
  duration_seconds: number
  total_hexagons_processed: number
  n_clusters: number
  noise_rate: number
  clusters: Axis2ClusterSummary[]
}

export interface Axis2Summary {
  n_clusters: number
  noise_rate: number
  clusters: Axis2ClusterSummary[]
}

export interface Axis3SegmentProfile {
  segment_id: number
  segment_name: string
  hexagon_count: number
  hexagon_fraction: number
  avg_centroid_distance: number
  avg_silhouette: number | null
}

export interface Axis3HexagonResult {
  h3_id: string
  lat_centroid: number
  lon_centroid: number
  segment_id: number
  segment_name: string
  centroid_distance: number
  silhouette_score_local: number | null
}

export interface Axis3RunResponse {
  run_id: string
  axis: string
  duration_seconds: number
  total_hexagons_segmented: number
  n_segments: number
  silhouette_score_global: number | null
  segment_profiles: Axis3SegmentProfile[]
  results: Axis3HexagonResult[]
}

export interface Axis3Summary {
  n_segments: number
  silhouette_score_global: number | null
  segment_profiles: Axis3SegmentProfile[]
}

// ── Audit types ────────────────────────────────────────────────────────────

export interface AuditEvent {
  event_id: string
  run_id: string
  agent_id: string
  event_type: string
  timestamp: string
  payload: Record<string, unknown>
}

export interface AuditQueryResponse {
  total_returned: number
  events: AuditEvent[]
}

export interface AuditQueryFilters {
  agent_id?: string
  event_type?: string
  run_id?: string
  date_start?: string
  date_end?: string
  limit: number
}

// ── Generic ────────────────────────────────────────────────────────────────

export interface ErrorEntry {
  node?: string
  error?: string
  [key: string]: unknown
}

// ── On-demand report generation ────────────────────────────────────────────

export interface AgentReportRequest {
  run_id: string
  user_prompt: string
  llm_provider: AgentRunRequest['llm_provider']
}

export interface AgentReportResponse {
  filename: string
  content: string
}

export interface Axis1RunRequest {
  region_filter?: string[] | null
  h3_resolution: 8 | 9
  anomaly_threshold: number
  contamination: number
  top_n: number
  feature_weights?: Record<string, number> | null
}

export interface Axis2RunRequest {
  region_filter?: string[] | null
  h3_resolution: 8 | 9
  min_cluster_size: number
  skip_umap: boolean
  feature_weights?: Record<string, number> | null
}

export interface Axis3RunRequest {
  region_filter?: string[] | null
  h3_resolution: 8 | 9
  n_clusters: number
  sweep_if_low_silhouette: boolean
  feature_weights?: Record<string, number> | null
}
