"""
Providers Package Initializer
"""
from app.providers.base import MarketDataProvider
from app.providers.fyers_adapter import FyersProviderAdapter
from app.providers.nse_adapter import NSEProviderAdapter
from app.providers.db_fallback_adapter import DatabaseFallbackProviderAdapter
from app.providers.simulator_adapter import SimulatorProviderAdapter
from app.providers.replay_adapter import ReplayProviderAdapter
from app.providers.composite_provider import CompositeMarketDataProvider, composite_provider
from app.providers.data_source_manager import DataSourceManager, data_source_manager, ProviderHealth

__all__ = [
    "MarketDataProvider",
    "FyersProviderAdapter",
    "NSEProviderAdapter",
    "DatabaseFallbackProviderAdapter",
    "SimulatorProviderAdapter",
    "ReplayProviderAdapter",
    "CompositeMarketDataProvider",
    "composite_provider",
    "DataSourceManager",
    "data_source_manager",
    "ProviderHealth"
]
