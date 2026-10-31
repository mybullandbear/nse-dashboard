"""
Smart OI Interrelated Multi-Pane Analytics Router
StockMojo-style synchronous Candlestick, Smart OI Flow, Cumulative OI Change & Dual PCR
"""
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Query, HTTPException
from app.db.storage import snapshot_storage
from app.services.fyers_service import fyers_service
from app.services.option_chain import parse_option_chain
from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/smart-oi", tags=["smart-oi"])


@router.get("/trend/{symbol}")
async def get_smart_oi_trend(
    symbol: str,
    interval: int = Query(5, description="Candle interval in minutes (1, 3, 5, 15)"),
    date: Optional[str] = Query(None, description="Trade date in YYYY-MM-DD format"),
    range_mode: Optional[str] = Query("ALL", description="Strike range mode (ALL, 5, 10, 15)")
) -> Dict[str, Any]:
    """
    Returns interrelated series matching the StockMojo layout:
    1. Candlestick OHLC + Volume + Smart OI Delta bars
    2. Cumulative Day Change: Put OI (Cr), Call OI (Cr), PE - CE (Cr)
    3. Dual PCR Oscillators: OI PCR, Vol PCR
    4. Expiries & Strike Bounds
    """
    sym = symbol.upper()
    settings = get_settings()
    step = settings.STRIKE_STEPS.get(sym, 50)

    # 1. Fetch time series from SQLite
    res = snapshot_storage.get_smart_oi_series(
        symbol=sym,
        trade_date=date,
        interval_min=interval,
        strike_range=range_mode
    )

    # 2. Add metadata: expiries and strike bounds
    expiries: List[str] = []
    spot = res.get("current_spot", 0.0)

    try:
        raw_chain = fyers_service.get_option_chain(sym)
        if raw_chain:
            parsed = parse_option_chain(raw_chain, sym)
            if parsed:
                expiries = parsed.expiry_list
                if not spot:
                    spot = parsed.spot_price
    except Exception as e:
        logger.debug(f"Could not fetch live expiries: {e}")

    if not expiries:
        expiries = ["22 Sep 2026 (6d)", "29 Sep 2026 (13d)", "06 Oct 2026 (20d)", "29 Oct 2026 (43d)"]

    atm_strike = round(spot / step) * step if spot > 0 else 23200
    min_strike = atm_strike - (25 * step)
    max_strike = atm_strike + (25 * step)

    res["atm_strike"] = atm_strike
    res["step"] = step
    res["strike_bounds"] = {
        "min": min_strike,
        "max": max_strike,
        "label": f"({min_strike} - {max_strike})"
    }
    res["expiries"] = expiries
    res["selected_expiry"] = expiries[0] if expiries else ""

    return res


@router.get("/dates/{symbol}")
async def get_trading_dates(symbol: str) -> Dict[str, Any]:
    """Returns available historical trading dates in storage for the symbol."""
    sym = symbol.upper()
    dates = snapshot_storage.get_available_dates(sym)
    return {"symbol": sym, "dates": dates}
