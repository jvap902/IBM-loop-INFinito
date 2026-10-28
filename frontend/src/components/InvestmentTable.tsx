import { useState } from 'react'
import type { InvestmentHypothesis } from '../types'
import InterpretationCard from './InterpretationCard'

const fmtBrl = (v: number) =>
  'R$ ' + v.toLocaleString('pt-BR', { maximumFractionDigits: 0 })

type SortKey = keyof InvestmentHypothesis
type SortDir = 'asc' | 'desc'

const PRIORITY_COLORS: Record<string, string> = {
  P1_CRITICAL_EXPANSION: 'text-red-400 font-semibold',
  P2_HIGH_EXPANSION:     'text-orange-400 font-semibold',
  P3_STANDARD_EXPANSION: 'text-yellow-400',
}

// ── Per-hypothesis expandable row ──────────────────────────────────────────

function HypothesisRow({ h }: { h: InvestmentHypothesis }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <>
      <tr
        className="border-b border-ind-border/50 hover:bg-ind-surface transition-colors cursor-pointer"
        onClick={() => setExpanded(v => !v)}
      >
        <td className="px-3 py-2">
          <span className={`text-xs ${PRIORITY_COLORS[h.priority_class] ?? 'text-ind-muted'}`}>
            {h.priority_class.replace(/_/g, ' ')}
          </span>
        </td>
        <td className="px-3 py-2 font-mono text-ind-muted text-xs">C{h.cluster_id}</td>
        <td className="px-3 py-2 text-ind-accent font-semibold text-xs">{fmtBrl(h.tam_estimate_brl)}</td>
        <td className="px-3 py-2 text-ind-text text-xs">{h.avg_n_dom.toFixed(0)}</td>
        <td className="px-3 py-2 text-ind-text text-xs">{h.avg_d_down_mbps.toFixed(1)}</td>
        <td className="px-3 py-2 text-ind-text text-xs">{h.avg_hhi.toFixed(0)}</td>
        <td className="px-3 py-2 text-ind-muted text-xs max-w-xs truncate" title={h.rationale}>
          {h.rationale}
        </td>
        <td className="px-3 py-2 text-ind-muted text-[10px]">
          {h.interpretation ? (expanded ? '▲' : '▼ ver análise') : ''}
        </td>
      </tr>
      {expanded && h.interpretation && (
        <tr className="border-b border-ind-border bg-ind-bg/30">
          <td colSpan={8} className="px-4 py-3">
            <InterpretationCard
              title={`Análise detalhada — Cluster ${h.cluster_id}`}
              text={h.interpretation}
              accentColor="border-ind-accent"
              collapsible={false}
            />
          </td>
        </tr>
      )}
    </>
  )
}

// ── Main table component ───────────────────────────────────────────────────

interface Props {
  hypotheses: InvestmentHypothesis[]
}

export default function InvestmentTable({ hypotheses }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('tam_estimate_brl')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir('desc') }
  }

  const sorted = [...hypotheses].sort((a, b) => {
    const av = a[sortKey] as number
    const bv = b[sortKey] as number
    return sortDir === 'asc' ? av - bv : bv - av
  })

  const th = (label: string, key: SortKey) => (
    <th
      className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-ind-muted cursor-pointer hover:text-ind-text select-none"
      onClick={() => toggleSort(key)}
    >
      {label}
      {sortKey === key && <span className="ml-1">{sortDir === 'asc' ? '↑' : '↓'}</span>}
    </th>
  )

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead className="border-b border-ind-border">
          <tr>
            <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-ind-muted">Prioridade</th>
            {th('Cluster', 'cluster_id')}
            {th('TAM (R$)', 'tam_estimate_brl')}
            {th('Dom/Hex', 'avg_n_dom')}
            {th('Vel↓ Mbps', 'avg_d_down_mbps')}
            {th('HHI', 'avg_hhi')}
            <th className="px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-wider text-ind-muted">Justificativa</th>
            <th className="px-3 py-2 w-20"></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((h) => (
            <HypothesisRow key={h.cluster_id} h={h} />
          ))}
        </tbody>
      </table>
      {sorted.length === 0 && (
        <div className="text-center py-8 text-ind-muted text-sm">Nenhuma hipótese de investimento disponível.</div>
      )}
      {sorted.length > 0 && sorted[0].interpretation && (
        <p className="text-[10px] text-ind-muted mt-2 text-right">Clique em uma linha para ver a análise detalhada</p>
      )}
    </div>
  )
}
