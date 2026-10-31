"""
Trading Signals & Confluence Decision Router
Provides quantitative decision support and option seller trade guides.
"""
import logging
from fastapi import APIRouter, HTTPException
from app.api.market import fetch_live_chain_data
from app.services.option_chain import parse_option_chain
from app.services.oi_analyzer import oi_analyzer
from app.services.signal_engine import signal_engine
from app.services.smart_money import smart_money_service
from app.services.atm_signals_service import atm_signals_service

from pydantic import BaseModel, Field
from app.core.credentials import credentials, save_trading_fund
from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/signals", tags=["signals"])


class FundUpdateRequest(BaseModel):
    total_fund: float = Field(..., gt=0, description="Total trading capital in INR")


@router.get("/fund")
async def get_trading_fund():
    """
    Returns the total configured trading capital and system lot sizes:
    - NIFTY: 65
    - BANKNIFTY: 30
    - FINNIFTY: 60
    - MIDCPNIFTY: 120
    """
    settings = get_settings()
    return {
        "success": True,
        "total_fund": getattr(credentials, "total_fund", 50000.0),
        "lot_sizes": settings.LOT_SIZES,
        "strike_steps": settings.STRIKE_STEPS
    }


@router.post("/fund")
async def update_trading_fund(req: FundUpdateRequest):
    """
    Updates and persists the total trading capital into credentials.json.
    """
    updated_fund = save_trading_fund(req.total_fund)
    settings = get_settings()
    _decision_cache.clear()
    _decision_cache_time.clear()
    return {
        "success": True,
        "total_fund": updated_fund,
        "lot_sizes": settings.LOT_SIZES,
        "message": f"Trading fund successfully updated and saved to ₹{updated_fund:,.2f}"
    }


_decision_cache = {}
_decision_cache_time = {}


@router.get("/decision/{symbol}")
async def get_signal_decision(symbol: str = "NIFTY"):
    """
    Returns multi-factor confluence score, operational state,
    market regime, and high-probability option seller strategy recommendation.
    """
    import time
    from datetime import datetime, timezone

    sym = symbol.upper()
    now = time.time()
    if sym in _decision_cache and (now - _decision_cache_time.get(sym, 0.0)) < 4.0:
        return _decision_cache[sym]

    raw_chain, source = await fetch_live_chain_data(sym)
    parsed = parse_option_chain(raw_chain, sym)
    if not parsed:
        if sym in _decision_cache:
            return _decision_cache[sym]
        raise HTTPException(status_code=503, detail=f"Failed to evaluate signals for {sym}")

    # Ensure live index percent change and day change are passed to signal engine
    if getattr(parsed, "spot_pchange", 0.0) == 0.0:
        try:
            from app.api.market import _indices_cache, get_indices
            if not _indices_cache.get("indices"):
                await get_indices()
            for idx in _indices_cache.get("indices", []):
                if idx.get("symbol") == sym:
                    parsed.spot_pchange = float(idx.get("percent_change", 0.0))
                    parsed.spot_change = float(idx.get("change", 0.0))
                    break
        except Exception as e:
            logger.debug(f"Could not read index quote for {sym}: {e}")

    oi_data = oi_analyzer.analyze(parsed)
    decision = signal_engine.evaluate(parsed, oi_data)
    decision["source"] = source

    # Integrate Live AI Trade Advisor (Groq LPU with Gemini Fallback)
    try:
        from app.services.ai_advisor_service import ai_advisor
        indicators = {
            "hull_state": getattr(parsed, "spot_hull", {}).get("state", "NEUTRAL") if getattr(parsed, "spot_hull", None) else "NEUTRAL",
            "alphatrend_state": "BULLISH" if decision["confluence_score"] >= 60 else ("BEARISH" if decision["confluence_score"] <= 40 else "NEUTRAL"),
            "adx": 28.0
        }
        chain_summary = {
            "pcr": parsed.pcr,
            "dominant_pressure": oi_data.get("pressure", {}).get("dominant_side", "BALANCED")
        }
        ai_alert = ai_advisor.get_ai_recommendation(
            symbol=sym,
            spot=parsed.spot_price,
            spot_pchange=parsed.spot_pchange,
            atm_strike=parsed.atm_strike,
            confluence_score=decision["confluence_score"],
            direction=decision["direction"],
            chain_summary=chain_summary,
            indicators=indicators
        )
        decision["ai_trade_recommendation"] = ai_alert
        if ai_alert and ai_alert.get("success"):
            decision["top_recommendation"]["ai_audit"] = ai_alert
    except Exception as e:
        logger.warning(f"Error attaching AI advisor recommendation for {sym}: {e}")
    
    envelope = {
        "success": True,
        "data": decision,
        "meta": {
            "symbol": sym,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "version": "4.1.0"
        },
        **decision
    }
    _decision_cache[sym] = envelope
    _decision_cache_time[sym] = now
    return envelope


@router.get("/smart-money/{symbol}")
async def get_smart_money(symbol: str = "NIFTY"):
    """Returns institutional order flow metrics in ₹ Crores and conviction score."""
    sym = symbol.upper()
    raw_chain, source = await fetch_live_chain_data(sym)
    parsed = parse_option_chain(raw_chain, sym)
    if not parsed:
        raise HTTPException(status_code=503, detail=f"Failed to evaluate smart money for {sym}")

    sm_data = smart_money_service.compute(parsed)
    sm_data["source"] = source
    return sm_data


@router.get("/atm-signals")
async def get_all_atm_signals():
    """
    Returns live tabular signals strictly restricted to MAX TO MAX ATM +- 1 options
    across all 4 index symbols (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY).
    Integrates PineScript OTT & ADX indicators with Option Chain pricing, Greeks, and live Tracker Bot state.
    """
    signals = await atm_signals_service.get_all_atm_signals()
    from datetime import datetime, timezone
    return {
        "success": True,
        "count": len(signals),
        "data": signals,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@router.get("/atm-signals/{symbol}")
async def get_symbol_atm_signals(symbol: str = "NIFTY"):
    """
    Returns live ATM +- 1 buying & selling signals for a specific symbol.
    """
    sig = await atm_signals_service.get_symbol_atm_signal(symbol)
    if not sig:
        raise HTTPException(status_code=503, detail=f"Failed to generate ATM signals for {symbol}")
    return {
        "success": True,
        "data": sig
    }

