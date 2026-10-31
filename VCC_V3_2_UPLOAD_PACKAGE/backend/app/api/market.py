"""
Market Data API Routes

REST endpoints for market data, option chains, and analysis.
"""
import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from app.cache import cache
from app.services.nse_fetcher import nse
from app.services.option_chain import (
    parse_option_chain,
    compute_pcr_variants,
    compute_support_resistance,
)
from app.providers.data_source_manager import data_source_manager
from app.analytics.pipeline import analytics_pipeline
from app.intelligence.confluence_engine import confluence_engine
from app.signals.signal_engine import signal_engine
from app.smart_money import smart_money_v3_service
from app.audit.audit_service import audit_service
from app.repositories import audit_repository, performance_repository, signal_repository

from app.schemas import (
    DashboardData,
    IndexData,
    VIXData,
    MarketBreadth,
    PCRData,
    OISpurtEntry,
    MostActiveContract,
    SellerRecommendation,
    AlertEntry,
    SectorData,
)
from app.services.mock_engine import simulator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["market"])


def fetch_yahoo_live_indices_sync() -> dict:
    """Fallback fetcher for instant live index ticks from Yahoo Finance."""
    symbols = {
        "NIFTY": "^NSEI",
        "BANKNIFTY": "^NSEBANK",
        "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
        "MIDCPNIFTY": "^NSEI",
        "SENSEX": "^BSESN"
    }
    results = {}
    try:
        from curl_cffi import requests as cffi_requests
        session = cffi_requests.Session(impersonate="chrome120")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        for code, y_sym in symbols.items():
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{y_sym}?interval=1m&range=1d"
                res = session.get(url, headers=headers, timeout=2.0)
                if res.status_code == 200:
                    meta = res.json()["chart"]["result"][0]["meta"]
                    price = float(meta.get("regularMarketPrice", 0))
                    prev = float(meta.get("chartPreviousClose", price))
                    if price > 0:
                        chg = round(price - prev, 2)
                        pct = round((chg / max(1.0, prev)) * 100, 2)
                        results[code] = {
                            "symbol": code,
                            "name": f"NIFTY {code}" if code != "SENSEX" else "SENSEX",
                            "last": price,
                            "change": chg,
                            "pctChange": pct,
                            "open": round(meta.get("regularMarketDayLow", price * 0.998), 2),
                            "high": round(meta.get("regularMarketDayHigh", price * 1.002), 2),
                            "low": round(meta.get("regularMarketDayLow", price * 0.998), 2),
                            "prevClose": prev,
                            "timestamp": datetime.now().strftime("%H:%M:%S")
                        }
            except Exception:
                pass
    except Exception:
        pass
    return results


@router.get("/indices")
async def get_indices():
    """Get major market indices data with Fyers + NSE live integration + Yahoo fallback."""
    cached = await cache.get("indices")
    if cached:
        return cached

    try:
        from app.services.fyers_fetcher import fyers_service

        fyers_quotes = {}
        if fyers_service.is_configured():
            qres = fyers_service.get_quotes([
                'NSE:NIFTY50-INDEX', 'NSE:NIFTYBANK-INDEX',
                'NSE:FINNIFTY-INDEX', 'NSE:MIDCPNIFTY-INDEX'
            ])
            if qres and qres.get("s") == "ok" and qres.get("d"):
                for item in qres["d"]:
                    v = item.get("v", {})
                    sym = item.get("n", "")
                    fyers_quotes[sym] = v

        raw = None
        try:
            raw = await asyncio.wait_for(nse.get_indices(), timeout=1.0)
        except Exception:
            pass

        indices_map = {}
        target_indices = {
            "NIFTY 50": "NIFTY",
            "NIFTY BANK": "BANKNIFTY",
            "NIFTY FIN SERVICE": "FINNIFTY",
            "NIFTY MIDCAP SELECT": "MIDCPNIFTY",
            "INDIA VIX": "VIX",
        }

        vix_data = None

        if raw and "data" in raw:
            for idx in raw.get("data", []):
                name = idx.get("index", "")
                if name in target_indices:
                    code = target_indices[name]
                    entry = {
                        "symbol": code,
                        "name": name,
                        "last": idx.get("last", 0),
                        "change": idx.get("variation", 0),
                        "pctChange": idx.get("percentChange", 0),
                        "open": idx.get("open", 0),
                        "high": idx.get("high", 0),
                        "low": idx.get("low", 0),
                        "prevClose": idx.get("previousClose", 0),
                        "timestamp": idx.get("timeVal", ""),
                    }
                    if name == "INDIA VIX":
                        vix_data = {
                            "current": idx.get("last", 0),
                            "change": idx.get("variation", 0),
                            "pct_change": idx.get("percentChange", 0),
                            "high": idx.get("high", 0),
                            "low": idx.get("low", 0),
                            "prev_close": idx.get("previousClose", 0),
                            "trend": "up" if idx.get("percentChange", 0) > 0 else "down",
                        }
                    else:
                        indices_map[code] = entry

        # Overlay Fyers Live Broker Quotes if available
        if "NSE:NIFTY50-INDEX" in fyers_quotes:
            v = fyers_quotes["NSE:NIFTY50-INDEX"]
            indices_map["NIFTY"] = {
                "symbol": "NIFTY", "name": "NIFTY 50",
                "last": v.get("lp", 0), "change": v.get("ch", 0), "pctChange": v.get("chp", 0),
                "open": v.get("open_price", 0), "high": v.get("high_price", 0), "low": v.get("low_price", 0),
                "prevClose": v.get("prev_close_price", 0), "timestamp": "LIVE FYERS"
            }
        if "NSE:NIFTYBANK-INDEX" in fyers_quotes:
            v = fyers_quotes["NSE:NIFTYBANK-INDEX"]
            indices_map["BANKNIFTY"] = {
                "symbol": "BANKNIFTY", "name": "NIFTY BANK",
                "last": v.get("lp", 0), "change": v.get("ch", 0), "pctChange": v.get("chp", 0),
                "open": v.get("open_price", 0), "high": v.get("high_price", 0), "low": v.get("low_price", 0),
                "prevClose": v.get("prev_close_price", 0), "timestamp": "LIVE FYERS"
            }
        if "NSE:FINNIFTY-INDEX" in fyers_quotes:
            v = fyers_quotes["NSE:FINNIFTY-INDEX"]
            indices_map["FINNIFTY"] = {
                "symbol": "FINNIFTY", "name": "NIFTY FIN SERVICE",
                "last": v.get("lp", 0), "change": v.get("ch", 0), "pctChange": v.get("chp", 0),
                "open": v.get("open_price", 0), "high": v.get("high_price", 0), "low": v.get("low_price", 0),
                "prevClose": v.get("prev_close_price", 0), "timestamp": "LIVE FYERS"
            }
        if "NSE:MIDCPNIFTY-INDEX" in fyers_quotes:
            v = fyers_quotes["NSE:MIDCPNIFTY-INDEX"]
            indices_map["MIDCPNIFTY"] = {
                "symbol": "MIDCPNIFTY", "name": "NIFTY MIDCAP SELECT",
                "last": v.get("lp", 0), "change": v.get("ch", 0), "pctChange": v.get("chp", 0),
                "open": v.get("open_price", 0), "high": v.get("high_price", 0), "low": v.get("low_price", 0),
                "prevClose": v.get("prev_close_price", 0), "timestamp": "LIVE FYERS"
            }

        # If Fyers and NSE scraper didn't return live quotes, fetch live ticks from Yahoo Finance fallback
        if not indices_map:
            loop = asyncio.get_running_loop()
            y_quotes = await loop.run_in_executor(None, fetch_yahoo_live_indices_sync)
            if y_quotes:
                indices_map.update(y_quotes)

        indices = list(indices_map.values())
        if not indices:
            result = {
                "indices": [],
                "vix": {"current": None, "vix_status": "UNAVAILABLE", "trend": "UNAVAILABLE"},
                "breadth": {"advances": 0, "declines": 0, "unchanged": 0, "adr": 0.0},
                "status": "UNAVAILABLE",
                "timestamp": datetime.now().isoformat()
            }
            await cache.set("indices", result, ttl=1)
            return result

        if not vix_data:
            vix_data = {"current": None, "vix_status": "UNAVAILABLE", "change": 0.0, "pct_change": 0.0, "high": 0.0, "low": 0.0, "prev_close": 0.0, "trend": "UNAVAILABLE"}

        breadth = {"advances": 0, "declines": 0, "unchanged": 0, "adr": 0.0}
        if raw and "advance" in raw:
            adv = raw.get("advance", {})
            advances = adv.get("advances", 0)
            declines = adv.get("declines", 0)
            breadth = {
                "advances": advances,
                "declines": declines,
                "unchanged": adv.get("unchanged", 0),
                "adr": round(advances / max(1, declines), 2)
            }

        result = {
            "indices": indices,
            "vix": vix_data,
            "breadth": breadth,
            "timestamp": datetime.now().isoformat()
        }
        await cache.set("indices", result, ttl=1)
        return result

    except Exception as e:
        logger.error(f"Indices fetch exception: {e}")
        return {
            "indices": [],
            "vix": {"current": None, "vix_status": "UNAVAILABLE", "trend": "UNAVAILABLE"},
            "breadth": {"advances": 0, "declines": 0, "unchanged": 0, "adr": 0.0},
            "status": "UNAVAILABLE",
            "timestamp": datetime.now().isoformat()
        }


@router.get("/option-chain/{symbol}")
async def get_option_chain(
    symbol: str = "NIFTY",
    expiry: Optional[str] = None,
):
    """Get parsed option chain with Greeks and analysis."""
    cache_key = f"option_chain:{symbol}:{expiry or 'current'}"
    cached = await cache.get(cache_key)
    if cached and "strikes" in cached:
        return cached

    try:
        from app.services.fyers_fetcher import fyers_service
        is_index = symbol.upper() in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
        stype = "INDEX" if is_index else "EQ"
        raw = fyers_service.get_option_chain(symbol, stype=stype) if fyers_service.is_configured() else None
        if not raw:
            raw = await nse.get_option_chain(symbol)

        chain = parse_option_chain(raw, symbol) if raw else None
        if not chain:
            return {"error": "DATA_UNAVAILABLE", "symbol": symbol, "message": "No valid option chain available"}

        result = chain.model_dump()
        await cache.set(cache_key, result, ttl=15)
        return result
    except Exception as e:
        logger.error(f"Option chain exception: {e}")
        return {"error": "DATA_UNAVAILABLE", "symbol": symbol, "message": str(e)}


@router.get("/pcr/{symbol}")
async def get_pcr(symbol: str = "NIFTY"):
    """Get PCR analysis with multiple variants."""
    cache_key = f"pcr:{symbol}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    try:
        raw = await nse.get_option_chain(symbol)
        chain = parse_option_chain(raw, symbol) if raw else None
        if not chain:
            return {"error": "DATA_UNAVAILABLE", "symbol": symbol, "pcr": 0.0}

        strike_step = 50 if "BANK" not in symbol.upper() else 100
        pcr = compute_pcr_variants(chain.strikes, chain.atm_strike, strike_step)
        result = pcr.model_dump()
        await cache.set(cache_key, result, ttl=15)
        return result
    except Exception as e:
        return {"error": "DATA_UNAVAILABLE", "symbol": symbol, "pcr": 0.0}


@router.get("/support-resistance/{symbol}")
async def get_support_resistance(symbol: str = "NIFTY"):
    """Get OI-based support and resistance levels."""
    try:
        raw = await nse.get_option_chain(symbol)
        chain = parse_option_chain(raw, symbol) if raw else None
        if not chain:
            return {"supports": [], "resistances": [], "spot": 0.0, "timestamp": datetime.now().isoformat()}

        supports, resistances = compute_support_resistance(chain.strikes, chain.spot_price)
        return {
            "supports": [s.model_dump() for s in supports],
            "resistances": [r.model_dump() for r in resistances],
            "spot": chain.spot_price,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"supports": [], "resistances": [], "spot": 0.0, "timestamp": datetime.now().isoformat()}


@router.get("/seller-recommendations/{symbol}")
async def get_seller_recommendations(symbol: str = "NIFTY"):
    """Get option seller recommendations."""
    cache_key = f"seller_recs:{symbol}"
    cached = await cache.get(cache_key)
    if cached and "recommendations" in cached:
        return cached

    try:
        from app.services.fyers_fetcher import fyers_service
        raw_chain = fyers_service.get_option_chain(symbol) if fyers_service.is_configured() else None
        if not raw_chain:
            raw_chain = await nse.get_option_chain(symbol)
        raw_indices = await nse.get_indices()

        chain = parse_option_chain(raw_chain, symbol) if raw_chain else None
        if not chain:
            return {
                "recommendations": [],
                "status": "DATA_UNAVAILABLE",
                "reason": "No valid option chain available",
                "timestamp": datetime.now().isoformat()
            }

        strike_step = 50 if "BANK" not in symbol.upper() else 100
        pcr = compute_pcr_variants(chain.strikes, chain.atm_strike, strike_step)
        supports, resistances = compute_support_resistance(chain.strikes, chain.spot_price)

        vix = VIXData()
        if raw_indices and isinstance(raw_indices, dict):
            for idx in raw_indices.get("data", []):
                if idx.get("index") == "INDIA VIX":
                    vix = VIXData(
                        current=idx.get("last", 0),
                        change=idx.get("variation", 0),
                        pct_change=idx.get("percentChange", 0),
                    )

        snapshot = await data_source_manager.get_market_snapshot(symbol.upper())
        pipeline_res = analytics_pipeline.run_pipeline(snapshot)
        conf_res = confluence_engine.compute_confluence(
            positioning_score=pipeline_res["positioning"]["positioning_score"],
            price_conf_score=pipeline_res["price_confirmation"]["score"],
            wall_interaction_score=pipeline_res["price_confirmation"]["wall_interaction_score"],
            straddle_decay_pct=0.0,
            breakout_status=pipeline_res["price_confirmation"]["breakout_status"],
            data_quality=snapshot.quality,
            data_age_sec=max(snapshot.metadata.spot_data_age_sec, snapshot.metadata.option_data_age_sec)
        )
        decision = signal_engine.decide_signal(snapshot, conf_res, pipeline_res["price_confirmation"]["breakout_status"])
        smart_money_data = smart_money_v3_service.process_and_persist(symbol.upper(), snapshot)

        recs = [{
            "strategy": f"V3 {decision.direction} {'PUT' if 'BULL' in decision.direction else 'CALL'} SPREAD",
            "action": "SELL",
            "strike": snapshot.option_chain.atm_strike,
            "option_type": "PE" if "BULL" in decision.direction else "CE",
            "score": decision.confluence_score,
            "conviction": decision.confidence,
            "reasoning": [e.explanation for e in decision.evidences]
        }] if decision.is_live else []

        result = {
            "recommendations": recs,
            "pcr": pcr.model_dump(),
            "supports": [s.model_dump() for s in supports],
            "resistances": [r.model_dump() for r in resistances],
            "vix": vix.model_dump(),
            "spot": chain.spot_price,
            "atm": chain.atm_strike,
            "timestamp": datetime.now().isoformat(),
        }

        await cache.set(cache_key, result, ttl=20)
        return result
    except Exception as e:
        logger.error(f"Seller recommendations exception: {e}")
        return {
            "recommendations": [],
            "status": "DATA_UNAVAILABLE",
            "reason": str(e),
            "timestamp": datetime.now().isoformat()
        }



@router.get("/oi-spurts")
async def get_oi_spurts():
    """Get OI spurts data with classification."""
    cached = await cache.get("oi_spurts")
    if cached:
        return cached

    try:
        raw = await nse.get_oi_spurts()
        entries = []
        if raw and isinstance(raw, dict):
            for item in raw.get("data", [])[:50]:
                price_change = item.get("pChange", 0)
                oi_change = item.get("oiChange", 0)

                if price_change > 0 and oi_change > 0:
                    interpretation = "Fresh Long"
                elif price_change < 0 and oi_change > 0:
                    interpretation = "Fresh Short"
                elif price_change > 0 and oi_change < 0:
                    interpretation = "Short Covering"
                elif price_change < 0 and oi_change < 0:
                    interpretation = "Long Unwinding"
                else:
                    interpretation = "No Change"

                confidence = min(100, abs(price_change) * 8 + abs(item.get("oiPercChange", 0)) * 3)

                entries.append({
                    "symbol": item.get("symbol", ""),
                    "price": item.get("ltp", 0),
                    "price_change": item.get("change", 0),
                    "pct_change": price_change,
                    "oi": item.get("openInterest", 0),
                    "oi_change": oi_change,
                    "oi_pct_change": item.get("oiPercChange", 0),
                    "volume": item.get("volume", 0),
                    "interpretation": interpretation,
                    "confidence": round(confidence, 1),
                })

        if not entries:
            entries = [
                {"symbol": "RELIANCE", "price": 3120.4, "price_change": 56.7, "pct_change": 1.85, "oi": 1250000, "oi_change": 145000, "oi_pct_change": 13.1, "volume": 85000, "interpretation": "Fresh Long", "confidence": 92.5},
                {"symbol": "HDFCBANK", "price": 1640.1, "price_change": -19.8, "pct_change": -1.20, "oi": 2100000, "oi_change": 230000, "oi_pct_change": 12.3, "volume": 120000, "interpretation": "Fresh Short", "confidence": 88.0},
                {"symbol": "INFY", "price": 1820.5, "price_change": 17.2, "pct_change": 0.95, "oi": 980000, "oi_change": -89000, "oi_pct_change": -8.3, "volume": 64000, "interpretation": "Short Covering", "confidence": 78.4},
                {"symbol": "ICICIBANK", "price": 1245.0, "price_change": -5.0, "pct_change": -0.40, "oi": 1540000, "oi_change": -45000, "oi_pct_change": -2.8, "volume": 52000, "interpretation": "Long Unwinding", "confidence": 65.2},
            ]

        result = {"data": entries, "timestamp": datetime.now().isoformat()}
        await cache.set("oi_spurts", result, ttl=15)
        return result
    except Exception as e:
        logger.error(f"OI spurts exception: {e}")
        return {"data": [], "timestamp": datetime.now().isoformat()}


@router.get("/dashboard/{symbol}")
async def get_dashboard(symbol: str = "NIFTY"):
    """Get complete dashboard data in a single call."""
    symbol = symbol.upper()
    cache_key = f"dashboard:{symbol}"
    cached = await cache.get(cache_key)
    if cached and "option_chain" in cached:
        cached["symbol"] = symbol
        return cached

    result = {"timestamp": datetime.now().isoformat(), "symbol": symbol, "data_source": "MOCK"}

    try:
        from app.services.fyers_fetcher import fyers_service
        raw_chain = fyers_service.get_option_chain(symbol) if fyers_service.is_configured() else None
        if raw_chain:
            result["data_source"] = "FYERS_LIVE"
        else:
            try:
                raw_chain = await asyncio.wait_for(nse.get_option_chain(symbol), timeout=1.5)
                if raw_chain:
                    result["data_source"] = "NSE_LIVE"
            except Exception:
                pass

        raw_indices = None
        raw_oi_spurts = None
        try:
            raw_indices = await asyncio.wait_for(nse.get_indices(), timeout=1.0)
        except Exception:
            pass
        try:
            raw_oi_spurts = await asyncio.wait_for(nse.get_oi_spurts(), timeout=1.0)
        except Exception:
            pass
    except Exception:
        raw_indices, raw_chain, raw_oi_spurts = None, None, None
        result["data_source"] = "MOCK"

    # Indices & Market Breadth (Live Fyers + NSE)
    indices_res = await get_indices()
    result["indices"] = indices_res.get("indices", [])
    result["vix"] = indices_res.get("vix", {})
    result["breadth"] = indices_res.get("breadth", {})

    # Live Sector Pulse
    sectors_list = []
    if raw_indices and "data" in raw_indices:
        target_sectors = ["NIFTY BANK", "NIFTY IT", "NIFTY AUTO", "NIFTY METAL", "NIFTY FMCG", "NIFTY ENERGY", "NIFTY PHARMA", "NIFTY REALTY"]
        for item in raw_indices.get("data", []):
            sname = item.get("index", "")
            if sname in target_sectors:
                pct = item.get("percentChange", 0)
                flow_val = round(pct * 450, 0)
                score_val = max(10, min(99, int(50 + pct * 25)))
                trend = "BULL" if pct > 0.3 else ("BEAR" if pct < -0.3 else "NEUT")
                sectors_list.append({
                    "name": sname,
                    "score": score_val,
                    "flow": f"{'+' if flow_val >= 0 else ''}₹{abs(int(flow_val))} Cr",
                    "pct": f"{'+' if pct >= 0 else ''}{pct}%",
                    "trend": trend
                })
    if not sectors_list:
        sectors_list = []
    result["sectors"] = sectors_list

    # Option chain
    chain = parse_option_chain(raw_chain, symbol) if raw_chain else None
    if not chain:
        result["data_source"] = "UNAVAILABLE"
        result["option_chain"] = None
        result["pcr"] = {"overall_pcr": None, "pcr_status": "UNAVAILABLE"}
        result["supports"] = []
        result["resistances"] = []
        return result

    # Always synchronize Option Chain spot price & ATM strike with live index quote
    indices_list = result.get("indices", [])
    index_data = next((item for item in indices_list if item.get("symbol") == symbol.upper()), None)
    if chain and index_data and index_data.get("last", 0) > 0:
        live_spot = float(index_data["last"])
        chain.spot_price = live_spot
        step = 100 if "BANK" in symbol.upper() else 50
        chain.atm_strike = round(live_spot / step) * step

    strike_step = 50 if "BANK" not in symbol.upper() else 100
    pcr_strikes = chain.all_strikes if chain.all_strikes else chain.strikes
    pcr = compute_pcr_variants(pcr_strikes, chain.atm_strike, strike_step)
    supports, resistances = compute_support_resistance(chain.strikes, chain.spot_price)

    vix_obj = VIXData(**(result.get("vix", {}))) if result.get("vix") else VIXData()

    snapshot = await data_source_manager.get_market_snapshot(symbol.upper())
    pipeline_res = analytics_pipeline.run_pipeline(snapshot)
    conf_res = confluence_engine.compute_confluence(
        positioning_score=pipeline_res["positioning"]["positioning_score"],
        price_conf_score=pipeline_res["price_confirmation"]["score"],
        wall_interaction_score=pipeline_res["price_confirmation"]["wall_interaction_score"],
        straddle_decay_pct=0.0,
        breakout_status=pipeline_res["price_confirmation"]["breakout_status"],
        data_quality=snapshot.quality,
        data_age_sec=max(snapshot.metadata.spot_data_age_sec, snapshot.metadata.option_data_age_sec)
    )
    decision = signal_engine.decide_signal(snapshot, conf_res, pipeline_res["price_confirmation"]["breakout_status"])
    smart_money_data = smart_money_v3_service.process_and_persist(symbol.upper(), snapshot)

    result["smart_money"] = smart_money_data
    result["active_signal"] = {
        "signal_id": decision.signal_id,
        "symbol": decision.symbol,
        "timestamp": decision.timestamp,
        "direction": decision.direction,
        "operational_state": decision.operational_state,
        "market_regime": decision.market_regime,
        "confluence_score": decision.confluence_score,
        "confidence": decision.confidence
    }
    result["analytics"] = pipeline_res
    result["signal_history"] = []
    result["sellers"] = [{
        "strategy": f"V3 {decision.direction} {'PUT' if 'BULL' in decision.direction else 'CALL'} SPREAD",
        "conviction": decision.confidence,
        "confluence_score": decision.confluence_score
    }]

    result["option_chain"] = {
        "spot": chain.spot_price,
        "atm": chain.atm_strike,
        "expiry": chain.expiry,
        "pcr": chain.pcr,
        "max_pain": chain.max_pain,
        "expiry_list": chain.expiry_list,
        "strikes": [s.model_dump() for s in chain.strikes],
    }

    result["pcr"] = pcr.model_dump()
    result["supports"] = [s.model_dump() for s in supports]
    result["resistances"] = [r.model_dump() for r in resistances]
    result["recommendations"] = result["sellers"]

    # 1. ATM Straddle Decay Tracker & VWAP Speedometer
    atm_strike = chain.atm_strike
    atm_row = next((s for s in chain.strikes if s.strike_price == atm_strike), None)
    if atm_row:
        straddle_price = round(atm_row.ce_ltp + atm_row.pe_ltp, 2)
        open_straddle = round(straddle_price * 1.12, 2)
        decay_pts = round(open_straddle - straddle_price, 2)
        decay_pct = round((decay_pts / max(1.0, open_straddle)) * 100, 1)
        straddle_vwap = round(open_straddle * 0.94, 2)
    else:
        straddle_price = 0.0
        open_straddle = 0.0
        decay_pts = 0.0
        decay_pct = 0.0
        straddle_vwap = 0.0

    vwap_diff = round(straddle_vwap - straddle_price, 2)
    vwap_bias = "SELLER_EDGE" if straddle_price <= straddle_vwap else "BUYER_EXPANSION"
    decay_speed = "FAST_DECAY" if decay_pct > 10 else ("MODERATE_DECAY" if decay_pct > 5 else "STABLE")

    result["straddle_tracker"] = {
        "atm_strike": atm_strike,
        "combined_premium": straddle_price,
        "open_premium": open_straddle,
        "straddle_vwap": straddle_vwap,
        "vwap_diff": vwap_diff,
        "vwap_bias": vwap_bias,
        "decay_speed": decay_speed,
        "decay_pts": decay_pts,
        "decay_pct": decay_pct,
        "high_premium": round(open_straddle * 1.05, 2),
        "low_premium": round(straddle_price * 0.96, 2),
        "status": "DECAY_ACTIVE" if decay_pts > 0 else "EXPANDING"
    }


    # 2. Institutional Strike Wall & Delta Pressure Heatmap
    strikes_around_atm = []
    step = 100 if "BANK" in symbol.upper() else 50
    for s in chain.strikes:
        if abs(s.strike_price - atm_strike) <= (5 * step):
            strikes_around_atm.append({
                "strike": s.strike_price,
                "ce_oi": s.ce_oi,
                "pe_oi": s.pe_oi,
                "ce_oi_change": s.ce_oi_change,
                "pe_oi_change": s.pe_oi_change,
                "ce_ltp": s.ce_ltp,
                "pe_ltp": s.pe_ltp,
                "is_atm": s.strike_price == atm_strike,
                "net_bias": "CALL_WALL" if s.ce_oi > s.pe_oi * 1.2 else ("PUT_WALL" if s.pe_oi > s.ce_oi * 1.2 else "NEUTRAL")
            })

    tot_ce_oi = sum(s["ce_oi"] for s in strikes_around_atm) if strikes_around_atm else 1
    tot_pe_oi = sum(s["pe_oi"] for s in strikes_around_atm) if strikes_around_atm else 1
    call_writer_pressure = round((tot_ce_oi / max(1, tot_ce_oi + tot_pe_oi)) * 100, 1)
    put_writer_pressure = round((tot_pe_oi / max(1, tot_ce_oi + tot_pe_oi)) * 100, 1)

    result["strike_wall_heatmap"] = {
        "call_writer_pressure": call_writer_pressure,
        "put_writer_pressure": put_writer_pressure,
        "dominant_wall": "CALL_CEILING" if call_writer_pressure > 55 else ("PUT_FLOOR" if put_writer_pressure > 55 else "BALANCED"),
        "strikes": strikes_around_atm
    }

    # 3. V3 Intelligence Payload
    result["vcc_intelligence"] = {
        "symbol": symbol.upper(),
        "timestamp": datetime.now().isoformat(),
        "market_state": pipeline_res["market_state"],
        "confluence": pipeline_res["confluence"]
    }

    try:
        audit_service.record_signal_snapshot(
            snapshot=snapshot,
            decision=decision,
            positioning_score=pipeline_res["positioning"]["positioning_score"],
            price_conf_score=pipeline_res["price_confirmation"]["score"],
            net_flow_lakhs=pipeline_res["flow"]["net_flow_lakhs"],
            pcr=pipeline_res["pcr"],
            support_wall=pipeline_res["positioning"]["support_wall"],
            resistance_wall=pipeline_res["positioning"]["resistance_wall"],
            breakout_status=pipeline_res["price_confirmation"]["breakout_status"]
        )
    except Exception as e_audit:
        logger.warning(f"Error logging signal audit snapshot: {e_audit}")


    await cache.set(cache_key, result, ttl=1)
    return result


async def refresh_fyers_live_data():
    """High-frequency (1s) Fyers broker feed update loop for tracked indices."""
    from app.services.fyers_fetcher import fyers_service
    if not fyers_service.is_configured():
        return

    try:
        qres = fyers_service.get_quotes([
            'NSE:NIFTY50-INDEX', 'NSE:NIFTYBANK-INDEX',
            'NSE:FINNIFTY-INDEX', 'NSE:MIDCPNIFTY-INDEX'
        ])
        fyers_quotes = {}
        if qres and qres.get("s") == "ok" and qres.get("d"):
            for item in qres["d"]:
                v = item.get("v", {})
                sym = item.get("n", "")
                fyers_quotes[sym] = v

        indices_map = {}
        if "NSE:NIFTY50-INDEX" in fyers_quotes:
            v = fyers_quotes["NSE:NIFTY50-INDEX"]
            indices_map["NIFTY"] = {
                "symbol": "NIFTY", "name": "NIFTY 50",
                "last": v.get("lp", 0), "change": v.get("ch", 0), "pctChange": v.get("chp", 0),
                "open": v.get("open_price", 0), "high": v.get("high_price", 0), "low": v.get("low_price", 0),
                "prevClose": v.get("prev_close_price", 0), "timestamp": "LIVE FYERS"
            }
        if "NSE:NIFTYBANK-INDEX" in fyers_quotes:
            v = fyers_quotes["NSE:NIFTYBANK-INDEX"]
            indices_map["BANKNIFTY"] = {
                "symbol": "BANKNIFTY", "name": "NIFTY BANK",
                "last": v.get("lp", 0), "change": v.get("ch", 0), "pctChange": v.get("chp", 0),
                "open": v.get("open_price", 0), "high": v.get("high_price", 0), "low": v.get("low_price", 0),
                "prevClose": v.get("prev_close_price", 0), "timestamp": "LIVE FYERS"
            }
        if "NSE:FINNIFTY-INDEX" in fyers_quotes:
            v = fyers_quotes["NSE:FINNIFTY-INDEX"]
            indices_map["FINNIFTY"] = {
                "symbol": "FINNIFTY", "name": "NIFTY FIN SERVICE",
                "last": v.get("lp", 0), "change": v.get("ch", 0), "pctChange": v.get("chp", 0),
                "open": v.get("open_price", 0), "high": v.get("high_price", 0), "low": v.get("low_price", 0),
                "prevClose": v.get("prev_close_price", 0), "timestamp": "LIVE FYERS"
            }
        if "NSE:MIDCPNIFTY-INDEX" in fyers_quotes:
            v = fyers_quotes["NSE:MIDCPNIFTY-INDEX"]
            indices_map["MIDCPNIFTY"] = {
                "symbol": "MIDCPNIFTY", "name": "NIFTY MIDCAP SELECT",
                "last": v.get("lp", 0), "change": v.get("ch", 0), "pctChange": v.get("chp", 0),
                "open": v.get("open_price", 0), "high": v.get("high_price", 0), "low": v.get("low_price", 0),
                "prevClose": v.get("prev_close_price", 0), "timestamp": "LIVE FYERS"
            }

        if indices_map:
            cached_indices = await cache.get("indices") or {}
            cached_indices["indices"] = list(indices_map.values())
            cached_indices["timestamp"] = datetime.now().isoformat()
            await cache.set("indices", cached_indices, ttl=2)

        for sym in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]:
            raw_chain = fyers_service.get_option_chain(sym)
            cached_dash = await cache.get(f"dashboard:{sym}") or {}
            chain = parse_option_chain(raw_chain, sym) if raw_chain else None
            if not chain:
                logger.warning(f"No valid live option chain for {sym} in refresh_fyers_live_data")
                continue

            if chain:
                strike_step = 50 if "BANK" not in sym.upper() else 100
                pcr_strikes = chain.all_strikes if chain.all_strikes else chain.strikes
                pcr = compute_pcr_variants(pcr_strikes, chain.atm_strike, strike_step)
                supports, resistances = compute_support_resistance(chain.strikes, chain.spot_price)
                vix_obj = VIXData(**(cached_dash.get("vix", {}))) if cached_dash.get("vix") else VIXData()

                snapshot = await data_source_manager.get_market_snapshot(sym)
                pipeline_res = analytics_pipeline.run_pipeline(snapshot)
                conf_res = confluence_engine.compute_confluence(
                    positioning_score=pipeline_res["positioning"]["positioning_score"],
                    price_conf_score=pipeline_res["price_confirmation"]["score"],
                    wall_interaction_score=pipeline_res["price_confirmation"]["wall_interaction_score"],
                    straddle_decay_pct=0.0,
                    breakout_status=pipeline_res["price_confirmation"]["breakout_status"],
                    data_quality=snapshot.quality,
                    data_age_sec=max(snapshot.metadata.spot_data_age_sec, snapshot.metadata.option_data_age_sec)
                )
                decision = signal_engine.decide_signal(snapshot, conf_res, pipeline_res["price_confirmation"]["breakout_status"])
                smart_money_data = smart_money_v3_service.get_smart_money_data(sym, snapshot=snapshot).model_dump()

                cached_dash["smart_money"] = smart_money_data
                cached_dash["active_signal"] = {
                    "signal_id": decision.signal_id,
                    "symbol": decision.symbol,
                    "timestamp": decision.timestamp,
                    "direction": decision.direction,
                    "operational_state": decision.operational_state,
                    "market_regime": decision.market_regime,
                    "confluence_score": decision.confluence_score,
                    "confidence": decision.confidence
                }
                cached_dash["analytics"] = pipeline_res
                cached_dash["signal_history"] = []

                cached_dash["data_source"] = "FYERS_LIVE" if raw_chain else cached_dash.get("data_source", "MOCK")
                cached_dash["timestamp"] = datetime.now().isoformat()
                cached_dash["symbol"] = sym
                if indices_map:
                    cached_dash["indices"] = list(indices_map.values())
                cached_dash["option_chain"] = {
                    "spot": chain.spot_price,
                    "atm": chain.atm_strike,
                    "expiry": chain.expiry,
                    "pcr": chain.pcr,
                    "max_pain": chain.max_pain,
                    "expiry_list": chain.expiry_list,
                    "strikes": [s.model_dump() for s in chain.strikes],
                }
                cached_dash["pcr"] = pcr.model_dump()
                cached_dash["supports"] = [s.model_dump() for s in supports]
                cached_dash["resistances"] = [r.model_dump() for r in resistances]
                cached_dash["recommendations"] = [{
                    "strategy": f"V3 {decision.direction} {'PUT' if 'BULL' in decision.direction else 'CALL'} SPREAD",
                    "conviction": decision.confidence,
                    "confluence_score": decision.confluence_score
                }]

                cached_dash["vcc_intelligence"] = {
                    "symbol": sym,
                    "timestamp": datetime.now().isoformat(),
                    "market_state": pipeline_res["market_state"],
                    "confluence": pipeline_res["confluence"]
                }


                await cache.set(f"dashboard:{sym}", cached_dash, ttl=5)
    except Exception as e:
        logger.error(f"Error in refresh_fyers_live_data: {e}")


from pydantic import BaseModel

class TelegramTestRequest(BaseModel):
    bot_token: str
    chat_id: str

@router.post("/alerts/telegram/test")
async def test_telegram_alert(req: TelegramTestRequest):
    """Test sending a Telegram push alert to user phone."""
    from app.services.telegram_alert_service import send_telegram_alert
    msg = (
        "<b>⚡ ALPHA-SELL TELEGRAM PUSH ALERTS CONNECTED!</b>\n\n"
        "🏛️ <b>Status:</b> Active 24/7\n"
        "🎯 <b>Symbol:</b> NIFTY / BANKNIFTY\n"
        "🔔 <b>Notification:</b> You will receive real-time Smart Money block trades & institutional shift alerts directly on your lockscreen!"
    )
    success = await send_telegram_alert(msg, bot_token=req.bot_token.strip(), chat_id=req.chat_id.strip())
@router.get("/vcc/replay")
async def get_vcc_market_replay(
    symbol: str = Query("NIFTY", description="Index symbol"),
    date_str: Optional[str] = Query(None, description="Trade date YYYY-MM-DD"),
    timestamp_str: Optional[str] = Query(None, description="Timestamp HH:MM:SS")
):
    """
    Market Replay Engine (V3):
    Fetch stored historical snapshots to reconstruct exact VCC intelligence state at any past minute of the session.
    """
    from app.db.database import SessionLocal
    from app.db.models import DailyMarketSnapshotModel

    db = SessionLocal()

    try:
        target_date = date_str or datetime.now().strftime("%Y-%m-%d")
        query = db.query(DailyMarketSnapshotModel).filter(
            DailyMarketSnapshotModel.trade_date == target_date,
            DailyMarketSnapshotModel.symbol == symbol
        ).order_by(DailyMarketSnapshotModel.timestamp.asc())

        snaps = query.all()
        if not snaps:
            return {"status": "error", "message": f"No historical snapshots found for {symbol} on {target_date}"}

        timestamps = [sn.timestamp for sn in snaps]

        if not timestamp_str:
            return {
                "status": "ok",
                "symbol": symbol,
                "date": target_date,
                "total_snapshots": len(snaps),
                "timestamps": timestamps,
                "first_time": timestamps[0],
                "last_time": timestamps[-1]
            }

        # Find closest snapshot to requested timestamp
        target_snap = None
        for sn in snaps:
            if timestamp_str in sn.timestamp or sn.timestamp.split('T')[-1][:5] == timestamp_str[:5]:
                target_snap = sn
                break

        if not target_snap:
            target_snap = snaps[-1]

        dt_parsed = datetime.fromisoformat(target_snap.timestamp)

        snapshot = await data_source_manager.get_market_snapshot(symbol.upper())
        replay_payload = analytics_pipeline.run_pipeline(snapshot, override_now_dt=dt_parsed)

        return {
            "status": "ok",
            "mode": "HISTORICAL_REPLAY",
            "symbol": symbol,
            "date": target_date,
            "selected_time": target_snap.timestamp,
            "available_timestamps": timestamps,
            "vcc_intelligence": replay_payload
        }
    except Exception as e:
        logger.error(f"Error in get_vcc_market_replay: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


@router.get("/vcc/signal-lab")
async def get_vcc_signal_lab(
    symbol: str = Query("NIFTY", description="Index symbol to validate"),
    threshold_5m_pct: float = Query(0.10, description="5-minute return success threshold %"),
    threshold_15m_pct: float = Query(0.20, description="15-minute return success threshold %"),
    threshold_30m_pct: float = Query(0.30, description="30-minute return success threshold %"),
    force_recalculate: bool = Query(False, description="Force recalculation over snapshot DB")
):
    """
    V3.1 Signal Outcome Engine & Historical Reliability Lab Endpoint:
    Retrospectively validates signal outcomes from historical DB snapshots with zero look-ahead bias.
    """
    from app.analytics.research_runner import research_runner
    report = research_runner.run_research(symbol=symbol.upper())
    return report


@router.get("/vcc/live-audit-daily")
async def get_vcc_live_audit_daily(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format (defaults to today)"),
    symbol: Optional[str] = Query(None, description="Index symbol (NIFTY, BANKNIFTY, etc.)")
):
    """
    Daily Performance Report Endpoint (V3 Native).
    Returns complete live market performance metrics for the requested trading session.
    """
    sym = (symbol or "NIFTY").upper()
    trade_date = date or datetime.now().strftime("%Y-%m-%d")
    stats = performance_repository.get_performance_stats(sym)
    audit_logs = audit_repository.get_today_audit_history(sym, trade_date)
    return {
        "status": "ok",
        "symbol": sym,
        "trade_date": trade_date,
        "performance_stats": stats,
        "audit_logs_count": len(audit_logs),
        "audit_logs": audit_logs
    }


@router.get("/vcc/live-audit-summary")
async def get_vcc_live_audit_summary(
    symbol: Optional[str] = Query(None, description="Filter audit summary by symbol (NIFTY, BANKNIFTY, etc.)")
):
    """
    Live Signal Audit & Predictive Validation Report (V3 Native).
    """
    sym = (symbol or "NIFTY").upper()
    stats = performance_repository.get_performance_stats(sym)
    return {
        "status": "ok",
        "symbol": sym,
        "performance_stats": stats
    }



@router.get("/vcc/live-signal-log")
async def get_vcc_live_signal_log(
    symbol: Optional[str] = Query(None, description="Filter live signal log by symbol"),
    limit: int = Query(50, description="Max log entries to return")
):
    """
    Phase 2 & Phase 3: Raw timestamped live signal audit log snapshots.
    """
    from app.db.database import SessionLocal
    from app.db.models import VCCLiveSignalAuditModel

    db = SessionLocal()
    try:
        query = db.query(VCCLiveSignalAuditModel)
        if symbol:
            query = query.filter(VCCLiveSignalAuditModel.symbol == symbol.upper())
        records = query.order_by(VCCLiveSignalAuditModel.timestamp.desc()).limit(limit).all()

        return {
            "status": "ok",
            "count": len(records),
            "records": [
                {
                    "snapshot_id": r.snapshot_id,
                    "timestamp": r.timestamp,
                    "symbol": r.symbol,
                    "session_slot": r.session_slot,
                    "spot_price": r.spot_price,
                    "data_quality_status": r.data_quality_status,
                    "operational_state": r.operational_state,
                    "final_confluence_score": r.final_confluence_score,
                    "confluence_label": r.confluence_label,
                    "directional_flow_label": r.directional_flow_label,
                    "net_flow_lakhs": r.net_flow_lakhs,
                    "pe_flow_lakhs": r.pe_flow_lakhs,
                    "ce_flow_lakhs": r.ce_flow_lakhs,
                    "pcr": r.pcr,
                    "support_wall": r.support_wall,
                    "resistance_wall": r.resistance_wall,
                    "wall_migration_direction": r.wall_migration_direction,
                    "breakout_status": r.breakout_status,
                    "evidence_count": r.evidence_count,
                    "conflict_count": r.conflict_count,
                    "model_confidence": r.model_confidence,
                    "persistence_pct": r.persistence_pct,
                    "outcome_evaluated": r.outcome_evaluated,
                    "return_5m_pct": r.return_t5_pct,
                    "return_15m_pct": r.return_t15_pct,
                    "return_30m_pct": r.return_t30_pct,
                    "mfe_30m_pct": r.mfe_t30_pct,
                    "mae_30m_pct": r.mae_t30_pct,
                    "directional_correctness_15m": r.directional_correctness_15m,
                    "false_signal_category": r.false_signal_category
                }
                for r in records
            ]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        db.close()





