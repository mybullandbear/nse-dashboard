"""
ShonyaBot Controls and Manual Order Execution Router
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.intelligence.shonya_engine import shonya_engine
from app.core.config import settings
from app.state.market_state_store import market_state

router = APIRouter(prefix="/api/shonya", tags=["shonya_orders"])

class ModeSwitchRequest(BaseModel):
    mode: str # "PAPER" | "LIVE"

class ToggleRequest(BaseModel):
    active: bool

class ManualOrderRequest(BaseModel):
    symbol: str
    strike: float
    option_type: str
    side: str
    quantity: int

@router.get("/status")
async def get_status():
    return shonya_engine.get_terminal_summary()

@router.post("/mode")
async def set_mode(req: ModeSwitchRequest):
    requested = req.mode.upper()
    if requested not in {"PAPER", "LIVE"}:
        raise HTTPException(status_code=422, detail="Mode must be PAPER or LIVE")
    if requested == "LIVE" and not settings.LIVE_TRADING_ENABLED:
        raise HTTPException(status_code=403, detail="Live trading disabled by server configuration")
    shonya_engine.mode = requested
    market_state.update_shonya_state({"mode": shonya_engine.mode})
    return {"status": "success", "mode": shonya_engine.mode}

@router.post("/toggle")
async def toggle_bot(req: ToggleRequest):
    shonya_engine.is_active = req.active
    market_state.update_shonya_state({"active": shonya_engine.is_active})
    return {"status": "success", "active": shonya_engine.is_active}

@router.post("/squareoff_all")
async def squareoff_all():
    count = len(shonya_engine.positions)
    shonya_engine.positions = []
    market_state.update_shonya_state({"positions": []})
    return {"status": "success", "closed_count": count, "message": "All positions squared off."}
