"""
Layer 2: Shared Market State Store & Data Quality Gate
Single canonical in-memory repository for all market data and precomputed metrics.
"""
import time
import logging
from typing import Dict, Any, Optional
from app.market_data.instrument_state import IndexSymbol, NormalizedTick, OptionChainSnapshot

logger = logging.getLogger(__name__)

class DataQualityStatus:
    FRESH = "FRESH"
    STALE = "STALE"
    INCOMPLETE = "INCOMPLETE"
    UNAVAILABLE = "UNAVAILABLE"

class MarketStateStore:
    def __init__(self):
        # Ticks for indices
        self._index_ticks: Dict[str, NormalizedTick] = {}
        self._vix_tick: Optional[NormalizedTick] = None
        
        # Option Chain Snapshots by Symbol
        self._chains: Dict[str, OptionChainSnapshot] = {}
        
        # Precomputed Intelligence Outputs
        self._confluence_results: Dict[str, Dict[str, Any]] = {}
        self._directional_results: Dict[str, Dict[str, Any]] = {}
        self._oi_analytics_results: Dict[str, Dict[str, Any]] = {}
        self._strike_buildup_results: Dict[str, Dict[str, Any]] = {}
        self._price_vs_oi_results: Dict[str, Dict[str, Any]] = {}
        self._shonya_state: Dict[str, Any] = {
            "mode": "PAPER",
            "active": False,
            "daily_pnl": 0.0,
            "positions": [],
            "max_daily_loss": 5000.0,
            "target_daily_profit": 15000.0,
            "updated_at": time.time()
        }
        
        # Snapshot versioning
        self._global_version: int = 1
        self._last_state_change: float = time.time()

    def bump_version(self):
        self._global_version += 1
        self._last_state_change = time.time()

    # ─── Index Ticks ──────────────────────────────────────────────────────────
    def update_tick(self, tick: NormalizedTick):
        sym = tick.symbol
        self._index_ticks[sym] = tick
        self.bump_version()

    def get_tick(self, symbol: str) -> Optional[NormalizedTick]:
        return self._index_ticks.get(symbol)

    def get_all_indices(self) -> Dict[str, Any]:
        cards = []
        now = time.time()
        for sym, tick in self._index_ticks.items():
            age_sec = now - tick.timestamp
            status = DataQualityStatus.FRESH if age_sec < 10.0 else DataQualityStatus.STALE
            cards.append({
                "symbol": sym,
                "name": sym,
                "last": round(tick.ltp, 2),
                "change": round(tick.change, 2),
                "pChange": round(tick.pchange, 2),
                "high": round(tick.high, 2),
                "low": round(tick.low, 2),
                "open": round(tick.open, 2),
                "prev_close": round(tick.prev_close, 2),
                "status": status,
                "source": tick.source
            })
        
        vix_val = self._vix_tick.ltp if self._vix_tick else 13.5
        vix_change = self._vix_tick.change if self._vix_tick else 0.0
        vix_pchange = self._vix_tick.pchange if self._vix_tick else 0.0

        return {
            "indices": cards,
            "vix": {
                "last": round(vix_val, 2),
                "change": round(vix_change, 2),
                "pChange": round(vix_pchange, 2)
            },
            "version": self._global_version,
            "updated_at": self._last_state_change
        }

    # ─── Option Chain Snapshots ───────────────────────────────────────────────
    def update_chain(self, chain: OptionChainSnapshot):
        self._chains[chain.symbol] = chain
        self.bump_version()

    def get_chain(self, symbol: str) -> Optional[OptionChainSnapshot]:
        return self._chains.get(symbol)

    # ─── Intelligence Engines Cache ───────────────────────────────────────────
    def set_confluence(self, symbol: str, data: Dict[str, Any]):
        self._confluence_results[symbol] = data
        self.bump_version()

    def get_confluence(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._confluence_results.get(symbol)

    def set_directional(self, symbol: str, data: Dict[str, Any]):
        self._directional_results[symbol] = data
        self.bump_version()

    def get_directional(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._directional_results.get(symbol)

    def set_oi_analytics(self, symbol: str, data: Dict[str, Any]):
        self._oi_analytics_results[symbol] = data
        self.bump_version()

    def get_oi_analytics(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._oi_analytics_results.get(symbol)

    def set_strike_buildup(self, symbol: str, data: Dict[str, Any]):
        self._strike_buildup_results[symbol] = data
        self.bump_version()

    def get_strike_buildup(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._strike_buildup_results.get(symbol)

    def set_price_vs_oi(self, symbol: str, data: Dict[str, Any]):
        self._price_vs_oi_results[symbol] = data
        self.bump_version()

    def get_price_vs_oi(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._price_vs_oi_results.get(symbol)

    def get_shonya_state(self) -> Dict[str, Any]:
        return self._shonya_state

    def update_shonya_state(self, updates: Dict[str, Any]):
        self._shonya_state.update(updates)
        self._shonya_state["updated_at"] = time.time()
        self.bump_version()

    def get_full_snapshot(self, symbol: str = "NIFTY") -> Dict[str, Any]:
        """Single consolidated output for the frontend client."""
        return {
            "version": self._global_version,
            "timestamp": time.time(),
            "indices": self.get_all_indices(),
            "directional": self.get_directional(symbol) or {},
            "confluence": self.get_confluence(symbol) or {},
            "oi_analytics": self.get_oi_analytics(symbol) or {},
            "strike_buildup": self.get_strike_buildup(symbol) or {},
            "price_vs_oi": self.get_price_vs_oi(symbol) or {},
            "shonya": self.get_shonya_state()
        }

market_state = MarketStateStore()
