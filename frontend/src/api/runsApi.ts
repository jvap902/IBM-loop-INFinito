import client from './client'
import type { AgentRunResponse } from '../types'

export interface RunMeta {
  run_id: string
  region_scope: string
  axes_executed: string[]
  duration_seconds: number
  timestamp: string
  n_critical_hexagons: number
  n_expansion_clusters: number
  n_market_segments: number
  total_tam_brl: number
  p1_clusters: number
  p2_clusters: number
}

export interface RunListResponse {
  total: number
  runs: RunMeta[]
}

export async function listRuns(): Promise<RunListResponse> {
  const { data } = await client.get<RunListResponse>('/agent/runs')
  return data
}

export async function getRun(runId: string): Promise<AgentRunResponse> {
  const { data } = await client.get<AgentRunResponse>(`/agent/runs/${encodeURIComponent(runId)}`)
  return data
}
