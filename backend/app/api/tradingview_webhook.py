"""
TradingView Webhook Integration Endpoint
Receives instant Pine Script / TradingView alerts for NIFTY, BANKNIFTY, FINNIFTY, and strikes.
Keeps TradingView signals as an independent advisory feed.
"""
import logging
import hmac
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Request

from app.core.config import get_settings
from app.core.market_hours import get_current_ist

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhook", tags=["TradingView Webhooks"])

_recent_tv_alerts: List[Dict[str, Any]] = []
_active_tv_states: Dict[str, Dict[str, Any]] = {}


class TradingViewAlertPayload(BaseModel):
    passphrase: Optional[str] = Field(None, description="Secret security token")
    symbol: str = Field(..., description="Index or ticker: NIFTY, BANKNIFTY, FINNIFTY")
    indicator: str = Field("AlphaTrend", description="Indicator name: AlphaTrend, Hull, OTT, TrendDir")
    signal: str = Field(..., description="Signal trigger: BUY_CE, BUY_PE, EXIT_CE, EXIT_PE, BULLISH, BEARISH")
    timeframe: Optional[str] = Field("5m", description="Chart timeframe: 1m, 3m, 5m, 15m")
    price: Optional[float] = Field(None, description="Close price at alert trigger")
    strike: Optional[float] = Field(None, description="Strike price if option chart, else None")
    opt_type: Optional[str] = Field(None, description="CE or PE if option chart")
    message: Optional[str] = Field(None, description="Custom message or description")
    timestamp: Optional[str] = Field(None, description="Alert trigger timestamp")


@router.post("/tradingview")
async def receive_tradingview_alert(payload: TradingViewAlertPayload, request: Request):
    """
    Receives incoming TradingView Webhook alert.
    Validates token and records signal as independent advisory feed.
    """
    settings = get_settings()
    configured_pass = settings.TRADINGVIEW_WEBHOOK_SECRET

    if not configured_pass or not payload.passphrase or not hmac.compare_digest(payload.passphrase.encode(), configured_pass.encode()):
        logger.warning("Unauthorized TradingView webhook attempt")
        raise HTTPException(status_code=401, detail="Invalid TradingView webhook secret token")

    now = get_current_ist()
    time_str = now.strftime("%H:%M:%S")
    sym = payload.symbol.upper()

    alert_record = {
        "id": len(_recent_tv_alerts) + 1,
        "time": time_str,
        "datetime": now.isoformat(),
        "symbol": sym,
        "indicator": payload.indicator,
        "signal": payload.signal.upper(),
        "timeframe": payload.timeframe or "5m",
        "price": payload.price,
        "strike": payload.strike,
        "opt_type": payload.opt_type.upper() if payload.opt_type else None,
        "message": payload.message or f"{payload.indicator} {payload.signal} on {sym} @ ₹{payload.price}",
    }

    _recent_tv_alerts.insert(0, alert_record)
    if len(_recent_tv_alerts) > 100:
        _recent_tv_alerts.pop()

    state_key = sym if not payload.strike else f"{sym}_{int(payload.strike)}_{payload.opt_type}"
    _active_tv_states[state_key] = alert_record

    logger.info(f"⚡ [TradingView Alert] {sym} | {payload.indicator} -> {payload.signal} @ ₹{payload.price} [{time_str}]")

    try:
        from app.api.websocket import ws_manager
        await ws_manager.broadcast({
            "type": "TRADINGVIEW_ALERT",
            "data": alert_record
        })
    except Exception:
        pass

    return {
        "status": "success",
        "received_at": time_str,
        "alert": alert_record
    }


@router.get("/tradingview/latest")
async def get_latest_tradingview_alerts(symbol: Optional[str] = None):
    """Returns recent TradingView alerts as independent information."""
    if symbol:
        sym_upper = symbol.upper()
        filtered = [a for a in _recent_tv_alerts if a["symbol"] == sym_upper]
        return {
            "status": "success",
            "symbol": sym_upper,
            "active_state": _active_tv_states.get(sym_upper),
            "alerts": filtered[:20]
        }
    return {
        "status": "success",
        "active_states": _active_tv_states,
        "alerts": _recent_tv_alerts[:20]
    }
