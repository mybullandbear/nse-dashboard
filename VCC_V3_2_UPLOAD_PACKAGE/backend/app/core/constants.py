"""
Core Business Configuration & Technical Constants for VCC V3.2.
All values reflect existing baseline operational parameters.
"""
from typing import Dict, List
from pydantic import BaseModel, Field


class SymbolConfig(BaseModel):
    supported_symbols: List[str] = Field(
        default=["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
    )
    strike_steps: Dict[str, int] = Field(
        default={
            "NIFTY": 50,
            "BANKNIFTY": 100,
            "FINNIFTY": 50,
            "MIDCPNIFTY": 25,
            "SENSEX": 100
        }
    )

    def get_strike_step(self, symbol: str) -> int:
        return self.strike_steps.get(symbol.upper(), 50)


class MarketHoursConfig(BaseModel):
    timezone: str = "Asia/Kolkata"
    pre_market_start: str = "09:00:00"
    live_market_start: str = "09:15:00"
    live_market_end: str = "15:15:00"
    post_market_end: str = "15:40:00"


class PollingConfig(BaseModel):
    fyers_poll_interval_sec: float = 1.0
    fyers_offmarket_poll_interval_sec: float = 15.0
    nse_poll_interval_sec: float = 30.0
    stock_poll_interval_sec: float = 60.0
    db_cleanup_interval_sec: float = 14400.0  # 4 hours


class SourcePriorityConfig(BaseModel):
    priority_order: List[str] = Field(
        default=["FYERS_LIVE", "NSE_LIVE", "PERSISTED_DB", "SIMULATED"]
    )


class AnalyticalThresholdsConfig(BaseModel):
    min_win_points: float = 10.0
    wall_migration_threshold_pts_per_hr: float = 25.0
    compression_threshold_score: float = 50.0
    atm_pressure_high_threshold: float = 70.0
    data_stale_warning_sec: float = 5.0
    data_stale_invalid_sec: float = 30.0


class ConfluenceWeightsConfig(BaseModel):
    positioning: float = 0.35
    price_confirmation: float = 0.30
    wall_proximity: float = 0.15
    straddle_decay: float = 0.20


class AuditHorizonsConfig(BaseModel):
    t5_sec: int = 300
    t15_sec: int = 900
    t30_sec: int = 1800
    min_sample_size: int = 30


class VCCSystemConfig(BaseModel):
    symbols: SymbolConfig = SymbolConfig()
    market_hours: MarketHoursConfig = MarketHoursConfig()
    polling: PollingConfig = PollingConfig()
    source_priority: SourcePriorityConfig = SourcePriorityConfig()
    thresholds: AnalyticalThresholdsConfig = AnalyticalThresholdsConfig()
    confluence_weights: ConfluenceWeightsConfig = ConfluenceWeightsConfig()
    audit_horizons: AuditHorizonsConfig = AuditHorizonsConfig()


# System-wide Singleton Instance
system_config = VCCSystemConfig()
