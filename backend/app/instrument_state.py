"""
Instrument Models & Symbol Mapping
Standardizes symbols across NSE, Fyers, and internal intelligence engines.
"""
from enum import Enum
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
import time

class IndexSymbol(str, Enum):
    NIFTY = "NIFTY"
    BANKNIFTY = "BANKNIFTY"
    FINNIFTY = "FINNIFTY"
    MIDCPNIFTY = "MIDCPNIFTY"
    SENSEX = "SENSEX"

# Official Fyers Exchange Symbols
INDEX_FYERS_MAP = {
    IndexSymbol.NIFTY: "NSE:NIFTY50-INDEX",
    IndexSymbol.BANKNIFTY: "NSE:NIFTYBANK-INDEX",
    IndexSymbol.FINNIFTY: "NSE:FINNIFTY-INDEX",
    IndexSymbol.MIDCPNIFTY: "NSE:MIDCPNIFTY-INDEX",
    IndexSymbol.SENSEX: "BSE:SENSEX-INDEX",
}

FYERS_TO_INTERNAL_MAP = {v: k for k, v in INDEX_FYERS_MAP.items()}

# Index Step Sizes & Lot Sizes
INDEX_STEP_MAP = {
    IndexSymbol.NIFTY: 50,
    IndexSymbol.BANKNIFTY: 100,
    IndexSymbol.FINNIFTY: 50,
    IndexSymbol.MIDCPNIFTY: 25,
    IndexSymbol.SENSEX: 100,
}

INDEX_LOT_MAP = {
    IndexSymbol.NIFTY: 65,
    IndexSymbol.BANKNIFTY: 30,
    IndexSymbol.FINNIFTY: 60,
    IndexSymbol.MIDCPNIFTY: 120,
    IndexSymbol.SENSEX: 20,
}

INDEX_EXPIRY_MAP = {
    IndexSymbol.NIFTY: "Tuesday (Weekly/Monthly)",
    IndexSymbol.BANKNIFTY: "Last Tuesday (Monthly)",
    IndexSymbol.FINNIFTY: "Last Tuesday (Monthly)",
    IndexSymbol.MIDCPNIFTY: "Last Tuesday (Monthly)",
    IndexSymbol.SENSEX: "Thursday (Weekly/Monthly)",
}

class NormalizedTick(BaseModel):
    symbol: str
    fyers_symbol: str
    ltp: float
    change: float = 0.0
    pchange: float = 0.0
    high: float = 0.0
    low: float = 0.0
    open: float = 0.0
    prev_close: float = 0.0
    timestamp: float = Field(default_factory=time.time)
    source: str = "REST" # "WEBSOCKET" or "REST"

class OptionStrikeData(BaseModel):
    strike_price: float
    expiry_date: str = ""
    # Call Side
    ce_ltp: float = 0.0
    ce_change: float = 0.0
    ce_pchange: float = 0.0
    ce_oi: int = 0
    ce_oich: int = 0
    ce_volume: int = 0
    ce_iv: float = 0.0
    ce_symbol: str = ""
    ce_buildup: str = "NEUTRAL"
    # Put Side
    pe_ltp: float = 0.0
    pe_change: float = 0.0
    pe_pchange: float = 0.0
    pe_oi: int = 0
    pe_oich: int = 0
    pe_volume: int = 0
    pe_iv: float = 0.0
    pe_symbol: str = ""
    pe_buildup: str = "NEUTRAL"

class OptionChainSnapshot(BaseModel):
    symbol: str
    spot_price: float
    spot_change: float = 0.0
    spot_pchange: float = 0.0
    atm_strike: float
    expiry_dates: List[str] = []
    selected_expiry: str = ""
    strikes: Dict[float, OptionStrikeData] = {}
    timestamp: float = Field(default_factory=time.time)
    version: int = 1
    source: str = "FYERS_REST"
