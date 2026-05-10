import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import Plot from '@/lib/Plot2D'
import { optDashboardApi, type GEXSnapshotRow } from '@/api/optdashboard'
import { useThemeStore } from '@/stores/themeStore'

interface Props {
  symbol: string
}

function fmtGex(v: number): string {
  const abs = Math.abs(v)
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`
  if (abs >= 1_000) return `${(v / 1_000).toFixed(1)}K`
  return v.toFixed(2)
}

function percentileBadgeClass(p: number): string {
  if (p >= 80) return 'text-green-400'
  if (p >= 50) return 'text-yellow-400'
  return 'text-red-400'
}

function EmptyState() {
  return (
    <Card>
      <CardContent className="pt-4 pb-4 px-4">
        <p className="text-sm font-medium text-muted-foreground mb-1">
          Net GEX Time Series — 60-Day History
        </p>
        <p className="text-xs text-muted-foreground py-6 text-center">
          No GEX history yet. Snapshots are recorded at 09:20, 12:30, 15:25 and 15:32 IST on market days.
        </p>
      </CardContent>
    </Card>
  )
}

export function GEXTimeSeries({ symbol }: Props) {
  const { mode, appMode } = useThemeStore()
  const isDark = mode === 'dark' || appMode === 'analyzer'

  const { data, isLoading } = useQuery({
    queryKey: ['gex-history', symbol],
    queryFn: () => optDashboardApi.getGEXHistory(symbol, 60),
    staleTime: 10 * 60 * 1000,
  })

  const rows: GEXSnapshotRow[] = data?.data ?? []

  const { times, netGex, spots, gammaFlips, barColors } = useMemo(() => {
    const times = rows.map((r) => r.ts)
    const netGex = rows.map((r) => r.net_gex)
    const spots = rows.map((r) => r.spot)
    const gammaFlips = rows.map((r) => r.gamma_flip)
    const barColors = netGex.map((v) =>
      v >= 0 ? 'rgba(34,197,94,0.75)' : 'rgba(239,68,68,0.75)'
    )
    return { times, netGex, spots, gammaFlips, barColors }
  }, [rows])

  const latest = rows.length > 0 ? rows[rows.length - 1] : null

  const paper = isDark ? '#0a0a0a' : '#ffffff'
  const plotBg = isDark ? '#111111' : '#f9fafb'
  const gridColor = isDark ? '#222' : '#e5e7eb'
  const textColor = isDark ? '#e5e7eb' : '#374151'
  const spotColor = isDark ? '#facc15' : '#ca8a04'

  if (isLoading) {
    return (
      <Card>
        <CardContent className="pt-4 px-3 pb-2">
          <Skeleton className="h-5 w-56 mb-3" />
          <Skeleton className="h-72 w-full rounded" />
        </CardContent>
      </Card>
    )
  }

  if (rows.length === 0) return <EmptyState />

  return (
    <Card>
      <CardContent className="pt-4 px-3 pb-2">
        <div className="flex items-center justify-between mb-2 px-1">
          <p className="text-sm font-medium text-muted-foreground">
            Net GEX Time Series — {symbol} ({rows.length} snapshots, 60d)
          </p>
          {latest && (
            <div className="flex items-center gap-3 text-xs">
              <span className="text-muted-foreground">
                Latest:{' '}
                <span className={latest.net_gex >= 0 ? 'text-green-400' : 'text-red-400'}>
                  {fmtGex(latest.net_gex)}
                </span>
              </span>
              <span className={`font-medium ${percentileBadgeClass(latest.percentile)}`}>
                {latest.percentile.toFixed(0)}th pct
              </span>
            </div>
          )}
        </div>

        <Plot
          data={[
            {
              type: 'bar',
              x: times,
              y: netGex,
              marker: { color: barColors },
              name: 'Net GEX',
              yaxis: 'y',
              hovertemplate:
                '%{x|%d %b %H:%M}<br>Net GEX: <b>%{customdata}</b><extra></extra>',
              customdata: netGex.map(fmtGex),
            },
            {
              type: 'scatter',
              mode: 'lines+markers',
              x: times,
              y: spots,
              name: 'Spot',
              yaxis: 'y2',
              line: { color: spotColor, width: 1.5 },
              marker: { size: 4, color: spotColor },
              hovertemplate: '%{x|%d %b %H:%M}<br>Spot: <b>%{y:.0f}</b><extra></extra>',
            },
            {
              type: 'scatter',
              mode: 'lines',
              x: times,
              y: gammaFlips,
              name: 'Gamma Flip',
              yaxis: 'y2',
              line: { color: 'rgba(168,85,247,0.8)', width: 1.5, dash: 'dash' },
              hovertemplate:
                '%{x|%d %b %H:%M}<br>Gamma Flip: <b>%{y:.0f}</b><extra></extra>',
              connectgaps: false,
            },
          ]}
          layout={{
            paper_bgcolor: paper,
            plot_bgcolor: plotBg,
            height: 300,
            margin: { t: 10, r: 70, b: 50, l: 70 },
            barmode: 'relative',
            xaxis: {
              type: 'date',
              tickformat: '%d %b\n%H:%M',
              color: textColor,
              gridcolor: gridColor,
              tickfont: { size: 10 },
              rangeslider: { visible: false },
            },
            yaxis: {
              title: 'Net GEX',
              color: textColor,
              gridcolor: gridColor,
              zeroline: true,
              zerolinecolor: textColor,
              tickfont: { size: 10 },
              tickformat: '.3s',
            },
            yaxis2: {
              title: 'Price',
              overlaying: 'y',
              side: 'right',
              color: textColor,
              gridcolor: 'transparent',
              tickfont: { size: 10 },
              showgrid: false,
            },
            legend: {
              orientation: 'h',
              x: 0,
              y: -0.25,
              font: { color: textColor, size: 11 },
            },
            font: { color: textColor },
            showlegend: true,
          }}
          config={{ displayModeBar: false, responsive: true }}
          style={{ width: '100%' }}
          useResizeHandler
        />

        <div className="flex flex-wrap gap-3 mt-1 px-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 bg-green-500 rounded" /> Net +GEX (dealers long γ)
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 bg-red-500 rounded" /> Net −GEX (squeeze risk)
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-yellow-400 rounded" /> Spot
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5 bg-purple-400 rounded border-dashed" /> Gamma Flip
          </span>
          <span className="ml-auto">
            Percentile vs 60d window · Snapshots at 09:20 / 12:30 / 15:25 / 15:32 IST
          </span>
        </div>
      </CardContent>
    </Card>
  )
}
