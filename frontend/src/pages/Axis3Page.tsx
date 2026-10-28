import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import AxisForm, { FormField, Slider, SelectInput, Toggle, RunButton, ErrorBanner, TextInput } from '../components/AxisForm'
import KpiCard from '../components/KpiCard'
import SegmentPieChart from '../components/SegmentPieChart'
import { runAxis3 } from '../api/axisApi'
import type { Axis3RunResponse, Axis3RunRequest } from '../types'

function SegmentTable({ profiles }: { profiles: Axis3RunResponse['segment_profiles'] }) {
  return (
    <div className="overflow-x-auto mt-3">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-ind-border">
            {['Seg.', 'Nome', 'Hexágonos', '% Total', 'Silhouette Médio'].map((h) => (
              <th key={h} className="px-3 py-2 text-left font-semibold uppercase tracking-wider text-ind-muted text-[10px]">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {profiles.map((s) => (
            <tr key={s.segment_id} className="border-b border-ind-border/40 hover:bg-ind-surface transition-colors">
              <td className="px-3 py-1.5 font-mono text-ind-segment font-semibold">S{s.segment_id}</td>
              <td className="px-3 py-1.5 text-ind-text">{s.segment_name}</td>
              <td className="px-3 py-1.5">{s.hexagon_count.toLocaleString('pt-BR')}</td>
              <td className="px-3 py-1.5">{(s.hexagon_fraction * 100).toFixed(1)}%</td>
              <td className="px-3 py-1.5">{s.avg_silhouette?.toFixed(3) ?? '—'}</td>
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

  const { mutate, isPending, error, data } = useMutation({
    mutationFn: (req: Axis3RunRequest) => runAxis3(req),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const region_filter = regionFilter.trim()
      ? regionFilter.split(',').map((s) => s.trim()).filter(Boolean)
      : null
    mutate({ region_filter, h3_resolution: resolution, n_clusters: nClusters, sweep_if_low_silhouette: sweep })
  }

  const err = error as { response?: { data?: { detail?: string } }; message?: string } | null

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-bold text-ind-text">Eixo 3 — Segmentação Promocional</h1>
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
              <div className="grid grid-cols-3 gap-3">
                <KpiCard label="Hexágonos Segmentados" value={data.total_hexagons_segmented.toLocaleString('pt-BR')} />
                <KpiCard label="Segmentos" value={data.n_segments.toLocaleString('pt-BR')} sub="K-Means++" valueColor="text-ind-segment" />
                <KpiCard label="Silhouette Global" value={data.silhouette_score_global?.toFixed(3) ?? '—'} sub={`Duração: ${data.duration_seconds.toFixed(2)}s`} />
              </div>
              <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted mb-3 pb-2 border-b border-ind-border">Distribuição de Segmentos</div>
                <SegmentPieChart segments={data.segment_profiles} />
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
