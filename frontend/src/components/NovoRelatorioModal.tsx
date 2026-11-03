import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { generateReport } from '../api/reportsApi'
import type { AgentRunRequest } from '../types'

const LLM_OPTIONS: { value: AgentRunRequest['llm_provider']; label: string; description: string }[] = [
  { value: 'stub',    label: 'Stub (sem credenciais)', description: 'Seleção determinística, sem chamada LLM' },
  { value: 'gemini',  label: 'Google Gemini',          description: 'Requer GEMINI_API_KEY no servidor' },
  { value: 'openai',  label: 'OpenAI GPT-4o',          description: 'Requer OPENAI_API_KEY no servidor' },
  { value: 'watsonx', label: 'IBM watsonx.ai',         description: 'Requer WATSONX_API_KEY + WML no servidor' },
]

interface NovoRelatorioModalProps {
  isOpen: boolean
  runId: string
  onClose: () => void
  onSuccess: (filename: string) => void
}

export default function NovoRelatorioModal({ isOpen, runId, onClose, onSuccess }: NovoRelatorioModalProps) {
  const [prompt, setPrompt] = useState('')
  const [llm, setLlm] = useState<AgentRunRequest['llm_provider']>('stub')

  const { mutate, isPending, error, reset } = useMutation({
    mutationFn: () => generateReport({ run_id: runId, user_prompt: prompt, llm_provider: llm }),
    onSuccess: (data) => {
      reset()
      setPrompt('')
      onSuccess(data.filename)
    },
  })

  const apiError = error as { response?: { data?: { detail?: string } }; message?: string } | null

  if (!isOpen) return null

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!prompt.trim()) return
    reset()
    mutate()
  }

  const handleClose = () => {
    if (isPending) return
    reset()
    setPrompt('')
    onClose()
  }

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-ind-bg/70 z-40 backdrop-blur-sm"
        onClick={handleClose}
        aria-hidden="true"
      />

      {/* Modal */}
      <div
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="novo-relatorio-title"
      >
        <div className="relative bg-ind-surface border border-ind-border rounded-lg w-full max-w-lg shadow-xl">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-ind-border">
            <div>
              <h2 id="novo-relatorio-title" className="text-ind-text font-bold text-base">
                Novo Relatório
              </h2>
              <p className="text-ind-muted text-xs mt-0.5">
                O agente LLM gerará um relatório usando os dados da análise atual.
              </p>
            </div>
            <button
              onClick={handleClose}
              disabled={isPending}
              className="text-ind-muted hover:text-ind-text transition-colors disabled:opacity-30 text-lg leading-none"
              aria-label="Fechar"
            >
              ✕
            </button>
          </div>

          <form onSubmit={handleSubmit} className="p-5 space-y-5">
            {/* Prompt textarea */}
            <div>
              <label htmlFor="report-prompt" className="block text-ind-text text-sm font-medium mb-1.5">
                Instrução para o agente
              </label>
              <textarea
                id="report-prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Ex.: Foque nos clusters P1 e destaque o risco de CAPEX nas regiões nordeste."
                rows={4}
                maxLength={2000}
                disabled={isPending}
                className="w-full bg-ind-bg border border-ind-border rounded px-3 py-2.5 text-ind-text text-sm resize-none focus:outline-none focus:border-ind-accent disabled:opacity-50"
              />
              <div className="flex justify-end mt-1">
                <span className="text-ind-muted text-[10px] font-mono">{prompt.length}/2000</span>
              </div>
            </div>

            {/* LLM Provider */}
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-widest text-ind-muted mb-2">
                Provedor LLM
              </div>
              <div className="space-y-1.5">
                {LLM_OPTIONS.map(({ value, label, description }) => (
                  <label key={value} className="flex items-start gap-3 cursor-pointer group">
                    <input
                      type="radio"
                      name="llm-modal"
                      value={value}
                      checked={llm === value}
                      onChange={() => setLlm(value)}
                      disabled={isPending}
                      className="mt-0.5 accent-amber-500 disabled:opacity-50"
                    />
                    <div>
                      <div className="text-ind-text text-sm group-hover:text-ind-accent transition-colors">{label}</div>
                      <div className="text-ind-muted text-xs">{description}</div>
                    </div>
                  </label>
                ))}
              </div>
            </div>

            {/* Error banner */}
            {apiError && (
              <div className="bg-red-950/50 border border-red-800 rounded-lg p-3 text-sm">
                <div className="text-red-400 font-semibold mb-0.5">Falha na geração</div>
                <div className="text-red-300 text-xs">
                  {apiError.response?.data?.detail ?? apiError.message ?? 'Erro desconhecido'}
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-3 pt-1">
              <button
                type="button"
                onClick={handleClose}
                disabled={isPending}
                className="flex-1 py-2.5 rounded border border-ind-border text-ind-muted text-sm hover:text-ind-text hover:border-ind-text transition-colors disabled:opacity-30"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={isPending || !prompt.trim()}
                className="flex-1 py-2.5 bg-ind-accent text-ind-bg rounded font-bold text-sm hover:bg-amber-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
              >
                {isPending ? (
                  <>
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    Gerando…
                  </>
                ) : (
                  'Gerar Relatório'
                )}
              </button>
            </div>
          </form>

          {/* Full-modal loading overlay */}
          {isPending && (
            <div className="absolute inset-0 bg-ind-surface/80 rounded-lg flex flex-col items-center justify-center gap-3 z-10">
              <svg className="animate-spin h-8 w-8 text-ind-accent" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              <div className="text-ind-text text-sm font-semibold">O agente está escrevendo o relatório…</div>
              <div className="text-ind-muted text-xs">Isso pode levar alguns segundos.</div>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
