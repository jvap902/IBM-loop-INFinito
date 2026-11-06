interface Props {
  title: string
  description: string
  children: React.ReactNode
}

export default function AxisForm({ title, description, children }: Props) {
  return (
    <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
      <div className="mb-4">
        <h2 className="text-sm font-bold text-ind-text">{title}</h2>
        <p className="text-ind-muted text-xs mt-0.5">{description}</p>
      </div>
      <div className="space-y-4">{children}</div>
    </div>
  )
}

interface FieldProps {
  label: string
  hint?: string
  children: React.ReactNode
}

export function FormField({ label, hint, children }: FieldProps) {
  return (
    <div>
      <label className="block text-ind-text text-xs font-semibold mb-1.5">{label}</label>
      {children}
      {hint && <p className="text-ind-muted text-xs mt-1">{hint}</p>}
    </div>
  )
}

interface SliderProps {
  min: number
  max: number
  step?: number
  value: number
  onChange: (v: number) => void
  format?: (v: number) => string
}

export function Slider({ min, max, step = 0.01, value, onChange, format }: SliderProps) {
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="flex-1 accent-amber-500"
      />
      <span className="text-ind-accent font-mono text-sm w-16 text-right">
        {format ? format(value) : value}
      </span>
    </div>
  )
}

export function TextInput({
  value,
  onChange,
  placeholder,
  monospace = false,
}: {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  monospace?: boolean
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={`w-full bg-ind-bg border border-ind-border rounded px-3 py-2 text-ind-text text-sm focus:outline-none focus:border-ind-accent ${monospace ? 'font-mono' : ''}`}
    />
  )
}

export function NumberInput({
  value,
  onChange,
  min,
  max,
}: {
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
}) {
  return (
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      onChange={(e) => onChange(parseInt(e.target.value, 10))}
      className="w-full bg-ind-bg border border-ind-border rounded px-3 py-2 text-ind-text text-sm font-mono focus:outline-none focus:border-ind-accent"
    />
  )
}

export function Toggle({
  value,
  onChange,
  label,
  description,
}: {
  value: boolean
  onChange: (v: boolean) => void
  label: string
  description?: string
}) {
  return (
    <label className="flex items-start gap-3 cursor-pointer">
      <div
        onClick={() => onChange(!value)}
        className={`w-10 h-5 rounded-full transition-colors relative cursor-pointer shrink-0 mt-0.5 ${value ? 'bg-ind-accent' : 'bg-ind-border'}`}
      >
        <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${value ? 'translate-x-5' : 'translate-x-0.5'}`} />
      </div>
      <div className="min-w-0">
        <div className="text-ind-text text-sm">{label}</div>
        {description && <div className="text-ind-muted text-xs">{description}</div>}
      </div>
    </label>
  )
}

export function SelectInput({
  value,
  onChange,
  options,
}: {
  value: string | number
  onChange: (v: string) => void
  options: { value: string | number; label: string }[]
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full bg-ind-bg border border-ind-border rounded px-3 py-2 text-ind-text text-sm focus:outline-none focus:border-ind-accent"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  )
}

export function RunButton({ isPending }: { isPending: boolean }) {
  return (
    <button
      type="submit"
      disabled={isPending}
      className="w-full py-2.5 bg-ind-accent text-ind-bg rounded font-bold text-sm hover:bg-amber-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
    >
      {isPending ? (
        <>
          <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          Processando…
        </>
      ) : (
        'Executar Eixo'
      )}
    </button>
  )
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="bg-red-950/50 border border-red-800 rounded-lg p-3 text-xs text-red-300">
      <span className="font-semibold text-red-400">Erro: </span>{message}
    </div>
  )
}
