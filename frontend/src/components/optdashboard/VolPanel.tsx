import { useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import Plot from '@/lib/Plot2D'
import type { DashboardSnapshot } from '@/api/optdashboard'

interface VolPanelProps {
  data: DashboardSnapshot
  isDark: boolean
}

export function VolPanel({ data, isDark }: VolPanelProps) {
  const paper = isDark ? '#0a0a0a' : '#ffffff'
  const plotBg = isDark ? '#111111' : '#f9fafb'
  const gridColor = isDark ? '#222' : '#e5e7eb'
  const textColor = isDark ? '#e5e7eb' : '#374151'

  const smileData = useMemo(() => {
    const strikes = data.iv_smile_chain.map((x) => x.strike)
    const ceIV = data.iv_smile_chain.map((x) => x.ce_iv)
    const peIV = data.iv_smile_chain.map((x) => x.pe_iv)
    return { strikes, ceIV, peIV }
  }, [data.iv_smile_chain])

  const termData = useMemo(() => {
    const labels = data.term_structure.map((x) =>
      x.dte != null ? `${x.date}\n(${x.dte.toFixed(0)}d)` : x.date
    )
    const ivs = data.term_structure.map((x) => x.atm_iv)
    return { labels, ivs }
  }, [data.term_structure])

  const smileAnnotations = useMemo(() => {
    if (!data.atm_strike) return []
    return [{
      x: data.atm_strike, y: 1, xref: 'x', yref: 'paper',
      text: `ATM`, showarrow: false,
      font: { color: isDark ? '#facc15' : '#ca8a04', size: 11 },
      xanchor: 'center', yanchor: 'bottom',
    }]
  }, [data.atm_strike, isDark])

  const smileShapes = useMemo(() => {
    if (!data.atm_strike) return []
    return [{
      type: 'line', x0: data.atm_strike, x1: data.atm_strike, y0: 0, y1: 1,
      yref: 'paper', line: { color: isDark ? '#facc15' : '#ca8a04', dash: 'dot', width: 1.5 },
    }]
  }, [data.atm_strike, isDark])

  return (
    <div className="h-full flex flex-col gap-3">
      {/* IV Smile */}
      <Card className="flex-1">
        <CardContent className="pt-4 px-3 pb-2">
          <p className="text-sm font-medium text-muted-foreground mb-1 px-1">
            IV Smile — {data.expiry_date}
            {data.atm_iv != null && (
              <span className="ml-2 text-xs">
                ATM IV {data.atm_iv.toFixed(1)}%
                {data.iv_skew != null && (
                  <span className={data.iv_skew > 0 ? ' text-red-400' : ' text-green-400'}>
                    {' '}· Skew {data.iv_skew > 0 ? '+' : ''}{data.iv_skew.toFixed(2)}%
                  </span>
                )}
              </span>
            )}
          </p>
          <Plot
            data={[
              {
                type: 'scatter', mode: 'lines+markers',
                x: smileData.strikes, y: smileData.ceIV,
                name: 'CE IV', line: { color: '#3b82f6', width: 2 },
                marker: { size: 4 },
                connectgaps: true,
                hovertemplate: 'Strike %{x}<br>CE IV %{y:.2f}%<extra></extra>',
              },
              {
                type: 'scatter', mode: 'lines+markers',
                x: smileData.strikes, y: smileData.peIV,
                name: 'PE IV', line: { color: '#f97316', width: 2, dash: 'dot' },
                marker: { size: 4 },
                connectgaps: true,
                hovertemplate: 'Strike %{x}<br>PE IV %{y:.2f}%<extra></extra>',
              },
            ]}
            layout={{
              paper_bgcolor: paper, plot_bgcolor: plotBg, height: 200,
              margin: { t: 8, r: 10, b: 45, l: 50 },
              xaxis: { title: 'Strike', color: textColor, gridcolor: gridColor, tickfont: { size: 10 } },
              yaxis: { title: 'IV %', color: textColor, gridcolor: gridColor },
              legend: { orientation: 'h', y: -0.25, font: { size: 11, color: textColor } },
              font: { color: textColor },
              shapes: smileShapes,
              annotations: smileAnnotations,
            }}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: '100%' }}
            useResizeHandler
          />
        </CardContent>
      </Card>

      {/* Term Structure */}
      <Card className="flex-1">
        <CardContent className="pt-4 px-3 pb-2">
          <p className="text-sm font-medium text-muted-foreground mb-1 px-1">
            Term Structure — ATM IV across expiries
            {data.term_structure_slope != null && (
              <span className={`ml-2 text-xs ${data.term_structure_slope < -2 ? 'text-orange-400' : 'text-muted-foreground'}`}>
                {data.term_structure_slope > 0 ? '▲' : '▼'} {Math.abs(data.term_structure_slope).toFixed(1)}% slope
              </span>
            )}
          </p>
          {termData.labels.length > 0 ? (
            <Plot
              data={[
                {
                  type: 'bar',
                  x: termData.labels,
                  y: termData.ivs,
                  marker: {
                    color: termData.ivs.map((_, i) =>
                      i === 0 ? 'rgba(59,130,246,0.8)' : 'rgba(148,163,184,0.6)'
                    ),
                  },
                  hovertemplate: '%{x}<br>ATM IV %{y:.2f}%<extra></extra>',
                },
              ]}
              layout={{
                paper_bgcolor: paper, plot_bgcolor: plotBg, height: 200,
                margin: { t: 8, r: 10, b: 55, l: 50 },
                xaxis: { color: textColor, gridcolor: gridColor, tickfont: { size: 10 } },
                yaxis: { title: 'IV %', color: textColor, gridcolor: gridColor },
                showlegend: false, font: { color: textColor },
              }}
              config={{ displayModeBar: false, responsive: true }}
              style={{ width: '100%' }}
              useResizeHandler
            />
          ) : (
            <p className="text-xs text-muted-foreground px-1 py-8 text-center">
              Select both expiries to see term structure
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
