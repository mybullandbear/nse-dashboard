"""
Smart Money V3.2 Presentation API Endpoints
Provides datewise smart money tracking, conviction metrics, block trades, and historical date query endpoints.
Fully decoupled from legacy intelligence pipeline.
"""
from fastapi import APIRouter, Query
from typing import Optional

from app.smart_money.service import smart_money_v3_service
from app.repositories.smart_money_repository import smart_money_repository

router = APIRouter(prefix="/api/smart-money", tags=["Smart Money"])


@router.get("/dates")
def get_smart_money_dates():
    """Get list of distinct dates stored in database for historical comparison."""
    dates = smart_money_repository.get_available_dates()
    return {"dates": dates}


@router.get("/{symbol}")
def get_smart_money_by_symbol(symbol: str, date: Optional[str] = Query(None)):
    """Fetch datewise Smart Money tracking data for symbol using V3 Smart Money engine."""
    res = smart_money_v3_service.get_smart_money_data(symbol.upper(), target_date=date)
    return res.model_dump()
