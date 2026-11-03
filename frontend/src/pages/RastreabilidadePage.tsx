import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useReportStore } from '../stores/reportStore'
import ShapBarChart from '../components/ShapBarChart'
import InterpretationCard from '../components/InterpretationCard'
import type { ShapClusterFeature } from '../types'

// ── Local helpers ───────────────────────────────────────────────────────────

function PageHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-lg font-bold text-ind-text">{title}</h1>
      {sub && <p className="text-ind-muted text-sm mt-0.5">{sub}</p>}
    </div>
  )
}

function SectionCard({
  title,
  badge,
  badgeColor = 'bg-ind-accent/10 text-ind-accent',
  accentColor = 'border-ind-accent',
  defaultExpanded = true,
  children,
}: {
  title: string
  badge?: string
  badgeColor?: string
  accentColor?: string
  defaultExpanded?: boolean
  children: React.ReactNode
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  return (
    <div className={`bg-ind-surface border-l-4 ${accentColor} rounded-r-lg p-4 mb-4`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-ind-muted">{title}</span>
          {badge && (
            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${badgeColor}`}>
              {badge}
            </span>
          )}
        </div>
        <button
          onClick={() => setExpanded(v => !v)}
          className="text-ind-muted hover:text-ind-text text-xs transition-colors"
        >
          {expanded ? '▲ recolher' : '▼ expandir'}
        </button>
      </div>
      {expanded && <div>{children}</div>}
    </div>
  )
}

function UnavailableNote({ text = 'Dados não disponíveis para este eixo.' }: { text?: string }) {
  return <p className="text-ind-muted text-xs italic">{text}</p>
}

// ── Main page ───────────────────────────────────────────────────────────────

export default function RastreabilidadePage() {
  const report = useReportStore(s => s.report)
  const navigate = useNavigate()

  // ── Empty state ────────────────────────────────────────────────────────
  if (!report) {
    return (
      <div className="p-8 flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <div className="text-ind-muted text-5xl mb-2">🔍</div>
        <h2 className="text-ind-text text-xl font-bold">Nenhuma análise disponível</h2>
        <p className="text-ind-muted text-sm text-center max-w-sm">
          Execute uma análise completa para visualizar a rastreabilidade dos modelos aqui.
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

  const {
    run_id,
    region_scope,
    axes_executed,
    duration_seconds,
    explanations,
    axis2_summary,
    axis3_summary,
    interpretations,
  } = report

  // ── Axis 2: pick top-3 non-noise clusters by TAM ──────────────────────
  const rawClusters = (axis2_summary?.clusters ?? [])
    .filter(c => c.is_noise === 0 && c.tam_estimate != null)
    .sort((a, b) => (b.tam_estimate ?? 0) - (a.tam_estimate ?? 0))
    .slice(0, 3)

  // ── Axis 3: segment profiles lookup ───────────────────────────────────
  const seg3ProfileMap: Record<number, string> = {}
  for (const p of axis3_summary?.segment_profiles ?? []) {
    seg3ProfileMap[p.segment_id] = p.segment_name
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <PageHeader
        title="Rastreabilidade da Análise"
        sub="Explicabilidade dos modelos e cadeia de raciocínio do agente"
      />

      {/* ── Header Card ──────────────────────────────────────────────────── */}
      <div className="bg-ind-surface border border-ind-border rounded-lg p-4 mb-6">
        <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted mb-3 pb-2 border-b border-ind-border">
          Metadados da Execução
        </div>
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
          <div>
            <dt className="text-ind-muted mb-0.5">Run ID</dt>
            <dd className="font-mono text-ind-text bg-ind-bg px-1.5 py-0.5 rounded text-[11px] truncate">
              {run_id}
            </dd>
          </div>
          <div>
            <dt className="text-ind-muted mb-0.5">Região</dt>
            <dd className="text-ind-text font-medium">{region_scope}</dd>
          </div>
          <div>
            <dt className="text-ind-muted mb-0.5">Eixos Executados</dt>
            <dd className="text-ind-text font-medium">{axes_executed.join(', ')}</dd>
          </div>
          <div>
            <dt className="text-ind-muted mb-0.5">Duração</dt>
            <dd className="text-ind-text font-medium">{duration_seconds.toFixed(2)}s</dd>
          </div>
        </dl>
      </div>

      {/* ── Axis 1 — Anomalias de Infraestrutura ─────────────────────────── */}
      <SectionCard
        title="Eixo 1 — Anomalias de Infraestrutura"
        badge="Detecção Automática"
        badgeColor="bg-red-900/30 text-red-400"
        accentColor="border-ind-danger"
      >
        {explanations?.axis1?.status === 'ok' ? (
          <>
            <ShapBarChart
              features={(explanations.axis1.top_features ?? []).map(f => ({
                feature: f.feature,
                value: f.shap_value,
              }))}
              title=""
              colorPositive="#ef4444"
              colorNegative="#64748b"
            />
          </>
        ) : (
          <UnavailableNote
            text={
              explanations?.axis1
                ? `Dados indisponíveis — status: ${explanations.axis1.status}`
                : 'Dados de análise de anomalias não disponíveis nesta execução.'
            }
          />
        )}
      </SectionCard>

      {/* ── Axis 2 — Features por Cluster ────────────────────────────────── */}
      <SectionCard
        title="Eixo 2 — Features por Cluster (Oportunidades de Expansão)"
        badge="Agrupamento Geográfico"
        badgeColor="bg-blue-900/30 text-blue-400"
        accentColor="border-ind-cluster"
      >
        {explanations?.axis2?.status === 'ok' ? (
          <div className="space-y-3">
            {rawClusters.length === 0 ? (
              <UnavailableNote text="Nenhum cluster válido encontrado no Eixo 2." />
            ) : (
              rawClusters.map((cluster, idx) => {
                const clusterKey = String(cluster.cluster_id)
                const clusterExp = explanations.axis2!.clusters?.[clusterKey]
                return (
                  <ClusterAccordion
                    key={clusterKey}
                    clusterId={cluster.cluster_id}
                    tamEstimate={cluster.tam_estimate}
                    features={clusterExp?.top_features ?? []}
                    defaultExpanded={idx === 0}
                  />
                )
              })
            )}
          </div>
        ) : (
          <UnavailableNote
            text={
              explanations?.axis2
                ? `Dados indisponíveis — status: ${explanations.axis2.status}`
                : 'Dados de agrupamento não disponíveis nesta execução.'
            }
          />
        )}
      </SectionCard>

      {/* ── Axis 3 — Segmentação de Mercado ──────────────────────────────── */}
      <SectionCard
        title="Eixo 3 — Segmentação de Mercado"
        badge="Perfil de Mercado"
        badgeColor="bg-green-900/30 text-green-400"
        accentColor="border-ind-segment"
      >
        {explanations?.axis3?.status === 'ok' ? (
          <>
            <div className="space-y-4">
              {Object.entries(explanations.axis3.segments ?? {}).map(([segKey, segData]) => {
                const segName = seg3ProfileMap[segData.segment_id] ?? `Segmento ${segData.segment_id}`
                return (
                  <div key={segKey}>
                    <p className="text-[11px] text-ind-muted mb-1">
                      <span className="text-ind-text font-medium">{segName}</span>
                    </p>
                    <ShapBarChart
                      features={(segData.top_features ?? []).map(f => ({
                        feature: f.feature,
                        value: f.shap_value,
                      }))}
                      title=""
                      colorPositive="#22c55e"
                      colorNegative="#64748b"
                    />
                  </div>
                )
              })}
            </div>
          </>
        ) : (
          <UnavailableNote
            text={
              explanations?.axis3
                ? `Dados indisponíveis — status: ${explanations.axis3.status}`
                : 'Dados de perfil de mercado não disponíveis nesta execução.'
            }
          />
        )}
      </SectionCard>

      {/* ── Interpretações ────────────────────────────────────────────────── */}
      {interpretations && (
        <div className="mt-2">
          <div className="text-xs font-bold uppercase tracking-wider text-ind-muted mb-3">
            Interpretações do Agente
          </div>
          {interpretations.executive_summary && (
            <InterpretationCard
              title="Sumário Executivo"
              text={interpretations.executive_summary}
              accentColor="border-ind-accent"
              badge="Agente"
              collapsible
            />
          )}
          {interpretations.axis1_interpretation && (
            <InterpretationCard
              title="Análise de Infraestrutura — Eixo 1"
              text={interpretations.axis1_interpretation}
              accentColor="border-ind-danger"
              badge="Manutenção"
              badgeColor="bg-red-900/30 text-red-400"
              collapsible
            />
          )}
          {interpretations.axis2_interpretation && (
            <InterpretationCard
              title="Oportunidades de Expansão — Eixo 2"
              text={interpretations.axis2_interpretation}
              accentColor="border-ind-cluster"
              badge="Expansão"
              badgeColor="bg-blue-900/30 text-blue-400"
              collapsible
            />
          )}
          {interpretations.axis3_interpretation && (
            <InterpretationCard
              title="Segmentação de Mercado — Eixo 3"
              text={interpretations.axis3_interpretation}
              accentColor="border-ind-segment"
              badge="Segmentação"
              badgeColor="bg-green-900/30 text-green-400"
              collapsible
            />
          )}
        </div>
      )}
    </div>
  )
}

// ── ClusterAccordion sub-component ──────────────────────────────────────────

function ClusterAccordion({
  clusterId,
  tamEstimate,
  features,
  defaultExpanded,
}: {
  clusterId: number
  tamEstimate: number | null
  features: ShapClusterFeature[]
  defaultExpanded: boolean
}) {
  const [expanded, setExpanded] = useState(defaultExpanded)
  const fmtBrl = (v: number) =>
    'R$ ' + v.toLocaleString('pt-BR', { maximumFractionDigits: 0 })

  return (
    <div className="border border-ind-border rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(v => !v)}
        className="w-full flex items-center justify-between px-3 py-2 bg-ind-bg hover:bg-ind-surface transition-colors text-left"
      >
        <span className="text-xs font-medium text-ind-text">
          Cluster {clusterId}
          {tamEstimate != null && (
            <span className="ml-2 text-ind-accent text-[11px]">TAM {fmtBrl(tamEstimate)}</span>
          )}
        </span>
        <span className="text-ind-muted text-xs">{expanded ? '▲' : '▼'}</span>
      </button>
      {expanded && (
        <div className="px-3 py-3 bg-ind-surface">
          {features.length > 0 ? (
            <ShapBarChart
              features={features.map(f => ({ feature: f.feature, value: f.z_score }))}
              title=""
              colorPositive="#3b82f6"
              colorNegative="#64748b"
            />
          ) : (
            <p className="text-ind-muted text-xs italic">
              Dados Z-Score não disponíveis para este cluster.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
