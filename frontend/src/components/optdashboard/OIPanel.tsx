import { useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import Plot from '@/lib/Plot2D'
import type { DashboardSnapshot } from '@/api/optdashboard'

interface OIPanelProps {
  data: DashboardSnapshot
  isDark: boolean
}

export function OIPanel({ data, isDark }: OIPanelProps) {
  const paper = isDark ? '#0a0a0a' : '#ffffff'
  const plotBg = isDark ? '#111111' : '#f9fafb'
  const gridColor = isDark ? '#222' : '#e5e7eb'
  const textColor = isDark ? '#e5e7eb' : '#374151'

  const { strikes, ceOI, peOI } = useMemo(() => {
    const strikes = data.oi_chain.map((x) => x.strike)
    const ceOI = data.oi_chain.map((x) => x.ce_oi)
    const peOI = data.oi_chain.map((x) => -x.pe_oi)  // negative for butterfly
    return { strikes, ceOI, peOI }
  }, [data.oi_chain])

  const shapes = useMemo(() => {
    const s: object[] = []
    const addLine = (x: number | null, color: string, dash: string) => {
      if (x == null) return
      s.push({
        type: 'line', x0: 0, x1: 1, y0: x, y1: x,
        xref: 'paper', line: { color, dash, width: 2 },
      })
    }
    addLine(data.spot_price, isDark ? '#facc15' : '#ca8a04', 'solid')
    addLine(data.max_pain, 'rgba(168,85,247,0.85)', 'dash')
    return s
  }, [data.spot_price, data.max_pain, isDark])

  const annotations = useMemo(() => {
    const a: object[] = []
    if (data.spot_price) {
      a.push({
        y: data.spot_price, x: 1, xref: 'paper', yref: 'y',
        text: `Spot ${data.spot_price.toFixed(0)}`,
        showarrow: false, font: { color: isDark ? '#facc15' : '#ca8a04', size: 11 },
        xanchor: 'left',
      })
    }
    if (data.max_pain) {
      a.push({
        y: data.max_pain, x: 1, xref: 'paper', yref: 'y',
        text: `MaxPain ${data.max_pain}`,
        showarrow: false, font: { color: 'rgba(168,85,247,0.9)', size: 11 },
        xanchor: 'left',
      })
    }
    return a
  }, [data.spot_price, data.max_pain, isDark])

  const totalCE = data.total_ce_oi
  const totalPE = data.total_pe_oi

  return (
    <Card className="h-full">
      <CardContent className="pt-4 px-3 pb-2">
        <p className="text-sm font-medium text-muted-foreground mb-1 px-1">
          OI Butterfly — {data.expiry_date}
        </p>
        <div className="flex gap-4 text-xs px-1 mb-2">
          <span>
            Total CE OI: <strong className="text-red-400">
              {totalCE >= 1_000_000 ? `${(totalCE / 1_000_000).toFixed(1)}M` : `${(totalCE / 1_000).toFixed(0)}K`}
            </strong>
          </span>
          <span>
            Total PE OI: <strong className="text-green-400">
              {totalPE >= 1_000_000 ? `${(totalPE / 1_000_000).toFixed(1)}M` : `${(totalPE / 1_000).toFixed(0)}K`}
            </strong>
          </span>
          <span>PCR: <strong>{data.pcr_oi?.toFixed(2)}</strong></span>
        </div>
        <Plot
          data={[
            {
              type: 'bar', orientation: 'h',
              x: ceOI, y: strikes,
              name: 'CE OI',
              marker: { color: 'rgba(239,68,68,0.7)' },
              hovertemplate: 'Strike %{y}<br>CE OI %{x:,.0f}<extra></extra>',
            },
            {
              type: 'bar', orientation: 'h',
              x: peOI, y: strikes,
              name: 'PE OI',
              marker: { color: 'rgba(34,197,94,0.7)' },
              hovertemplate: 'Strike %{y}<br>PE OI %{customdata:,.0f}<extra></extra>',
              customdata: data.oi_chain.map((x) => x.pe_oi),
            },
          ]}
          layout={{
            paper_bgcolor: paper, plot_bgcolor: plotBg, height: 380,
            barmode: 'overlay',
            margin: { t: 8, r: 70, b: 40, l: 60 },
            xaxis: {
              title: 'Open Interest', color: textColor, gridcolor: gridColor, tickfont: { size: 10 },
              tickformat: ',.0f',
            },
            yaxis: { title: 'Strike', color: textColor, gridcolor: gridColor, tickfont: { size: 10 } },
            legend: { orientation: 'h', y: -0.12, font: { size: 11, color: textColor } },
            font: { color: textColor },
            shapes,
            annotations,
          }}
          config={{ displayModeBar: false, responsive: true }}
          style={{ width: '100%' }}
          useResizeHandler
        />
        <div className="flex flex-wrap gap-3 mt-1 px-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-yellow-400" /> Spot</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 bg-purple-400" /> Max Pain</span>
        </div>
      </CardContent>
    </Card>
  )
}
