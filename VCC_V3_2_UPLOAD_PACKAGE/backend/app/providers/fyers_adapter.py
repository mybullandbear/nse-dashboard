"""
Fyers Broker Data Provider Adapter.
Wraps fyers_service to produce canonical MarketSnapshot instances.
"""
from typing import Optional
from datetime import datetime
import logging

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
from app.services.fyers_fetcher import fyers_service
from app.services.option_chain import parse_option_chain, calculate_atm_strike, validate_option_chain

logger = logging.getLogger(__name__)


class FyersProviderAdapter(MarketDataProvider):

    def provider_name(self) -> str:
        return "FYERS_LIVE"

    def is_available(self) -> bool:
        return fyers_service.is_configured()

    async def get_market_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        if not self.is_available():
            return None

        symbol = symbol.upper()
        
        # 1. Fetch live quotes for spot data
        fyers_symbol_map = {
            "NIFTY": "NSE:NIFTY50-INDEX",
            "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
            "FINNIFTY": "NSE:FINNIFTY-INDEX",
            "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX"
        }
        fy_sym = fyers_symbol_map.get(symbol, f"NSE:{symbol}-INDEX")
        
        qres = fyers_service.get_quotes([fy_sym])
        spot_price = 0.0
        change = 0.0
        pct_change = 0.0
        day_high = 0.0
        day_low = 0.0
        open_price = 0.0
        prev_close = 0.0

        if qres and qres.get("s") == "ok" and qres.get("d"):
            for item in qres["d"]:
                if item.get("n") == fy_sym or item.get("v", {}).get("symbol") == fy_sym:
                    v = item.get("v", {})
                    spot_price = float(v.get("lp", 0.0))
                    change = float(v.get("ch", 0.0))
                    pct_change = float(v.get("chp", 0.0))
                    day_high = float(v.get("high_price", 0.0))
                    day_low = float(v.get("low_price", 0.0))
                    open_price = float(v.get("open_price", 0.0))
                    prev_close = float(v.get("prev_close_price", 0.0))
                    break

        # 2. Fetch raw option chain
        raw_chain = fyers_service.get_option_chain(symbol)
        if not raw_chain:
            logger.warning(f"Fyers raw option chain returned None for {symbol}")
            return None

        from app.services.market_hours import IST
        from app.domain.contracts import DataStatus

        now_dt = datetime.now(IST)
        now_iso = now_dt.isoformat()
        now_str = now_dt.strftime("%H:%M:%S")

        parsed_chain = parse_option_chain(raw_chain, symbol=symbol)
        if not parsed_chain:
            logger.warning(f"Failed to parse FYERS option chain for {symbol}")
            return None

        if spot_price <= 0 and parsed_chain.spot_price > 0:
            spot_price = parsed_chain.spot_price

        # Extract available strikes from parsed chain
        available_strikes = [s.strike_price for s in parsed_chain.strikes] if parsed_chain.strikes else []

        # Calculate Authoritative ATM Strike & Telemetry
        atm_strike, atm_source, strike_step, strike_step_source = calculate_atm_strike(
            spot_price=spot_price,
            available_strikes=available_strikes,
            symbol=symbol
        )

        # Map OptionStrikeData -> OptionContract for canonical OptionChainSnapshot
        converted_strikes = []
        for s in parsed_chain.strikes:
            ce_greeks_obj = getattr(s, 'ce_greeks', None)
            pe_greeks_obj = getattr(s, 'pe_greeks', None)
            
            ce_greeks = OptionGreeks(
                delta=getattr(ce_greeks_obj, 'delta', 0.0) if ce_greeks_obj else 0.0,
                theta=getattr(ce_greeks_obj, 'theta', 0.0) if ce_greeks_obj else 0.0,
                gamma=getattr(ce_greeks_obj, 'gamma', 0.0) if ce_greeks_obj else 0.0,
                vega=getattr(ce_greeks_obj, 'vega', 0.0) if ce_greeks_obj else 0.0,
                iv=getattr(s, 'ce_iv', 0.0)
            )
            pe_greeks = OptionGreeks(
                delta=getattr(pe_greeks_obj, 'delta', 0.0) if pe_greeks_obj else 0.0,
                theta=getattr(pe_greeks_obj, 'theta', 0.0) if pe_greeks_obj else 0.0,
                gamma=getattr(pe_greeks_obj, 'gamma', 0.0) if pe_greeks_obj else 0.0,
                vega=getattr(pe_greeks_obj, 'vega', 0.0) if pe_greeks_obj else 0.0,
                iv=getattr(s, 'pe_iv', 0.0)
            )
            ce_tick = OptionTick(
                ltp=getattr(s, 'ce_ltp', 0.0),
                change=getattr(s, 'ce_change', 0.0),
                pct_change=getattr(s, 'ce_pct_change', 0.0),
                oi=getattr(s, 'ce_oi', 0),
                oi_change=getattr(s, 'ce_oi_change', 0),
                volume=getattr(s, 'ce_volume', 0),
                iv=getattr(s, 'ce_iv', 0.0),
                bid=getattr(s, 'ce_bid', 0.0),
                ask=getattr(s, 'ce_ask', 0.0),
                greeks=ce_greeks
            )
            pe_tick = OptionTick(
                ltp=getattr(s, 'pe_ltp', 0.0),
                change=getattr(s, 'pe_change', 0.0),
                pct_change=getattr(s, 'pe_pct_change', 0.0),
                oi=getattr(s, 'pe_oi', 0),
                oi_change=getattr(s, 'pe_oi_change', 0),
                volume=getattr(s, 'pe_volume', 0),
                iv=getattr(s, 'pe_iv', 0.0),
                bid=getattr(s, 'pe_bid', 0.0),
                ask=getattr(s, 'pe_ask', 0.0),
                greeks=pe_greeks
            )
            contract = OptionContract(
                strike_price=s.strike_price,
                expiry=getattr(s, 'expiry', parsed_chain.expiry),
                ce_tick=ce_tick,
                pe_tick=pe_tick,
                oi_interpretation_ce=getattr(s, 'oi_interpretation_ce', 'NEUTRAL'),
                oi_interpretation_pe=getattr(s, 'oi_interpretation_pe', 'NEUTRAL')
            )
            converted_strikes.append(contract)

        is_valid_chain, val_reason = validate_option_chain(spot_price, now_str, converted_strikes)
        validation_status = "VALID" if is_valid_chain else val_reason

        opt_chain_snap = OptionChainSnapshot(
            symbol=symbol,
            expiry=parsed_chain.expiry,
            spot_price=spot_price,
            atm_strike=atm_strike,
            strikes=converted_strikes,
            pcr=parsed_chain.pcr,
            max_pain=parsed_chain.max_pain,
            timestamp=now_str,
            expiry_list=parsed_chain.expiry_list or [parsed_chain.expiry],
            spot_timestamp=now_str,
            atm_source=atm_source,
            strike_step=strike_step,
            strike_step_source=strike_step_source,
            validation_status=validation_status
        )

        spot_data = SpotData(
            symbol=symbol,
            spot_price=spot_price,
            pct_change=pct_change,
            day_high=day_high,
            day_low=day_low,
            open_price=open_price,
            prev_close=prev_close,
            timestamp=now_str
        )

        metadata = DataSourceMetadata(
            symbol=symbol,
            exchange="NSE",
            provider="FYERS_LIVE",
            source_name="FYERS_LIVE",
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
            quality=DataQuality.GOOD,
            last_error=fyers_service.last_error
        )

        snap = MarketSnapshot(
            symbol=symbol,
            timestamp=now_iso,
            spot=spot_data,
            expiry=parsed_chain.expiry,
            option_chain=opt_chain_snap,
            metadata=metadata,
            quality=DataQuality.GOOD,
            vix=0.0
        )
        return snap
