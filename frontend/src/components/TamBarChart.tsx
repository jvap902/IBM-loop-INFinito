import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import type { Axis2ClusterSummary } from '../types'

interface Props {
  clusters: Axis2ClusterSummary[]
}

const fmtBrl = (v: number) =>
  'R$ ' + v.toLocaleString('pt-BR', { maximumFractionDigits: 0 })

export default function TamBarChart({ clusters }: Props) {
  const data = clusters
    .filter((c) => c.is_noise === 0 && c.tam_estimate != null)
    .sort((a, b) => (b.tam_estimate ?? 0) - (a.tam_estimate ?? 0))
    .slice(0, 15)
    .map((c) => ({
      name: `C${c.cluster_id}`,
      tam: c.tam_estimate ?? 0,
    }))

  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
        <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis tickFormatter={(v) => 'R$' + (v / 1e6).toFixed(1) + 'M'} tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} />
        <Tooltip
          formatter={(v: number) => [fmtBrl(v), 'TAM']}
          contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 12 }}
          labelStyle={{ color: '#e2e8f0' }}
        />
        <Bar dataKey="tam" radius={[3, 3, 0, 0]}>
          {data.map((_, i) => (
            <Cell key={i} fill={i === 0 ? '#f59e0b' : '#3b82f6'} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
