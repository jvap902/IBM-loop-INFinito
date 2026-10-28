import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import AxisForm, { FormField, Slider, SelectInput, Toggle, RunButton, ErrorBanner, TextInput } from '../components/AxisForm'
import KpiCard from '../components/KpiCard'
import HexMap from '../components/HexMap'
import TamBarChart from '../components/TamBarChart'
import { runAxis2 } from '../api/axisApi'
import type { Axis2RunResponse, Axis2RunRequest } from '../types'

const fmtBrl = (v: number | null) =>
  v == null ? '—' : 'R$ ' + v.toLocaleString('pt-BR', { maximumFractionDigits: 0 })

function ClusterTable({ clusters }: { clusters: Axis2RunResponse['clusters'] }) {
  const real = clusters.filter((c) => c.is_noise === 0)
  return (
    <div className="overflow-x-auto mt-3">
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-ind-border">
            {['Cluster', 'Hexágonos', 'Vel↓ Mbps', 'Domic.', 'HHI', 'TAM'].map((h) => (
              <th key={h} className="px-3 py-2 text-left font-semibold uppercase tracking-wider text-ind-muted text-[10px]">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {real.map((c) => (
            <tr key={c.cluster_id} className="border-b border-ind-border/40 hover:bg-ind-surface transition-colors">
              <td className="px-3 py-1.5">
                <div className="font-mono text-ind-cluster font-semibold">C{c.cluster_id}</div>
                {c.place_name && <div className="text-[10px] text-ind-muted mt-0.5">{c.place_name}</div>}
              </td>
              <td className="px-3 py-1.5">{c.cluster_size}</td>
              <td className="px-3 py-1.5">{c.avg_d_down?.toFixed(1) ?? '—'}</td>
              <td className="px-3 py-1.5">{c.avg_n_dom?.toFixed(0) ?? '—'}</td>
              <td className="px-3 py-1.5">{c.avg_HHI?.toFixed(0) ?? '—'}</td>
              <td className="px-3 py-1.5 text-ind-accent font-semibold">{fmtBrl(c.tam_estimate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {real.length === 0 && <div className="text-center py-6 text-ind-muted">Nenhum cluster encontrado.</div>}
    </div>
  )
}

export default function Axis2Page() {
  const [regionFilter, setRegionFilter] = useState('')
  const [resolution, setResolution] = useState<8 | 9>(8)
  const [minClusterSize, setMinClusterSize] = useState(50)
  const [skipUmap, setSkipUmap] = useState(false)

  const { mutate, isPending, error, data } = useMutation({
    mutationFn: (req: Axis2RunRequest) => runAxis2(req),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const region_filter = regionFilter.trim()
      ? regionFilter.split(',').map((s) => s.trim()).filter(Boolean)
      : null
    mutate({ region_filter, h3_resolution: resolution, min_cluster_size: minClusterSize, skip_umap: skipUmap })
  }

  const err = error as { response?: { data?: { detail?: string } }; message?: string } | null

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-bold text-ind-text">Oportunidades de Expansão</h1>
        <p className="text-ind-muted text-sm mt-0.5">Identifica zonas de alta demanda não atendida usando UMAP + HDBSCAN.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div>
          <form onSubmit={handleSubmit}>
            <AxisForm title="Parâmetros" description="Configure o pipeline de clustering.">
              <FormField label="Filtrar por região (opcional)" hint="Deixe em branco para analisar todo o dataset. Para restringir a uma área, informe os códigos de região fornecidos pelo administrador.">
                <TextInput value={regionFilter} onChange={setRegionFilter} placeholder="Ex.: 85283473fffffff" monospace />
              </FormField>
              <FormField label="Nível de detalhe geográfico" hint="Padrão é mais rápido. Detalhado revela problemas em áreas densas, mas demora mais.">
                <SelectInput value={resolution} onChange={(v) => setResolution(parseInt(v) as 8 | 9)} options={[{ value: 8, label: 'Padrão (visão por bairro)' }, { value: 9, label: 'Detalhado (visão por quarteirão)' }]} />
              </FormField>
              <FormField label={`Tamanho Mínimo de Cluster: ${minClusterSize}`} hint="HDBSCAN min_cluster_size">
                <Slider min={2} max={500} step={1} value={minClusterSize} onChange={setMinClusterSize} format={(v) => String(Math.round(v))} />
              </FormField>
              <Toggle value={skipUmap} onChange={setSkipUmap} label="Pular UMAP" description="Usa features escaladas diretamente (mais rápido)" />
              {err && <ErrorBanner message={err.response?.data?.detail ?? err.message ?? 'Erro desconhecido'} />}
              <RunButton isPending={isPending} />
            </AxisForm>
          </form>
        </div>

        <div className="lg:col-span-2 space-y-4">
          {data ? (
            <>
              <div className="grid grid-cols-3 gap-3">
                <KpiCard label="Hexágonos Processados" value={data.total_hexagons_processed.toLocaleString('pt-BR')} />
                <KpiCard label="Clusters de Expansão" value={data.n_clusters.toLocaleString('pt-BR')} sub={`Taxa ruído: ${(data.noise_rate * 100).toFixed(1)}%`} valueColor="text-ind-cluster" />
                <KpiCard label="Duração" value={`${data.duration_seconds.toFixed(2)}s`} sub={`Run: ${data.run_id.slice(0, 8)}…`} />
              </div>
              <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted mb-3 pb-2 border-b border-ind-border">TAM por Cluster</div>
                <TamBarChart clusters={data.clusters} />
              </div>
              <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted mb-3 pb-2 border-b border-ind-border">Mapa — Clusters</div>
                <HexMap axis2Clusters={data.clusters} height="260px" />
              </div>
              <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
                <div className="text-xs font-semibold uppercase tracking-wider text-ind-muted mb-2 pb-2 border-b border-ind-border">
                  Tabela de Clusters ({data.n_clusters})
                </div>
                <ClusterTable clusters={data.clusters} />
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
