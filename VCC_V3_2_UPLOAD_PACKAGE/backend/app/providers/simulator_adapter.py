"""
Simulator Provider Adapter.
Wraps LiveMarketSimulator to produce canonical MarketSnapshot instances.
"""
from typing import Optional
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
from app.services.mock_engine import simulator


class SimulatorProviderAdapter(MarketDataProvider):

    def provider_name(self) -> str:
        return "SIMULATED"

    def is_available(self) -> bool:
        return True

    async def get_market_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        symbol = symbol.upper()
        raw_chain = simulator.get_option_chain(symbol)
        from app.services.market_hours import IST
        from app.domain.contracts import DataStatus

        now_dt = datetime.now(IST)
        now_iso = now_dt.isoformat()
        now_str = now_dt.strftime("%H:%M:%S")

        spot_data = SpotData(
            symbol=symbol,
            spot_price=raw_chain.spot_price,
            change=0.0,
            pct_change=0.0,
            open_price=round(raw_chain.spot_price * 0.998, 2),
            day_high=round(raw_chain.spot_price * 1.004, 2),
            day_low=round(raw_chain.spot_price * 0.996, 2),
            prev_close=raw_chain.spot_price,
            timestamp=now_str
        )

        contracts = []
        for s in raw_chain.strikes:
            ce_g = s.ce_greeks
            pe_g = s.pe_greeks
            contracts.append(OptionContract(
                strike_price=s.strike_price,
                expiry=s.expiry,
                ce_tick=OptionTick(
                    ltp=s.ce_ltp,
                    oi=s.ce_oi,
                    oi_change=s.ce_oi_change,
                    volume=s.ce_volume,
                    iv=s.ce_iv,
                    bid=s.ce_bid,
                    ask=s.ce_ask,
                    greeks=OptionGreeks(
                        delta=ce_g.delta if ce_g else 0.0,
                        theta=ce_g.theta if ce_g else 0.0,
                        gamma=ce_g.gamma if ce_g else 0.0004,
                        vega=ce_g.vega if ce_g else 12.0,
                        iv=s.ce_iv
                    )
                ),
                pe_tick=OptionTick(
                    ltp=s.pe_ltp,
                    oi=s.pe_oi,
                    oi_change=s.pe_oi_change,
                    volume=s.pe_volume,
                    iv=s.pe_iv,
                    bid=s.pe_bid,
                    ask=s.pe_ask,
                    greeks=OptionGreeks(
                        delta=pe_g.delta if pe_g else 0.0,
                        theta=pe_g.theta if pe_g else 0.0,
                        gamma=pe_g.gamma if pe_g else 0.0004,
                        vega=pe_g.vega if pe_g else 12.0,
                        iv=s.pe_iv
                    )
                ),
                oi_interpretation_ce=s.oi_interpretation_ce or "NEUTRAL",
                oi_interpretation_pe=s.oi_interpretation_pe or "NEUTRAL"
            ))

        chain_snap = OptionChainSnapshot(
            symbol=symbol,
            expiry=raw_chain.expiry,
            spot_price=raw_chain.spot_price,
            atm_strike=raw_chain.atm_strike,
            strikes=contracts,
            pcr=raw_chain.pcr,
            max_pain=raw_chain.max_pain,
            timestamp=now_str,
            expiry_list=raw_chain.expiry_list or [raw_chain.expiry]
        )

        metadata = DataSourceMetadata(
            symbol=symbol,
            exchange="NSE",
            provider="SIMULATED",
            source_name="SIMULATED",
            provider_timestamp=now_iso,
            received_timestamp=now_iso,
            market_timestamp=now_iso,
            spot_timestamp=now_iso,
            option_timestamp=now_iso,
            spot_data_age_sec=0.0,
            option_data_age_sec=0.0,
            data_age_seconds=0.0,
            data_status=DataStatus.SYNTHETIC,
            is_real_data=False,
            is_stale=True,
            completeness_status="SYNTHETIC",
            validation_status="SYNTHETIC_DATA_PROHIBITED",
            quality=DataQuality.INVALID
        )

        snap = MarketSnapshot(
            symbol=symbol,
            timestamp=now_iso,
            spot=spot_data,
            expiry=raw_chain.expiry,
            option_chain=chain_snap,
            metadata=metadata,
            quality=DataQuality.INVALID,
            vix=13.45
        )
        return snap
