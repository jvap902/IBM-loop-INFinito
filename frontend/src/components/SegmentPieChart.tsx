import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import type { Axis3SegmentProfile } from '../types'

const COLORS = ['#f59e0b', '#3b82f6', '#22c55e', '#a855f7', '#ef4444', '#0ea5e9']

interface Props {
  segments: Axis3SegmentProfile[]
}

export default function SegmentPieChart({ segments }: Props) {
  const data = segments.map((s) => ({
    name: s.segment_name,
    value: s.hexagon_count,
  }))

  return (
    <ResponsiveContainer width="100%" height={220}>
      <PieChart>
        <Pie
          data={data}
          cx="50%"
          cy="50%"
          innerRadius={55}
          outerRadius={80}
          paddingAngle={3}
          dataKey="value"
        >
          {data.map((_, i) => (
            <Cell key={i} fill={COLORS[i % COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          formatter={(v: number) => [v + ' hex', 'Hexágonos']}
          contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 12 }}
          labelStyle={{ color: '#e2e8f0' }}
        />
        <Legend
          iconType="circle"
          iconSize={9}
          wrapperStyle={{ fontSize: 11, color: '#94a3b8' }}
        />
      </PieChart>
    </ResponsiveContainer>
  )
}
