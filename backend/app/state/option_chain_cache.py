"""
Single-Flight Option Chain Acquisition & Deduplication Service
Ensures only ONE request per index is in-flight at any time.
"""
import asyncio
import time
import logging
from typing import Optional, Dict
from app.market_data.instrument_state import IndexSymbol, INDEX_FYERS_MAP, OptionChainSnapshot, OptionStrikeData
from app.market_data.fyers_client import fyers_client
from app.state.market_state_store import market_state
from app.core.config import settings

logger = logging.getLogger(__name__)

class OptionChainCoordinator:
    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = {}
        self._last_fetch_time: Dict[str, float] = {}

    def _get_lock(self, symbol: str) -> asyncio.Lock:
        if symbol not in self._locks:
            self._locks[symbol] = asyncio.Lock()
        return self._locks[symbol]

    async def get_or_fetch(self, symbol: str, force: bool = False) -> Optional[OptionChainSnapshot]:
        now = time.time()
        cached = market_state.get_chain(symbol)
        
        # If cache is valid and not forced, return immediately (0ms)
        if not force and cached and (now - cached.timestamp) < settings.CHAIN_SNAPSHOT_INTERVAL_SEC:
            return cached

        # Single-flight deduplication: only 1 network fetch runs
        lock = self._get_lock(symbol)
        async with lock:
            # Recheck cache after lock acquisition
            now = time.time()
            cached = market_state.get_chain(symbol)
            if not force and cached and (now - cached.timestamp) < settings.CHAIN_SNAPSHOT_INTERVAL_SEC:
                return cached

            # Perform single fetch
            fyers_sym = INDEX_FYERS_MAP.get(IndexSymbol(symbol), f"NSE:{symbol}50-INDEX")
            logger.info(f"[Single-Flight] Fetching option chain for {symbol} ({fyers_sym})...")
            
            raw_res = await asyncio.to_thread(fyers_client.get_option_chain_raw, fyers_sym)
            if not raw_res or raw_res.get("s") != "ok":
                logger.warning(f"Failed to fetch Fyers chain for {symbol}")
                return cached  # Serve last-known if network blip

            snapshot = self._parse_fyers_chain(symbol, raw_res)
            if snapshot:
                market_state.update_chain(snapshot)
                self._last_fetch_time[symbol] = time.time()
                return snapshot
            return cached

    def _parse_fyers_chain(self, symbol: str, res: dict) -> Optional[OptionChainSnapshot]:
        try:
            data = res.get("data", {})
            raw_items = data.get("optionsChain", [])
            if not raw_items:
                return None

            spot_price = 0.0
            spot_change = 0.0
            spot_pchange = 0.0
            strikes: Dict[float, OptionStrikeData] = {}
            expiries = set()

            for item in raw_items:
                strike = float(item.get("strike_price", -1))
                if strike == -1:
                    spot_price = float(item.get("ltp", 0.0))
                    spot_change = float(item.get("ltpch", 0.0))
                    spot_pchange = float(item.get("ltpchp", 0.0))
                    continue

                exp = item.get("expiry") or ""
                if exp:
                    expiries.add(exp)

                if strike not in strikes:
                    strikes[strike] = OptionStrikeData(strike_price=strike, expiry_date=exp)

                s_data = strikes[strike]
                opt_type = (item.get("option_type") or "").upper()
                ltp = float(item.get("ltp", 0.0))
                ch = float(item.get("ltpch", 0.0))
                chp = float(item.get("ltpchp", 0.0))
                oi = int(item.get("oi", 0))
                oich = int(item.get("oich", 0))
                vol = int(item.get("volume", 0))

                # Buildup formula
                buildup = "NEUTRAL"
                if ch > 0 and oich > 0:
                    buildup = "LONG_BUILDUP"
                elif ch > 0 and oich < 0:
                    buildup = "SHORT_COVERING"
                elif ch < 0 and oich > 0:
                    buildup = "SHORT_BUILDUP"
                elif ch < 0 and oich < 0:
                    buildup = "LONG_UNWINDING"

                if opt_type == "CE":
                    s_data.ce_ltp = ltp
                    s_data.ce_change = ch
                    s_data.ce_pchange = chp
                    s_data.ce_oi = oi
                    s_data.ce_oich = oich
                    s_data.ce_volume = vol
                    s_data.ce_symbol = item.get("symbol", "")
                    s_data.ce_buildup = buildup
                elif opt_type == "PE":
                    s_data.pe_ltp = ltp
                    s_data.pe_change = ch
                    s_data.pe_pchange = chp
                    s_data.pe_oi = oi
                    s_data.pe_oich = oich
                    s_data.pe_volume = vol
                    s_data.pe_symbol = item.get("symbol", "")
                    s_data.pe_buildup = buildup

            # Calculate ATM Strike
            step = 50 if "NIFTY" in symbol and "BANK" not in symbol else 100
            atm = round(spot_price / step) * step if spot_price > 0 else 0.0

            return OptionChainSnapshot(
                symbol=symbol,
                spot_price=spot_price,
                spot_change=spot_change,
                spot_pchange=spot_pchange,
                atm_strike=atm,
                expiry_dates=sorted(list(expiries)),
                strikes=strikes,
                timestamp=time.time(),
                version=market_state._global_version + 1
            )
        except Exception as e:
            logger.error(f"Error parsing chain for {symbol}: {e}")
            return None

chain_coordinator = OptionChainCoordinator()
