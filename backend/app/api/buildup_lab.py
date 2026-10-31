"""
Strike Buildup Lab API Router
Provides 4-quadrant bubble scatter metrics for ATM +- 5 strikes:
- Price % Change vs OI % Change
- Long Buildup, Short Buildup, Short Covering, Long Unwinding
- Option Seller & Market Sentiment Insights (Call/Put Writing & Buying)
- Timeline playback for intraday slider (09:15 - 15:30 IST)
"""
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Query, HTTPException

from app.services.option_chain import parse_option_chain
from app.api.market import fetch_live_chain_data
from app.db.storage import snapshot_storage
from app.core.config import get_settings
from app.core.market_hours import get_current_ist, is_market_open

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/buildup-lab", tags=["buildup-lab"])


def classify_buildup(option_type: str, price_pchg: float, oi_pchg: float) -> tuple[str, str, str]:
    """
    Returns: (buildup_type, market_sentiment, sentiment_label)
    - buildup_type: LONG_BUILDUP, SHORT_BUILDUP, SHORT_COVERING, LONG_UNWINDING
    - market_sentiment: BULLISH, BEARISH, NEUTRAL
    - sentiment_label: Actionable trader text
    """
    opt = option_type.upper()
    is_price_up = price_pchg >= 0
    is_oi_up = oi_pchg >= 0

    if is_price_up and is_oi_up:
        b_type = "LONG_BUILDUP"
        if opt == "CE":
            m_sent = "BULLISH"
            label = "Call Buying (Bullish Momentum)"
        else:
            m_sent = "BEARISH"
            label = "Put Buying (Bearish Downside Bet)"
    elif not is_price_up and is_oi_up:
        b_type = "SHORT_BUILDUP"
        if opt == "CE":
            m_sent = "BEARISH"
            label = "Call Writing (Bearish Resistance Wall)"
        else:
            m_sent = "BULLISH"
            label = "Put Writing (Bullish Support Cushion)"
    elif is_price_up and not is_oi_up:
        b_type = "SHORT_COVERING"
        if opt == "CE":
            m_sent = "BULLISH"
            label = "Call Short Squeeze (Bears Covering)"
        else:
            m_sent = "BEARISH"
            label = "Put Short Squeeze (Downside Panic)"
    else:
        b_type = "LONG_UNWINDING"
        if opt == "CE":
            m_sent = "BEARISH"
            label = "Call Longs Liquidating (Profit Taking)"
        else:
            m_sent = "BULLISH"
            label = "Put Longs Liquidating (Bulls Rebounding)"

    return b_type, m_sent, label


def format_strike_number(val: float) -> str:
    return str(int(val)) if val.is_integer() else str(val)


@router.get("/strikes/{symbol}")
async def get_strike_buildup(
    symbol: str,
    range: int = Query(5, description="Number of strikes above & below ATM (5, 7, 10)"),
    time_str: Optional[str] = Query(None, description="Optional playback time 'HH:MM'"),
    trade_date: Optional[str] = Query(None, description="Optional trade date 'YYYY-MM-DD'")
) -> Dict[str, Any]:
    """
    Returns ATM +- N strike buildup metrics for the specified symbol.
    - If market is OPEN and time_str is None: returns live market chain.
    - If market is CLOSED or time_str is provided: returns real historical database snapshot.
    """
    sym = symbol.upper()
    settings = get_settings()
    step = settings.STRIKE_STEPS.get(sym, 50)
    strike_range = max(3, min(range, 15))
    market_live = is_market_open()

    # Determine resolved trading date
    avail_dates = snapshot_storage.get_available_dates(sym)
    resolved_date = trade_date
    if not resolved_date:
        if market_live:
            resolved_date = get_current_ist().strftime("%Y-%m-%d")
        else:
            resolved_date = avail_dates[0] if avail_dates else get_current_ist().strftime("%Y-%m-%d")

    # 1. Historical Playback lookup OR Market Closed lookup from SQLite
    if time_str or not market_live:
        timeline = snapshot_storage.get_strike_timeline(sym, resolved_date)
        if timeline:
            matching_slot = None
            if time_str:
                for slot in timeline:
                    if slot["time"] <= time_str:
                        matching_slot = slot
                    elif slot["time"] > time_str:
                        break
            if not matching_slot:
                matching_slot = timeline[-1]  # Market close slot (15:30)

            strikes_data = matching_slot.get("strikes", [])
            atm_val = next((s["strike"] for s in strikes_data if s.get("is_atm")), None)
            if atm_val is None and strikes_data:
                atm_val = strikes_data[len(strikes_data) // 2]["strike"]

            filtered = [s for s in strikes_data if abs(s["strike"] - atm_val) <= (strike_range * step)]
            processed_strikes = []
            counts = {"LONG_BUILDUP": 0, "SHORT_BUILDUP": 0, "SHORT_COVERING": 0, "LONG_UNWINDING": 0}

            for s in filtered:
                stk = s["strike"]
                opt = s["option_type"]
                p_chg = s.get("price_pchange", 0.0)
                oi_chg = s.get("oi_pchange", 0.0)
                b_type, m_sent, s_label = classify_buildup(opt, p_chg, oi_chg)
                counts[b_type] = counts.get(b_type, 0) + 1

                processed_strikes.append({
                    "strike": stk,
                    "option_type": opt,
                    "label": f"{format_strike_number(stk)} {opt}",
                    "ltp": s.get("ltp", 0.0),
                    "price_pchange": round(p_chg, 2),
                    "oi": s.get("oi", 0),
                    "oi_chg": s.get("oi_chg", 0),
                    "oi_pchange": round(oi_chg, 2),
                    "volume": s.get("volume", 0),
                    "is_atm": bool(s.get("is_atm")),
                    "buildup_type": b_type,
                    "market_sentiment": m_sent,
                    "sentiment_label": s_label
                })

            return {
                "symbol": sym,
                "time": matching_slot["time"],
                "trade_date": resolved_date,
                "is_live": False,
                "source": "HISTORICAL_PLAYBACK" if time_str else "MARKET_CLOSED",
                "range": strike_range,
                "atm_strike": atm_val,
                "counts": counts,
                "strikes": processed_strikes
            }

    # 2. Live Data lookup (during official market hours Mon-Fri 09:15-15:30)
    raw_chain, source = await fetch_live_chain_data(sym)
    parsed = parse_option_chain(raw_chain, sym) if raw_chain else None

    if not parsed:
        # Fallback to last recorded session
        timeline = snapshot_storage.get_strike_timeline(sym, resolved_date)
        if timeline:
            last_slot = timeline[-1]
            strikes_data = last_slot.get("strikes", [])
            atm_val = next((s["strike"] for s in strikes_data if s.get("is_atm")), None)
            if atm_val is None and strikes_data:
                atm_val = strikes_data[len(strikes_data) // 2]["strike"]

            filtered = [s for s in strikes_data if abs(s["strike"] - atm_val) <= (strike_range * step)]
            processed_strikes = []
            counts = {"LONG_BUILDUP": 0, "SHORT_BUILDUP": 0, "SHORT_COVERING": 0, "LONG_UNWINDING": 0}

            for s in filtered:
                stk = s["strike"]
                opt = s["option_type"]
                p_chg = s.get("price_pchange", 0.0)
                oi_chg = s.get("oi_pchange", 0.0)
                b_type, m_sent, s_label = classify_buildup(opt, p_chg, oi_chg)
                counts[b_type] = counts.get(b_type, 0) + 1

                processed_strikes.append({
                    "strike": stk,
                    "option_type": opt,
                    "label": f"{format_strike_number(stk)} {opt}",
                    "ltp": s.get("ltp", 0.0),
                    "price_pchange": round(p_chg, 2),
                    "oi": s.get("oi", 0),
                    "oi_chg": s.get("oi_chg", 0),
                    "oi_pchange": round(oi_chg, 2),
                    "volume": s.get("volume", 0),
                    "is_atm": bool(s.get("is_atm")),
                    "buildup_type": b_type,
                    "market_sentiment": m_sent,
                    "sentiment_label": s_label
                })

            return {
                "symbol": sym,
                "time": last_slot["time"],
                "trade_date": resolved_date,
                "is_live": False,
                "source": "MARKET_CLOSED",
                "spot_price": 0.0,
                "atm_strike": atm_val,
                "range": strike_range,
                "counts": counts,
                "strikes": processed_strikes
            }

        now_ist = get_current_ist()
        return {
            "symbol": sym,
            "time": now_ist.strftime("%H:%M"),
            "timestamp": now_ist.isoformat(),
            "trade_date": resolved_date,
            "is_live": False,
            "source": "MARKET_CLOSED",
            "spot_price": 0.0,
            "atm_strike": 0.0,
            "range": strike_range,
            "counts": {"LONG_BUILDUP": 0, "SHORT_BUILDUP": 0, "SHORT_COVERING": 0, "LONG_UNWINDING": 0},
            "strikes": []
        }

    atm = parsed.atm_strike
    spot = parsed.spot_price

    # Filter to ATM +- strike_range
    target_strikes = [s for s in parsed.strikes if abs(s.strikePrice - atm) <= (strike_range * step)]
    if not target_strikes:
        target_strikes = parsed.strikes[:(strike_range * 2 + 1)]

    processed_strikes = []
    counts = {"LONG_BUILDUP": 0, "SHORT_BUILDUP": 0, "SHORT_COVERING": 0, "LONG_UNWINDING": 0}

    for row in target_strikes:
        # CE Contract
        c = row.CE
        c_prev_oi = max(0, c.openInterest - c.changeinOpenInterest)
        c_oi_pchg = (c.changeinOpenInterest / c_prev_oi * 100.0) if c_prev_oi > 0 else (
            100.0 if c.openInterest > 0 and c.changeinOpenInterest > 0 else 0.0
        )
        c_btype, c_msent, c_slabel = classify_buildup("CE", c.pChange, c_oi_pchg)
        counts[c_btype] = counts.get(c_btype, 0) + 1

        processed_strikes.append({
            "strike": row.strikePrice,
            "option_type": "CE",
            "label": f"{format_strike_number(row.strikePrice)} CE",
            "ltp": c.lastPrice,
            "price_pchange": round(c.pChange, 2),
            "oi": c.openInterest,
            "oi_chg": c.changeinOpenInterest,
            "oi_pchange": round(c_oi_pchg, 2),
            "volume": c.totalTradedVolume,
            "is_atm": (row.strikePrice == atm),
            "is_itm": (row.strikePrice < spot),
            "buildup_type": c_btype,
            "market_sentiment": c_msent,
            "sentiment_label": c_slabel
        })

        # PE Contract
        p = row.PE
        p_prev_oi = max(0, p.openInterest - p.changeinOpenInterest)
        p_oi_pchg = (p.changeinOpenInterest / p_prev_oi * 100.0) if p_prev_oi > 0 else (
            100.0 if p.openInterest > 0 and p.changeinOpenInterest > 0 else 0.0
        )
        p_btype, p_msent, p_slabel = classify_buildup("PE", p.pChange, p_oi_pchg)
        counts[p_btype] = counts.get(p_btype, 0) + 1

        processed_strikes.append({
            "strike": row.strikePrice,
            "option_type": "PE",
            "label": f"{format_strike_number(row.strikePrice)} PE",
            "ltp": p.lastPrice,
            "price_pchange": round(p.pChange, 2),
            "oi": p.openInterest,
            "oi_chg": p.changeinOpenInterest,
            "oi_pchange": round(p_oi_pchg, 2),
            "volume": p.totalTradedVolume,
            "is_atm": (row.strikePrice == atm),
            "is_itm": (row.strikePrice > spot),
            "buildup_type": p_btype,
            "market_sentiment": p_msent,
            "sentiment_label": p_slabel
        })

    now_ist = get_current_ist()
    return {
        "symbol": sym,
        "time": now_ist.strftime("%H:%M"),
        "timestamp": now_ist.isoformat(),
        "trade_date": resolved_date,
        "is_live": market_live,
        "source": source if market_live else "MARKET_CLOSED",
        "spot_price": spot,
        "atm_strike": atm,
        "range": strike_range,
        "counts": counts,
        "strikes": processed_strikes
    }


@router.get("/timeline/{symbol}")
async def get_strike_timeline(
    symbol: str,
    range: int = Query(5, description="Strike range (5, 7, 10)"),
    trade_date: Optional[str] = Query(None, description="Optional trade date 'YYYY-MM-DD'")
) -> Dict[str, Any]:
    """
    Returns time series snapshots across the intraday trading session (09:15 - 15:30 IST)
    for playback and slider scrubbing.
    """
    sym = symbol.upper()
    settings = get_settings()
    step = settings.STRIKE_STEPS.get(sym, 50)
    strike_range = max(3, min(range, 15))

    # Resolve date: if None, use today if open, or latest stored weekday date
    resolved_date = trade_date
    if not resolved_date:
        now = get_current_ist()
        if now.weekday() < 5 and is_market_open():
            resolved_date = now.strftime("%Y-%m-%d")
        else:
            avail = snapshot_storage.get_available_dates(sym)
            resolved_date = avail[0] if avail else now.strftime("%Y-%m-%d")

    # Fetch strictly from SQLite storage (Zero Dummy Data)
    stored_timeline = snapshot_storage.get_strike_timeline(sym, resolved_date)
    if stored_timeline:
        enriched_timeline = []
        for slot in stored_timeline:
            slot_time = slot.get("time", "")
            raw_strikes = slot.get("strikes", [])
            enriched_strikes = []
            for s in raw_strikes:
                opt = s.get("option_type", "CE")
                p_chg = float(s.get("price_pchange", 0.0))
                oi_chg = float(s.get("oi_pchange", 0.0))
                b_type, m_sent, s_label = classify_buildup(opt, p_chg, oi_chg)
                enriched_strikes.append({
                    **s,
                    "label": f"{format_strike_number(s.get('strike', 0))} {opt}",
                    "buildup_type": b_type,
                    "market_sentiment": m_sent,
                    "sentiment_label": s_label
                })
            enriched_timeline.append({
                "time": slot_time,
                "strikes": enriched_strikes
            })

        return {
            "symbol": sym,
            "trade_date": resolved_date,
            "count": len(enriched_timeline),
            "timeline": enriched_timeline
        }

    # If no recorded snapshots exist for this date, return empty timeline (no dummy data)
    return {
        "symbol": sym,
        "trade_date": resolved_date,
        "count": 0,
        "timeline": []
    }


@router.get("/dates/{symbol}")
async def get_strike_available_dates(symbol: str) -> Dict[str, Any]:
    """Returns list of real trading dates stored in the database for this symbol."""
    sym = symbol.upper()
    dates = snapshot_storage.get_available_dates(sym)
    return {"symbol": sym, "dates": dates}
