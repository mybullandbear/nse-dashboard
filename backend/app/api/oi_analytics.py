"""
Call vs Put Open Interest Analytics Router
Supplies data for intraday timeline charts, strike-wise comparisons, and wall heatmaps.
"""
import logging
from fastapi import APIRouter, HTTPException
from app.api.market import fetch_live_chain_data
from app.services.option_chain import parse_option_chain
from app.services.oi_analyzer import oi_analyzer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/oi", tags=["oi-analytics"])


@router.get("/analytics/{symbol}")
async def get_oi_analytics(symbol: str = "NIFTY"):
    """
    Returns full Call vs Put Open Interest analytics including:
    - Intraday timeline series (Total OI, Change in OI, Net Difference vs Spot)
    - Strike-by-strike comparative distribution for ATM ± 10 strikes
    - Support & Resistance walls
    - Writer pressure percentages
    - Straddle decay metrics
    """
    sym = symbol.upper()
    raw_chain, source = await fetch_live_chain_data(sym)
    parsed = parse_option_chain(raw_chain, sym)
    if not parsed:
        raise HTTPException(status_code=503, detail=f"Failed to fetch option chain for {sym}")

    analytics = oi_analyzer.analyze(parsed)
    analytics["source"] = source
    return analytics


@router.get("/timeline/{symbol}")
async def get_oi_timeline(symbol: str = "NIFTY"):
    """Returns the intraday Call vs Put OI timeline series."""
    analytics = await get_oi_analytics(symbol)
    return {
        "symbol": symbol.upper(),
        "source": analytics.get("source"),
        "spot_price": analytics.get("spot_price"),
        "timeline": analytics.get("timeline", [])
    }
