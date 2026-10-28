import { useNavigate } from 'react-router-dom'
import { useReportStore } from '../stores/reportStore'
import KpiCard from '../components/KpiCard'
import HexMap from '../components/HexMap'
import TamBarChart from '../components/TamBarChart'
import SegmentPieChart from '../components/SegmentPieChart'
import InvestmentTable from '../components/InvestmentTable'
import InterpretationCard from '../components/InterpretationCard'

const fmtBrl = (v: number) =>
  'R$ ' + v.toLocaleString('pt-BR', { maximumFractionDigits: 2 })

function PageHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-lg font-bold text-ind-text">{title}</h1>
      {sub && <p className="text-ind-muted text-sm mt-0.5">{sub}</p>}
    </div>
  )
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
      <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted mb-3 pb-2 border-b border-ind-border">
        {title}
      </div>
      {children}
    </div>
  )
}

export default function Dashboard() {
  const report = useReportStore((s) => s.report)
  const navigate = useNavigate()

  if (!report) {
    return (
      <div className="p-8 flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <div className="text-ind-muted text-5xl mb-2">▦</div>
        <h2 className="text-ind-text text-xl font-bold">Nenhuma análise disponível</h2>
        <p className="text-ind-muted text-sm text-center max-w-sm">
          Execute uma análise completa para visualizar os resultados aqui.
        </p>
        <button
          onClick={() => navigate('/run')}
          className="mt-2 px-5 py-2.5 bg-ind-accent text-ind-bg rounded font-semibold text-sm hover:bg-amber-400 transition-colors"
        >
          Executar Análise Completa
        </button>
      </div>
    )
  }

  const { summary, investment_hypotheses, axis1_summary, axis2_summary, axis3_summary, run_id, region_scope, axes_executed, duration_seconds, interpretations } = report

  const axis1Results = (axis1_summary as { top_critical?: unknown[] } | null)?.top_critical as
    | Parameters<typeof HexMap>[0]['axis1Results']
    | undefined

  const axis2Clusters = axis2_summary?.clusters as
    | Parameters<typeof HexMap>[0]['axis2Clusters']
    | undefined

  const axis3Results = undefined // axis3 raw hexagons not in summary, skipped on dashboard map

  const seg3Profiles = axis3_summary?.segment_profiles ?? []
  const clusters2 = axis2_summary?.clusters ?? []

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <PageHeader
        title="Dashboard de Resultados"
        sub={`Região: ${region_scope} · Eixos: ${axes_executed.join(', ')} · Run: ${run_id.slice(0, 8)}…`}
      />

      {/* Executive Summary Interpretation */}
      {interpretations?.executive_summary && (
        <InterpretationCard
          title="Sumário Executivo"
          text={interpretations.executive_summary}
          accentColor="border-ind-accent"
          badge="Agente"
          collapsible
        />
      )}

      {/* KPI Row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-6">
        <KpiCard
          label="Hexágonos Analisados"
          value={(summary.n_critical_hexagons + (axis2_summary?.clusters?.reduce((s, c) => s + c.cluster_size, 0) ?? 0)).toLocaleString('pt-BR')}
          sub="Gold Feature Store"
        />
        <KpiCard
          label="Infraestrutura Crítica"
          value={summary.n_critical_hexagons.toLocaleString('pt-BR')}
          sub={`${axis1_summary ? (axis1_summary.anomaly_rate * 100).toFixed(1) + '% do total' : '—'} · Manutenção`}
          valueColor="text-ind-danger"
        />
        <KpiCard
          label="Zonas de Expansão"
          value={summary.n_expansion_clusters.toLocaleString('pt-BR')}
          sub="Oportunidades · HDBSCAN"
          valueColor="text-ind-cluster"
        />
        <KpiCard
          label="Segmentos de Mercado"
          value={summary.n_market_segments.toLocaleString('pt-BR')}
          sub="Segmentação · K-Means++"
          valueColor="text-ind-segment"
        />
        <KpiCard
          label="TAM Total"
          value={fmtBrl(summary.total_tam_brl)}
          sub={`${summary.n_investment_hypotheses} hipóteses · ${duration_seconds.toFixed(1)}s`}
          valueColor="text-ind-accent"
        />
      </div>

      {/* Map + TAM Chart */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
        <div className="flex flex-col gap-4">
          {/* Map card — zero body padding so the map fills edge-to-edge */}
          <div className="bg-ind-surface border border-ind-border rounded-lg overflow-hidden flex flex-col" style={{ minHeight: '420px' }}>
            <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted px-4 pt-4 pb-2 border-b border-ind-border shrink-0">
              Mapa Geoespacial — H3 Centroides
            </div>
            <div className="flex-1 min-h-0 p-3 pt-2">
              <HexMap
                axis1Results={axis1Results}
                axis2Clusters={axis2Clusters}
                axis3Results={axis3Results}
                height="100%"
              />
            </div>
          </div>
          {/* Axis 1 interpretation */}
          {interpretations?.axis1_interpretation && (
            <InterpretationCard
              title="Análise de Infraestrutura"
              text={interpretations.axis1_interpretation}
              accentColor="border-ind-danger"
              badge="Manutenção"
              badgeColor="bg-red-900/30 text-red-400"
              collapsible
            />
          )}
        </div>

        <div className="flex flex-col gap-4">
          {clusters2.length > 0 && (
            <Card title="TAM por Zona de Expansão">
              <TamBarChart clusters={clusters2} />
            </Card>
          )}
          {/* Axis 2 interpretation */}
          {interpretations?.axis2_interpretation && (
            <InterpretationCard
              title="Oportunidades de Expansão"
              text={interpretations.axis2_interpretation}
              accentColor="border-ind-cluster"
              badge="Expansão"
              badgeColor="bg-blue-900/30 text-blue-400"
              collapsible
            />
          )}
          {seg3Profiles.length > 0 && (
            <Card title="Distribuição de Segmentos de Mercado">
              <SegmentPieChart segments={seg3Profiles} />
            </Card>
          )}
          {/* Axis 3 interpretation */}
          {interpretations?.axis3_interpretation && (
            <InterpretationCard
              title="Segmentação de Mercado"
              text={interpretations.axis3_interpretation}
              accentColor="border-ind-segment"
              badge="Segmentação"
              badgeColor="bg-green-900/30 text-green-400"
              collapsible
            />
          )}
        </div>
      </div>

      {/* Investment Hypotheses Table */}
      {investment_hypotheses.length > 0 && (
        <Card title={`Hipóteses de Investimento (${investment_hypotheses.length})`}>
          <InvestmentTable hypotheses={investment_hypotheses} />
        </Card>
      )}

      {/* Run metadata */}
      <div className="mt-4 text-xs text-ind-muted flex flex-wrap gap-4 border-t border-ind-border pt-3">
        <span>Run ID: <code className="font-mono bg-ind-surface px-1 rounded">{run_id}</code></span>
        <span>Duração: {duration_seconds.toFixed(2)}s</span>
        <span>P1: {summary.p1_clusters} · P2: {summary.p2_clusters}</span>
        <span>CAPEX proxy: {fmtBrl(summary.capex_proxy_brl)}</span>
      </div>
    </div>
  )
}
