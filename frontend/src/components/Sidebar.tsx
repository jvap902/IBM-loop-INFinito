import { NavLink } from 'react-router-dom'

const links = [
  { to: '/',         label: 'Dashboard',             icon: '▦' },
  { to: '/run',      label: 'Análise Completa',      icon: '▶' },
  { to: '/history',  label: 'Histórico',             icon: '◷' },
  { to: '/axis1',    label: 'Eixo 1 — Criticidade',  icon: '⬡' },
  { to: '/axis2',    label: 'Eixo 2 — Expansão',     icon: '⬡' },
  { to: '/axis3',    label: 'Eixo 3 — Segmentação',  icon: '⬡' },
  { to: '/reports',  label: 'Relatórios',             icon: '🗎' },
  { to: '/audit',    label: 'Auditoria',              icon: '≡' },
]

export default function Sidebar() {
  return (
    <aside className="w-56 min-h-screen bg-ind-surface border-r border-ind-border flex flex-col shrink-0">
      {/* Logo area */}
      <div className="px-5 py-5 border-b border-ind-border">
        <div className="text-ind-accent font-mono text-xs font-bold uppercase tracking-widest">
          Telecom AI
        </div>
        <div className="text-ind-muted text-xs mt-0.5">Plataforma de Análise</div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-4 px-3">
        <ul className="space-y-0.5">
          {links.map(({ to, label, icon }) => (
            <li key={to}>
              <NavLink
                to={to}
                end={to === '/'}
                className={({ isActive }) =>
                  [
                    'flex items-center gap-2.5 px-3 py-2 rounded text-sm transition-colors',
                    isActive
                      ? 'bg-ind-accent/10 text-ind-accent font-semibold'
                      : 'text-ind-muted hover:text-ind-text hover:bg-ind-border/40',
                  ].join(' ')
                }
              >
                <span className="text-base leading-none">{icon}</span>
                <span>{label}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>

      {/* Footer */}
      <div className="px-5 py-4 border-t border-ind-border text-ind-muted text-xs">
        v1.0.0 &mdash; IBM Watsonx
      </div>
    </aside>
  )
}
