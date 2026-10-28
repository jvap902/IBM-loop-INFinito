import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import { listRuns, getRun } from '../api/runsApi'
import { useReportStore } from '../stores/reportStore'
import type { RunMeta } from '../api/runsApi'

const fmtBrl = (v: number) =>
  'R$ ' + v.toLocaleString('pt-BR', { maximumFractionDigits: 0 })

const PRIORITY_COLORS: Record<string, string> = {
  P1: 'text-red-400 bg-red-900/20 border-red-800/40',
  P2: 'text-amber-400 bg-amber-900/20 border-amber-800/40',
  P3: 'text-ind-muted bg-ind-surface border-ind-border',
}

function PriorityBadge({ p1, p2 }: { p1: number; p2: number }) {
  if (p1 > 0)
    return (
      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${PRIORITY_COLORS.P1}`}>
        {p1} P1
      </span>
    )
  if (p2 > 0)
    return (
      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${PRIORITY_COLORS.P2}`}>
        {p2} P2
      </span>
    )
  return (
    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${PRIORITY_COLORS.P3}`}>
      P3
    </span>
  )
}

function RunCard({
  run,
  isActive,
  onLoad,
  isLoading,
}: {
  run: RunMeta
  isActive: boolean
  onLoad: () => void
  isLoading: boolean
}) {
  return (
    <div
      className={[
        'border rounded-lg p-4 transition-colors',
        isActive
          ? 'border-ind-accent bg-ind-accent/5'
          : 'border-ind-border bg-ind-surface hover:border-ind-accent/50',
      ].join(' ')}
    >
      {/* Top row */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div>
          <div className="font-semibold text-ind-text text-sm">{run.region_scope}</div>
          <div className="text-ind-muted text-xs mt-0.5">{run.timestamp}</div>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <PriorityBadge p1={run.p1_clusters} p2={run.p2_clusters} />
          {isActive && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded border border-ind-accent/40 text-ind-accent bg-ind-accent/10">
              ativo
            </span>
          )}
        </div>
      </div>

      {/* KPI row */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className="text-center">
          <div className="text-ind-danger font-bold text-sm">{run.n_critical_hexagons}</div>
          <div className="text-ind-muted text-[10px]">Críticos</div>
        </div>
        <div className="text-center">
          <div className="text-ind-cluster font-bold text-sm">{run.n_expansion_clusters}</div>
          <div className="text-ind-muted text-[10px]">Clusters</div>
        </div>
        <div className="text-center">
          <div className="text-ind-accent font-bold text-sm truncate">{fmtBrl(run.total_tam_brl)}</div>
          <div className="text-ind-muted text-[10px]">TAM/ano</div>
        </div>
      </div>

      {/* Axes + duration */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex gap-1">
          {run.axes_executed.map((a) => (
            <span
              key={a}
              className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-ind-bg border border-ind-border text-ind-muted"
            >
              {a}
            </span>
          ))}
        </div>
        <span className="text-[10px] text-ind-muted font-mono">{run.duration_seconds.toFixed(1)}s</span>
      </div>

      {/* Load button */}
      <button
        onClick={onLoad}
        disabled={isLoading || isActive}
        className={[
          'w-full py-1.5 rounded text-xs font-bold transition-colors',
          isActive
            ? 'bg-ind-accent/10 text-ind-accent cursor-default'
            : 'bg-ind-accent text-ind-bg hover:bg-amber-400 disabled:opacity-50 disabled:cursor-not-allowed',
        ].join(' ')}
      >
        {isLoading ? 'Carregando…' : isActive ? '✓ Carregado no Dashboard' : 'Carregar no Dashboard'}
      </button>
    </div>
  )
}

export default function RunHistoryPage() {
  const navigate = useNavigate()
  const setReport = useReportStore((s) => s.setReport)
  const activeReport = useReportStore((s) => s.report)

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['runs-list'],
    queryFn: listRuns,
  })

  const { mutate: loadRun, isPending, variables: loadingRunId } = useMutation({
    mutationFn: (runId: string) => getRun(runId),
    onSuccess: (runData) => {
      setReport(runData)
      navigate('/')
    },
  })

  const listErr = error as { response?: { data?: { detail?: string } }; message?: string } | null

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-lg font-bold text-ind-text">Histórico de Análises</h1>
          <p className="text-ind-muted text-sm mt-0.5">
            Análises anteriores salvas no servidor. Carregue qualquer uma para o Dashboard e Chat.
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="text-xs text-ind-muted hover:text-ind-text border border-ind-border rounded px-3 py-1.5 transition-colors"
        >
          ↻ Atualizar
        </button>
      </div>

      {isLoading && (
        <div className="text-ind-muted text-sm py-12 text-center">Carregando histórico…</div>
      )}

      {listErr && (
        <div className="bg-red-950/50 border border-red-800 rounded-lg p-4 text-sm text-red-300">
          <span className="font-semibold text-red-400">Erro: </span>
          {listErr.response?.data?.detail ?? listErr.message ?? 'Falha ao carregar histórico'}
        </div>
      )}

      {data && data.runs.length === 0 && (
        <div className="flex flex-col items-center justify-center min-h-[300px] border border-ind-border border-dashed rounded-lg gap-3 text-ind-muted">
          <div className="text-4xl">▦</div>
          <div className="text-sm">Nenhuma análise encontrada.</div>
          <button
            onClick={() => navigate('/run')}
            className="mt-1 px-4 py-2 bg-ind-accent text-ind-bg rounded font-semibold text-xs hover:bg-amber-400 transition-colors"
          >
            Executar Análise Completa
          </button>
        </div>
      )}

      {data && data.runs.length > 0 && (
        <>
          <div className="text-[10px] text-ind-muted mb-3 uppercase tracking-wider">
            {data.total} análise(s) encontrada(s)
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {data.runs.map((run) => (
              <RunCard
                key={run.run_id}
                run={run}
                isActive={activeReport?.run_id === run.run_id}
                onLoad={() => loadRun(run.run_id)}
                isLoading={isPending && loadingRunId === run.run_id}
              />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
