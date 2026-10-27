import client from './client'
import type { AuditQueryFilters, AuditQueryResponse } from '../types'

export async function queryAuditEvents(filters: AuditQueryFilters): Promise<AuditQueryResponse> {
  const params: Record<string, string | number> = { limit: filters.limit }
  if (filters.agent_id) params.agent_id = filters.agent_id
  if (filters.event_type) params.event_type = filters.event_type
  if (filters.run_id) params.run_id = filters.run_id
  if (filters.date_start) params.date_start = filters.date_start
  if (filters.date_end) params.date_end = filters.date_end
  const { data } = await client.get<AuditQueryResponse>('/audit/events', { params })
  return data
}
