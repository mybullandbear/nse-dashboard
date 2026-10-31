"""
Abstract Base Provider Interface for VCC Market Data Providers.
Decouples intelligence engines from specific data source implementations.
"""
from abc import ABC, abstractmethod
from typing import Optional
from app.domain.contracts import MarketSnapshot


class MarketDataProvider(ABC):
    """
    Abstract interface for all market data ingestion sources.
    Every provider adapter must return a standardized canonical MarketSnapshot object.
    """

    @abstractmethod
    async def get_market_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        """Fetch real-time normalized MarketSnapshot for the given symbol."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if the provider is currently connected and operational."""
        pass

    @abstractmethod
    def provider_name(self) -> str:
        """Returns the canonical source identifier string."""
        pass
