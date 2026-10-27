import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { runAgent } from '../api/agentApi'
import { useReportStore } from '../stores/reportStore'
import type { AgentRunRequest } from '../types'

const AXES = [
  { id: 'axis1', label: 'Eixo 1 — Manutenção / Criticidade', description: 'IsolationForest + LOF para detecção de anomalias' },
  { id: 'axis2', label: 'Eixo 2 — Expansão',                  description: 'UMAP + HDBSCAN para clusters de oportunidade' },
  { id: 'axis3', label: 'Eixo 3 — Segmentação Promocional',   description: 'K-Means++ para perfis de mercado' },
]

const LLM_OPTIONS = [
  { value: 'stub',    label: 'Stub (sem credenciais)', description: 'Seleciona todos os eixos automaticamente' },
  { value: 'watsonx', label: 'IBM watsonx.ai',         description: 'Requer WATSONX_API_KEY no servidor' },
  { value: 'openai',  label: 'OpenAI GPT-4o',          description: 'Requer OPENAI_API_KEY no servidor' },
]

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-semibold uppercase tracking-widest text-ind-muted mb-2">
      {children}
    </div>
  )
}

export default function RunPage() {
  const navigate = useNavigate()
  const setReport = useReportStore((s) => s.setReport)

  const [region, setRegion] = useState('all')
  const [selectedAxes, setSelectedAxes] = useState<string[]>(['axis1', 'axis2', 'axis3'])
  const [llm, setLlm] = useState<AgentRunRequest['llm_provider']>('stub')
  const [force, setForce] = useState(false)
  const [apiKey, setApiKey] = useState(() => sessionStorage.getItem('api_key') ?? '')
  const [saveKey, setSaveKey] = useState(!!sessionStorage.getItem('api_key'))

  const toggleAxis = (id: string) => {
    setSelectedAxes((prev) =>
      prev.includes(id) ? prev.filter((a) => a !== id) : [...prev, id]
    )
  }

  const { mutate, isPending, error, reset } = useMutation({
    mutationFn: (req: AgentRunRequest) => {
      if (saveKey) sessionStorage.setItem('api_key', apiKey)
      else sessionStorage.removeItem('api_key')
      // Inject key for this request
      sessionStorage.setItem('api_key', apiKey)
      return runAgent(req)
    },
    onSuccess: (data) => {
      setReport(data)
      navigate('/')
    },
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    reset()
    if (selectedAxes.length === 0) return
    mutate({ region, axes: selectedAxes, force, llm_provider: llm })
  }

  const apiError = error as { response?: { data?: { detail?: string } }; message?: string } | null

  return (
    <div className="p-6 max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-bold text-ind-text">Análise Completa</h1>
        <p className="text-ind-muted text-sm mt-0.5">
          Configura e dispara o agente LangGraph com todos os parâmetros selecionados.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">

        {/* API Key */}
        <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
          <SectionTitle>Autenticação</SectionTitle>
          <label className="block text-ind-text text-sm mb-1.5">X-API-Key</label>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="telecom-dev-key-2024"
            className="w-full bg-ind-bg border border-ind-border rounded px-3 py-2 text-ind-text text-sm font-mono focus:outline-none focus:border-ind-accent"
          />
          <label className="flex items-center gap-2 mt-2 text-ind-muted text-xs cursor-pointer">
            <input
              type="checkbox"
              checked={saveKey}
              onChange={(e) => setSaveKey(e.target.checked)}
              className="accent-amber-500"
            />
            Salvar na sessão
          </label>
        </div>

        {/* Region */}
        <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
          <SectionTitle>Região</SectionTitle>
          <label className="block text-ind-text text-sm mb-1.5">
            Região / Identificador H3
          </label>
          <input
            type="text"
            value={region}
            onChange={(e) => setRegion(e.target.value)}
            placeholder="all · BR-SP · 855198c7fffffff"
            className="w-full bg-ind-bg border border-ind-border rounded px-3 py-2 text-ind-text text-sm font-mono focus:outline-none focus:border-ind-accent"
          />
          <p className="text-ind-muted text-xs mt-1">
            Use <code className="font-mono bg-ind-bg px-1 rounded">all</code> para o dataset completo, um label de região (ex: <code className="font-mono bg-ind-bg px-1 rounded">BR-SP</code>), ou um H3 parent cell ID (res 5/6).
          </p>
        </div>

        {/* Axes */}
        <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
          <SectionTitle>Eixos de Análise</SectionTitle>
          <div className="space-y-2">
            {AXES.map(({ id, label, description }) => (
              <label key={id} className="flex items-start gap-3 cursor-pointer group">
                <input
                  type="checkbox"
                  checked={selectedAxes.includes(id)}
                  onChange={() => toggleAxis(id)}
                  className="mt-0.5 accent-amber-500"
                />
                <div>
                  <div className="text-ind-text text-sm group-hover:text-ind-accent transition-colors">{label}</div>
                  <div className="text-ind-muted text-xs">{description}</div>
                </div>
              </label>
            ))}
          </div>
          {selectedAxes.length === 0 && (
            <p className="text-red-400 text-xs mt-2">Selecione ao menos um eixo.</p>
          )}
        </div>

        {/* LLM Provider */}
        <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
          <SectionTitle>Provedor LLM</SectionTitle>
          <div className="space-y-2">
            {LLM_OPTIONS.map(({ value, label, description }) => (
              <label key={value} className="flex items-start gap-3 cursor-pointer group">
                <input
                  type="radio"
                  name="llm"
                  value={value}
                  checked={llm === value}
                  onChange={() => setLlm(value as AgentRunRequest['llm_provider'])}
                  className="mt-0.5 accent-amber-500"
                />
                <div>
                  <div className="text-ind-text text-sm group-hover:text-ind-accent transition-colors">{label}</div>
                  <div className="text-ind-muted text-xs">{description}</div>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* Force toggle */}
        <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
          <SectionTitle>Opções Avançadas</SectionTitle>
          <label className="flex items-center gap-3 cursor-pointer">
            <div
              onClick={() => setForce((f) => !f)}
              className={`w-10 h-5 rounded-full transition-colors relative cursor-pointer ${force ? 'bg-ind-accent' : 'bg-ind-border'}`}
            >
              <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${force ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </div>
            <div>
              <div className="text-ind-text text-sm">Forçar re-execução</div>
              <div className="text-ind-muted text-xs">Ignora verificações de freshness e re-executa todos os eixos</div>
            </div>
          </label>
        </div>

        {/* Error banner */}
        {apiError && (
          <div className="bg-red-950/50 border border-red-800 rounded-lg p-4 text-sm">
            <div className="text-red-400 font-semibold mb-1">Falha na execução</div>
            <div className="text-red-300">
              {apiError.response?.data?.detail ?? apiError.message ?? 'Erro desconhecido'}
            </div>
          </div>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={isPending || selectedAxes.length === 0}
          className="w-full py-3 bg-ind-accent text-ind-bg rounded font-bold text-sm hover:bg-amber-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {isPending ? (
            <>
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              Analisando — aguarde…
            </>
          ) : (
            'Executar Análise'
          )}
        </button>
      </form>

      {/* Loading overlay */}
      {isPending && (
        <div className="fixed inset-0 bg-ind-bg/80 flex flex-col items-center justify-center z-50">
          <svg className="animate-spin h-10 w-10 text-ind-accent mb-4" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          <div className="text-ind-text font-semibold">O agente está processando</div>
          <div className="text-ind-muted text-sm mt-1">Isso pode levar alguns segundos…</div>
        </div>
      )}
    </div>
  )
}
