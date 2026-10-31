"""
NSE India Data Fetcher with curl_cffi Chrome impersonation & fallback handlers.
"""
import asyncio
import json
import logging
import time
from typing import Any, Optional

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    cffi_requests = None
    HAS_CURL_CFFI = False

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class NSEFetcher:
    """
    NSE India data fetcher with TLS fingerprint browser impersonation.
    """

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/option-chain",
    }

    def __init__(self):
        self._session: Optional[Any] = None
        self._warmed = False
        self._lock = asyncio.Lock()

    def _init_session(self):
        if HAS_CURL_CFFI and self._session is None:
            self._session = cffi_requests.Session(impersonate="chrome120")
            self._session.headers.update(self.HEADERS)

    def _warm_session_sync(self):
        if not HAS_CURL_CFFI:
            return
        self._init_session()
        try:
            logger.info("Warming NSE session with Chrome TLS impersonation...")
            self._session.get("https://www.nseindia.com", timeout=10)
            self._session.get("https://www.nseindia.com/option-chain", timeout=10)
            self._warmed = True
            logger.info("NSE session successfully warmed")
        except Exception as e:
            logger.warning(f"NSE session warmup exception: {e}")

    async def _ensure_session(self):
        if not self._warmed:
            async with self._lock:
                if not self._warmed:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, self._warm_session_sync)

    async def fetch(self, url: str) -> Optional[dict]:
        await self._ensure_session()
        if not HAS_CURL_CFFI or not self._session:
            return None

        loop = asyncio.get_running_loop()
        def _sync_fetch():
            try:
                resp = self._session.get(url, timeout=12)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code in (401, 403):
                    self._warmed = False
                    self._warm_session_sync()
                    resp = self._session.get(url, timeout=12)
                    if resp.status_code == 200:
                        return resp.json()
                logger.warning(f"NSE fetch returned {resp.status_code} for {url}")
            except Exception as e:
                logger.warning(f"NSE fetch exception for {url}: {e}")
            return None

        return await loop.run_in_executor(None, _sync_fetch)

    async def get_indices(self) -> Optional[dict]:
        return await self.fetch("https://www.nseindia.com/api/allIndices")

    async def get_option_chain(self, symbol: str = "NIFTY") -> Optional[dict]:
        if symbol.upper() in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"):
            res = await self.fetch(f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol.upper()}")
            if not res:
                res = await self.fetch(f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol.upper()}")
            return res
        return await self.fetch(f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol.upper()}")

    async def get_oi_spurts(self) -> Optional[dict]:
        return await self.fetch("https://www.nseindia.com/api/live-analysis-oi-spurts-contracts")

    async def get_most_active(self) -> Optional[dict]:
        return await self.fetch("https://www.nseindia.com/api/live-analysis-most-active-securities?index=futopt&optionType=CE,PE")

    async def close(self):
        """Close the curl_cffi session gracefully."""
        if self._session:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
            self._warmed = False


nse = NSEFetcher()
