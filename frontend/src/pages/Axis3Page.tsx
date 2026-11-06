import { useState, useMemo } from 'react'
import { useMutation } from '@tanstack/react-query'
import AxisForm, { FormField, Slider, SelectInput, Toggle, RunButton, ErrorBanner, TextInput } from '../components/AxisForm'
import KpiCard from '../components/KpiCard'
import SegmentPieChart from '../components/SegmentPieChart'
import HexMap from '../components/HexMap'
import { runAxis3 } from '../api/axisApi'
import type { Axis3RunResponse, Axis3RunRequest } from '../types'

// Must match the palette in HexMap.tsx
const SEGMENT_COLOURS = [
  '#22c55e', '#3b82f6', '#f59e0b', '#ec4899', '#a78bfa',
  '#06b6d4', '#f97316', '#84cc16', '#e11d48', '#14b8a6',
]
function segmentColour(id: number) { return SEGMENT_COLOURS[id % SEGMENT_COLOURS.length] }

function silhouetteBadge(score: number | null) {
  if (score == null) return null
  if (score >= 0.50) return <span className="ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-green-950/60 text-green-400 border border-green-800">Boa</span>
  if (score >= 0.30) return <span className="ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-yellow-950/60 text-yellow-500 border border-yellow-800">Razoável</span>
  return <span className="ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-950/60 text-red-400 border border-red-800">Fraca</span>
}

function SegmentTable({ profiles }: { profiles: Axis3RunResponse['segment_profiles'] }) {
  return (
    <div className="overflow-x-auto mt-3">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-ind-border">
            {['Segmento', 'Hexágonos', '% do Total', 'Qualidade (Silhouette)', 'Distância ao Centróide'].map((h) => (
              <th key={h} className="px-3 py-2 text-left font-semibold uppercase tracking-wider text-ind-muted text-[10px]">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {profiles.map((s) => (
            <tr key={s.segment_id} className="border-b border-ind-border/40 hover:bg-ind-surface transition-colors">
              <td className="px-3 py-1.5">
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-ind-segment font-semibold">S{s.segment_id}</span>
                  <span className="text-ind-text">{s.segment_name}</span>
                </div>
                {s.place_name
                  ? <div className="text-[10px] text-ind-muted mt-0.5">{s.place_name}</div>
                  : null}
              </td>
              <td className="px-3 py-1.5">{s.hexagon_count.toLocaleString('pt-BR')}</td>
              <td className="px-3 py-1.5">{(s.hexagon_fraction * 100).toFixed(1)}%</td>
              <td className="px-3 py-1.5">
                {s.avg_silhouette?.toFixed(3) ?? '—'}{silhouetteBadge(s.avg_silhouette ?? null)}
              </td>
              <td className="px-3 py-1.5">{s.avg_centroid_distance.toFixed(3)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Axis3Page() {
  const [regionFilter, setRegionFilter] = useState('')
  const [resolution, setResolution] = useState<8 | 9>(8)
  const [nClusters, setNClusters] = useState(3)
  const [sweep, setSweep] = useState(true)
  // null = all visible; Set = only these segment ids are shown
  const [visibleSegments, setVisibleSegments] = useState<Set<number> | null>(null)

  const { mutate, isPending, error, data } = useMutation({
    mutationFn: (req: Axis3RunRequest) => runAxis3(req),
    onSuccess: () => setVisibleSegments(null), // reset filter on new run
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const region_filter = regionFilter.trim()
      ? regionFilter.split(',').map((s) => s.trim()).filter(Boolean)
      : null
    mutate({ region_filter, h3_resolution: resolution, n_clusters: nClusters, sweep_if_low_silhouette: sweep })
  }

  // Derived: sorted unique segments from the last run
  const segments = useMemo(() => {
    if (!data) return []
    return [...data.segment_profiles].sort((a, b) => a.segment_id - b.segment_id)
  }, [data])

  function toggleSegment(id: number) {
    setVisibleSegments((prev) => {
      // Start from "all visible" when first toggling
      const base = prev ?? new Set(segments.map((s) => s.segment_id))
      const next = new Set(base)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      // If all are selected again, go back to null (= all)
      return next.size === segments.length ? null : next
    })
  }

  const err = error as { response?: { data?: { detail?: string } }; message?: string } | null

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-bold text-ind-text">Segmentação de Mercado</h1>
        <p className="text-ind-muted text-sm mt-0.5">Perfis de mercado para targeting promocional com K-Means++.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div>
          <form onSubmit={handleSubmit}>
            <AxisForm title="Parâmetros" description="Configure o pipeline de segmentação.">
              <FormField label="Filtrar por região (opcional)" hint="Deixe em branco para analisar todo o dataset. Para restringir a uma área, informe os códigos de região fornecidos pelo administrador.">
                <TextInput value={regionFilter} onChange={setRegionFilter} placeholder="Ex.: 85283473fffffff" monospace />
              </FormField>
              <FormField label="Nível de detalhe geográfico" hint="Padrão é mais rápido. Detalhado revela problemas em áreas densas, mas demora mais.">
                <SelectInput value={resolution} onChange={(v) => setResolution(parseInt(v) as 8 | 9)} options={[{ value: 8, label: 'Padrão (visão por bairro)' }, { value: 9, label: 'Detalhado (visão por quarteirão)' }]} />
              </FormField>
              <FormField label={`Número de Segmentos (k): ${nClusters}`} hint="K-Means++ — número de clusters">
                <Slider min={2} max={10} step={1} value={nClusters} onChange={setNClusters} format={(v) => String(Math.round(v))} />
              </FormField>
              <Toggle value={sweep} onChange={setSweep} label="Sweep automático se silhouette baixo" description="Busca k ∈ [3,6] quando silhouette < 0.30" />
              {err && <ErrorBanner message={err.response?.data?.detail ?? err.message ?? 'Erro desconhecido'} />}
              <RunButton isPending={isPending} />
            </AxisForm>
          </form>
        </div>

        <div className="lg:col-span-2 space-y-4">
          {data ? (
            <>
              {data.resolution_warning && (
                <div className="bg-yellow-950/40 border border-yellow-700 rounded-lg p-3 text-xs text-yellow-300">
                  <span className="font-semibold text-yellow-400">⚠ Aviso: </span>{data.resolution_warning}
                </div>
              )}
              <div className="grid grid-cols-3 gap-3">
                <KpiCard label="Hexágonos Segmentados" value={data.total_hexagons_segmented.toLocaleString('pt-BR')} />
                <KpiCard label="Segmentos" value={data.n_segments.toLocaleString('pt-BR')} sub="K-Means++" valueColor="text-ind-segment" />
                <KpiCard label="Silhouette Global" value={data.silhouette_score_global?.toFixed(3) ?? '—'} sub={data.silhouette_score_global == null ? undefined : data.silhouette_score_global >= 0.50 ? 'Boa separação' : data.silhouette_score_global >= 0.30 ? 'Separação razoável' : 'Sobreposição detectada'} />
              </div>
              <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted mb-3 pb-2 border-b border-ind-border">Distribuição de Segmentos</div>
                <SegmentPieChart segments={data.segment_profiles} />
              </div>
              <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
                <div className="flex items-center justify-between mb-3 pb-2 border-b border-ind-border">
                  <span className="text-xs font-semibold uppercase tracking-wider text-ind-muted">Mapa — Segmentos de Mercado</span>
                  {/* Segment filter pills */}
                  <div className="flex items-center gap-1.5 flex-wrap justify-end">
                    <button
                      type="button"
                      onClick={() => setVisibleSegments(null)}
                      className={`px-2 py-0.5 rounded text-[10px] font-semibold border transition-colors ${
                        visibleSegments === null
                          ? 'bg-ind-accent/20 border-ind-accent text-ind-accent'
                          : 'border-ind-border text-ind-muted hover:border-ind-accent/60 hover:text-ind-text'
                      }`}
                    >
                      Todos
                    </button>
                    {segments.map((s) => {
                      const col = segmentColour(s.segment_id)
                      const active = visibleSegments === null || visibleSegments.has(s.segment_id)
                      return (
                        <button
                          key={s.segment_id}
                          type="button"
                          onClick={() => toggleSegment(s.segment_id)}
                          title={s.segment_name}
                          className="px-2 py-0.5 rounded text-[10px] font-semibold border transition-all"
                          style={{
                            borderColor: active ? col : 'transparent',
                            color: active ? col : '#6b7280',
                            backgroundColor: active ? `${col}1a` : 'transparent',
                            outline: active ? undefined : '1px solid #374151',
                          }}
                        >
                          S{s.segment_id}
                        </button>
                      )
                    })}
                  </div>
                </div>
                <HexMap axis3Results={data.results} axis3VisibleSegments={visibleSegments ?? undefined} height="260px" />
              </div>
              <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted mb-2 pb-2 border-b border-ind-border">
                  Perfis de Segmento
                </div>
                <SegmentTable profiles={data.segment_profiles} />
              </div>
            </>
          ) : (
            <div className="flex items-center justify-center min-h-[300px] text-ind-muted text-sm border border-ind-border border-dashed rounded-lg">
              Configure os parâmetros e clique em "Executar Eixo" para ver os resultados.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
