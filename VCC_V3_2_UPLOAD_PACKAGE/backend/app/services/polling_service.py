"""
Polling & Scheduler Service for VCC V3.2.
Responsible strictly for fetching, retry/backoff, and snapshot caching.
Does NOT compute analytical confluence, signals, or trading decisions.
"""
import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime
from app.providers.data_source_manager import data_source_manager, DataSourceManager
from app.domain.contracts import MarketSnapshot
from app.core.constants import system_config

logger = logging.getLogger(__name__)


class PollingService:
    """
    Dedicated Background Polling Scheduler.
    Pure data acquisition and snapshot publishing.
    """

    def __init__(self, manager: Optional[DataSourceManager] = None):
        self.manager = manager or data_source_manager
        self.snapshot_cache: Dict[str, MarketSnapshot] = {}
        self.is_running: bool = False
        self._task: Optional[asyncio.Task] = None

    async def fetch_snapshot_for_symbol(self, symbol: str) -> MarketSnapshot:
        symbol = symbol.upper()
        try:
            snapshot = await self.manager.get_market_snapshot(symbol)
            self.snapshot_cache[symbol] = snapshot
            return snapshot
        except Exception as e:
            logger.error(f"PollingService error fetching {symbol}: {e}")
            # Fallback snapshot
            sim_snap = await self.manager.get_market_snapshot(symbol)
            self.snapshot_cache[symbol] = sim_snap
            return sim_snap

    def get_latest_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        return self.snapshot_cache.get(symbol.upper())

    async def start_polling(self, symbols: Optional[list] = None) -> None:
        if self.is_running:
            return

        self.is_running = True
        target_symbols = symbols or system_config.symbols.supported_symbols

        async def _polling_loop():
            while self.is_running:
                for symbol in target_symbols:
                    await self.fetch_snapshot_for_symbol(symbol)
                await asyncio.sleep(system_config.polling.fyers_poll_interval_sec)

        self._task = asyncio.create_task(_polling_loop())

    async def stop_polling(self) -> None:
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


polling_service = PollingService()
