import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import AxisForm, { FormField, Slider, SelectInput, NumberInput, RunButton, ErrorBanner, TextInput } from '../components/AxisForm'
import KpiCard from '../components/KpiCard'
import HexMap from '../components/HexMap'
import { runAxis1 } from '../api/axisApi'
import type { Axis1RunResponse, Axis1RunRequest } from '../types'

function CriticalTable({ results }: { results: Axis1RunResponse['results'] }) {
  const critical = results.filter((r) => r.is_critical === 1).slice(0, 50)
  return (
    <div className="overflow-x-auto mt-3">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-ind-border">
            {['H3 ID', 'Lat', 'Lon', 'Score Anomalia', 'LOF', 'Cloudflare'].map((h) => (
              <th key={h} className="px-3 py-2 text-left font-semibold uppercase tracking-wider text-ind-muted text-[10px]">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {critical.map((r) => (
            <tr key={r.h3_id} className="border-b border-ind-border/40 hover:bg-ind-surface transition-colors">
              <td className="px-3 py-1.5 font-mono text-ind-muted">{r.h3_id}</td>
              <td className="px-3 py-1.5">{r.lat_centroid.toFixed(4)}</td>
              <td className="px-3 py-1.5">{r.lon_centroid.toFixed(4)}</td>
              <td className="px-3 py-1.5 text-ind-danger font-semibold">{r.anomaly_score.toFixed(3)}</td>
              <td className="px-3 py-1.5">{r.lof_score.toFixed(3)}</td>
              <td className="px-3 py-1.5">{r.cloudflare_outage_overlap === 1 ? <span className="text-orange-400 font-semibold">Sim</span> : 'Não'}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {critical.length === 0 && <div className="text-center py-6 text-ind-muted">Nenhum hexágono crítico encontrado.</div>}
    </div>
  )
}

export default function Axis1Page() {
  const [regionFilter, setRegionFilter] = useState('')
  const [resolution, setResolution] = useState<8 | 9>(8)
  const [threshold, setThreshold] = useState(0.65)
  const [contamination, setContamination] = useState(0.05)
  const [topN, setTopN] = useState(50)

  const { mutate, isPending, error, data } = useMutation({
    mutationFn: (req: Axis1RunRequest) => runAxis1(req),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const region_filter = regionFilter.trim()
      ? regionFilter.split(',').map((s) => s.trim()).filter(Boolean)
      : null
    mutate({ region_filter, h3_resolution: resolution, anomaly_threshold: threshold, contamination, top_n: topN })
  }

  const err = error as { response?: { data?: { detail?: string } }; message?: string } | null

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-bold text-ind-text">Eixo 1 — Manutenção / Criticidade</h1>
        <p className="text-ind-muted text-sm mt-0.5">Detecção de anomalias com IsolationForest + Local Outlier Factor.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Form panel */}
        <div>
          <form onSubmit={handleSubmit}>
            <AxisForm title="Parâmetros" description="Configure o pipeline de anomalias.">
              <FormField label="Filtro de Região (H3 IDs, vírgula)" hint="Deixe vazio para o dataset completo">
                <TextInput value={regionFilter} onChange={setRegionFilter} placeholder="85283473fffffff, 8528347bfffffff" monospace />
              </FormField>
              <FormField label="Resolução H3">
                <SelectInput value={resolution} onChange={(v) => setResolution(parseInt(v) as 8 | 9)} options={[{ value: 8, label: 'Resolução 8' }, { value: 9, label: 'Resolução 9' }]} />
              </FormField>
              <FormField label={`Threshold de Anomalia: ${threshold.toFixed(2)}`} hint="Score ≥ threshold → hexágono crítico">
                <Slider min={0} max={1} step={0.01} value={threshold} onChange={setThreshold} format={(v) => v.toFixed(2)} />
              </FormField>
              <FormField label={`Contaminação: ${contamination.toFixed(2)}`} hint="Fração esperada de anomalias">
                <Slider min={0.01} max={0.5} step={0.01} value={contamination} onChange={setContamination} format={(v) => v.toFixed(2)} />
              </FormField>
              <FormField label="Top N hexágonos críticos">
                <NumberInput value={topN} onChange={setTopN} min={1} max={5000} />
              </FormField>
              {err && <ErrorBanner message={err.response?.data?.detail ?? err.message ?? 'Erro desconhecido'} />}
              <RunButton isPending={isPending} />
            </AxisForm>
          </form>
        </div>

        {/* Results panel */}
        <div className="lg:col-span-2 space-y-4">
          {data ? (
            <>
              <div className="grid grid-cols-3 gap-3">
                <KpiCard label="Hexágonos Analisados" value={data.total_hexagons_scored.toLocaleString('pt-BR')} sub={`Res. ${resolution}`} />
                <KpiCard label="Anomalias Críticas" value={data.n_critical.toLocaleString('pt-BR')} sub={`${(data.anomaly_rate * 100).toFixed(1)}% do total`} valueColor="text-ind-danger" />
                <KpiCard label="Duração" value={`${data.duration_seconds.toFixed(2)}s`} sub={`Run: ${data.run_id.slice(0, 8)}…`} />
              </div>
              <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted mb-3 pb-2 border-b border-ind-border">Mapa — Hexágonos Críticos</div>
                <HexMap axis1Results={data.results} height="280px" />
              </div>
              <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted mb-2 pb-2 border-b border-ind-border">
                  Top {Math.min(50, data.n_critical)} Hexágonos Críticos
                </div>
                <CriticalTable results={data.results} />
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
