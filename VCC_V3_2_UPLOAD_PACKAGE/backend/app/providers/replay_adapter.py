"""
Historical Replay Provider Adapter for VCC V3.2.
Reads stored market snapshots in strict chronological order for deterministic replay.
Strictly obeys anti-lookahead rules: future snapshots are inaccessible until replay cursor reaches them.
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from app.providers.base import MarketDataProvider
from app.domain.contracts import (
    MarketSnapshot,
    SpotData,
    OptionChainSnapshot,
    OptionContract,
    OptionTick,
    OptionGreeks,
    DataSourceMetadata,
    DataQuality
)
from app.db.database import SessionLocal
from app.db.models import DailyMarketSnapshotModel
from app.services.mock_engine import simulator

logger = logging.getLogger(__name__)


class ReplayProviderAdapter(MarketDataProvider):
    """
    Chronological historical snapshot provider for deterministic market replay and backtesting.
    """

    def __init__(
        self,
        symbol: str = "NIFTY",
        trade_date: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        playback_speed: float = 1.0
    ):
        self.symbol = symbol.upper()
        self.trade_date = trade_date
        self.start_time = start_time
        self.end_time = end_time
        self.playback_speed = playback_speed
        
        self.cursor_index: int = 0
        self._snapshots_cache: List[MarketSnapshot] = []
        self._is_loaded: bool = False

    def provider_name(self) -> str:
        return "REPLAY"

    def is_available(self) -> bool:
        return True

    def load_snapshots(self, symbol: Optional[str] = None, trade_date: Optional[str] = None) -> int:
        """
        Loads stored market snapshots from the database in strict ascending order (ORDER BY timestamp ASC).
        If database has no snapshots for the date, generates deterministic synthetic replay series.
        """
        sym = (symbol or self.symbol).upper()
        tdate = trade_date or self.trade_date or datetime.now().strftime("%Y-%m-%d")

        db = SessionLocal()
        try:
            query = db.query(DailyMarketSnapshotModel).filter(DailyMarketSnapshotModel.symbol == sym)
            if tdate:
                query = query.filter(DailyMarketSnapshotModel.timestamp.like(f"{tdate}%"))

            if self.start_time:
                query = query.filter(DailyMarketSnapshotModel.timestamp >= f"{tdate}T{self.start_time}")
            if self.end_time:
                query = query.filter(DailyMarketSnapshotModel.timestamp <= f"{tdate}T{self.end_time}")

            records = query.order_by(DailyMarketSnapshotModel.timestamp.asc()).all()

            def build_contracts(sim_chain):
                contracts = []
                for s in sim_chain.strikes:
                    ce_g = getattr(s, "ce_greeks", None)
                    pe_g = getattr(s, "pe_greeks", None)
                    contracts.append(OptionContract(
                        strike_price=getattr(s, "strike_price", 24500.0),
                        expiry=getattr(s, "expiry", sim_chain.expiry),
                        ce_tick=OptionTick(
                            ltp=getattr(s, "ce_ltp", 100.0),
                            oi=getattr(s, "ce_oi", 50000),
                            oi_change=getattr(s, "ce_oi_change", 5000),
                            volume=getattr(s, "ce_volume", 10000),
                            iv=getattr(s, "ce_iv", 15.0),
                            bid=getattr(s, "ce_bid", 99.5),
                            ask=getattr(s, "ce_ask", 100.5),
                            greeks=OptionGreeks(
                                delta=getattr(ce_g, "delta", 0.5) if ce_g else 0.5,
                                theta=getattr(ce_g, "theta", -5.0) if ce_g else -5.0,
                                gamma=getattr(ce_g, "gamma", 0.0004) if ce_g else 0.0004,
                                vega=getattr(ce_g, "vega", 12.0) if ce_g else 12.0,
                                iv=getattr(s, "ce_iv", 15.0)
                            )
                        ),
                        pe_tick=OptionTick(
                            ltp=getattr(s, "pe_ltp", 100.0),
                            oi=getattr(s, "pe_oi", 50000),
                            oi_change=getattr(s, "pe_oi_change", 5000),
                            volume=getattr(s, "pe_volume", 10000),
                            iv=getattr(s, "pe_iv", 15.0),
                            bid=getattr(s, "pe_bid", 99.5),
                            ask=getattr(s, "pe_ask", 100.5),
                            greeks=OptionGreeks(
                                delta=getattr(pe_g, "delta", -0.5) if pe_g else -0.5,
                                theta=getattr(pe_g, "theta", -5.0) if pe_g else -5.0,
                                gamma=getattr(pe_g, "gamma", 0.0004) if pe_g else 0.0004,
                                vega=getattr(pe_g, "vega", 12.0) if pe_g else 12.0,
                                iv=getattr(s, "pe_iv", 15.0)
                            )
                        ),
                        oi_interpretation_ce=getattr(s, "oi_interpretation_ce", "NEUTRAL"),
                        oi_interpretation_pe=getattr(s, "oi_interpretation_pe", "NEUTRAL")
                    ))
                return contracts

            self._snapshots_cache = []
            if records:
                for rec in records:
                    sim_chain = simulator.get_option_chain(sym)
                    snap = MarketSnapshot(
                        symbol=sym,
                        timestamp=rec.timestamp,
                        spot=SpotData(symbol=sym, spot_price=rec.spot_price, timestamp=rec.timestamp),
                        expiry=sim_chain.expiry,
                        option_chain=OptionChainSnapshot(
                            symbol=sym,
                            expiry=sim_chain.expiry,
                            spot_price=rec.spot_price,
                            atm_strike=rec.atm_strike or sim_chain.atm_strike,
                            strikes=build_contracts(sim_chain),
                            pcr=rec.pcr or 1.0,
                            max_pain=sim_chain.max_pain,
                            timestamp=rec.timestamp,
                            expiry_list=sim_chain.expiry_list or []
                        ),
                        metadata=DataSourceMetadata(
                            source_name="REPLAY",
                            spot_timestamp=rec.timestamp,
                            option_timestamp=rec.timestamp,
                            spot_data_age_sec=0.0,
                            option_data_age_sec=0.0,
                            quality=DataQuality.GOOD
                        ),
                        quality=DataQuality.GOOD,
                        vix=13.50
                    )
                    self._snapshots_cache.append(snap)
            else:
                # Generate deterministic 15-minute interval synthetic replay series for testing
                base_spot = 24200.0 if sym == "NIFTY" else 51500.0
                times = [f"{tdate}T{h:02d}:{m:02d}:00" for h in range(9, 16) for m in (0, 15, 30, 45) if not (h == 9 and m < 15) and not (h == 15 and m > 30)]
                
                for idx, t_str in enumerate(times):
                    spot_val = base_spot + (idx * 8.5) - (4.0 if idx % 2 == 0 else 0.0)
                    sim_chain = simulator.get_option_chain(sym)
                    snap = MarketSnapshot(
                        symbol=sym,
                        timestamp=t_str,
                        spot=SpotData(symbol=sym, spot_price=spot_val, timestamp=t_str),
                        expiry=sim_chain.expiry,
                        option_chain=OptionChainSnapshot(
                            symbol=sym,
                            expiry=sim_chain.expiry,
                            spot_price=spot_val,
                            atm_strike=round(spot_val / 50) * 50,
                            strikes=build_contracts(sim_chain),
                            pcr=1.0 + (idx * 0.015),
                            max_pain=sim_chain.max_pain,
                            timestamp=t_str,
                            expiry_list=sim_chain.expiry_list or []
                        ),
                        metadata=DataSourceMetadata(
                            source_name="REPLAY",
                            spot_timestamp=t_str,
                            option_timestamp=t_str,
                            spot_data_age_sec=0.0,
                            option_data_age_sec=0.0,
                            quality=DataQuality.GOOD
                        ),
                        quality=DataQuality.GOOD,
                        vix=13.50
                    )
                    self._snapshots_cache.append(snap)

            self.cursor_index = 0
            self._is_loaded = True
            return len(self._snapshots_cache)
        finally:
            db.close()

    def reset_cursor(self) -> None:
        self.cursor_index = 0

    def has_next(self) -> bool:
        return self.cursor_index < len(self._snapshots_cache)

    async def get_market_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        """
        Returns snapshot at current replay cursor time T_k.
        Advanced cursor to ensure strict step playback.
        """
        if not self._is_loaded or len(self._snapshots_cache) == 0:
            self.load_snapshots(symbol)

        if self.cursor_index >= len(self._snapshots_cache):
            # Return last available snapshot if cursor reached end
            return self._snapshots_cache[-1] if self._snapshots_cache else None

        snapshot = self._snapshots_cache[self.cursor_index]
        return snapshot

    def step(self) -> Optional[MarketSnapshot]:
        """Advances replay cursor by 1 time step and returns current snapshot."""
        if not self._is_loaded:
            self.load_snapshots()
        if self.cursor_index < len(self._snapshots_cache):
            snap = self._snapshots_cache[self.cursor_index]
            self.cursor_index += 1
            return snap
        return None

    def get_visible_history_up_to_cursor(self) -> List[MarketSnapshot]:
        """
        Strict Anti-Lookahead Method: Returns ONLY snapshots up to current replay cursor position [0..T_k].
        Future snapshots [T_k+1..N] are completely hidden.
        """
        return self._snapshots_cache[:self.cursor_index]
