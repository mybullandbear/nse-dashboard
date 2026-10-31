"""
Option Confluence Analysis Router
Provides REST API endpoints for the ATM +- 2 Option Confluence Analysis Dashboard:
- Multi-strike matrix (ATM-2, ATM-1, ATM, ATM+1, ATM+2, extensible to +-3 / +-5)
- Layered analytical model: Raw Data -> Derived Flow -> Price Confirmation -> Final Confluence
- Integration with AlphaTrend, TrendDirection, Shonya Gravity, and Proximity MAPO
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.services.option_confluence_service import option_confluence_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/confluence", tags=["confluence"])


@router.get("/{symbol}")
async def get_option_confluence(
    symbol: str = "NIFTY",
    range: int = Query(2, ge=1, le=5, description="Number of strikes above & below ATM to analyze (default: 2)")
):
    """
    Returns complete multi-layered Option Confluence Analysis for the given index symbol across ATM +- range strikes.
    """
    sym = symbol.upper()
    try:
        data = await option_confluence_service.analyze_confluence(sym, range_strikes=range)
        if not data:
            raise HTTPException(status_code=503, detail=f"Failed to generate option confluence analysis for {sym}")
        return data
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error analyzing option confluence for {sym}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
