import { useState } from 'react'
import { Copy, Check, ChevronDown, ChevronUp } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import type { DashboardSnapshot, Strategy, StrategyLeg } from '@/api/optdashboard'
import { showToast } from '@/utils/toast'

interface StrategySuggestionsProps {
  data: DashboardSnapshot
}

function fitColor(score: number): string {
  if (score >= 0.7) return 'text-green-400'
  if (score >= 0.4) return 'text-yellow-400'
  return 'text-red-400'
}

function fmt(v: number | null, decimals = 0): string {
  if (v == null) return '—'
  return v.toFixed(decimals)
}

function fmtPnL(v: number | null): string {
  if (v == null) return '—'
  return `₹${v.toLocaleString('en-IN')}`
}

interface LegRowProps {
  leg: StrategyLeg
}

function LegRow({ leg }: LegRowProps) {
  return (
    <div className="flex items-center justify-between text-xs py-1 border-b border-border/40 last:border-0">
      <Badge
        variant="outline"
        className={`text-[10px] w-10 justify-center ${leg.action === 'BUY' ? 'text-green-400 border-green-500/40' : 'text-red-400 border-red-500/40'}`}
      >
        {leg.action}
      </Badge>
      <span className="font-mono text-muted-foreground mx-2 truncate max-w-[160px]">{leg.symbol}</span>
      <span className={`font-medium ${leg.option_type === 'CE' ? 'text-red-400' : 'text-green-400'}`}>
        {leg.option_type}
      </span>
      <span className="text-muted-foreground ml-2">{leg.strike}</span>
      <span className="ml-2 text-muted-foreground tabular-nums">
        {leg.ltp > 0 ? `₹${leg.ltp.toFixed(1)}` : '—'}
      </span>
    </div>
  )
}

interface StrategyCardProps {
  strategy: Strategy
  lotSize: number
}

function StrategyCard({ strategy, lotSize }: StrategyCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  const sandboxPayload = strategy.legs.map((leg) => ({
    apikey: '<YOUR_API_KEY>',
    strategy: `OptDashboard-${strategy.name}`,
    symbol: leg.symbol,
    action: leg.action,
    exchange: leg.exchange,
    pricetype: 'MARKET',
    product: 'NRML',
    quantity: lotSize,
  }))

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(sandboxPayload, null, 2))
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
      showToast.success('Copied to clipboard')
    } catch {
      showToast.error('Copy failed')
    }
  }

  return (
    <>
      <Card className="border border-border/60">
        <CardContent className="pt-4 pb-3 px-4">
          {/* Header */}
          <div className="flex items-center gap-2 mb-2">
            <Badge variant="outline" className="text-[10px] w-5 h-5 p-0 justify-center">
              {strategy.rank}
            </Badge>
            <span className="font-semibold text-sm">{strategy.name}</span>
            <span className={`text-xs font-medium ml-auto ${fitColor(strategy.fit_score)}`}>
              Fit {(strategy.fit_score * 100).toFixed(0)}%
            </span>
          </div>

          {/* Fit score bar */}
          <div className="h-1 bg-muted rounded-full mb-3 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${
                strategy.fit_score >= 0.7
                  ? 'bg-green-500'
                  : strategy.fit_score >= 0.4
                  ? 'bg-yellow-500'
                  : 'bg-red-500'
              }`}
              style={{ width: `${strategy.fit_score * 100}%` }}
            />
          </div>

          {/* Rationale */}
          <p className="text-xs text-muted-foreground mb-3 leading-relaxed">{strategy.rationale}</p>

          {/* Metrics */}
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs mb-3">
            <div>
              <span className="text-muted-foreground">Max Profit/lot: </span>
              <span className="text-green-400 font-medium">{fmtPnL(strategy.max_profit_per_lot)}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Max Loss/lot: </span>
              <span className="text-red-400 font-medium">{fmtPnL(strategy.max_loss_per_lot)}</span>
            </div>
            {strategy.upper_breakeven != null && (
              <div>
                <span className="text-muted-foreground">Upper BE: </span>
                <span className="font-medium">{fmt(strategy.upper_breakeven)}</span>
              </div>
            )}
            {strategy.lower_breakeven != null && (
              <div>
                <span className="text-muted-foreground">Lower BE: </span>
                <span className="font-medium">{fmt(strategy.lower_breakeven)}</span>
              </div>
            )}
            <div>
              <span className="text-muted-foreground">Net Premium: </span>
              <span className={`font-medium ${strategy.net_premium >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                ₹{Math.abs(strategy.net_premium).toFixed(1)}
                {strategy.net_premium >= 0 ? ' credit' : ' debit'}
              </span>
            </div>
          </div>

          {strategy.note && (
            <p className="text-[10px] text-yellow-400/80 mb-2">{strategy.note}</p>
          )}

          {/* Legs toggle */}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs w-full justify-between mb-2"
            onClick={() => setExpanded(!expanded)}
          >
            <span>{expanded ? 'Hide' : 'Show'} legs ({strategy.legs.length})</span>
            {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </Button>

          {expanded && (
            <div className="mb-3">
              {strategy.legs.map((leg, i) => (
                <LegRow key={i} leg={leg} />
              ))}
            </div>
          )}

          {/* Actions */}
          <Button
            size="sm"
            className="w-full h-8 text-xs"
            onClick={() => setDialogOpen(true)}
          >
            Pre-fill in Sandbox
          </Button>
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{strategy.name} — Sandbox Pre-fill</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground text-xs">
              Switch to <strong>Analyze Mode</strong> in the top nav, then place each leg below via
              the Sandbox or paste the JSON into the API playground.
            </p>

            <div className="space-y-2">
              {strategy.legs.map((leg, i) => (
                <div
                  key={i}
                  className={`rounded-lg border px-3 py-2 text-xs flex flex-col gap-1 ${
                    leg.action === 'BUY'
                      ? 'border-green-500/30 bg-green-500/5'
                      : 'border-red-500/30 bg-red-500/5'
                  }`}
                >
                  <div className="flex items-center gap-2 font-medium">
                    <Badge
                      variant="outline"
                      className={`text-[10px] ${
                        leg.action === 'BUY'
                          ? 'text-green-400 border-green-500/40'
                          : 'text-red-400 border-red-500/40'
                      }`}
                    >
                      {leg.action}
                    </Badge>
                    <span className="font-mono">{leg.symbol}</span>
                    <span className="ml-auto text-muted-foreground">
                      {leg.ltp > 0 ? `LTP ₹${leg.ltp.toFixed(1)}` : 'LTP N/A'}
                    </span>
                  </div>
                  <div className="text-muted-foreground">
                    Exchange: {leg.exchange} · Product: NRML · Qty: {lotSize} ({lotSize} = 1 lot)
                  </div>
                </div>
              ))}
            </div>

            <div className="rounded-md bg-muted p-3">
              <p className="text-xs text-muted-foreground mb-2">API Playground JSON (replace API key):</p>
              <pre className="text-[10px] overflow-auto max-h-48 leading-relaxed">
                {JSON.stringify(sandboxPayload, null, 2)}
              </pre>
            </div>

            <Button size="sm" variant="outline" className="w-full" onClick={handleCopy}>
              {copied ? (
                <><Check className="h-3 w-3 mr-2" /> Copied</>
              ) : (
                <><Copy className="h-3 w-3 mr-2" /> Copy JSON</>
              )}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

export function StrategySuggestions({ data }: StrategySuggestionsProps) {
  if (!data.strategies?.length) {
    return (
      <Card>
        <CardContent className="pt-6 pb-4 text-center text-sm text-muted-foreground">
          No strategy suggestions available for current market conditions.
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-muted-foreground">
        Strategy Suggestions — ranked by regime fit
      </p>
      {data.strategies.map((strategy) => (
        <StrategyCard
          key={strategy.rank}
          strategy={strategy}
          lotSize={data.lot_size}
        />
      ))}
    </div>
  )
}
