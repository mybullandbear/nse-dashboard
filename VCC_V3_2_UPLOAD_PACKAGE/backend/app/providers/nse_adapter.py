"""
NSE India Scraper Provider Adapter.
Wraps nse scraper to produce canonical MarketSnapshot instances.
"""
from typing import Optional
import asyncio
from datetime import datetime
from app.providers.base import MarketDataProvider
from app.domain.contracts import (
    MarketSnapshot,
    SpotData,
    DataSourceMetadata,
    DataQuality
)
from app.services.nse_fetcher import nse
from app.services.option_chain import parse_option_chain


class NSEProviderAdapter(MarketDataProvider):

    def provider_name(self) -> str:
        return "NSE_LIVE"

    def is_available(self) -> bool:
        return True

    async def get_market_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        symbol = symbol.upper()
        try:
            raw_chain = await asyncio.wait_for(nse.get_option_chain(symbol), timeout=2.5)
            if not raw_chain:
                return None

            from app.services.market_hours import IST
            from app.domain.contracts import DataStatus

            now_dt = datetime.now(IST)
            now_iso = now_dt.isoformat()
            now_str = now_dt.strftime("%H:%M:%S")

            parsed_chain = parse_option_chain(raw_chain, symbol)
            if not parsed_chain:
                return None

            spot_data = SpotData(
                symbol=symbol,
                spot_price=parsed_chain.spot_price,
                change=0.0,
                pct_change=0.0,
                timestamp=now_str
            )

            metadata = DataSourceMetadata(
                symbol=symbol,
                exchange="NSE",
                provider="NSE_LIVE",
                source_name="NSE_LIVE",
                provider_timestamp=now_iso,
                received_timestamp=now_iso,
                market_timestamp=now_iso,
                spot_timestamp=now_iso,
                option_timestamp=now_iso,
                spot_data_age_sec=0.0,
                option_data_age_sec=0.0,
                data_age_seconds=0.0,
                data_status=DataStatus.REAL_LIVE,
                is_real_data=True,
                is_stale=False,
                completeness_status="COMPLETE",
                validation_status="REAL_DATA_LIVE",
                quality=DataQuality.GOOD
            )

            snap = MarketSnapshot(
                symbol=symbol,
                timestamp=now_iso,
                spot=spot_data,
                expiry=parsed_chain.expiry,
                option_chain=parsed_chain,
                metadata=metadata,
                quality=DataQuality.GOOD,
                vix=0.0
            )
            return snap
        except Exception:
            return None
