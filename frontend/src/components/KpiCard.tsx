interface Props {
  label: string
  value: string | number
  sub?: string
  valueColor?: string
}

export default function KpiCard({ label, value, sub, valueColor }: Props) {
  return (
    <div className="bg-ind-surface border border-ind-border rounded-lg p-4">
      <div className="text-ind-muted text-[10px] font-semibold uppercase tracking-widest mb-1.5">
        {label}
      </div>
      <div className={`text-2xl font-bold ${valueColor ?? 'text-ind-text'}`}>
        {value}
      </div>
      {sub && <div className="text-ind-muted text-xs mt-0.5">{sub}</div>}
    </div>
  )
}
