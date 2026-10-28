import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listReports, getReport, deleteReport } from '../api/reportsApi'
import type { ReportMeta } from '../api/reportsApi'

// ── Minimal Markdown → HTML renderer (no external dep) ────────────────────

function renderMarkdown(md: string): string {
  return md
    // Headings
    .replace(/^#### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    // Bold / italic
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Horizontal rule
    .replace(/^---+$/gm, '<hr />')
    // Blockquote
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
    // Table rows — detect | … | lines
    .replace(/^\|(.+)\|$/gm, (_, inner) => {
      const cells = inner.split('|').map((c: string) => c.trim())
      const isHeader = cells.every((c: string) => /^-+$/.test(c))
      if (isHeader) return ''
      return '<tr>' + cells.map((c: string) => `<td>${c}</td>`).join('') + '</tr>'
    })
    // Wrap consecutive <tr> in <table>
    .replace(/(<tr>[\s\S]*?<\/tr>\n?)+/g, (match) => `<table>${match}</table>`)
    // Unordered list items
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>[\s\S]*?<\/li>\n?)+/g, (match) => `<ul>${match}</ul>`)
    // Paragraphs — blank-line separated blocks that aren't already HTML
    .split(/\n{2,}/)
    .map((block) => {
      const trimmed = block.trim()
      if (!trimmed) return ''
      if (/^<(h[1-6]|ul|ol|li|table|tr|td|th|hr|blockquote)/.test(trimmed)) return trimmed
      return `<p>${trimmed.replace(/\n/g, '<br />')}</p>`
    })
    .join('\n')
}

// ── Sub-components ─────────────────────────────────────────────────────────

function ReportListItem({
  report,
  isSelected,
  onClick,
  onDelete,
  isDeleting,
}: {
  report: ReportMeta
  isSelected: boolean
  onClick: () => void
  onDelete: () => void
  isDeleting: boolean
}) {
  const [confirming, setConfirming] = useState(false)
  const kb = (report.size_bytes / 1024).toFixed(1)

  return (
    <div className="group relative">
      <button
        onClick={onClick}
        className={[
          'w-full text-left px-3 py-2.5 rounded transition-colors border pr-8',
          isSelected
            ? 'bg-ind-accent/10 border-ind-accent text-ind-accent'
            : 'border-transparent text-ind-muted hover:text-ind-text hover:bg-ind-surface',
        ].join(' ')}
      >
        <div className="text-sm font-semibold truncate">{report.region}</div>
        <div className="text-xs mt-0.5 flex items-center justify-between">
          <span>{report.date}</span>
          <span className="font-mono">{kb} KB</span>
        </div>
      </button>

      {/* Delete button — visible on hover */}
      {!confirming && (
        <button
          onClick={(e) => { e.stopPropagation(); setConfirming(true) }}
          disabled={isDeleting}
          title="Excluir relatório"
          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity text-ind-muted hover:text-red-400 text-sm leading-none p-0.5 disabled:opacity-30"
        >
          ✕
        </button>
      )}

      {/* Inline confirm */}
      {confirming && (
        <div className="mt-1 px-1 flex gap-1.5 items-center">
          <span className="text-[10px] text-ind-muted flex-1">Excluir?</span>
          <button
            onClick={() => { onDelete(); setConfirming(false) }}
            className="px-2 py-0.5 rounded text-[10px] bg-red-900/40 text-red-400 border border-red-800/50 hover:bg-red-900/70 transition-colors"
          >
            Sim
          </button>
          <button
            onClick={() => setConfirming(false)}
            className="px-2 py-0.5 rounded text-[10px] text-ind-muted border border-ind-border hover:text-ind-text transition-colors"
          >
            Não
          </button>
        </div>
      )}
    </div>
  )
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <div
      className="prose-report"
      dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
    />
  )
}

// ── Page ───────────────────────────────────────────────────────────────────

export default function ReportsPage() {
  const [selectedFilename, setSelectedFilename] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const {
    data: listData,
    isLoading: listLoading,
    error: listError,
  } = useQuery({
    queryKey: ['reports-list'],
    queryFn: listReports,
  })

  const {
    data: reportData,
    isLoading: reportLoading,
    error: reportError,
  } = useQuery({
    queryKey: ['report-content', selectedFilename],
    queryFn: () => getReport(selectedFilename!),
    enabled: !!selectedFilename,
  })

  const { mutate: removeReport, variables: deletingFilename, isPending: isDeletePending } = useMutation({
    mutationFn: (filename: string) => deleteReport(filename),
    onSuccess: (_data, filename) => {
      // If the deleted report was selected, deselect it
      if (selectedFilename === filename) setSelectedFilename(null)
      queryClient.invalidateQueries({ queryKey: ['reports-list'] })
    },
  })

  const listErr = listError as { message?: string } | null
  const repErr = reportError as { response?: { data?: { detail?: string } }; message?: string } | null

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6">
        <h1 className="text-lg font-bold text-ind-text">Relatórios</h1>
        <p className="text-ind-muted text-sm mt-0.5">
          Relatórios gerados pelo agente após cada análise completa.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* ── List panel ── */}
        <div className="lg:col-span-1">
          <div className="bg-ind-surface border border-ind-border rounded-lg p-3">
            <div className="text-[10px] font-semibold uppercase tracking-widest text-ind-muted mb-2 pb-2 border-b border-ind-border">
              Arquivos disponíveis
            </div>

            {listLoading && (
              <div className="text-ind-muted text-xs py-4 text-center">Carregando…</div>
            )}

            {listErr && (
              <div className="text-red-400 text-xs py-2">
                Erro: {listErr.message ?? 'Falha ao carregar lista'}
              </div>
            )}

            {listData && listData.reports.length === 0 && (
              <div className="text-ind-muted text-xs py-4 text-center">
                Nenhum relatório encontrado.
              </div>
            )}

            {listData && listData.reports.length > 0 && (
              <div className="space-y-1">
                {listData.reports.map((r) => (
                  <ReportListItem
                    key={r.filename}
                    report={r}
                    isSelected={r.filename === selectedFilename}
                    onClick={() => setSelectedFilename(r.filename)}
                    onDelete={() => removeReport(r.filename)}
                    isDeleting={isDeletePending && deletingFilename === r.filename}
                  />
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Content panel ── */}
        <div className="lg:col-span-3">
          <div className="bg-ind-surface border border-ind-border rounded-lg min-h-[500px]">
            {!selectedFilename && (
              <div className="flex items-center justify-center h-[500px] text-ind-muted text-sm">
                Selecione um relatório para visualizar.
              </div>
            )}

            {selectedFilename && reportLoading && (
              <div className="flex items-center justify-center h-[500px] text-ind-muted text-sm">
                Carregando relatório…
              </div>
            )}

            {repErr && (
              <div className="p-6 text-red-400 text-sm">
                Erro: {repErr.response?.data?.detail ?? repErr.message ?? 'Falha ao carregar relatório'}
              </div>
            )}

            {reportData && (
              <>
                {/* Header bar */}
                <div className="flex items-center justify-between px-5 py-3 border-b border-ind-border">
                  <span className="font-mono text-xs text-ind-muted">{reportData.filename}</span>
                  <a
                    href={`/v1/reports/${encodeURIComponent(reportData.filename)}`}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-ind-accent hover:underline"
                  >
                    Abrir raw ↗
                  </a>
                </div>
                {/* Markdown body */}
                <div className="p-6 overflow-auto">
                  <MarkdownContent content={reportData.content} />
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
