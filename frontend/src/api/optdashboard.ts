import { webClient } from './client'

export interface StrategyLeg {
  action: 'BUY' | 'SELL'
  strike: number
  option_type: 'CE' | 'PE'
  expiry: string
  symbol: string
  exchange: string
  ltp: number
}

export interface Strategy {
  rank: number
  name: string
  fit_score: number
  rationale: string
  legs: StrategyLeg[]
  net_premium: number
  max_profit_per_lot: number | null
  max_loss_per_lot: number | null
  upper_breakeven: number | null
  lower_breakeven: number | null
  note?: string
}

export interface GEXChainItem {
  strike: number
  ce_oi: number
  pe_oi: number
  ce_gex: number
  pe_gex: number
  net_gex: number
}

export interface OIChainItem {
  strike: number
  ce_oi: number
  pe_oi: number
}

export interface IVSmileItem {
  strike: number
  ce_iv: number | null
  pe_iv: number | null
}

export interface TermStructureItem {
  date: string
  dte: number
  atm_iv: number | null
}

export interface DashboardSnapshot {
  status: 'success' | 'error'
  message?: string
  underlying: string
  spot_price: number
  atm_strike: number
  lot_size: number
  expiry_date: string
  next_expiry_date: string | null
  // GEX
  call_wall: number | null
  put_wall: number | null
  gamma_flip: number | null
  total_net_gex: number
  total_ce_oi: number
  total_pe_oi: number
  pcr_oi: number
  // OI
  max_pain: number | null
  // Vol
  atm_iv: number | null
  iv_skew: number | null
  front_atm_iv: number | null
  next_atm_iv: number | null
  term_structure_slope: number | null
  // Regime
  regime: string
  regime_description: string
  regime_color: 'green' | 'red' | 'orange' | 'yellow' | 'blue' | 'gray'
  // Historical volatility
  hv_10: number | null
  hv_30: number | null
  iv_rv_spread: number | null
  // Probable ranges
  range_gex: { lower: number; upper: number } | null
  range_iv_1sd: { lower: number; upper: number; dte: number; sigma_pts: number } | null
  range_straddle: { lower: number; upper: number; straddle_premium: number } | null
  // Charts
  gex_chain: GEXChainItem[]
  oi_chain: OIChainItem[]
  iv_smile_chain: IVSmileItem[]
  term_structure: TermStructureItem[]
  // Strategies
  strategies: Strategy[]
}

export interface GEXSnapshotRow {
  ts: string
  expiry: string
  spot: number
  net_gex: number
  call_wall: number | null
  put_wall: number | null
  gamma_flip: number | null
  percentile: number
}

export interface GEXHistoryResponse {
  status: 'success' | 'error'
  symbol: string
  days: number
  data: GEXSnapshotRow[]
}

export const optDashboardApi = {
  getSnapshot: async (params: {
    underlying: string
    exchange: string
    expiry_date: string
    next_expiry_date?: string
  }): Promise<DashboardSnapshot> => {
    const response = await webClient.post<DashboardSnapshot>(
      '/optdashboard/api/snapshot',
      params
    )
    return response.data
  },

  getExpiries: async (exchange: string, underlying: string): Promise<{ expiries: string[] }> => {
    const response = await webClient.get<{ status: string; expiries: string[] }>(
      `/search/api/expiries?exchange=${exchange}&underlying=${underlying}`
    )
    return response.data
  },

  getGEXHistory: async (symbol: string, days = 60): Promise<GEXHistoryResponse> => {
    const response = await webClient.get<GEXHistoryResponse>(
      `/optdashboard/api/gex-history?symbol=${symbol}&days=${days}`
    )
    return response.data
  },
}
