import client from './client'

export interface ReportMeta {
  filename: string
  region: string
  date: string
  size_bytes: number
}

export interface ReportListResponse {
  reports: ReportMeta[]
}

export interface ReportContentResponse {
  filename: string
  content: string
}

export async function listReports(): Promise<ReportListResponse> {
  const { data } = await client.get<ReportListResponse>('/reports')
  return data
}

export async function getReport(filename: string): Promise<ReportContentResponse> {
  const { data } = await client.get<ReportContentResponse>(`/reports/${encodeURIComponent(filename)}`)
  return data
}

export async function deleteReport(filename: string): Promise<void> {
  await client.delete(`/reports/${encodeURIComponent(filename)}`)
}
