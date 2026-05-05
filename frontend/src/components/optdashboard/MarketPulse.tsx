import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import type { DashboardSnapshot } from '@/api/optdashboard'

interface MarketPulseProps {
  data: DashboardSnapshot
}

const REGIME_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  green:  { bg: 'bg-green-500/10',  text: 'text-green-400',  border: 'border-green-500/30' },
  red:    { bg: 'bg-red-500/10',    text: 'text-red-400',    border: 'border-red-500/30' },
  orange: { bg: 'bg-orange-500/10', text: 'text-orange-400', border: 'border-orange-500/30' },
  yellow: { bg: 'bg-yellow-500/10', text: 'text-yellow-400', border: 'border-yellow-500/30' },
  blue:   { bg: 'bg-blue-500/10',   text: 'text-blue-400',   border: 'border-blue-500/30' },
  gray:   { bg: 'bg-gray-500/10',   text: 'text-gray-400',   border: 'border-gray-500/30' },
}

function fmt(v: number | null | undefined, decimals = 2): string {
  if (v == null) return '—'
  return v.toFixed(decimals)
}

function fmtGex(v: number): string {
  const abs = Math.abs(v)
  if (abs >= 10_000_000) return `${(v / 10_000_000).toFixed(1)}Cr`
  if (abs >= 100_000) return `${(v / 100_000).toFixed(1)}L`
  return v.toFixed(0)
}

interface StatCardProps {
  label: string
  value: string
  sub?: string
  valueClass?: string
}

function StatCard({ label, value, sub, valueClass }: StatCardProps) {
  return (
    <Card className="flex-1 min-w-[130px]">
      <CardContent className="pt-4 pb-3 px-4">
        <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">{label}</p>
        <p className={`text-xl font-bold tabular-nums ${valueClass ?? ''}`}>{value}</p>
        {sub && <p className="text-xs text-muted-foreground mt-0.5">{sub}</p>}
      </CardContent>
    </Card>
  )
}

export function MarketPulse({ data }: MarketPulseProps) {
  const rStyle = REGIME_STYLES[data.regime_color] ?? REGIME_STYLES.gray
  const gexPositive = data.total_net_gex >= 0

  return (
    <div className="space-y-3">
      {/* Regime banner */}
      <div className={`rounded-lg border px-4 py-3 ${rStyle.bg} ${rStyle.border}`}>
        <div className="flex flex-wrap items-center gap-3">
          <Badge className={`text-sm font-semibold px-3 py-1 ${rStyle.bg} ${rStyle.text} border ${rStyle.border}`}>
            {data.regime}
          </Badge>
          <p className={`text-sm ${rStyle.text}`}>{data.regime_description}</p>
        </div>
      </div>

      {/* KPI row */}
      <div className="flex flex-wrap gap-3">
        <StatCard label="Spot" value={fmt(data.spot_price, 0)} sub={`ATM ${fmt(data.atm_strike, 0)}`} />

        <StatCard
          label="Net GEX"
          value={fmtGex(data.total_net_gex)}
          sub={gexPositive ? 'Dealers Long Gamma' : 'Dealers Short Gamma'}
          valueClass={gexPositive ? 'text-green-400' : 'text-red-400'}
        />

        <StatCard label="PCR (OI)" value={fmt(data.pcr_oi)} sub={data.pcr_oi > 1 ? 'Bearish skew' : 'Bullish skew'} />

        <StatCard
          label="ATM IV"
          value={data.atm_iv != null ? `${fmt(data.atm_iv)}%` : '—'}
          sub={data.iv_skew != null ? `Skew ${data.iv_skew > 0 ? '+' : ''}${fmt(data.iv_skew)}%` : undefined}
        />

        <StatCard
          label="Max Pain"
          value={fmt(data.max_pain, 0)}
          sub={data.max_pain != null ? `${Math.abs(data.spot_price - data.max_pain).toFixed(0)} pts from spot` : undefined}
        />

        <StatCard
          label="Call Wall"
          value={fmt(data.call_wall, 0)}
          sub="OI resistance"
          valueClass="text-red-400"
        />

        <StatCard
          label="Put Wall"
          value={fmt(data.put_wall, 0)}
          sub="OI support"
          valueClass="text-green-400"
        />

        {data.gamma_flip != null && (
          <StatCard
            label="Gamma Flip"
            value={fmt(data.gamma_flip, 0)}
            sub={data.spot_price > data.gamma_flip ? 'Spot above flip' : 'Spot below flip'}
            valueClass="text-yellow-400"
          />
        )}

        {data.term_structure_slope != null && (
          <StatCard
            label="Term Slope"
            value={`${data.term_structure_slope > 0 ? '+' : ''}${fmt(data.term_structure_slope)}%`}
            sub={data.term_structure_slope > 0 ? 'Contango' : 'Backwardation'}
            valueClass={data.term_structure_slope < -2 ? 'text-orange-400' : 'text-muted-foreground'}
          />
        )}
      </div>
    </div>
  )
}
