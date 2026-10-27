import client from './client'
import type { AgentRunRequest, AgentRunResponse } from '../types'

export async function runAgent(params: AgentRunRequest): Promise<AgentRunResponse> {
  const { data } = await client.post<AgentRunResponse>('/agent/run', params)
  return data
}
