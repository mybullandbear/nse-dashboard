"""
Price vs OI Matrix API Router (StockMojo Parity)
Provides multi-pane intraday synchronized series for any chosen strike:
1. Call Price vs Put Price (LTP Overlay)
2. Straddle Price (CE+PE combined premium) + Strike PCR
3. Absolute Call OI vs Put OI accumulation
4. Net Intraday Call OI Change vs Put OI Change
5. CE Price vs CE OI Divergence
6. PE Price vs PE OI Divergence
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
router = APIRouter(prefix="/api/price-vs-oi", tags=["price-vs-oi"])


@router.get("/data/{symbol}")
async def get_price_vs_oi_data(
    symbol: str,
    strike: Optional[float] = Query(None, description="Target strike price (e.g. 23350)"),
    trade_date: Optional[str] = Query(None, description="Optional trade date 'YYYY-MM-DD'"),
    interval: int = Query(1, description="Interval in minutes (1, 3, 5, 15)"),
    mode: str = Query("AUTO", description="Mode: 'AUTO', 'LIVE', or 'HISTORICAL'")
) -> Dict[str, Any]:
    """
    Returns full synchronized 6-chart series and strike catalog for the specified symbol.
    """
    sym = symbol.upper()
    market_live = is_market_open()
    requested_mode = mode.upper()
    
    # 1. Determine execution mode
    is_live_query = (requested_mode == "LIVE") or (requested_mode == "AUTO" and market_live and not trade_date)

    # 2. Historical or Market Closed query from SQLite
    if not is_live_query:
        series_data = snapshot_storage.get_single_strike_series(
            symbol=sym,
            strike=strike,
            trade_date=trade_date,
            interval_min=interval
        )
        
        # Check if live chain has expiry list to augment metadata
        expiry_dates = []
        try:
            raw_chain, _ = await fetch_live_chain_data(sym)
            parsed = parse_option_chain(raw_chain, sym) if raw_chain else None
            if parsed and parsed.expiry_dates:
                expiry_dates = parsed.expiry_dates[:5]
        except Exception:
            pass

        return {
            "symbol": sym,
            "mode": "HISTORICAL",
            "is_market_open": market_live,
            "is_live": False,
            "source": "MARKET_CLOSED" if not market_live else "HISTORICAL_DB",
            "trade_date": series_data.get("trade_date"),
            "strike": series_data.get("strike"),
            "atm_strike": series_data.get("atm_strike"),
            "spot_price": series_data.get("spot_price"),
            "interval": interval,
            "expiry_dates": expiry_dates,
            "available_strikes": series_data.get("available_strikes", []),
            "available_dates": series_data.get("available_dates", []),
            "series": series_data.get("series", []),
            "latest": series_data.get("latest", {})
        }

    # 3. Live Market Mode: Merge SQLite intraday history with current live option chain tick
    raw_chain, source = await fetch_live_chain_data(sym)
    parsed = parse_option_chain(raw_chain, sym) if raw_chain else None

    # Retrieve base intraday series from SQLite for today
    today_str = get_current_ist().strftime("%Y-%m-%d")
    series_data = snapshot_storage.get_single_strike_series(
        symbol=sym,
        strike=strike,
        trade_date=today_str,
        interval_min=interval
    )

    available_strikes = series_data.get("available_strikes", [])
    atm_val = series_data.get("atm_strike")
    spot_val = series_data.get("spot_price")
    expiry_dates = []

    if parsed:
        atm_val = parsed.atm_strike
        spot_val = parsed.spot_price
        expiry_dates = parsed.expiry_dates[:5] if parsed.expiry_dates else []

        # If available strikes was empty from DB, build from parsed live chain
        if not available_strikes and parsed.strikes:
            settings = get_settings()
            step = settings.STRIKE_STEPS.get(sym, 50)
            target_strikes = [s for s in parsed.strikes if abs(s.strikePrice - atm_val) <= (10 * step)]
            available_strikes = [
                {"strike": float(s.strikePrice), "is_atm": (s.strikePrice == atm_val)}
                for s in target_strikes
            ]

    selected_strike = float(strike) if (strike is not None and strike > 0) else (atm_val or 0.0)
    series_points = series_data.get("series", [])

    # If parsed live chain has this strike, append or update the latest live minute
    if parsed and selected_strike > 0:
        matching_stk = next((s for s in parsed.strikes if s.strikePrice == selected_strike), None)
        if matching_stk:
            now_ist = get_current_ist()
            now_time = now_ist.strftime("%H:%M")
            c = matching_stk.CE
            p = matching_stk.PE

            ce_ltp = float(c.lastPrice)
            pe_ltp = float(p.lastPrice)
            ce_oi = int(c.openInterest)
            pe_oi = int(p.openInterest)
            ce_oi_chg = int(c.changeinOpenInterest)
            pe_oi_chg = int(p.changeinOpenInterest)
            straddle_price = round(ce_ltp + pe_ltp, 2)
            pcr = round(pe_oi / max(1, ce_oi), 3)

            live_point = {
                "time": now_time,
                "timestamp": now_ist.isoformat(),
                "ce_price": ce_ltp,
                "pe_price": pe_ltp,
                "straddle_price": straddle_price,
                "ce_oi": ce_oi,
                "pe_oi": pe_oi,
                "ce_oi_chg": ce_oi_chg,
                "pe_oi_chg": pe_oi_chg,
                "pcr": pcr
            }

            if not series_points or series_points[-1]["time"] != now_time:
                series_points.append(live_point)
            else:
                series_points[-1] = live_point

    latest = series_points[-1] if series_points else {}

    return {
        "symbol": sym,
        "mode": "LIVE",
        "is_market_open": market_live,
        "is_live": True,
        "source": source,
        "trade_date": today_str,
        "strike": selected_strike,
        "atm_strike": atm_val,
        "spot_price": spot_val,
        "interval": interval,
        "expiry_dates": expiry_dates,
        "available_strikes": available_strikes,
        "available_dates": series_data.get("available_dates", []),
        "series": series_points,
        "latest": latest
    }


@router.get("/dates/{symbol}")
async def get_price_vs_oi_dates(symbol: str) -> Dict[str, Any]:
    """Returns list of real trading dates stored for this symbol."""
    sym = symbol.upper()
    dates = snapshot_storage.get_available_dates(sym)
    return {"symbol": sym, "dates": dates}
