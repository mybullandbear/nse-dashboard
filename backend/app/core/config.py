"""
Application Configuration and Settings
"""
import os
from functools import lru_cache
from typing import List, Dict
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "mybullandbear - Institutional NSE Options & Signal Command Center"
    APP_NAME: str = "mybullandbear - Institutional NSE Options & Signal Command Center"
    VERSION: str = "2.0.0-centralized"
    API_PREFIX: str = "/api"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    POLL_INTERVAL_LIVE: float = 1.5
    POLL_INTERVAL_OFF_MARKET: float = 10.0
    
    # Fyers Prime Configuration
    FYERS_TIER: str = "PRIME"  # "PRIME" removes 50 req/min limit, allows 200 req/min & 100k daily calls
    FYERS_PRIME_RATE_LIMIT_PER_MIN: int = 200
    FYERS_PRIME_DAILY_LIMIT: int = 100000
    
    # Base paths
    BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    FYERS_CONFIG_PATH: str = os.path.join(BASE_DIR, "fyers_config.json")
    DATABASE_PATH: str = os.path.join(BASE_DIR, "db", "terminal_snapshots.db")
    SHONYA_DB_PATH: str = os.path.join(BASE_DIR, "db", "shonya_trades.db")
    
    TRACKED_SYMBOLS: List[str] = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
    
    STRIKE_STEPS: Dict[str, int] = {
        "NIFTY": 50,
        "BANKNIFTY": 100,
        "FINNIFTY": 50,
        "MIDCPNIFTY": 25,
        "SENSEX": 100,
    }
    
    LOT_SIZES: Dict[str, int] = {
        "NIFTY": 65,
        "BANKNIFTY": 30,
        "FINNIFTY": 60,
        "MIDCPNIFTY": 120,
        "SENSEX": 20,
    }

    EXPIRY_DAYS: Dict[str, str] = {
        "NIFTY": "Tuesday (Weekly/Monthly)",
        "BANKNIFTY": "Last Tuesday (Monthly)",
        "FINNIFTY": "Last Tuesday (Monthly)",
        "MIDCPNIFTY": "Last Tuesday (Monthly)",
        "SENSEX": "Thursday (Weekly/Monthly)",
    }
    
    # Fyers OAuth Defaults
    FYERS_CLIENT_ID: str = "7BRKBHOFP8-100"
    FYERS_SECRET_KEY: str = "TO0QPDNH7A"
    FYERS_REDIRECT_URI: str = "http://137.23.42.11:8000/api/fyers/callback"
    
    # Engine Refresh Cycles (Optimized for Fyers Prime)
    INDEX_TICK_INTERVAL_SEC: float = 1.0       # 1-second batch quote pull
    CHAIN_SNAPSHOT_INTERVAL_SEC: float = 4.0   # Fast 4-second option chain refresh
    CHAIN_FRESHNESS_TTL_SEC: float = 8.0      # Maximum validity for chain
    
    # WebSocket Configuration (Zero-Latency Real-Time Streaming)
    ENABLE_FYERS_WS: bool = True
    
    class Config:
        env_file = ".env"
        extra = "allow"

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
