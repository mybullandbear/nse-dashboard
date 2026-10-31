export interface IndexData {
  symbol: string;
  name: string;
  last: number;
  change: number;
  pctChange: number;
  open: number;
  high: number;
  low: number;
  prevClose: number;
  timestamp: string;
}

export interface VIXData {
  current: number;
  change: number;
  pct_change: number;
  high: number;
  low: number;
  prev_close: number;
  trend: 'up' | 'down' | 'neutral';
}

export interface MarketBreadth {
  advances: number;
  declines: number;
  unchanged: number;
  adr: number;
}

export interface OptionGreeks {
  delta: number;
  theta: number;
  gamma: number;
  vega: number;
  iv: number;
}

export interface OptionStrikeData {
  strike_price: number;
  expiry: string;
  ce_ltp: number;
  ce_oi: number;
  ce_oi_change: number;
  ce_volume: number;
  ce_iv: number;
  ce_bid: number;
  ce_ask: number;
  ce_greeks: OptionGreeks;
  pe_ltp: number;
  pe_oi: number;
  pe_oi_change: number;
  pe_volume: number;
  pe_iv: number;
  pe_bid: number;
  pe_ask: number;
  pe_greeks: OptionGreeks;
  oi_interpretation_ce: string;
  oi_interpretation_pe: string;
}

export interface OptionChainResponse {
  symbol: string;
  expiry: string;
  spot_price: number;
  atm_strike: number;
  strikes: OptionStrikeData[];
  pcr: number;
  max_pain: number;
  timestamp: string;
  expiry_list: string[];
}

export interface PCRData {
  overall: number;
  atm: number;
  five_strike: number;
  ten_strike: number;
  weighted: number;
  interpretation: string;
  color: string;
  timestamp: string;
}

export interface SupportResistance {
  level: number;
  strength: number;
  oi: number;
  type: 'support' | 'resistance';
  distance_pct: number;
  break_probability: number;
}

export interface SellerRecommendation {
  strategy: string;
  ce_strike?: number;
  pe_strike?: number;
  ce_premium: number;
  pe_premium: number;
  total_premium: number;
  probability_of_profit: number;
  theta_score: number;
  gamma_risk: number;
  iv_favorable: boolean;
  risk_level: 'safe' | 'moderate' | 'risky' | 'avoid';
  confidence: number;
  reasoning: string[];
  suggested_sl?: number;
  expected_decay: number;
  margin_required: number;
  expected_roi: number;
  timestamp: string;
  signal_id: string;
}

export interface OISpurtEntry {
  symbol: string;
  price: number;
  price_change: number;
  pct_change: number;
  oi: number;
  oi_change: number;
  oi_pct_change: number;
  volume: number;
  interpretation: string;
  confidence: number;
}

export interface AlertEntry {
  id: string;
  alert_type: string;
  message: string;
  severity: 'info' | 'warning' | 'critical';
  symbol: string;
  strike?: number;
  timestamp: string;
  acknowledged: boolean;
}

export interface SectorData {
  name: string;
  strength_score: number;
  money_flow: 'inflow' | 'outflow' | 'neutral';
  relative_strength: number;
  volume_change: number;
  heat: 'hot' | 'warm' | 'cold' | 'neutral';
  bullish_pct: number;
  bearish_pct: number;
  rank: number;
  change_pct: number;
}
