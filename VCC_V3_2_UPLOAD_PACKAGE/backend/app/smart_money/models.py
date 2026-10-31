"""
Smart Money Domain Data Models & DTOs for VCC V3.2.
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class SmartMoneyShiftEvent(BaseModel):
    symbol: str
    trade_date: str
    timestamp: str
    shift_text: str
    shift_type: str  # "BULL", "BEAR", "NEUT"
    strike_price: float
    option_type: str  # "CE", "PE"
    oi_change: float
    conviction_score: float = 50.0


class MarketDirectionDTO(BaseModel):
    status: str
    label: str
    score: int
    action: str
    sm_bias_5: str
    sm_bias_desc: str
    pe_chg_5: float
    ce_chg_5: float
    pcr: float
    since_time: Optional[str] = None
    duration: Optional[str] = None
    last_eval: Optional[str] = None
    established_iso: Optional[str] = None


class SmartMoneyAnalysisResult(BaseModel):
    symbol: str
    date: str
    last_updated: str = ""
    smart_money_score: int = 50
    call_conviction: str = "78%"
    put_conviction: str = "89%"
    expected_decay: float = 0.0
    call_wall_strike: Optional[float] = None
    put_wall_strike: Optional[float] = None
    net_bias: str = "NEUTRAL / STRADDLE ZONE"
    top_oi_distribution: List[Dict[str, Any]] = Field(default_factory=list)
    oi_chart_data: List[Dict[str, Any]] = Field(default_factory=list)
    intraday_timeline: List[Dict[str, Any]] = Field(default_factory=list)
    shifts: List[Dict[str, Any]] = Field(default_factory=list)
    market_direction: Dict[str, Any] = Field(default_factory=dict)
    is_database_connected: bool = True
