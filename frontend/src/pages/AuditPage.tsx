import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { queryAuditEvents } from '../api/auditApi'
import type { AuditQueryFilters, AuditEvent } from '../types'

const AGENT_IDS = ['', 'planner', 'operational', 'system']
const EVENT_TYPES = ['', 'tool_call', 'reasoning_step', 'report_generated', 'model_run']

function JsonViewer({ data }: { data: unknown }) {
  return (
    <pre className="text-[10px] font-mono text-ind-muted bg-ind-bg rounded p-3 overflow-auto max-h-48 border border-ind-border">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

function EventRow({ event }: { event: AuditEvent }) {
  const [expanded, setExpanded] = useState(false)
  const [copied, setCopied] = useState(false)

  const copy = () => {
    navigator.clipboard.writeText(event.run_id)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const TYPE_COLORS: Record<string, string> = {
    tool_call:       'text-ind-accent',
    reasoning_step:  'text-ind-accent2',
    report_generated:'text-ind-segment',
    model_run:       'text-ind-cluster',
  }

  return (
    <>
      <tr
        className="border-b border-ind-border/50 hover:bg-ind-surface/60 cursor-pointer transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <td className="px-3 py-2 font-mono text-ind-muted text-[11px]">{new Date(event.timestamp).toLocaleString('pt-BR')}</td>
        <td className="px-3 py-2">
          <button
            onClick={(e) => { e.stopPropagation(); copy() }}
            className="font-mono text-[10px] text-ind-muted hover:text-ind-accent transition-colors"
            title="Copiar Run ID"
          >
            {event.run_id.slice(0, 12)}… {copied ? '✓' : '⎘'}
          </button>
        </td>
        <td className="px-3 py-2 text-ind-muted text-xs">{event.agent_id}</td>
        <td className="px-3 py-2 text-xs">
          <span className={TYPE_COLORS[event.event_type] ?? 'text-ind-muted'}>{event.event_type}</span>
        </td>
        <td className="px-3 py-2 text-ind-muted text-[10px]">{expanded ? '▲' : '▼'}</td>
      </tr>
      {expanded && (
        <tr className="border-b border-ind-border bg-ind-bg/40">
          <td colSpan={5} className="px-4 py-3">
            <JsonViewer data={event.payload} />
          </td>
        </tr>
      )}
    </>
  )
}

export default function AuditPage() {
  const [filters, setFilters] = useState<AuditQueryFilters>({
    agent_id: '',
    event_type: '',
    run_id: '',
    date_start: '',
    date_end: '',
    limit: 100,
  })
  const [enabled, setEnabled] = useState(false)

  const { data, isFetching, error, refetch } = useQuery({
    queryKey: ['audit', filters],
    queryFn: () => queryAuditEvents(filters),
    enabled,
  })

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (!enabled) setEnabled(true)
    else refetch()
  }

  const err = error as { response?: { data?: { detail?: string } }; message?: string } | null

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-bold text-ind-text">Auditoria</h1>
        <p className="text-ind-muted text-sm mt-0.5">Consulta de eventos registrados pelo agente e pelas ferramentas.</p>
      </div>

      {/* Filter bar */}
      <form onSubmit={handleSearch} className="bg-ind-surface border border-ind-border rounded-lg p-4 mb-4">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 items-end">
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-ind-muted mb-1">Agent ID</label>
            <select
              value={filters.agent_id}
              onChange={(e) => setFilters((f) => ({ ...f, agent_id: e.target.value }))}
              className="w-full bg-ind-bg border border-ind-border rounded px-2 py-1.5 text-ind-text text-xs focus:outline-none focus:border-ind-accent"
            >
              {AGENT_IDS.map((v) => <option key={v} value={v}>{v || 'Todos'}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-ind-muted mb-1">Tipo de Evento</label>
            <select
              value={filters.event_type}
              onChange={(e) => setFilters((f) => ({ ...f, event_type: e.target.value }))}
              className="w-full bg-ind-bg border border-ind-border rounded px-2 py-1.5 text-ind-text text-xs focus:outline-none focus:border-ind-accent"
            >
              {EVENT_TYPES.map((v) => <option key={v} value={v}>{v || 'Todos'}</option>)}
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-ind-muted mb-1">Run ID</label>
            <input
              type="text"
              value={filters.run_id}
              onChange={(e) => setFilters((f) => ({ ...f, run_id: e.target.value }))}
              placeholder="uuid..."
              className="w-full bg-ind-bg border border-ind-border rounded px-2 py-1.5 text-ind-text text-xs font-mono focus:outline-none focus:border-ind-accent"
            />
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-ind-muted mb-1">De</label>
            <input
              type="date"
              value={filters.date_start}
              onChange={(e) => setFilters((f) => ({ ...f, date_start: e.target.value }))}
              className="w-full bg-ind-bg border border-ind-border rounded px-2 py-1.5 text-ind-text text-xs focus:outline-none focus:border-ind-accent"
            />
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-ind-muted mb-1">Até</label>
            <input
              type="date"
              value={filters.date_end}
              onChange={(e) => setFilters((f) => ({ ...f, date_end: e.target.value }))}
              className="w-full bg-ind-bg border border-ind-border rounded px-2 py-1.5 text-ind-text text-xs focus:outline-none focus:border-ind-accent"
            />
          </div>

          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-ind-muted mb-1">Limite</label>
            <div className="flex gap-2 items-center">
              <input
                type="number"
                min={1}
                max={1000}
                value={filters.limit}
                onChange={(e) => setFilters((f) => ({ ...f, limit: parseInt(e.target.value, 10) }))}
                className="w-20 bg-ind-bg border border-ind-border rounded px-2 py-1.5 text-ind-text text-xs font-mono focus:outline-none focus:border-ind-accent"
              />
              <button
                type="submit"
                disabled={isFetching}
                className="flex-1 py-1.5 bg-ind-accent text-ind-bg rounded font-bold text-xs hover:bg-amber-400 transition-colors disabled:opacity-50"
              >
                {isFetching ? '…' : 'Buscar'}
              </button>
            </div>
          </div>
        </div>
      </form>

      {err && (
        <div className="bg-red-950/50 border border-red-800 rounded p-3 text-xs text-red-300 mb-4">
          {err.response?.data?.detail ?? err.message ?? 'Erro ao buscar eventos'}
        </div>
      )}

      {/* Results table */}
      {data ? (
        <div className="bg-ind-surface border border-ind-border rounded-lg overflow-hidden">
          <div className="px-4 py-2.5 border-b border-ind-border text-xs text-ind-muted flex items-center justify-between">
            <span>{data.total_returned} evento(s) retornado(s)</span>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ind-border">
                {['Timestamp', 'Run ID', 'Agent', 'Tipo', ''].map((h) => (
                  <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-ind-muted">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.events.map((ev) => (
                <EventRow key={ev.event_id} event={ev} />
              ))}
            </tbody>
          </table>
          {data.events.length === 0 && (
            <div className="text-center py-10 text-ind-muted text-sm">Nenhum evento encontrado com os filtros aplicados.</div>
          )}
        </div>
      ) : !isFetching && (
        <div className="flex items-center justify-center min-h-[200px] text-ind-muted text-sm border border-ind-border border-dashed rounded-lg">
          Aplique filtros e clique em "Buscar" para consultar o log de auditoria.
        </div>
      )}
    </div>
  )
}
