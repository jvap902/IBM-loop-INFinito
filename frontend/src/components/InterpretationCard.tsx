import { useState } from 'react'

/**
 * Renders business-language interpretation text produced by the interpreter engine.
 * Handles **bold**, line breaks, and bullet points without a full Markdown parser.
 */
interface Props {
  title: string
  text: string
  accentColor?: string
  badge?: string
  badgeColor?: string
  collapsible?: boolean
}

function renderText(text: string) {
  return text.split(/\n\n+/).map((para, pi) => {
    const lines = para.split('\n')
    const hasBullets = lines.some(l => l.trimStart().startsWith('- '))

    const renderLine = (line: string, _li: number) => {
      const parts = line.replace(/^-\s*/, '').split(/\*\*(.*?)\*\*/g)
      return parts.map((part, i) =>
        i % 2 === 1
          ? <strong key={i} className="text-ind-text font-semibold">{part}</strong>
          : <span key={i}>{part}</span>
      )
    }

    if (hasBullets) {
      return (
        <ul key={pi} className="mb-3 space-y-0.5 ml-3">
          {lines.filter(l => l.trim()).map((line, li) => (
            <li key={li} className="list-disc ml-2 text-ind-muted text-sm leading-relaxed">
              {renderLine(line, li)}
            </li>
          ))}
        </ul>
      )
    }

    return (
      <p key={pi} className="mb-3 text-ind-muted text-sm leading-relaxed">
        {lines.map((line, li) => (
          <span key={li}>
            {renderLine(line, li)}
            {li < lines.length - 1 && <br />}
          </span>
        ))}
      </p>
    )
  })
}

export default function InterpretationCard({
  title,
  text,
  accentColor = 'border-ind-accent',
  badge,
  badgeColor = 'bg-ind-accent/10 text-ind-accent',
  collapsible = false,
}: Props) {
  const [collapsed, setCollapsed] = useState(false)

  if (!text || text.startsWith('_')) return null

  return (
    <div className={`bg-ind-surface border-l-4 ${accentColor} rounded-r-lg p-4 mb-4`}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-ind-muted">
            {title}
          </span>
          {badge && (
            <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${badgeColor}`}>
              {badge}
            </span>
          )}
        </div>
        {collapsible && (
          <button
            onClick={() => setCollapsed(c => !c)}
            className="text-ind-muted hover:text-ind-text text-xs transition-colors"
          >
            {collapsed ? '▼ expandir' : '▲ recolher'}
          </button>
        )}
      </div>
      {!collapsed && (
        <div>{renderText(text)}</div>
      )}
    </div>
  )
}
