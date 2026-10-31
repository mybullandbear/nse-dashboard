"""
Historical Context Provider Interface for VCC Analytics Engines.
Allows feeding historical snapshot context into analytical engines without
direct database coupling.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from app.db.database import SessionLocal
from app.db.models import DailyMarketSnapshotModel


class HistoricalContextProvider(ABC):

    @abstractmethod
    def get_snapshots_today(self, symbol: str, trade_date: str) -> List[Any]:
        """Return all intraday snapshots recorded for the symbol today."""
        pass

    @abstractmethod
    def get_snapshot_at_offset(self, symbol: str, now_dt: datetime, offset_sec: float) -> Optional[Any]:
        """Return the recorded snapshot closest to now - offset_sec."""
        pass


class DBHistoricalContextProvider(HistoricalContextProvider):
    """
    Standard Database-backed Historical Context Provider.
    """

    def get_snapshots_today(self, symbol: str, trade_date: str) -> List[Any]:
        db = SessionLocal()
        try:
            snaps = (
                db.query(DailyMarketSnapshotModel)
                .filter(
                    DailyMarketSnapshotModel.trade_date == trade_date,
                    DailyMarketSnapshotModel.symbol == symbol.upper(),
                    DailyMarketSnapshotModel.data_source != "SIMULATED"
                )
                .order_by(DailyMarketSnapshotModel.timestamp.asc())
                .all()
            )
            return snaps
        except Exception:
            return []
        finally:
            db.close()

    def get_snapshot_at_offset(self, symbol: str, now_dt: datetime, offset_sec: float) -> Optional[Any]:
        trade_date = now_dt.strftime("%Y-%m-%d")
        snaps = self.get_snapshots_today(symbol, trade_date)
        if not snaps:
            return None

        target_dt = now_dt if offset_sec == 0 else now_dt - timedelta(seconds=offset_sec)
        best_snap = None
        min_diff = float("inf")

        for sn in snaps:
            try:
                sn_dt = datetime.fromisoformat(str(sn.timestamp)) if isinstance(sn.timestamp, str) else sn.timestamp
                if sn_dt.tzinfo is None:
                    sn_dt = sn_dt.replace(tzinfo=now_dt.tzinfo or IST)
                # Anti-lookahead guard: future snapshot cannot influence current calculation
                if sn_dt > now_dt:
                    continue
                diff = abs((sn_dt - target_dt).total_seconds())
                if diff < min_diff:
                    min_diff = diff
                    best_snap = sn
            except Exception:
                continue

        return best_snap


class InMemoryHistoricalContextProvider(HistoricalContextProvider):
    """
    In-Memory Historical Context Provider for replay, testing, and decoupled execution.
    """

    def __init__(self, snapshots: Optional[List[Any]] = None):
        self._snapshots = snapshots or []

    def set_snapshots(self, snapshots: List[Any]):
        self._snapshots = snapshots

    def get_snapshots_today(self, symbol: str, trade_date: str) -> List[Any]:
        return [
            sn for sn in self._snapshots
            if getattr(sn, "symbol", symbol).upper() == symbol.upper()
        ]

    def get_snapshot_at_offset(self, symbol: str, now_dt: datetime, offset_sec: float) -> Optional[Any]:
        snaps = self.get_snapshots_today(symbol, now_dt.strftime("%Y-%m-%d"))
        if not snaps:
            return None
        return snaps[-1]


default_context_provider = DBHistoricalContextProvider()
