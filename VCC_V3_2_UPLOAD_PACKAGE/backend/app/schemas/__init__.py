"""Pydantic schemas for API responses."""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ── Market Index ──────────────────────────────────────────────
class IndexData(BaseModel):
    symbol: str
    name: str
    last: float = 0.0
    change: float = 0.0
    pct_change: float = Field(0.0, alias="pctChange")
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    prev_close: float = Field(0.0, alias="prevClose")
    timestamp: str = ""

    class Config:
        populate_by_name = True


class VIXData(BaseModel):
    current: float = 0.0
    change: float = 0.0
    pct_change: float = 0.0
    high: float = 0.0
    low: float = 0.0
    prev_close: float = 0.0
    trend: str = "neutral"  # up/down/neutral


class MarketBreadth(BaseModel):
    advances: int = 0
    declines: int = 0
    unchanged: int = 0
    adr: float = 0.0  # Advance-Decline Ratio


# ── Option Chain ──────────────────────────────────────────────
class OptionGreeks(BaseModel):
    delta: float = 0.0
    theta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0
    iv: float = 0.0


class OptionStrikeData(BaseModel):
    strike_price: float
    expiry: str

    # CE data
    ce_ltp: float = 0.0
    ce_oi: int = 0
    ce_oi_change: int = 0
    ce_volume: int = 0
    ce_iv: float = 0.0
    ce_bid: float = 0.0
    ce_ask: float = 0.0
    ce_greeks: OptionGreeks = Field(default_factory=OptionGreeks)

    # PE data
    pe_ltp: float = 0.0
    pe_oi: int = 0
    pe_oi_change: int = 0
    pe_volume: int = 0
    pe_iv: float = 0.0
    pe_bid: float = 0.0
    pe_ask: float = 0.0
    pe_greeks: OptionGreeks = Field(default_factory=OptionGreeks)

    # Classification
    oi_interpretation_ce: str = ""  # Fresh Writing, Fresh Buying, Short Covering, Long Unwinding
    oi_interpretation_pe: str = ""


class OptionChainResponse(BaseModel):
    symbol: str
    expiry: str
    spot_price: float
    atm_strike: float
    strikes: list[OptionStrikeData]
    all_strikes: list[OptionStrikeData] = Field(default_factory=list, exclude=True)
    pcr: float = 0.0
    max_pain: float = 0.0
    timestamp: str = ""
    expiry_list: list[str] = []


# ── PCR ───────────────────────────────────────────────────────
class PCRData(BaseModel):
    overall: float = 0.0
    atm: float = 0.0
    five_strike: float = 0.0
    ten_strike: float = 0.0
    weighted: float = 0.0
    interpretation: str = "Neutral"
    color: str = "#888"
    timestamp: str = ""


# ── OI Spurts ─────────────────────────────────────────────────
class OISpurtEntry(BaseModel):
    symbol: str
    price: float = 0.0
    price_change: float = 0.0
    pct_change: float = 0.0
    oi: int = 0
    oi_change: float = 0.0
    oi_pct_change: float = 0.0
    volume: int = 0
    interpretation: str = ""  # Fresh Long, Fresh Short, Short Covering, Long Unwinding
    confidence: float = 0.0


# ── Most Active ───────────────────────────────────────────────
class MostActiveContract(BaseModel):
    symbol: str
    instrument: str = ""
    expiry: str = ""
    strike: float = 0.0
    option_type: str = ""  # CE/PE
    ltp: float = 0.0
    change: float = 0.0
    pct_change: float = 0.0
    volume: int = 0
    oi: int = 0
    oi_change: int = 0
    value: float = 0.0


# ── Support / Resistance ─────────────────────────────────────
class SupportResistance(BaseModel):
    level: float
    strength: float = 0.0  # 0-100
    oi: int = 0
    type: str = ""  # support/resistance
    distance_pct: float = 0.0
    break_probability: float = 0.0


# ── Seller Engine ─────────────────────────────────────────────
class SellerRecommendation(BaseModel):
    strategy: str  # Short Strangle, Iron Condor, etc.
    ce_strike: Optional[float] = None
    pe_strike: Optional[float] = None
    ce_premium: float = 0.0
    pe_premium: float = 0.0
    total_premium: float = 0.0
    probability_of_profit: float = 0.0
    theta_score: float = 0.0
    gamma_risk: float = 0.0
    iv_favorable: bool = True
    risk_level: str = "moderate"  # safe, moderate, risky, avoid
    confidence: float = 0.0
    reasoning: list[str] = []
    suggested_sl: Optional[float] = None
    expected_decay: float = 0.0
    margin_required: float = 0.0
    expected_roi: float = 0.0
    timestamp: str = ""
    signal_id: str = ""


# ── Trade Score ───────────────────────────────────────────────
class TradeScore(BaseModel):
    symbol: str
    strike: float
    option_type: str
    momentum_score: float = 0.0  # /20
    volume_score: float = 0.0  # /15
    oi_score: float = 0.0  # /20
    pcr_score: float = 0.0  # /10
    iv_score: float = 0.0  # /10
    sector_score: float = 0.0  # /10
    trend_score: float = 0.0  # /10
    risk_score: float = 0.0  # /5
    total: float = 0.0  # /100
    recommendation: str = "Neutral"  # Strong Sell, Sell, Neutral, Avoid
    timestamp: str = ""


# ── Alert ─────────────────────────────────────────────────────
class AlertEntry(BaseModel):
    id: str = ""
    alert_type: str  # heavy_call_writing, pcr_change, iv_spike, etc.
    message: str
    severity: str = "info"  # info, warning, critical
    symbol: str = ""
    strike: Optional[float] = None
    data: dict = {}
    timestamp: str = ""
    acknowledged: bool = False


# ── Sector ────────────────────────────────────────────────────
class SectorData(BaseModel):
    name: str
    strength_score: float = 0.0
    money_flow: str = "neutral"  # inflow, outflow, neutral
    relative_strength: float = 0.0
    volume_change: float = 0.0
    heat: str = "neutral"  # hot, warm, cold, neutral
    bullish_pct: float = 0.0
    bearish_pct: float = 0.0
    rank: int = 0
    change_pct: float = 0.0


# ── Signal Lifecycle & Performance Analytics ─────────────
class SignalLifecycleItem(BaseModel):
    signal_id: str
    symbol: str
    strategy: str
    direction: str = "NEUTRAL"  # BULLISH, BEARISH, NEUTRAL
    status: str = "GENERATED"   # GENERATED, CONFIRMING, ACTIVE, MODIFIED, CLOSED
    version: int = 1
    
    # Entry snapshot
    entry_time: str = ""
    entry_time_formatted: str = ""
    active_duration: str = ""
    last_evaluated: str = ""
    entry_spot: float = 0.0
    entry_ce_ltp: float = 0.0
    entry_pe_ltp: float = 0.0
    entry_premium: float = 0.0
    
    # Target / SL / Margin
    target_premium: float = 0.0
    stop_loss: float = 0.0
    margin_required: float = 0.0
    
    # Confidence & Confluence Factors
    confidence: float = 0.0
    confluence_factors: list[str] = []
    
    # Active Tracking (MFE / MAE)
    current_spot: float = 0.0
    current_premium: float = 0.0
    unrealized_pnl_pts: float = 0.0
    mfe_pts: float = 0.0  # Max Favorable Excursion (Points)
    mae_pts: float = 0.0  # Max Adverse Excursion (Points)
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    
    # Exit snapshot
    exit_time: Optional[str] = None
    exit_spot: Optional[float] = None
    exit_premium: Optional[float] = None
    exit_reason: Optional[str] = None
    
    # Realized P&L
    realized_pnl_pts: float = 0.0
    realized_pnl_rupees: float = 0.0
    realized_roi_pct: float = 0.0
    holding_seconds: int = 0
    is_win: Optional[bool] = None


class PerformanceAnalytics(BaseModel):
    total_signals: int = 0
    closed_signals: int = 0
    active_signals: int = 0
    win_rate_pct: float = 0.0
    total_points_captured: float = 0.0
    total_realized_pnl_rupees: float = 0.0
    avg_win_pts: float = 0.0
    avg_loss_pts: float = 0.0
    profit_factor: float = 0.0
    avg_mfe_pts: float = 0.0
    avg_mae_pts: float = 0.0
    avg_holding_time_mins: float = 0.0
    accuracy_high_confidence: float = 0.0
    accuracy_med_confidence: float = 0.0
    factor_attribution: dict[str, float] = Field(default_factory=dict)


# ── Dashboard Aggregate ──────────────────────────────────────
class DashboardData(BaseModel):
    indices: list[IndexData] = []
    vix: VIXData = Field(default_factory=VIXData)
    breadth: MarketBreadth = Field(default_factory=MarketBreadth)
    pcr: PCRData = Field(default_factory=PCRData)
    option_chain: Optional[OptionChainResponse] = None
    oi_spurts: list[OISpurtEntry] = []
    most_active: list[MostActiveContract] = []
    supports: list[SupportResistance] = []
    resistances: list[SupportResistance] = []
    sectors: list[SectorData] = []
    recommendations: list[SellerRecommendation] = []
    active_signal: Optional[SignalLifecycleItem] = None
    analytics: Optional[PerformanceAnalytics] = None
    signal_history: list[SignalLifecycleItem] = []
    alerts: list[AlertEntry] = []
    timestamp: str = ""

