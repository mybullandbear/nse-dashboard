"""
Data models for option contracts, chain snapshots, and trade signals.
Supports Pydantic if available, otherwise gracefully falls back to standard dataclasses.
"""
from typing import List, Optional, Dict, Any

try:
    from pydantic import BaseModel, Field
except ImportError:
    from dataclasses import dataclass, field

    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

        def dict(self):
            return self.__dict__

    def Field(default=None, default_factory=None):
        if default_factory is not None:
            return field(default_factory=default_factory)
        return default


class StrikeContract(BaseModel):
    strikePrice: float = 0.0
    expiryDate: str = ""
    lastPrice: float = 0.0
    change: float = 0.0
    pChange: float = 0.0
    openInterest: int = 0
    changeinOpenInterest: int = 0
    totalTradedVolume: int = 0
    impliedVolatility: float = 0.0
    bidprice: float = 0.0
    askPrice: float = 0.0


class StrikeRow(BaseModel):
    strikePrice: float = 0.0
    expiryDate: str = ""
    CE: Optional[StrikeContract] = None
    PE: Optional[StrikeContract] = None


class ParsedOptionChain(BaseModel):
    symbol: str = "NIFTY"
    spot_price: float = 0.0
    atm_strike: float = 0.0
    expiry: str = ""
    expiry_list: List[str] = Field(default_factory=list)
    pcr: float = 1.0
    pcr_atm_5: float = 1.0
    max_pain: float = 0.0
    total_ce_oi: int = 0
    total_pe_oi: int = 0
    strikes: List[StrikeRow] = Field(default_factory=list)


class TradeSignal(BaseModel):
    symbol: str
    action: str  # BUY / SELL
    option_type: str  # CE / PE
    strike: float
    entry_price: float
    target_price: float
    stop_loss_price: float
    confidence: float = 0.0
    reason: str = ""
    tqs_score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
