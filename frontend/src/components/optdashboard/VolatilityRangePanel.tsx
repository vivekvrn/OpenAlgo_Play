import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { DashboardSnapshot } from '@/api/optdashboard'

interface Props {
  data: DashboardSnapshot
}

function fmt(v: number | null, decimals = 1): string {
  if (v == null) return '—'
  return v.toFixed(decimals)
}

function fmtPts(v: number | null): string {
  if (v == null) return '—'
  return Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

function ivRvColor(spread: number | null): string {
  if (spread == null) return 'text-muted-foreground'
  return spread >= 0 ? 'text-amber-400' : 'text-blue-400'
}

function ivRvLabel(spread: number | null): string {
  if (spread == null) return ''
  return spread >= 0 ? 'rich' : 'cheap'
}

function rangeWidth(lower: number | null, upper: number | null): string {
  if (lower == null || upper == null) return '—'
  return fmtPts(upper - lower)
}

export function VolatilityRangePanel({ data }: Props) {
  const { hv_10, hv_30, atm_iv, iv_rv_spread, range_gex, range_iv_1sd, range_straddle } = data

  const volRows = [
    { label: '10-Day HV', value: `${fmt(hv_10)}%`, extra: null },
    { label: '30-Day HV', value: `${fmt(hv_30)}%`, extra: null },
    { label: 'ATM IV', value: `${fmt(atm_iv)}%`, extra: null },
    {
      label: 'IV − RV',
      value: iv_rv_spread != null ? `${iv_rv_spread >= 0 ? '+' : ''}${fmt(iv_rv_spread)}%` : '—',
      extra: ivRvLabel(iv_rv_spread),
      valueClass: ivRvColor(iv_rv_spread),
    },
  ]

  const rangeRows = [
    {
      label: 'GEX Walls',
      lower: range_gex?.lower ?? null,
      upper: range_gex?.upper ?? null,
      note: null,
    },
    {
      label: range_iv_1sd ? `IV 1σ (${range_iv_1sd.dte}d)` : 'IV 1σ',
      lower: range_iv_1sd?.lower ?? null,
      upper: range_iv_1sd?.upper ?? null,
      note: range_iv_1sd ? `±${fmtPts(range_iv_1sd.sigma_pts)} pts` : null,
    },
    {
      label: 'ATM Straddle',
      lower: range_straddle?.lower ?? null,
      upper: range_straddle?.upper ?? null,
      note: range_straddle ? `₹${fmt(range_straddle.straddle_premium, 1)} premium` : null,
    },
  ]

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      {/* Volatility table */}
      <Card>
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm font-medium">Volatility</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted-foreground border-b border-border/40">
                <th className="text-left pb-1.5 font-normal">Metric</th>
                <th className="text-right pb-1.5 font-normal">Value</th>
                <th className="text-right pb-1.5 font-normal w-16"></th>
              </tr>
            </thead>
            <tbody>
              {volRows.map((row) => (
                <tr key={row.label} className="border-b border-border/20 last:border-0">
                  <td className="py-1.5 text-muted-foreground">{row.label}</td>
                  <td className={`py-1.5 text-right font-mono tabular-nums font-medium ${row.valueClass ?? ''}`}>
                    {row.value}
                  </td>
                  <td className="py-1.5 text-right">
                    {row.extra && (
                      <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${
                        row.extra === 'rich'
                          ? 'border-amber-500/40 text-amber-400 bg-amber-500/10'
                          : 'border-blue-500/40 text-blue-400 bg-blue-500/10'
                      }`}>
                        {row.extra}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[10px] text-muted-foreground mt-2 leading-relaxed">
            IV−RV positive = options priced rich vs realised vol (favours selling); negative = cheap (favours buying).
          </p>
        </CardContent>
      </Card>

      {/* Probable range table */}
      <Card>
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm font-medium">Probable Range</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-muted-foreground border-b border-border/40">
                <th className="text-left pb-1.5 font-normal">Basis</th>
                <th className="text-right pb-1.5 font-normal">Lower</th>
                <th className="text-right pb-1.5 font-normal">Upper</th>
                <th className="text-right pb-1.5 font-normal">Width</th>
              </tr>
            </thead>
            <tbody>
              {rangeRows.map((row) => (
                <tr key={row.label} className="border-b border-border/20 last:border-0">
                  <td className="py-1.5 text-muted-foreground">
                    <div>{row.label}</div>
                    {row.note && (
                      <div className="text-[10px] text-muted-foreground/60">{row.note}</div>
                    )}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums text-green-400">
                    {fmtPts(row.lower)}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums text-red-400">
                    {fmtPts(row.upper)}
                  </td>
                  <td className="py-1.5 text-right font-mono tabular-nums text-muted-foreground">
                    {rangeWidth(row.lower, row.upper)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[10px] text-muted-foreground mt-2 leading-relaxed">
            IV 1σ = spot × (IV/100) × √(DTE/365). Straddle range = spot ± ATM CE+PE premium. Both are 1-expiry expected-move estimates.
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
