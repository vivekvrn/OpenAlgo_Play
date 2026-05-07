import { useCallback, useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Skeleton } from '@/components/ui/skeleton'
import { MarketPulse } from '@/components/optdashboard/MarketPulse'
import { GEXWalls } from '@/components/optdashboard/GEXWalls'
import { VolPanel } from '@/components/optdashboard/VolPanel'
import { OIPanel } from '@/components/optdashboard/OIPanel'
import { StrategySuggestions } from '@/components/optdashboard/StrategySuggestions'
import { VolatilityRangePanel } from '@/components/optdashboard/VolatilityRangePanel'
import { optDashboardApi, type DashboardSnapshot } from '@/api/optdashboard'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

const AUTO_REFRESH_MS = 60_000

const UNDERLYINGS = [
  { label: 'NIFTY',  underlying: 'NIFTY',  exchange: 'NFO' },
  { label: 'SENSEX', underlying: 'SENSEX', exchange: 'BFO' },
] as const
type UnderlyingKey = typeof UNDERLYINGS[number]['underlying']

function convertExpiryForAPI(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-24 w-full rounded-lg" />
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Skeleton className="h-80 rounded-lg" />
        <Skeleton className="h-80 rounded-lg" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Skeleton className="h-96 rounded-lg" />
        <Skeleton className="h-96 rounded-lg" />
      </div>
    </div>
  )
}

export default function OptDashboard() {
  const { mode, appMode } = useThemeStore()
  const isAnalyzer = appMode === 'analyzer'
  const isDark = mode === 'dark' || isAnalyzer

  const [selectedUnderlying, setSelectedUnderlying] = useState<UnderlyingKey>('NIFTY')
  const [expiries, setExpiries] = useState<string[]>([])
  const [frontExpiry, setFrontExpiry] = useState('')
  const [nextExpiry, setNextExpiry] = useState('__none__')
  const [snapshot, setSnapshot] = useState<DashboardSnapshot | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  const requestIdRef = useRef(0)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const activeConfig = UNDERLYINGS.find((u) => u.underlying === selectedUnderlying) ?? UNDERLYINGS[0]

  // Reset and reload expiries when underlying changes
  useEffect(() => {
    setExpiries([])
    setFrontExpiry('')
    setNextExpiry('__none__')
    setSnapshot(null)
    let cancelled = false
    const load = async () => {
      try {
        const res = await optDashboardApi.getExpiries(activeConfig.exchange, activeConfig.underlying)
        if (cancelled) return
        const list = res.expiries || []
        setExpiries(list)
        if (list.length >= 1) setFrontExpiry(list[0])
        if (list.length >= 2) setNextExpiry(list[1])
      } catch {
        if (!cancelled) showToast.error(`Failed to load ${activeConfig.label} expiries`)
      }
    }
    load()
    return () => { cancelled = true }
  }, [selectedUnderlying, activeConfig.exchange, activeConfig.underlying, activeConfig.label])

  const fetchSnapshot = useCallback(async () => {
    if (!frontExpiry) return
    const reqId = ++requestIdRef.current
    setIsLoading(true)
    try {
      const data = await optDashboardApi.getSnapshot({
        underlying: activeConfig.underlying,
        exchange: activeConfig.exchange,
        expiry_date: convertExpiryForAPI(frontExpiry),
        next_expiry_date: nextExpiry && nextExpiry !== '__none__' ? convertExpiryForAPI(nextExpiry) : undefined,
      })
      if (requestIdRef.current !== reqId) return
      if (data.status === 'success') {
        setSnapshot(data)
        setLastUpdated(new Date())
      } else {
        showToast.error(data.message || 'Failed to fetch dashboard data')
      }
    } catch (err: unknown) {
      if (requestIdRef.current !== reqId) return
      const msg = err instanceof Error ? err.message : 'Failed to fetch dashboard data'
      showToast.error(msg)
    } finally {
      if (requestIdRef.current === reqId) setIsLoading(false)
    }
  }, [frontExpiry, nextExpiry, activeConfig])

  // Auto-refresh
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current)
    if (autoRefresh && frontExpiry) {
      intervalRef.current = setInterval(fetchSnapshot, AUTO_REFRESH_MS)
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [autoRefresh, fetchSnapshot, frontExpiry])

  return (
    <div className="container mx-auto px-4 py-6 max-w-screen-2xl space-y-4">
      {/* Page header */}
      <div className="flex flex-wrap items-center gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Options Intelligence</h1>
          <p className="text-xs text-muted-foreground">
            {activeConfig.label} · Vol &amp; Gamma Dashboard
            {lastUpdated && (
              <span className="ml-2">· Updated {lastUpdated.toLocaleTimeString()}</span>
            )}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 ml-auto">
          {/* Underlying selector */}
          <Select
            value={selectedUnderlying}
            onValueChange={(v) => setSelectedUnderlying(v as UnderlyingKey)}
          >
            <SelectTrigger className="h-8 text-xs w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {UNDERLYINGS.map((u) => (
                <SelectItem key={u.underlying} value={u.underlying} className="text-xs">
                  {u.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Front expiry */}
          <Select value={frontExpiry} onValueChange={setFrontExpiry} disabled={!expiries.length}>
            <SelectTrigger className="h-8 text-xs w-36">
              <SelectValue placeholder="Front expiry" />
            </SelectTrigger>
            <SelectContent>
              {expiries.map((e) => (
                <SelectItem key={e} value={e} className="text-xs">{e}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Next expiry (for calendar spreads) */}
          <Select value={nextExpiry} onValueChange={setNextExpiry} disabled={!expiries.length}>
            <SelectTrigger className="h-8 text-xs w-36">
              <SelectValue placeholder="Next expiry (calendar)" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__" className="text-xs text-muted-foreground">None</SelectItem>
              {expiries.map((e) => (
                <SelectItem key={e} value={e} className="text-xs">{e}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Auto refresh */}
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
            <Switch
              checked={autoRefresh}
              onCheckedChange={setAutoRefresh}
              className="h-4 w-7 data-[state=checked]:bg-primary"
            />
            Auto (60s)
          </label>

          {/* Fetch button */}
          <Button
            size="sm"
            className="h-8 px-3 text-xs"
            disabled={!frontExpiry || isLoading}
            onClick={fetchSnapshot}
          >
            <RefreshCw className={`h-3 w-3 mr-1.5 ${isLoading ? 'animate-spin' : ''}`} />
            {isLoading ? 'Loading…' : 'Refresh'}
          </Button>
        </div>
      </div>

      {/* Content */}
      {isLoading && !snapshot ? (
        <LoadingSkeleton />
      ) : !snapshot ? (
        <div className="flex flex-col items-center justify-center py-24 text-muted-foreground gap-3">
          <p className="text-sm">Select an expiry and click Refresh to load the dashboard.</p>
          <p className="text-xs">Requires an active broker session with a valid access token.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* Row 1: Market Pulse (full width) */}
          <MarketPulse data={snapshot} />

          {/* Row 2: Volatility | Probable Range */}
          <VolatilityRangePanel data={snapshot} />

          {/* Row 3: GEX Walls | Vol + Term Structure */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <GEXWalls data={snapshot} isDark={isDark} />
            <VolPanel data={snapshot} isDark={isDark} />
          </div>

          {/* Row 4: OI Butterfly | Strategy Suggestions */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <OIPanel data={snapshot} isDark={isDark} />
            <StrategySuggestions data={snapshot} />
          </div>
        </div>
      )}
    </div>
  )
}
