import { useState, useRef, useEffect } from 'react'
import { useMutation } from '@tanstack/react-query'
import { useReportStore } from '../stores/reportStore'
import { sendChatMessage } from '../api/chatApi'
import type { ChatMessage } from '../api/chatApi'

// ── Message bubble ─────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'
  const isStub = !isUser && msg.is_stub
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      {!isUser && (
        <div className={[
          'w-6 h-6 rounded-full flex items-center justify-center text-[9px] font-bold mr-2 mt-0.5 shrink-0',
          isStub
            ? 'bg-amber-900/30 border border-amber-600/40 text-amber-400'
            : 'bg-ind-accent/20 border border-ind-accent/40 text-ind-accent',
        ].join(' ')}>
          {isStub ? '⚠' : 'AI'}
        </div>
      )}
      <div
        className={[
          'max-w-[85%] px-3 py-2 rounded-lg text-sm leading-relaxed whitespace-pre-wrap',
          isUser
            ? 'bg-ind-accent/10 text-ind-text border border-ind-accent/20 rounded-tr-none'
            : isStub
              ? 'bg-amber-950/30 text-amber-300 border border-amber-800/50 rounded-tl-none'
              : 'bg-ind-surface text-ind-muted border border-ind-border rounded-tl-none',
        ].join(' ')}
      >
        {msg.content}
      </div>
    </div>
  )
}

// ── Typing indicator ───────────────────────────────────────────────────────

function TypingIndicator() {
  return (
    <div className="flex justify-start mb-3">
      <div className="w-6 h-6 rounded-full bg-ind-accent/20 border border-ind-accent/40 flex items-center justify-center text-[9px] font-bold text-ind-accent mr-2 mt-0.5 shrink-0">
        AI
      </div>
      <div className="bg-ind-surface border border-ind-border rounded-lg rounded-tl-none px-4 py-3 flex items-center gap-1">
        <span className="w-1.5 h-1.5 rounded-full bg-ind-muted animate-bounce" style={{ animationDelay: '0ms' }} />
        <span className="w-1.5 h-1.5 rounded-full bg-ind-muted animate-bounce" style={{ animationDelay: '150ms' }} />
        <span className="w-1.5 h-1.5 rounded-full bg-ind-muted animate-bounce" style={{ animationDelay: '300ms' }} />
      </div>
    </div>
  )
}

// ── Suggested questions ─────────────────────────────────────────────────────

const SUGGESTIONS = [
  'Qual cluster tem o maior TAM e por quê?',
  'Quais regiões têm infraestrutura crítica?',
  'Como devo priorizar os investimentos?',
  'Explique o segmento de maior vulnerabilidade.',
  'Qual é o potencial de receita mensal total?',
]

// ── Main drawer ────────────────────────────────────────────────────────────

// Provider hint stored from the last RunPage execution (persisted in localStorage)
function getProviderHint(): string {
  return localStorage.getItem('last_llm_provider') ?? sessionStorage.getItem('last_llm_provider') ?? 'stub'
}

export default function AgentChatDrawer() {
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [history, setHistory] = useState<ChatMessage[]>([])
  const [stubWarning, setStubWarning] = useState(false)
  const report = useReportStore(s => s.report)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [history])

  // Focus input when drawer opens
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 100)
  }, [open])

  const { mutate, isPending } = useMutation({
    mutationFn: ({ question }: { question: string }) => {
      if (!report) throw new Error('Nenhuma análise disponível.')
      // Pass a condensed version of the report as context, plus the LLM provider hint
      const ctx = {
        run_id: report.run_id,
        region_scope: report.region_scope,
        axes_executed: report.axes_executed,
        summary: report.summary,
        investment_hypotheses: report.investment_hypotheses,
        axis1_summary: report.axis1_summary,
        axis2_summary: report.axis2_summary,
        axis3_summary: report.axis3_summary,
        interpretations: report.interpretations,
        llm_provider_hint: getProviderHint(),
      } as Record<string, unknown>
      return sendChatMessage(question, ctx, history)
    },
    onSuccess: (data, { question }) => {
      setStubWarning(data.is_stub)
      setHistory(prev => [
        ...prev,
        { role: 'user', content: question },
        { role: 'assistant', content: data.answer, is_stub: data.is_stub },
      ])
    },
    onError: (err: unknown, { question }) => {
      setStubWarning(false)
      const status = (err as { response?: { status?: number } })?.response?.status
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
        ?? (err as { message?: string })?.message
        ?? 'Erro desconhecido'

      // 401/403 = chave ausente ou inválida
      const msg = (status === 401 || status === 403)
        ? 'Chave de API não configurada ou inválida. Acesse "Análise Completa" e preencha o campo X-API-Key antes de usar o chat.'
        : `Erro do servidor: ${detail}`

      setHistory(prev => [
        ...prev,
        { role: 'user', content: question },
        { role: 'assistant', content: msg, is_stub: true },
      ])
    },
  })

  const handleSend = () => {
    const q = input.trim()
    if (!q || isPending) return
    setInput('')
    mutate({ question: q })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleSuggestion = (s: string) => {
    setInput(s)
    inputRef.current?.focus()
  }

  const clearHistory = () => setHistory([])

  return (
    <>
      {/* Floating button */}
      <button
        onClick={() => setOpen(v => !v)}
        className={[
          'fixed bottom-6 right-6 z-40 w-14 h-14 rounded-full shadow-lg',
          'flex items-center justify-center transition-all duration-200',
          'border-2',
          open
            ? 'bg-ind-surface border-ind-border text-ind-muted hover:text-ind-text'
            : 'bg-ind-accent border-transparent text-ind-bg hover:bg-amber-400',
        ].join(' ')}
        title={open ? 'Fechar chat' : 'Perguntar ao agente'}
        aria-label={open ? 'Fechar chat' : 'Perguntar ao agente'}
      >
        {open
          ? <span className="text-xl leading-none">×</span>
          : <span className="text-xl leading-none">💬</span>
        }
      </button>

      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/20"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Drawer */}
      {open && (
        <div className="fixed bottom-24 right-6 z-40 w-96 max-h-[75vh] flex flex-col bg-ind-bg border border-ind-border rounded-xl shadow-2xl overflow-hidden">

          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 bg-ind-surface border-b border-ind-border shrink-0">
            <div>
              <div className="text-sm font-bold text-ind-text">Agente Telecom AI</div>
              <div className="text-[10px] text-ind-muted">
                {report
                  ? `Contexto: ${report.region_scope} · ${report.run_id.slice(0, 8)}…`
                  : 'Nenhuma análise carregada'}
              </div>
            </div>
            {history.length > 0 && (
              <button
                onClick={clearHistory}
                className="text-[10px] text-ind-muted hover:text-ind-danger transition-colors"
                title="Limpar conversa"
              >
                limpar
              </button>
            )}
          </div>

          {/* Messages area */}
          <div className="flex-1 overflow-y-auto px-4 py-4 min-h-0">
            {!report ? (
              <div className="text-center py-8 text-ind-muted text-sm">
                <div className="text-2xl mb-2">▦</div>
                Execute uma análise completa primeiro para poder perguntar sobre os dados.
              </div>
            ) : history.length === 0 ? (
              <div>
                <p className="text-ind-muted text-xs text-center mb-4">
                  Faça perguntas sobre os resultados da análise atual.
                </p>
                <div className="space-y-2">
                  {SUGGESTIONS.map(s => (
                    <button
                      key={s}
                      onClick={() => handleSuggestion(s)}
                      className="w-full text-left px-3 py-2 rounded-lg border border-ind-border text-xs text-ind-muted hover:border-ind-accent hover:text-ind-text transition-colors bg-ind-surface"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {history.map((msg, i) => (
                  <MessageBubble key={i} msg={msg} />
                ))}
                {isPending && <TypingIndicator />}
                <div ref={bottomRef} />
              </>
            )}
          </div>

          {/* Input area */}
          {report && (
            <div className="shrink-0 px-4 py-3 border-t border-ind-border bg-ind-surface">
              <div className="flex gap-2 items-center">
                <input
                  ref={inputRef}
                  type="text"
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Pergunte sobre clusters, TAM, anomalias…"
                  disabled={isPending}
                  className="flex-1 bg-ind-bg border border-ind-border rounded-lg px-3 py-2 text-ind-text text-sm placeholder:text-ind-muted/50 focus:outline-none focus:border-ind-accent disabled:opacity-50"
                />
                <button
                  onClick={handleSend}
                  disabled={!input.trim() || isPending}
                  className="shrink-0 w-9 h-9 rounded-lg bg-ind-accent text-ind-bg flex items-center justify-center hover:bg-amber-400 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  title="Enviar (Enter)"
                >
                  {isPending
                    ? <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/></svg>
                    : <span className="text-sm font-bold">↑</span>
                  }
                </button>
              </div>
              {stubWarning && (
                <p className="text-[10px] text-amber-400 mt-1.5 text-center">
                  ⚠️ Chat em modo stub — configure <code className="font-mono">LLM_PROVIDER=gemini</code> no servidor
                </p>
              )}
              {!stubWarning && (
                <p className="text-[10px] text-ind-muted mt-1.5 text-center">
                  Enter para enviar · Gemini · OpenAI · watsonx
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </>
  )
}
