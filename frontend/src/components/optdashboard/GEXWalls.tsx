import { useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import Plot from '@/lib/Plot2D'
import type { DashboardSnapshot } from '@/api/optdashboard'

interface GEXWallsProps {
  data: DashboardSnapshot
  isDark: boolean
}

export function GEXWalls({ data, isDark }: GEXWallsProps) {
  const paper = isDark ? '#0a0a0a' : '#ffffff'
  const plotBg = isDark ? '#111111' : '#f9fafb'
  const gridColor = isDark ? '#222' : '#e5e7eb'
  const textColor = isDark ? '#e5e7eb' : '#374151'

  const { strikes, netGex, barColors } = useMemo(() => {
    const strikes = data.gex_chain.map((x) => x.strike)
    const netGex = data.gex_chain.map((x) => x.net_gex)
    const barColors = netGex.map((v) => (v >= 0 ? 'rgba(34,197,94,0.75)' : 'rgba(239,68,68,0.75)'))
    return { strikes, netGex, barColors }
  }, [data.gex_chain])

  const shapes = useMemo(() => {
    const s: object[] = []
    const addLine = (x: number | null, color: string, dash: string) => {
      if (x == null) return
      s.push({
        type: 'line', x0: x, x1: x, y0: 0, y1: 1,
        yref: 'paper', line: { color, dash, width: 2 },
      })
    }
    addLine(data.spot_price, isDark ? '#facc15' : '#ca8a04', 'solid')
    addLine(data.call_wall, 'rgba(239,68,68,0.8)', 'dot')
    addLine(data.put_wall, 'rgba(34,197,94,0.8)', 'dot')
    addLine(data.gamma_flip, 'rgba(168,85,247,0.8)', 'dash')
    return s
  }, [data.spot_price, data.call_wall, data.put_wall, data.gamma_flip, isDark])

  const annotations = useMemo(() => {
    const a: object[] = []
    const add = (x: number | null, label: string, color: string) => {
      if (x == null) return
      a.push({
        x, y: 1, xref: 'x', yref: 'paper', text: label,
        showarrow: false, font: { color, size: 11 },
        xanchor: 'center', yanchor: 'bottom',
      })
    }
    add(data.spot_price, `Spot ${data.spot_price?.toFixed(0)}`, isDark ? '#facc15' : '#ca8a04')
    add(data.call_wall, `CW ${data.call_wall}`, 'rgba(239,68,68,0.9)')
    add(data.put_wall, `PW ${data.put_wall}`, 'rgba(34,197,94,0.9)')
    add(data.gamma_flip, `Flip ${data.gamma_flip}`, 'rgba(168,85,247,0.9)')
    return a
  }, [data.spot_price, data.call_wall, data.put_wall, data.gamma_flip, isDark])

  return (
    <Card className="h-full">
      <CardContent className="pt-4 px-3 pb-2">
        <p className="text-sm font-medium text-muted-foreground mb-2 px-1">
          GEX by Strike — Net Gamma Exposure
        </p>
        <Plot
          data={[
            {
              type: 'bar',
              x: strikes,
              y: netGex,
              marker: { color: barColors },
              name: 'Net GEX',
              hovertemplate: 'Strike %{x}<br>Net GEX %{y:.2f}<extra></extra>',
            },
          ]}
          layout={{
            paper_bgcolor: paper,
            plot_bgcolor: plotBg,
            height: 320,
            margin: { t: 10, r: 10, b: 50, l: 60 },
            xaxis: { title: 'Strike', color: textColor, gridcolor: gridColor, tickfont: { size: 10 } },
            yaxis: { title: 'Net GEX', color: textColor, gridcolor: gridColor, zeroline: true, zerolinecolor: textColor },
            showlegend: false,
            font: { color: textColor },
            shapes,
            annotations,
          }}
          config={{ displayModeBar: false, responsive: true }}
          style={{ width: '100%' }}
          useResizeHandler
        />
        <div className="flex flex-wrap gap-3 mt-2 px-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-1 bg-green-500 rounded" /> Net +GEX</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-1 bg-red-500 rounded" /> Net −GEX</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-yellow-400 rounded" /> Spot</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-red-400 rounded border-dashed" /> Call Wall</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-green-400 rounded" /> Put Wall</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-purple-400 rounded" /> Gamma Flip</span>
        </div>
      </CardContent>
    </Card>
  )
}
