import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import AxisForm, { FormField, Slider, SelectInput, NumberInput, RunButton, ErrorBanner, TextInput } from '../components/AxisForm'
import KpiCard from '../components/KpiCard'
import HexMap from '../components/HexMap'
import { runAxis1 } from '../api/axisApi'
import type { Axis1RunResponse, Axis1RunRequest } from '../types'

function severityBadge(score: number) {
  if (score >= 0.80) return <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-950/60 text-red-400 border border-red-800">Crítico</span>
  if (score >= 0.65) return <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-orange-950/60 text-orange-400 border border-orange-800">Alto</span>
  return <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-yellow-950/60 text-yellow-500 border border-yellow-800">Médio</span>
}

function scoreColor(score: number) {
  if (score >= 0.80) return 'text-red-400 font-semibold'
  if (score >= 0.65) return 'text-orange-400 font-semibold'
  return 'text-ind-text'
}

function CriticalTable({ results, cloudflareAvailable }: { results: Axis1RunResponse['results']; cloudflareAvailable: boolean }) {
  const critical = results.filter((r) => r.is_critical === 1).slice(0, 50)
  const cfHeader = cloudflareAvailable
    ? 'Ocorrência Cloudflare'
    : 'Ocorrência Cloudflare (sem token)'
  return (
    <div className="overflow-x-auto mt-3">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-ind-border">
            {['Localização', 'Prioridade', 'Score Anomalia', 'Fator LOF', cfHeader].map((h) => (
              <th key={h} className="px-3 py-2 text-left font-semibold uppercase tracking-wider text-ind-muted text-[10px]">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {critical.map((r) => (
            <tr key={r.h3_id} className="border-b border-ind-border/40 hover:bg-ind-surface transition-colors">
              <td className="px-3 py-1.5">
                {r.place_name
                  ? <><div className="text-ind-text">{r.place_name}</div><div className="font-mono text-[10px] text-ind-muted mt-0.5">{r.h3_id}</div></>
                  : <><div className="font-mono text-ind-muted">{r.h3_id}</div><div className="text-[10px] text-ind-muted mt-0.5">{r.lat_centroid.toFixed(4)}, {r.lon_centroid.toFixed(4)}</div></>
                }
              </td>
              <td className="px-3 py-1.5">{severityBadge(r.anomaly_score)}</td>
              <td className={`px-3 py-1.5 ${scoreColor(r.anomaly_score)}`}>{r.anomaly_score.toFixed(3)}</td>
              <td className="px-3 py-1.5">{r.lof_score.toFixed(3)}</td>
              <td className="px-3 py-1.5">
                {r.cloudflare_outage_overlap === 1
                  ? <span className="text-orange-400 font-semibold">⚠ Confirmado</span>
                  : <span className="text-ind-muted">—</span>}
              </td>
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
        <h1 className="text-lg font-bold text-ind-text">Manutenção Necessária</h1>
        <p className="text-ind-muted text-sm mt-0.5">Detecta hexágonos com infraestrutura degradada usando IsolationForest + Local Outlier Factor.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Form panel */}
        <div>
          <form onSubmit={handleSubmit}>
            <AxisForm title="Parâmetros" description="Configure o pipeline de anomalias.">
              <FormField label="Filtrar por região (opcional)" hint="Deixe em branco para o Brasil todo. Use código de estado (ex: SP), nome completo (ex: São Paulo), macro-região (ex: Sudeste) ou múltiplos valores separados por vírgula.">
                <TextInput value={regionFilter} onChange={setRegionFilter} placeholder="Ex.: SP, Sudeste" />
              </FormField>
              <FormField label="Nível de detalhe geográfico" hint="Padrão é mais rápido. Detalhado revela problemas em áreas densas, mas demora mais.">
                <SelectInput value={resolution} onChange={(v) => setResolution(parseInt(v) as 8 | 9)} options={[{ value: 8, label: 'Padrão (visão por bairro)' }, { value: 9, label: 'Detalhado (visão por quarteirão)' }]} />
              </FormField>
              <FormField label={`Threshold de Anomalia: ${threshold.toFixed(2)}`} hint="Score ≥ threshold → hexágono crítico. Faixa operacional validada: 0.30–0.90. Padrão confirmado pela EDA: 0.65.">
                <Slider min={0.30} max={0.90} step={0.01} value={threshold} onChange={setThreshold} format={(v) => v.toFixed(2)} />
              </FormField>
              <FormField label={`Contaminação: ${contamination.toFixed(2)}`} hint="Fração esperada de anomalias pelo IsolationForest. Limitado a 15% para garantir que o modelo opere dentro do intervalo validado.">
                <Slider min={0.01} max={0.15} step={0.01} value={contamination} onChange={setContamination} format={(v) => v.toFixed(2)} />
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
              {data.resolution_warning && (
                <div className="bg-yellow-950/40 border border-yellow-700 rounded-lg p-3 text-xs text-yellow-300">
                  <span className="font-semibold text-yellow-400">⚠ Aviso: </span>{data.resolution_warning}
                </div>
              )}
              {(() => {
                const cfAvailable = data.cloudflare_data_available ?? false
                const nCloudflare = data.results.filter((r) => r.cloudflare_outage_overlap === 1).length
                const cfPct = data.n_critical > 0 ? ((nCloudflare / data.n_critical) * 100).toFixed(1) : '0.0'
                const cfSub = cfAvailable ? `${cfPct}% dos críticos` : 'token não configurado'
                return (
                  <div className="grid grid-cols-3 gap-3">
                    <KpiCard label="Hexágonos Analisados" value={data.total_hexagons_scored.toLocaleString('pt-BR')} sub={`Res. ${resolution}`} />
                    <KpiCard label="Anomalias Críticas" value={data.n_critical.toLocaleString('pt-BR')} sub={`${(data.anomaly_rate * 100).toFixed(1)}% do total`} valueColor="text-ind-danger" />
                    <KpiCard label="Confirmados Cloudflare" value={nCloudflare.toLocaleString('pt-BR')} sub={cfSub} valueColor={cfAvailable ? 'text-orange-400' : 'text-ind-muted'} />
                  </div>
                )
              })()}
              <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted mb-3 pb-2 border-b border-ind-border">Mapa — Hexágonos Críticos</div>
                <HexMap axis1Results={data.results} height="280px" />
              </div>
              <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted mb-2 pb-2 border-b border-ind-border">
                  Top {Math.min(50, data.n_critical)} Hexágonos Críticos
                  <span className="ml-2 normal-case font-normal text-ind-muted">— ordenados por score de anomalia</span>
                </div>
                <CriticalTable results={data.results} cloudflareAvailable={data.cloudflare_data_available ?? false} />
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
