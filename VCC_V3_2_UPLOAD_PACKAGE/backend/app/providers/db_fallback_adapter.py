"""
Database Fallback Provider Adapter.
Pulls the latest persisted market snapshot from SQLite database when live feeds are unavailable.
Preserves original market timestamps and does NOT inject synthetic option chains.
"""
import logging
from typing import Optional
from datetime import datetime
from app.providers.base import MarketDataProvider
from app.domain.contracts import (
    MarketSnapshot,
    SpotData,
    OptionChainSnapshot,
    DataSourceMetadata,
    DataQuality,
    DataStatus
)
from app.db.database import SessionLocal
from app.db.models import DailyMarketSnapshotModel
from app.services.market_hours import IST

logger = logging.getLogger(__name__)


class DatabaseFallbackProviderAdapter(MarketDataProvider):

    def provider_name(self) -> str:
        return "PERSISTED_DB"

    def is_available(self) -> bool:
        db = SessionLocal()
        try:
            count = db.query(DailyMarketSnapshotModel).count()
            return count > 0
        except Exception:
            return False
        finally:
            db.close()

    async def get_market_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        symbol = symbol.upper()
        db = SessionLocal()
        try:
            record = (
                db.query(DailyMarketSnapshotModel)
                .filter(DailyMarketSnapshotModel.symbol == symbol)
                .order_by(DailyMarketSnapshotModel.id.desc())
                .first()
            )
            if not record:
                return None

            now_dt = datetime.now(IST)
            if record.timestamp:
                record_timestamp_str = record.timestamp
            elif hasattr(record, 'created_at') and record.created_at:
                record_timestamp_str = record.created_at.isoformat()
            else:
                record_timestamp_str = now_dt.isoformat()

            # Calculate true age relative to current IST time
            data_age = 0.0
            try:
                rec_dt = datetime.fromisoformat(record_timestamp_str.replace("Z", "+00:00"))
                if rec_dt.tzinfo is None:
                    rec_dt = rec_dt.replace(tzinfo=IST)
                data_age = max(0.0, (now_dt - rec_dt).total_seconds())
            except Exception:
                data_age = 3600.0

            spot_data = SpotData(
                symbol=symbol,
                spot_price=record.spot_price,
                timestamp=record_timestamp_str
            )

            # Do NOT generate synthetic option chains from simulator!
            # DB fallback snapshot preserves summary metrics with empty strike matrix.
            chain_snap = OptionChainSnapshot(
                symbol=symbol,
                expiry="",
                spot_price=record.spot_price,
                atm_strike=record.atm_strike or 0.0,
                strikes=[],
                pcr=record.pcr or 1.0,
                max_pain=record.max_pain or 0.0,
                timestamp=record_timestamp_str,
                expiry_list=[]
            )

            metadata = DataSourceMetadata(
                symbol=symbol,
                exchange="NSE",
                provider="PERSISTED_DB",
                source_name="PERSISTED_DB",
                provider_timestamp=record_timestamp_str,
                received_timestamp=now_dt.isoformat(),
                market_timestamp=record_timestamp_str,
                spot_timestamp=record_timestamp_str,
                option_timestamp=record_timestamp_str,
                spot_data_age_sec=round(data_age, 1),
                option_data_age_sec=round(data_age, 1),
                data_age_seconds=round(data_age, 1),
                data_status=DataStatus.REAL_STALE if data_age > 30.0 else DataStatus.REAL_RECENT,
                is_real_data=True,
                is_stale=data_age > 30.0,
                completeness_status="EMPTY_STRIKES",
                validation_status="STALE_HISTORICAL_RECORD",
                quality=DataQuality.INVALID
            )

            snap = MarketSnapshot(
                symbol=symbol,
                timestamp=record_timestamp_str,
                spot=spot_data,
                expiry="",
                option_chain=chain_snap,
                metadata=metadata,
                quality=DataQuality.INVALID,
                vix=record.vix or 0.0
            )
            return snap
        except Exception as e:
            logger.exception("DatabaseFallbackProviderAdapter exception: %s", e)
            return None
        finally:
            db.close()
