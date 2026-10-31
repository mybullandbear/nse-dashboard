"""Application configuration."""
from functools import lru_cache
import os

try:
    from pydantic_settings import BaseSettings
    class Settings(BaseSettings):
        APP_NAME: str = "NSE Options Terminal"
        DEBUG: bool = False
        HOST: str = "0.0.0.0"
        PORT: int = 8000
        DATABASE_URL: str = "sqlite:///./nse_terminal.db"
        REDIS_URL: str = "redis://localhost:6379/0"
        REDIS_CACHE_TTL: int = 30
        NSE_BASE_URL: str = "https://www.nseindia.com"
        NSE_API_URL: str = "https://www.nseindia.com/api"
        NSE_REFRESH_INTERVAL: int = 15
        NSE_REQUEST_TIMEOUT: int = 30
        WS_BROADCAST_INTERVAL: float = 1.0
        MARKET_OPEN_HOUR: int = 9
        MARKET_OPEN_MINUTE: int = 15
        MARKET_CLOSE_HOUR: int = 15
        MARKET_CLOSE_MINUTE: int = 30
        TRACKED_INDICES: list[str] = ["NIFTY 50", "NIFTY BANK", "NIFTY FIN SERVICE", "NIFTY MID SELECT", "INDIA VIX"]
        OPTION_INDICES: list[str] = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
        TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "8392685097:AAFnCGdGMcyjOlMScfqKLS6um9kY2wO7arA")
        TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "562973750")
        VCC_SIMULATION_MODE: bool = os.getenv("VCC_SIMULATION_MODE", "false").lower() == "true"

        
        class Config:
            env_file = ".env"
            case_sensitive = True

except ImportError:
    try:
        from pydantic import BaseModel
        class Settings(BaseModel):
            APP_NAME: str = "NSE Options Terminal"
            DEBUG: bool = False
            HOST: str = "0.0.0.0"
            PORT: int = 8000
            DATABASE_URL: str = "sqlite:///./nse_terminal.db"
            REDIS_URL: str = "redis://localhost:6379/0"
            REDIS_CACHE_TTL: int = 30
            NSE_BASE_URL: str = "https://www.nseindia.com"
            NSE_API_URL: str = "https://www.nseindia.com/api"
            NSE_REFRESH_INTERVAL: int = 15
            NSE_REQUEST_TIMEOUT: int = 30
            WS_BROADCAST_INTERVAL: float = 1.0
            MARKET_OPEN_HOUR: int = 9
            MARKET_OPEN_MINUTE: int = 15
            MARKET_CLOSE_HOUR: int = 15
            MARKET_CLOSE_MINUTE: int = 30
            TRACKED_INDICES: list[str] = ["NIFTY 50", "NIFTY BANK", "NIFTY FIN SERVICE", "NIFTY MID SELECT", "INDIA VIX"]
            OPTION_INDICES: list[str] = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
            VCC_SIMULATION_MODE: bool = os.getenv("VCC_SIMULATION_MODE", "false").lower() == "true"
    except ImportError:
        from dataclasses import dataclass, field
        @dataclass
        class Settings:
            APP_NAME: str = "NSE Options Terminal"
            DEBUG: bool = False
            HOST: str = "0.0.0.0"
            PORT: int = 8000
            DATABASE_URL: str = "sqlite:///./nse_terminal.db"
            REDIS_URL: str = "redis://localhost:6379/0"
            REDIS_CACHE_TTL: int = 30
            NSE_BASE_URL: str = "https://www.nseindia.com"
            NSE_API_URL: str = "https://www.nseindia.com/api"
            NSE_REFRESH_INTERVAL: int = 15
            NSE_REQUEST_TIMEOUT: int = 30
            WS_BROADCAST_INTERVAL: float = 1.0
            MARKET_OPEN_HOUR: int = 9
            MARKET_OPEN_MINUTE: int = 15
            MARKET_CLOSE_HOUR: int = 15
            MARKET_CLOSE_MINUTE: int = 30
            TRACKED_INDICES: list = field(default_factory=lambda: ["NIFTY 50", "NIFTY BANK", "NIFTY FIN SERVICE", "NIFTY MID SELECT", "INDIA VIX"])
            OPTION_INDICES: list = field(default_factory=lambda: ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"])
            VCC_SIMULATION_MODE: bool = os.getenv("VCC_SIMULATION_MODE", "false").lower() == "true"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.VCC_SIMULATION_MODE = os.getenv("VCC_SIMULATION_MODE", "false").lower() == "true"
    return s
