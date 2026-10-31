"""
NSE India Scraper Service (DEPRECATED & DISABLED)
Scraping from nseindia.com has been permanently removed to eliminate blocking/stalling issues.
All market data is sourced strictly through Fyers Broker API v3 with in-memory caching.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class NSEFetcher:
    """
    Deprecated stub. All scraping requests to nseindia.com are disabled.
    """
    async def get_indices(self) -> Optional[dict]:
        return None

    async def get_option_chain(self, symbol: str = "NIFTY") -> Optional[dict]:
        return None

    async def get_oi_spurts(self) -> Optional[dict]:
        return None

    async def close(self):
        pass


nse_fetcher = NSEFetcher()

