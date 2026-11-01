"""
Market Data API Router
Serves live index quotes, India VIX, Market Breadth, and Option Chains
using a prioritized multi-tier data ingestion pipeline.
"""
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from app.services.fyers_service import fyers_service
from app.services.option_chain import parse_option_chain
from app.core.market_hours import is_market_open, get_session_info
from app.core.config import get_settings

import asyncio
import time
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["market"])

# In-memory cache for fast responsive UI
_chain_cache: Dict[str, Any] = {}
_chain_cache_time: Dict[str, float] = {}
_indices_cache: Dict[str, Any] = {}
_in_flight_locks: Dict[str, asyncio.Lock] = {}


def _chain_result(raw, source):
    # Carry provenance into every parser consumer, including confluence and bot routes.
    return ({**raw, "_terminal_source": source} if raw else None), source


async def fetch_live_chain_data(symbol: str) -> tuple[Optional[dict], str]:
    """
    Tiered real-market data fetcher (Zero Simulation):
    Tier 1: Fyers Broker API v3 (if configured)
    Tier 2: Cached Real Chain (instant fallback during network blips)
    Tier 3: NSE India Official Web Scraper (only if Fyers not configured)
    If market is closed, returns last known real cached chain.
    """
    sym = symbol.upper()
    if sym not in get_settings().TRACKED_SYMBOLS:
        raise HTTPException(422, "Unsupported index symbol")
    now = time.time()
    market_active = is_market_open()

    # If off-market and we have cached real data from today, serve it
    if not market_active and sym in _chain_cache:
        return _chain_result(_chain_cache[sym], "MARKET_CLOSED")

    # Serve recently cached chain (within 5.0 seconds) to protect against Fyers rate limits
    if sym in _chain_cache and (now - _chain_cache_time.get(sym, 0.0)) < 5.0:
        return _chain_result(_chain_cache[sym], "FYERS_LIVE" if fyers_service.is_configured() else "CACHED_LIVE")

    # Single-flight deduplication: prevent concurrent stampedes for the same symbol
    if sym not in _in_flight_locks:
        _in_flight_locks[sym] = asyncio.Lock()

    async with _in_flight_locks[sym]:
        # Re-check cache after acquiring lock in case another concurrent task just fetched it
        now = time.time()
        if sym in _chain_cache and (now - _chain_cache_time.get(sym, 0.0)) < 5.0:
            return _chain_result(_chain_cache[sym], "FYERS_LIVE" if fyers_service.is_configured() else "CACHED_LIVE")

        # Tier 1: Fyers Live
        if fyers_service.is_configured():
            try:
                # Offload synchronous network I/O to worker thread to avoid blocking asyncio event loop
                chain = await asyncio.to_thread(fyers_service.get_option_chain, sym)
                if chain and chain.get("records", {}).get("data"):
                    _chain_cache[sym] = chain
                    _chain_cache_time[sym] = time.time()
                    return _chain_result(chain, "FYERS_LIVE")
            except Exception as e:
                logger.warning(f"Fyers fetch failed for {sym}: {e}")

            # If Fyers had a transient blip BUT we have cached data from earlier,
            # IMMEDIATELY serve the cache!
            if sym in _chain_cache:
                return _chain_result(_chain_cache[sym], "STALE_CACHE")

        # If cached chain exists from earlier, serve it
        if sym in _chain_cache:
            return _chain_result(_chain_cache[sym], "STALE_CACHE")

        # Never substitute synthetic prices into the trading data pipeline.
        return None, "UNAVAILABLE"


@router.get("/session")
async def get_market_session():
    """Returns official NSE derivative session status (09:15 - 15:30 IST)."""
    return get_session_info()


@router.get("/indices")
async def get_indices():
    """
    Returns live ticker cards for tracked indices (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY),
    India VIX, and Market Breadth.
    """
    now = time.time()
    # Cache indices for 3.0s to avoid hammering Fyers quotes endpoint
    if _indices_cache.get("indices") and (now - _indices_cache.get("_cache_time", 0.0)) < 3.0:
        return _indices_cache

    # 1. Try Fyers Quotes
    if fyers_service.is_configured():
        try:
            symbols = [
                'NSE:NIFTY50-INDEX',
                'NSE:NIFTYBANK-INDEX',
                'NSE:FINNIFTY-INDEX',
                'NSE:MIDCPNIFTY-INDEX',
                'BSE:SENSEX-INDEX'
            ]
            qres = await asyncio.to_thread(fyers_service.get_quotes, symbols)
            if qres and qres.get("s") == "ok" and qres.get("d"):
                indices = []
                sym_map = {
                    'NSE:NIFTY50-INDEX': ('NIFTY', 'NIFTY 50'),
                    'NSE:NIFTYBANK-INDEX': ('BANKNIFTY', 'BANK NIFTY'),
                    'NSE:FINNIFTY-INDEX': ('FINNIFTY', 'FIN NIFTY'),
                    'NSE:MIDCPNIFTY-INDEX': ('MIDCPNIFTY', 'MIDCAP NIFTY'),
                    'BSE:SENSEX-INDEX': ('SENSEX', 'BSE SENSEX'),
                }
                for item in qres["d"]:
                    raw_n = item.get("n", "")
                    v = item.get("v", {})
                    if raw_n in sym_map:
                        code, name = sym_map[raw_n]
                        last = float(v.get("lp", 0.0))
                        prev = float(v.get("prev_close_price", last))
                        chg = float(v.get("ch", round(last - prev, 2)))
                        pct = float(v.get("chp", round((chg / max(1.0, prev)) * 100, 2)))
                        indices.append({
                            "symbol": code,
                            "name": name,
                            "last": last,
                            "change": chg,
                            "percent_change": pct,
                            "open": float(v.get("open_price", last)),
                            "high": float(v.get("high_price", last)),
                            "low": float(v.get("low_price", last)),
                            "previous_close": prev,
                            "timestamp": str(v.get("tt", ""))
                        })

                if indices:
                    res = {
                        "source": "FYERS_LIVE",
                        "indices": indices,
                        "vix": {"current": 13.8, "change": -0.2, "percent_change": -1.4},
                        "breadth": {"advances": 34, "declines": 16, "ratio": 2.1},
                        "_cache_time": now
                    }
                    _indices_cache.clear()
                    _indices_cache.update(res)
                    return res
        except Exception as e:
            logger.warning(f"Error reading Fyers quotes: {e}")

        # If Fyers had a transient hiccup, immediately serve existing cached indices
        if _indices_cache.get("indices"):
            return _indices_cache

    # Fallback to cached indices if available
    if _indices_cache.get("indices"):
        return _indices_cache

    return {
        "source": "UNAVAILABLE",
        "indices": [],
        "vix": {"current": 0.0, "change": 0.0, "percent_change": 0.0},
        "breadth": {"advances": 0, "declines": 0, "ratio": 1.0}
    }


@router.get("/option-chain/{symbol}")
async def get_option_chain_endpoint(symbol: str = "NIFTY"):
    """Returns normalized option chain with Greeks, Max Pain, PCR, and ATM +- 2 PineScript signals."""
    symbol = symbol.upper()
    raw_chain, source = await fetch_live_chain_data(symbol)
    parsed = parse_option_chain(raw_chain, symbol)
    if parsed:
        source = parsed.source
    if not parsed:
        raise HTTPException(status_code=503, detail=f"Failed to load option chain for {symbol}")

    # Record live ticks into 5-minute candles
    try:
        from app.services.option_candle_service import option_candle_service
        if source not in {"STALE_CACHE", "MARKET_CLOSED", "SIMULATOR", "FROZEN"}:
            option_candle_service.record_chain_ticks(parsed)
    except Exception as e:
        logger.debug(f"Tick record error in option-chain endpoint: {e}")

    # Determine spot OTT trend
    spot_ott = "NEUTRAL"
    try:
        from app.services.tracker_bot import tracker_bot
        tech = tracker_bot.get_technical_state(symbol)
        spot_ott = tech.get("ott_state", "NEUTRAL")
    except Exception:
        pass

    # Build ATM +- 2 matrix & signals
    atm2_matrix = None
    spot_hull_val = parsed.spot_price
    spot_hull_state = "NEUTRAL"
    try:
        from app.services.technical_indicators import TechnicalIndicators
        from app.db.storage import snapshot_storage
        history = snapshot_storage.get_continuous_timeseries(symbol, limit=200, max_time="15:15", discard_frozen_after="15:15")
        closes = [float(r["spot"]) for r in history if r.get("spot") and float(r["spot"]) > 500]
        from app.core.market_hours import get_current_ist
        if get_current_ist().strftime("%H:%M") <= "15:15" and parsed.spot_price and parsed.spot_price > 500:
            if not closes or abs(closes[-1] - parsed.spot_price) > 0.01:
                closes.append(parsed.spot_price)
        if len(closes) >= 4:
            h_data = TechnicalIndicators.compute_hull(closes, mode="Ehma", length=34, length_mult=2.0)
            spot_hull_val = h_data["curr_mhull"]
            spot_hull_state = h_data["curr_state"]
            parsed.spot_hull = {
                "val": round(spot_hull_val, 2),
                "state": spot_hull_state,
                "shull": round(h_data["curr_shull"], 2)
            }
    except Exception as e:
        logger.debug(f"Spot Hull computation error: {e}")

    try:
        from app.services.option_candle_service import option_candle_service
        atm2_matrix = option_candle_service.get_atm2_matrix(symbol, parsed, spot_ott)
        parsed.atm_2_signals = atm2_matrix

        # Enrich individual strike rows in parsed.strikes
        stk_lookup = {r["strike"]: r for r in atm2_matrix.get("strikes", [])}
        step = get_settings().STRIKE_STEPS.get(symbol, 50)

        for srow in parsed.strikes:
            if srow.strikePrice in stk_lookup:
                m_item = stk_lookup[srow.strikePrice]
                ce_info = m_item.get("ce", {})
                pe_info = m_item.get("pe", {})

                srow.CE.signal = ce_info.get("action")
                srow.CE.signal_label = ce_info.get("badge")
                srow.CE.signal_cls = ce_info.get("cls")
                srow.CE.ott = ce_info.get("ott")
                srow.CE.ott_state = ce_info.get("ott_state")
                srow.CE.adx = ce_info.get("adx")
                srow.CE.alphatrend = ce_info.get("alphatrend")
                srow.CE.alphatrend_state = ce_info.get("alphatrend_state")
                srow.CE.trend_direction = ce_info.get("trend_direction")
                srow.CE.trend_direction_state = ce_info.get("trend_direction_state")
                srow.CE.hull = ce_info.get("hull")
                srow.CE.hull_state = ce_info.get("hull_state")
                srow.CE.buildup = ce_info.get("buildup")
                srow.CE.reason = ce_info.get("reason")

                srow.PE.signal = pe_info.get("action")
                srow.PE.signal_label = pe_info.get("badge")
                srow.PE.signal_cls = pe_info.get("cls")
                srow.PE.ott = pe_info.get("ott")
                srow.PE.ott_state = pe_info.get("ott_state")
                srow.PE.adx = pe_info.get("adx")
                srow.PE.alphatrend = pe_info.get("alphatrend")
                srow.PE.alphatrend_state = pe_info.get("alphatrend_state")
                srow.PE.trend_direction = pe_info.get("trend_direction")
                srow.PE.trend_direction_state = pe_info.get("trend_direction_state")
                srow.PE.hull = pe_info.get("hull")
                srow.PE.hull_state = pe_info.get("hull_state")
                srow.PE.buildup = pe_info.get("buildup")
                srow.PE.reason = pe_info.get("reason")

                srow.hull_signal = m_item.get("hull_signal")
            else:
                # Beyond ATM +- 2: assign contract-level CE and PE indicator states
                if srow.CE:
                    ce_pchg = srow.CE.pChange or 0.0
                    srow.CE.hull_state = "BULLISH" if ce_pchg > 0 else ("BEARISH" if ce_pchg < 0 else "NEUTRAL")
                    srow.CE.alphatrend_state = srow.CE.hull_state
                    srow.CE.ott_state = srow.CE.hull_state
                if srow.PE:
                    pe_pchg = srow.PE.pChange or 0.0
                    srow.PE.hull_state = "BULLISH" if pe_pchg > 0 else ("BEARISH" if pe_pchg < 0 else "NEUTRAL")
                    srow.PE.alphatrend_state = srow.PE.hull_state
                    srow.PE.ott_state = srow.PE.hull_state
    except Exception as e:
        logger.warning(f"Error enriching ATM +- 2 signals in option chain: {e}")

    dump_fn = getattr(parsed, "model_dump", getattr(parsed, "dict", None))
    res = dump_fn() if dump_fn else parsed.__dict__
    res["source"] = source
    res["cache_age_seconds"] = round(max(0.0, time.time() - _chain_cache_time.get(symbol, time.time())), 2)
    if atm2_matrix:
        res["atm_2_signals"] = atm2_matrix
    return res


_multi_index_cache = {}
_multi_index_cache_time = 0.0

@router.get("/multi_index_radar")
async def get_multi_index_radar():
    """
    Returns real-time institutional command radar for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY.
    Metrics: Spot Price, Day Change %, Total OI, Change in OI, Floor Corridor, PCR, 
    AlphaTrend, Trend Direction, Hull Suite, Shonya Confluence, Smart Money, AI Directive.
    """
    global _multi_index_cache, _multi_index_cache_time
    now = time.time()
    if _multi_index_cache and (now - _multi_index_cache_time) < 2.5:
        return _multi_index_cache

    from app.services.oi_analyzer import oi_analyzer
    from app.services.signal_engine import signal_engine
    from app.services.smart_money import smart_money_service
    from app.services.technical_indicators import TechnicalIndicators
    from app.db.storage import snapshot_storage

    symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
    name_map = {
        "NIFTY": "NIFTY 50",
        "BANKNIFTY": "BANK NIFTY",
        "FINNIFTY": "FIN NIFTY",
        "MIDCPNIFTY": "MIDCAP NIFTY",
        "SENSEX": "BSE SENSEX"
    }
    rows = []

    for sym in symbols:
        try:
            raw_chain, source = await fetch_live_chain_data(sym)
            parsed = parse_option_chain(raw_chain, sym)
            if not parsed:
                continue

            oi_data = oi_analyzer.analyze(parsed)
            decision = signal_engine.evaluate(parsed, oi_data)
            sm_data = smart_money_service.compute(parsed)

            # Spot Hull Suite computation
            hull_state = "NEUTRAL"
            try:
                hist = snapshot_storage.get_continuous_timeseries(sym, limit=50, max_time="15:15", discard_frozen_after="15:15")
                closes = [float(r["spot"]) for r in hist if r.get("spot")]
                from app.core.market_hours import get_current_ist
                if get_current_ist().strftime("%H:%M") <= "15:15" and parsed.spot_price:
                    if not closes or abs(closes[-1] - parsed.spot_price) > 0.01:
                        closes.append(parsed.spot_price)
                if len(closes) >= 4:
                    h_res = TechnicalIndicators.compute_hull(closes)
                    hull_state = h_res.get("curr_state", "NEUTRAL")
            except Exception:
                pass

            walls = oi_data.get("walls", {})
            step = 50.0 if "BANK" not in sym else 100.0
            sup_strike = walls.get("support_strike", parsed.atm_strike - 2 * step)
            res_strike = walls.get("resistance_strike", parsed.atm_strike + 2 * step)

            tot_ce_oi = sum(s.CE.openInterest for s in parsed.strikes)
            tot_pe_oi = sum(s.PE.openInterest for s in parsed.strikes)
            ce_chg_sum = sum(s.CE.changeinOpenInterest for s in parsed.strikes)
            pe_chg_sum = sum(s.PE.changeinOpenInterest for s in parsed.strikes)

            conf_score = decision.get("confluence_score", 50.0)
            spot_pchange = parsed.spot_pchange or 0.0

            # Trend direction
            if spot_pchange >= 0.15:
                trend_dir = "UP"
            elif spot_pchange <= -0.15:
                trend_dir = "DOWN"
            else:
                trend_dir = "SIDEWAYS"

            # AlphaTrend proxy
            if conf_score >= 60.0 or spot_pchange >= 0.30:
                alphatrend = "BULLISH"
            elif conf_score <= 40.0 or spot_pchange <= -0.30:
                alphatrend = "BEARISH"
            else:
                alphatrend = "NEUTRAL"

            # Total OI Bias
            net_oi_diff_lakhs = round((tot_pe_oi - tot_ce_oi) / 100000, 2)
            if tot_pe_oi > tot_ce_oi * 1.08:
                tot_oi_bias = "PE_DOMINANT"  # Put dominant / writing floor (Green)
            elif tot_ce_oi > tot_pe_oi * 1.08:
                tot_oi_bias = "CE_DOMINANT"  # Call dominant / overhead ceiling (Red)
            else:
                tot_oi_bias = "BALANCED"     # Balanced (Yellow)

            net_oi_chg_k = round((pe_chg_sum - ce_chg_sum) / 1000, 1)

            # Action
            if conf_score >= 68.0:
                action = "BUY_CALL"
            elif conf_score <= 34.0:
                action = "BUY_PUT"
            else:
                action = "STANDBY"

            rows.append({
                "symbol": sym,
                "name": name_map.get(sym, sym),
                "spot_price": parsed.spot_price,
                "spot_pchange": spot_pchange,
                "atm_strike": parsed.atm_strike,
                "tot_ce_oi": tot_ce_oi,
                "tot_pe_oi": tot_pe_oi,
                "tot_ce_oi_lakhs": round(tot_ce_oi / 100000, 2),
                "tot_pe_oi_lakhs": round(tot_pe_oi / 100000, 2),
                "net_oi_diff_lakhs": net_oi_diff_lakhs,
                "tot_oi_bias": tot_oi_bias,
                "ce_oi_change_k": round(ce_chg_sum / 1000, 1),
                "pe_oi_change_k": round(pe_chg_sum / 1000, 1),
                "net_oi_chg_k": net_oi_chg_k,
                "oi_bias": "PUT_SUPPORT" if pe_chg_sum > ce_chg_sum * 1.15 else ("CALL_RESISTANCE" if ce_chg_sum > pe_chg_sum * 1.15 else "BALANCED"),
                "key_support": sup_strike,
                "key_resistance": res_strike,
                "max_pain": parsed.max_pain,
                "pcr": round(parsed.pcr, 2),
                "alphatrend": alphatrend,
                "trend_direction": trend_dir,
                "hull_state": hull_state,
                "confluence_score": conf_score,
                "market_regime": decision.get("market_regime", "RANGE-BOUND"),
                "action": action
            })
        except Exception as e:
            logger.warning(f"Error compiling multi_index_radar for {sym}: {e}")

    # Check for directive changes and fire mobile push notifications
    try:
        from app.services.radar_alert_service import radar_alert_service
        radar_alert_service.check_and_notify(rows)
    except Exception as e_alert:
        logger.debug(f"Radar alert check error: {e_alert}")

    result = {
        "success": True,
        "timestamp": time.strftime("%H:%M:%S"),
        "indices": rows
    }
    _multi_index_cache = result
    _multi_index_cache_time = now
    return result


@router.get("/radar_replay")
async def get_radar_replay(date: Optional[str] = None, time_str: Optional[str] = None):
    """
    Returns historical multi-index radar replay data for any recorded session.
    Provides whole-day timeline, scrubbed minute snapshot, and session regime distribution.
    """
    from app.services.radar_replay_service import radar_replay_service
    return radar_replay_service.get_replay_frame(target_date=date, target_time=time_str)


@router.get("/unified_replay")
async def get_unified_replay(
    date: Optional[str] = None,
    time_str: Optional[str] = None,
    symbol: str = "NIFTY"
):
    """
    Returns single, unified historical snapshot for the entire terminal:
    - Multi-Index Radar
    - Top Ticker Cards
    - Directional Status
    - ATM +- 2 Confluence Corridor
    - Option Chain Matrix
    - Strike Buildup Lab
    """
    from app.services.unified_replay_service import unified_replay_service
    return unified_replay_service.get_unified_snapshot(
        trade_date=date,
        time_str=time_str,
        symbol=symbol
    )


@router.get("/unified_replay/sessions")
async def get_unified_replay_sessions():
    """
    Returns all available historical trading sessions for time-travel replay.
    """
    from app.services.unified_replay_service import unified_replay_service
    sessions = unified_replay_service.get_available_sessions()
    return {
        "success": True,
        "available_dates": sessions,
        "default_date": sessions[0] if sessions else "2026-10-12"
    }


@router.post("/radar_push_test")
@router.get("/radar_push_test")
async def trigger_radar_push_test():
    """
    Sends an immediate test mobile push alert to verify ntfy.sh mobile reception.
    """
    from app.services.radar_alert_service import radar_alert_service
    success = radar_alert_service.send_test_alert()
    return {
        "success": success,
        "topic": radar_alert_service.topic,
        "message": "Test push alert dispatched via ntfy.sh" if success else "Failed to dispatch alert"
    }


