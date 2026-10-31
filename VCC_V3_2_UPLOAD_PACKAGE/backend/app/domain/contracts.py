"""
Canonical Domain Contracts & Strongly Typed Data Models for VCC V3.2.
Provides provider-agnostic domain representations for the market snapshot, option chain,
analytical results, signal decisions, and governance audit outcomes.
"""
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field


class DataQuality(str, Enum):
    GOOD = "DATA QUALITY GOOD"
    DEGRADED = "DATA QUALITY DEGRADED"
    INVALID = "DATA QUALITY INVALID"


class DataStatus(str, Enum):
    REAL_LIVE = "REAL_LIVE"
    REAL_RECENT = "REAL_RECENT"
    REAL_STALE = "REAL_STALE"
    INVALID = "INVALID"
    MISSING = "MISSING"
    SYNTHETIC = "SYNTHETIC"
    UNKNOWN = "UNKNOWN"


class MarketSession(str, Enum):
    PRE_MARKET = "PRE-MARKET"
    LIVE_MARKET = "LIVE MARKET"
    POST_MARKET = "POST-MARKET"
    MARKET_CLOSED = "MARKET CLOSED"


class MarketState(BaseModel):
    session: MarketSession = MarketSession.MARKET_CLOSED
    is_market_open: bool = False
    session_slot: str = "OFF_MARKET"
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class DataSourceMetadata(BaseModel):
    symbol: str = ""
    exchange: str = "NSE"
    provider: str = "SIMULATED"  # FYERS_LIVE, NSE_LIVE, PERSISTED_DB, SIMULATED, UNAVAILABLE
    source_name: str = "SIMULATED"
    provider_timestamp: Optional[str] = None
    received_timestamp: Optional[str] = None
    market_timestamp: Optional[str] = None
    spot_timestamp: Optional[str] = None
    option_timestamp: Optional[str] = None
    spot_data_age_sec: float = 0.0
    option_data_age_sec: float = 0.0
    data_age_seconds: float = 0.0
    data_status: DataStatus = DataStatus.SYNTHETIC
    is_real_data: bool = False
    is_stale: bool = False
    completeness_status: str = "COMPLETE"
    validation_status: str = "VALID"
    quality: DataQuality = DataQuality.GOOD
    last_error: Optional[str] = None



class SpotData(BaseModel):
    symbol: str
    spot_price: float
    change: float = 0.0
    pct_change: float = 0.0
    vwap: float = 0.0
    day_high: float = 0.0
    day_low: float = 0.0
    open_price: float = 0.0
    prev_close: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))


class OptionGreeks(BaseModel):
    delta: Optional[float] = None
    theta: Optional[float] = None
    gamma: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None
    greeks_status: str = "UNAVAILABLE"


class OptionTick(BaseModel):
    ltp: Optional[float] = None
    change: Optional[float] = None
    pct_change: Optional[float] = None
    oi: Optional[int] = None
    oi_change: Optional[int] = None
    volume: Optional[int] = None
    iv: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    greeks: OptionGreeks = Field(default_factory=OptionGreeks)
    tick_status: str = "UNAVAILABLE"


class OptionContract(BaseModel):
    strike_price: float
    expiry: str
    ce_tick: OptionTick = Field(default_factory=OptionTick)
    pe_tick: OptionTick = Field(default_factory=OptionTick)
    oi_interpretation_ce: str = "NEUTRAL"
    oi_interpretation_pe: str = "NEUTRAL"


class OptionChainSnapshot(BaseModel):
    symbol: str
    expiry: str
    spot_price: float
    atm_strike: float
    strikes: List[OptionContract] = Field(default_factory=list)
    pcr: Optional[float] = None
    max_pain: Optional[float] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    expiry_list: List[str] = Field(default_factory=list)
    spot_timestamp: Optional[str] = None
    atm_source: str = "EXACT_MATCH"
    strike_step: float = 50.0
    strike_step_source: str = "INDEX_CONFIG"
    validation_status: str = "VALID"


class MarketSnapshot(BaseModel):
    """
    Master Canonical Object representing complete market state at a point in time.
    Provider-agnostic structure consumed by analytical & intelligence engines.
    """
    symbol: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    spot: SpotData
    expiry: str
    option_chain: OptionChainSnapshot
    metadata: DataSourceMetadata = Field(default_factory=DataSourceMetadata)
    quality: DataQuality = DataQuality.GOOD
    vix: Optional[float] = None
    vix_status: str = "UNAVAILABLE"

    def compute_data_age(self, now_dt: Optional[datetime] = None) -> None:
        """Compute spot and option chain data ages relative to current IST time."""
        if now_dt is None:
            try:
                ts_cand = self.metadata.market_timestamp or self.timestamp
                if ts_cand:
                    m_p = datetime.fromisoformat(ts_cand)
                    now = m_p if m_p.tzinfo else m_p.replace(tzinfo=IST)
                else:
                    now = datetime.now(IST)
            except Exception:
                now = datetime.now(IST)
        else:
            now = now_dt

        if now.tzinfo is None:
            now = now.replace(tzinfo=IST)

        if self.metadata.spot_timestamp:
            try:
                spot_dt = datetime.fromisoformat(self.metadata.spot_timestamp)
                if spot_dt.tzinfo is None:
                    spot_dt = spot_dt.replace(tzinfo=IST)
                self.metadata.spot_data_age_sec = max(0.0, (now - spot_dt).total_seconds())
            except Exception:
                pass
        if self.metadata.option_timestamp:
            try:
                opt_dt = datetime.fromisoformat(self.metadata.option_timestamp)
                if opt_dt.tzinfo is None:
                    opt_dt = opt_dt.replace(tzinfo=IST)
                self.metadata.option_data_age_sec = max(0.0, (now - opt_dt).total_seconds())
            except Exception:
                pass
        
        max_age = max(self.metadata.spot_data_age_sec, self.metadata.option_data_age_sec)
        self.metadata.data_age_seconds = max_age

        provider = self.metadata.provider or self.metadata.source_name
        if provider in ["FYERS_LIVE", "NSE_LIVE", "PERSISTED_DB"] and self.metadata.source_name != "SIMULATED":
            self.metadata.is_real_data = True
        else:
            self.metadata.is_real_data = False

        if not self.metadata.is_real_data or self.metadata.source_name == "SIMULATED":
            self.metadata.data_status = DataStatus.SYNTHETIC
            self.metadata.is_stale = True
            self.quality = DataQuality.INVALID
            self.metadata.quality = DataQuality.INVALID
        elif not self.spot or self.spot.spot_price <= 0 or not self.option_chain or not self.option_chain.strikes:
            self.metadata.data_status = DataStatus.INVALID
            self.metadata.is_stale = True
            self.quality = DataQuality.INVALID
            self.metadata.quality = DataQuality.INVALID
        elif max_age > 30.0:
            self.metadata.data_status = DataStatus.REAL_STALE
            self.metadata.is_stale = True
            self.quality = DataQuality.INVALID
            self.metadata.quality = DataQuality.INVALID
        elif max_age > 5.0:
            self.metadata.data_status = DataStatus.REAL_RECENT
            self.metadata.is_stale = False
            self.quality = DataQuality.DEGRADED
            self.metadata.quality = DataQuality.DEGRADED
        else:
            self.metadata.data_status = DataStatus.REAL_LIVE
            self.metadata.is_stale = False
            self.quality = DataQuality.GOOD
            self.metadata.quality = DataQuality.GOOD



class AnalyticalResult(BaseModel):
    """
    Normalized result payload from the VCC Intelligence Engine.
    """
    symbol: str
    timestamp: str
    spot_price: float
    atm_strike: float
    positioning_score: float = 50.0
    price_confirmation_score: float = 50.0
    final_confluence_score: float = 50.0
    confluence_label: str = "MODERATE / TWO-SIDED"
    directional_flow_label: str = "NEUTRAL"
    net_flow_lakhs: float = 0.0
    pe_flow_lakhs: float = 0.0
    ce_flow_lakhs: float = 0.0
    total_activity_lakhs: float = 0.0
    pcr: float = 1.0
    atm_straddle_premium: float = 0.0
    support_wall: Optional[float] = None
    resistance_wall: Optional[float] = None
    wall_migration_direction: str = "STABLE"
    breakout_status: str = "NO BREAKOUT"
    range_compression_status: str = "NORMAL"
    atm_pressure_score: float = 0.0
    operational_state: str = "ENTRY READY"
    market_regime: str = "RANGE"


class SignalEvidence(BaseModel):
    evidence_type: str = "FACTOR"
    description: str = ""
    factor_name: Optional[str] = None
    direction: str = "NEUTRAL"
    weight: float = 1.0
    score: float = 0.0
    contribution_score: float = 0.0
    value_str: str = ""
    is_supportive: bool = True
    explanation: str = ""


class SignalDecision(BaseModel):
    signal_id: str
    symbol: str
    timestamp: str
    direction: str = "NEUTRAL"  # BULLISH, BEARISH, NEUTRAL
    operational_state: str = "NO SIGNAL"
    market_regime: str = "RANGE"
    confluence_score: float = 50.0
    confidence: float = 50.0
    persistence_pct: float = 50.0
    evidences: List[SignalEvidence] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    conflict_count: int = 0
    data_quality: DataQuality = DataQuality.GOOD
    reason_codes: List[str] = Field(default_factory=list)

    # Phase 3 Immutable Signal Timestamp Integrity
    signal_initiated_at: str = ""
    signal_initiated_at_ist: str = ""
    market_timestamp_at_initiation: str = ""
    last_evaluated_at: str = ""
    last_updated_at: str = ""
    timestamp_status: str = "VERIFIED"  # VERIFIED or TIMESTAMP_UNVERIFIED
    created_at: Optional[str] = None
    confirming_started_at: Optional[str] = None
    activated_at: Optional[str] = None
    closed_at: Optional[str] = None

    # Phase 4 Live vs Historical Signal Separation
    signal_category: str = "LIVE_SIGNAL"  # LIVE_SIGNAL, HISTORICAL_SIGNAL, CLOSED_SIGNAL, RECOVERED_SIGNAL, INVALID_UNVERIFIED_EVENT
    is_live: bool = False




class SignalOutcome(BaseModel):
    snapshot_id: str
    timestamp: str
    symbol: str
    direction: str = "NEUTRAL"
    spot_price: float = 0.0
    spot_t5: Optional[float] = None
    spot_t15: Optional[float] = None
    spot_t30: Optional[float] = None
    return_t5_pct: Optional[float] = None
    return_t15_pct: Optional[float] = None
    return_t30_pct: Optional[float] = None
    mfe_t30_pct: Optional[float] = None
    mae_t30_pct: Optional[float] = None
    directional_correctness_5m: Optional[str] = None
    directional_correctness_15m: Optional[str] = None
    directional_correctness_30m: Optional[str] = None
    false_signal_category: str = "NONE"
    outcome_evaluated: bool = False
