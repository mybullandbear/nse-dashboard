"""
Market Repository for VCC V3.2 Persistence Layer.
Manages database persistence and retrieval of raw/normalized DailyMarketSnapshot records.
Decouples domain logic from SQLAlchemy.
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models import DailyMarketSnapshotModel

logger = logging.getLogger(__name__)


class MarketRepository:

    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    def save_snapshot(self, snapshot_dict: Dict[str, Any]) -> int:
        db: Session = self.session_factory()
        try:
            valid_cols = {c.name for c in DailyMarketSnapshotModel.__table__.columns}
            filtered_data = {k: v for k, v in snapshot_dict.items() if k in valid_cols}
            record = DailyMarketSnapshotModel(**filtered_data)
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id
        except Exception:
            db.rollback()
            return 0
        finally:
            db.close()

    def get_today_snapshots(self, symbol: str, trade_date: str) -> List[Dict[str, Any]]:
        db: Session = self.session_factory()
        try:
            recs = (
                db.query(DailyMarketSnapshotModel)
                .filter(
                    DailyMarketSnapshotModel.symbol == symbol.upper(),
                    DailyMarketSnapshotModel.trade_date == trade_date
                )
                .order_by(DailyMarketSnapshotModel.timestamp.asc())
                .all()
            )
            return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in recs]
        finally:
            db.close()

    def get_snapshots_today(self, symbol: str, trade_date: str) -> List[Dict[str, Any]]:
        return self.get_today_snapshots(symbol, trade_date)


    def save_snapshot_throttled(
        self,
        symbol: str,
        trade_date: str,
        now_iso: str,
        snapshot: Any,
        scoring_res: Dict[str, Any],
        min_interval_sec: float = 30.0
    ) -> int:
        db: Session = self.session_factory()
        try:
            latest = (
                db.query(DailyMarketSnapshotModel)
                .filter(
                    DailyMarketSnapshotModel.symbol == symbol.upper(),
                    DailyMarketSnapshotModel.trade_date == trade_date
                )
                .order_by(DailyMarketSnapshotModel.timestamp.desc())
                .first()
            )
            if latest and hasattr(latest, 'timestamp') and latest.timestamp:
                try:
                    last_dt = datetime.fromisoformat(str(latest.timestamp))
                    now_dt = datetime.fromisoformat(now_iso)
                    if (now_dt - last_dt).total_seconds() < min_interval_sec:
                        return 0
                except Exception:
                    pass

            chain = getattr(snapshot, 'option_chain', None)
            spot_val = snapshot.spot.spot_price if getattr(snapshot, 'spot', None) else 0.0
            def _val(tick, field):
                if not tick:
                    return 0.0
                v = getattr(tick, field, 0)
                return float(v) if v is not None else 0.0

            tot_ce = sum(_val(getattr(s, 'ce_tick', None), 'oi') for s in chain.strikes) if chain and chain.strikes else 0
            tot_pe = sum(_val(getattr(s, 'pe_tick', None), 'oi') for s in chain.strikes) if chain and chain.strikes else 0
            tot_ce_chg = sum(_val(getattr(s, 'ce_tick', None), 'oi_change') for s in chain.strikes) if chain and chain.strikes else 0
            tot_pe_chg = sum(_val(getattr(s, 'pe_tick', None), 'oi_change') for s in chain.strikes) if chain and chain.strikes else 0

            source_name = "SIMULATED"
            if hasattr(snapshot, "metadata") and snapshot.metadata:
                source_name = getattr(snapshot.metadata, "source_name", getattr(snapshot.metadata, "provider", "SIMULATED"))

            record = DailyMarketSnapshotModel(
                symbol=symbol.upper(),
                trade_date=trade_date,
                timestamp=now_iso,
                spot_price=spot_val,
                atm_strike=chain.atm_strike if chain else 0,
                pcr=chain.pcr if chain else 1.0,
                total_ce_oi=tot_ce,
                total_pe_oi=tot_pe,
                total_ce_chg=tot_ce_chg,
                total_pe_chg=tot_pe_chg,
                data_source=source_name
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id
        except Exception as e:
            logger.exception("save_snapshot_throttled exception: %s", e)
            db.rollback()
            return 0
        finally:
            db.close()


market_repository = MarketRepository()

