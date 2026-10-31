"""
Composite Market Data Provider.
Orchestrates fallback execution across Fyers, NSE Scraper, and Simulator Adapters.
"""
from typing import Optional, List
from app.providers.base import MarketDataProvider
from app.providers.fyers_adapter import FyersProviderAdapter
from app.providers.nse_adapter import NSEProviderAdapter
from app.providers.simulator_adapter import SimulatorProviderAdapter
from app.domain.contracts import MarketSnapshot


class CompositeMarketDataProvider(MarketDataProvider):

    def __init__(self, adapters: Optional[List[MarketDataProvider]] = None):
        self.adapters = adapters or [
            FyersProviderAdapter(),
            NSEProviderAdapter(),
            SimulatorProviderAdapter()
        ]

    def provider_name(self) -> str:
        return "COMPOSITE"

    def is_available(self) -> bool:
        return any(adapter.is_available() for adapter in self.adapters)

    async def get_market_snapshot(self, symbol: str) -> MarketSnapshot:
        symbol = symbol.upper()
        for adapter in self.adapters:
            if adapter.is_available():
                try:
                    snap = await adapter.get_market_snapshot(symbol)
                    if snap is not None:
                        return snap
                except Exception:
                    continue

        # In live production mode, do NOT fall back to SimulatorProviderAdapter
        from app.config import get_settings
        from app.providers.data_source_manager import data_source_manager
        settings = get_settings()
        if settings.VCC_SIMULATION_MODE:
            sim_adapter = SimulatorProviderAdapter()
            return await sim_adapter.get_market_snapshot(symbol)

        return data_source_manager._build_fallback_snapshot(symbol)


composite_provider = CompositeMarketDataProvider()
