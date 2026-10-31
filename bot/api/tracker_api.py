"""
Smart Signal Tracker Bot API Router
Exposes REST endpoints for the trading bot:
- GET /api/tracker/dashboard : Active positions, category P&L, learning state, risk, indicators
- GET /api/tracker/history : Completed trade journal with MFE/MAE
- POST /api/tracker/toggle : Pause or resume bot
- POST /api/tracker/squareoff/{trade_id} : Manual position close
- POST /api/tracker/squareoff_all : Emergency squareoff all active trades
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..storage.tracker_storage import tracker_storage
from ..engine.tracker_bot import tracker_bot
from ..engine.market_hours import get_current_ist

router = APIRouter(prefix="/api/tracker", tags=["tracker"])


class ToggleBotRequest(BaseModel):
    active: bool


@router.get("/dashboard")
async def get_tracker_dashboard():
    """Returns active positions, category-wise P&L breakdown, learning state, and bot status."""
    open_trades = tracker_storage.get_open_trades()
    summary = tracker_storage.get_category_pnl_summary()
    learning = tracker_storage.get_learning_params()

    now_dt = get_current_ist()
    today_pnl = tracker_storage.get_today_realized_pnl(now_dt.strftime("%Y-%m-%d"))
    daily_loss_limit = learning.get("daily_loss_limit_inr", 3500.0)

    # Cooldown info
    cooldowns = {}
    for sym, exp_dt in tracker_bot._symbol_cooldowns.items():
        if now_dt < exp_dt:
            cooldowns[sym] = exp_dt.strftime("%H:%M:%S")

    risk_status = {
        "today_realized_pnl_inr": round(today_pnl, 2),
        "daily_loss_limit_inr": daily_loss_limit,
        "circuit_breaker_tripped": today_pnl <= -daily_loss_limit,
        "symbol_cooldowns": cooldowns,
        "brokerage_per_lot_inr": 100.0
    }

    dashboard_data = {
        "is_active": tracker_bot.is_bot_active(),
        "active_positions": open_trades,
        "concurrency": {
            "active_count": len(open_trades),
            "max_concurrent": 4,
            "symbols_trading": [t["symbol"] for t in open_trades]
        },
        "summary": summary,
        "risk_status": risk_status,
        "learning": learning,
        "technical_indicators": {
            sym: tracker_bot.get_technical_state(sym)
            for sym in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
        }
    }

    return {
        "success": True,
        "data": dashboard_data,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "4.3.0"
        },
        **dashboard_data
    }


@router.get("/history")
async def get_tracker_history(limit: int = 50):
    """Returns completed trade journal records."""
    closed_trades = tracker_storage.get_closed_trades(limit=min(100, max(5, limit)))
    return {
        "success": True,
        "data": closed_trades,
        "meta": {
            "count": len(closed_trades),
            "timestamp": datetime.now(timezone.utc).isoformat()
        },
        "trades": closed_trades
    }


@router.post("/toggle")
async def toggle_tracker_bot(req: ToggleBotRequest):
    """Enables or pauses the Smart Tracker Bot."""
    tracker_bot.set_bot_active(req.active)
    return {
        "success": True,
        "is_active": tracker_bot.is_bot_active(),
        "message": f"Smart Tracker Bot is now {'ACTIVE' if req.active else 'PAUSED'}."
    }


@router.post("/squareoff/{trade_id}")
async def manual_squareoff(trade_id: str):
    """Manually squares off an active open position."""
    open_trades = tracker_storage.get_open_trades()
    target_trade = next((t for t in open_trades if t["id"] == trade_id), None)
    if not target_trade:
        raise HTTPException(status_code=404, detail="Trade position not found or already closed.")

    curr_price = target_trade.get("current_net_price", target_trade["entry_net_price"])
    entry_price = target_trade["entry_net_price"]
    lot_size = target_trade["lot_size"]
    role = target_trade["role"]

    if role == "SELLER":
        gross_pnl = round((entry_price - curr_price) * lot_size, 2)
    else:
        gross_pnl = round((curr_price - entry_price) * lot_size, 2)

    net_pnl = round(gross_pnl - 100.0, 2)

    mfe_pts = target_trade.get("mfe_pts", 0.0)
    mfe_inr = target_trade.get("mfe_inr", 0.0)
    mae_pts = target_trade.get("mae_pts", 0.0)
    mae_inr = target_trade.get("mae_inr", 0.0)

    tracker_storage.close_trade(
        trade_id=trade_id,
        exit_net_price=curr_price,
        gross_realized_pnl=gross_pnl,
        net_realized_pnl=net_pnl,
        exit_reason="MANUAL_SQUAREOFF",
        mfe_pts=mfe_pts,
        mfe_inr=mfe_inr,
        mae_pts=mae_pts,
        mae_inr=mae_inr
    )
    return {
        "success": True,
        "message": f"Position {trade_id} squared off successfully at ₹{curr_price}.",
        "gross_realized_pnl_inr": gross_pnl,
        "net_realized_pnl_inr": net_pnl,
        "brokerage_inr": 100.0
    }


@router.post("/squareoff_all")
async def squareoff_all_trades():
    """Emergency squareoff for all currently active trades."""
    closed_count = tracker_bot.square_off_all(reason="MANUAL_EMERGENCY_SQUAREOFF")
    return {
        "success": True,
        "message": f"Closed {closed_count} active position(s).",
        "closed_count": closed_count
    }
