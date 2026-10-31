"""
Data Source Manager for VCC V3.2.
Orchestrates provider selection, health tracking, failover, recovery,
and centralized DataQuality evaluation.
The intelligence engine must NEVER contain provider-selection logic.
"""
import logging
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
from app.providers.base import MarketDataProvider
from app.providers.fyers_adapter import FyersProviderAdapter
from app.providers.nse_adapter import NSEProviderAdapter
from app.providers.db_fallback_adapter import DatabaseFallbackProviderAdapter
from app.providers.simulator_adapter import SimulatorProviderAdapter
from app.providers.replay_adapter import ReplayProviderAdapter
from app.domain.contracts import MarketSnapshot, DataQuality
from app.domain.quality import data_quality_evaluator

logger = logging.getLogger(__name__)


class ProviderHealth:

    def __init__(self, name: str):
        self.name = name
        self.is_healthy: bool = True
        self.consecutive_failures: int = 0
        self.total_requests: int = 0
        self.successful_requests: int = 0
        self.last_success_time: Optional[str] = None
        self.last_error: Optional[str] = None

    def record_success(self) -> None:
        self.total_requests += 1
        self.successful_requests += 1
        self.consecutive_failures = 0
        self.is_healthy = True
        self.last_success_time = datetime.now().isoformat()
        self.last_error = None

    def record_failure(self, error_msg: str) -> None:
        self.total_requests += 1
        self.consecutive_failures += 1
        self.last_error = error_msg
        if self.consecutive_failures >= 3:
            self.is_healthy = False


class DataSourceManager:
    """
    Dedicated manager for provider health, failover, data quality, and transitions.
    """

    def __init__(self, providers: Optional[List[MarketDataProvider]] = None):
        self.providers: List[MarketDataProvider] = providers or [
            FyersProviderAdapter(),
            NSEProviderAdapter(),
            DatabaseFallbackProviderAdapter(),
            SimulatorProviderAdapter()
        ]
        self.health_registry: Dict[str, ProviderHealth] = {
            p.provider_name(): ProviderHealth(p.provider_name()) for p in self.providers
        }
        self.active_source: str = "SIMULATED"
        self.transition_listeners: List[Callable[[str, str], None]] = []

    def add_transition_listener(self, listener: Callable[[str, str], None]) -> None:
        self.transition_listeners.append(listener)

    def _notify_transition(self, old_source: str, new_source: str) -> None:
        if old_source != new_source:
            logger.info(f"Data source transition: {old_source} -> {new_source}")
            self.active_source = new_source
            for listener in self.transition_listeners:
                try:
                    listener(old_source, new_source)
                except Exception as e:
                    logger.error(f"Error in source transition listener: {e}")

    async def get_market_snapshot(self, symbol: str) -> MarketSnapshot:
        symbol = symbol.upper()
        old_source = self.active_source
        from app.config import get_settings
        from app.services.market_hours import is_market_open
        settings = get_settings()

        market_open_flag = is_market_open()
        sim_allowed = settings.VCC_SIMULATION_MODE

        # Failover Loop across configured providers
        for provider in self.providers:
            pname = provider.provider_name()
            
            # Skip SIMULATED provider in automatic production loop if simulation mode is disabled
            if pname == "SIMULATED" and not sim_allowed:
                continue

            health = self.health_registry.get(pname, ProviderHealth(pname))

            if not provider.is_available():
                health.record_failure("Provider reported unavailable")
                continue

            try:
                snapshot = await provider.get_market_snapshot(symbol)
                if snapshot is not None and snapshot.spot and snapshot.spot.spot_price > 0:
                    # Evaluate Data Quality
                    quality, reasons = data_quality_evaluator.evaluate(snapshot)
                    snapshot.quality = quality
                    snapshot.metadata.quality = quality

                    health.record_success()
                    self._notify_transition(old_source, pname)
                    return snapshot

                health.record_failure("Returned empty or invalid snapshot")
            except Exception as e:
                health.record_failure(str(e))
                continue

        # If explicit simulation mode is enabled, use Simulator
        if sim_allowed:
            sim_provider = SimulatorProviderAdapter()
            snapshot = await sim_provider.get_market_snapshot(symbol)
            quality, reasons = data_quality_evaluator.evaluate(snapshot)
            snapshot.quality = quality
            snapshot.metadata.quality = quality
            self._notify_transition(old_source, "SIMULATED")
            return snapshot

        # Market Closed or Live Providers Failed: Try PERSISTED_DB fallback
        db_fallback = DatabaseFallbackProviderAdapter()
        if db_fallback.is_available():
            snapshot = await db_fallback.get_market_snapshot(symbol)
            if snapshot is not None:
                snapshot.quality = DataQuality.DEGRADED
                snapshot.metadata.quality = DataQuality.DEGRADED
                self._notify_transition(old_source, "PERSISTED_DB")
                return snapshot

        # Emergency Fallback Snapshot: Marked DATA_UNAVAILABLE (No synthetic ticks generated)
        from app.services.market_hours import IST
        from app.domain.contracts import DataStatus, SpotData, OptionChainSnapshot, DataSourceMetadata

        now_dt = datetime.now(IST)
        now_iso = now_dt.isoformat()
        now_str = now_dt.strftime("%H:%M:%S")
        
        fallback_spot = SpotData(symbol=symbol, spot_price=0.0, timestamp=now_str)
        fallback_chain = OptionChainSnapshot(symbol=symbol, expiry="N/A", spot_price=0.0, atm_strike=0.0, strikes=[], timestamp=now_str, validation_status="NO_VALID_DATA: Fallback snapshot")
        fallback_metadata = DataSourceMetadata(
            symbol=symbol,
            exchange="NSE",
            provider="UNAVAILABLE",
            source_name="UNAVAILABLE",
            provider_timestamp=now_iso,
            received_timestamp=now_iso,
            market_timestamp=now_iso,
            spot_timestamp=now_iso,
            option_timestamp=now_iso,
            spot_data_age_sec=86400.0,
            option_data_age_sec=86400.0,
            data_age_seconds=86400.0,
            data_status=DataStatus.MISSING,
            is_real_data=False,
            is_stale=True,
            completeness_status="MISSING",
            validation_status="UNAVAILABLE",
            quality=DataQuality.INVALID
        )
        
        snap = MarketSnapshot(symbol=symbol, timestamp=now_iso, spot=fallback_spot, expiry="N/A", option_chain=fallback_chain, metadata=fallback_metadata, quality=DataQuality.INVALID, vix=0.0)
        self._notify_transition(old_source, "UNAVAILABLE")
        return snap

    def get_system_health(self) -> Dict[str, Any]:
        from app.services.market_hours import is_market_open
        from app.config import get_settings
        settings = get_settings()
        return {
            "active_provider": self.active_source,
            "market_open": is_market_open(),
            "simulation_mode": settings.VCC_SIMULATION_MODE,
            "providers": {
                name: {
                    "is_healthy": h.is_healthy,
                    "consecutive_failures": h.consecutive_failures,
                    "total_requests": h.total_requests,
                    "successful_requests": h.successful_requests,
                    "last_success_time": h.last_success_time,
                    "last_error": h.last_error
                } for name, h in self.health_registry.items()
            }
        }


# Singleton Instance for system ingestion
data_source_manager = DataSourceManager()
