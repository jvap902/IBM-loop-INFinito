import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

interface ShapBarChartProps {
  features: Array<{ feature: string; value: number }>
  title: string
  colorPositive?: string
  colorNegative?: string
}

export default function ShapBarChart({
  features,
  title,
  colorPositive = '#f59e0b',
  colorNegative = '#64748b',
}: ShapBarChartProps) {
  if (features.length === 0) {
    return <p className="text-ind-muted text-xs">Dados SHAP não disponíveis</p>
  }

  const data = features.map((f) => ({ feature: f.feature, value: f.value }))

  return (
    <div>
      {title && <p className="text-ind-text text-xs font-medium mb-1">{title}</p>}
      <ResponsiveContainer width="100%" height={Math.max(120, data.length * 28)}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, left: 8, bottom: 4 }}>
          <XAxis
            type="number"
            tickFormatter={(v: number) => v.toFixed(1)}
            tick={{ fill: '#94a3b8', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            type="category"
            dataKey="feature"
            width={140}
            tick={{ fill: '#94a3b8', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            formatter={(v: number) => [v.toFixed(4), 'valor']}
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: '#e2e8f0' }}
            itemStyle={{ color: '#e2e8f0' }}
          />
          <Bar dataKey="value" radius={[0, 3, 3, 0]}>
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.value >= 0 ? colorPositive : colorNegative} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
