import { create } from 'zustand'
import type { AgentRunResponse } from '../types'

interface ReportStore {
  report: AgentRunResponse | null
  setReport: (r: AgentRunResponse) => void
  clearReport: () => void
}

export const useReportStore = create<ReportStore>((set) => ({
  report: null,
  setReport: (r) => set({ report: r }),
  clearReport: () => set({ report: null }),
}))
