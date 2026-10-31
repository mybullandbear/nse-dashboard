"""
ShonyaBot API Router:
High-speed execution endpoints for ShonyaBot:
- Master Bot Toggle (Active ON/OFF)
- Trading Mode Switch (PAPER vs LIVE FYERS)
- Manual Chart Trading Execution (Instant Buy CE / Buy PE)
- Grok AI Signal Execution
- Dynamic In-Trade Target & SL Modification
- Live Tracking HUD & Zero-Theoretical Fyers Broker P&L
- Emergency Square-Off Kill-Switch
"""
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.shonya_bot import shonya_bot
from app.services.fyers_service import fyers_service
from app.services.ai_advisor_service import ai_advisor
from app.api.market import fetch_live_chain_data
from app.services.option_chain import parse_option_chain
from app.services.oi_analyzer import oi_analyzer
from app.services.signal_engine import signal_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/shonya", tags=["shonya"])


class BotToggleRequest(BaseModel):
    active: bool = Field(..., description="Enable or disable automated ShonyaBot trading")


class BotModeRequest(BaseModel):
    mode: str = Field(..., description="'PAPER' or 'LIVE'")


class ManualTradeRequest(BaseModel):
    symbol: str = Field(..., json_schema_extra={"example": "NIFTY"})
    strike: float = Field(..., json_schema_extra={"example": 22600.0})
    option_type: str = Field(..., json_schema_extra={"example": "CE"})
    lots: int = Field(1, ge=1, le=10)
    entry_price: Optional[float] = None
    target1: Optional[float] = None
    target2: Optional[float] = None
    stop_loss: Optional[float] = None
    thesis: Optional[str] = "Manual Chart Execution"


class ModifyTradeRequest(BaseModel):
    target1: Optional[float] = None
    target2: Optional[float] = None
    stop_loss: Optional[float] = None


class GrokExecuteRequest(BaseModel):
    symbol: str = Field("NIFTY", json_schema_extra={"example": "NIFTY"})


class MultiIndexMarketViewRequest(BaseModel):
    symbols: Optional[list[str]] = Field(default=["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"])


class CapitalUpdateRequest(BaseModel):
    capital: float = Field(..., gt=1000.0, description="Total trading capital in INR")


class SymbolsUpdateRequest(BaseModel):
    symbols: list[str] = Field(..., description="List of enabled trading symbols (NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY)")


@router.get("/status")
async def get_shonya_status():
    """Returns ShonyaBot operational state, mode, live broker connectivity, and performance metrics."""
    return shonya_bot.get_status()


@router.post("/toggle")
async def toggle_shonya_bot(req: BotToggleRequest):
    """Turns ShonyaBot ON or OFF."""
    new_state = shonya_bot.set_active(req.active)
    return {
        "success": True,
        "is_active": new_state,
        "message": f"ShonyaBot is now {'ACTIVE' if new_state else 'PAUSED'}"
    }


@router.post("/mode")
async def set_shonya_mode(req: BotModeRequest):
    """Switches execution mode between PAPER and LIVE FYERS."""
    mode = req.mode.upper()
    if mode not in ["PAPER", "LIVE"]:
        raise HTTPException(status_code=400, detail="Mode must be 'PAPER' or 'LIVE'")
    
    if mode == "LIVE":
        raise HTTPException(status_code=403, detail="Live trading is disabled in this build")

    current_mode = shonya_bot.set_mode(mode)
    return {
        "success": True,
        "trading_mode": current_mode,
        "message": f"ShonyaBot mode set to {current_mode}"
    }


@router.post("/capital")
async def update_trading_capital(req: CapitalUpdateRequest):
    """Updates total trading capital ceiling for paper trading and margin enforcement."""
    new_cap = shonya_bot.set_capital(req.capital)
    return {
        "success": True,
        "capital_ceiling": new_cap,
        "capital_status": shonya_bot.get_capital_status(),
        "message": f"Trading capital updated to ₹{new_cap:,.2f}"
    }


@router.get("/capital")
async def get_trading_capital():
    """Returns trading capital status, deployed margin, and available buffer."""
    return {
        "success": True,
        "capital_ceiling": shonya_bot.capital_ceiling,
        "capital_status": shonya_bot.get_capital_status()
    }


@router.post("/symbols")
async def update_enabled_symbols(req: SymbolsUpdateRequest):
    """Updates enabled trading symbols (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY)."""
    updated_syms = shonya_bot.set_enabled_symbols(req.symbols)
    return {
        "success": True,
        "enabled_symbols": updated_syms,
        "message": f"Trading targets updated: {', '.join(updated_syms)}"
    }


@router.get("/symbols")
async def get_enabled_symbols():
    """Returns list of enabled trading symbols and all available symbols."""
    return {
        "success": True,
        "enabled_symbols": shonya_bot.enabled_symbols,
        "available_symbols": ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"]
    }


@router.get("/positions")
async def get_shonya_positions():
    """
    Returns real-time open positions. In LIVE mode, reads directly from Fyers API.
    Also executes tick evaluation (Breakeven Armor, T1/T2 checks, SL trigger).
    """
    updated_ticks = shonya_bot.update_positions_tick()
    open_trades = shonya_bot.get_open_trades()
    return {
        "success": True,
        "count": len(open_trades),
        "positions": open_trades,
        "updated": updated_ticks
    }


@router.post("/trade/manual")
async def place_manual_trade(req: ManualTradeRequest):
    """
    Executes a manual option trade directly from the interactive chart setup.
    Enforces risk rules and executes via PAPER or LIVE Fyers gateway.
    """
    res = shonya_bot.place_trade(
        symbol=req.symbol,
        strike=req.strike,
        option_type=req.option_type,
        lots=req.lots,
        entry_price=req.entry_price,
        target1=req.target1,
        target2=req.target2,
        stop_loss=req.stop_loss,
        source="MANUAL",
        thesis=req.thesis or "Manual Chart Trade"
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message", "Trade placement failed"))
    return res


@router.post("/position/{trade_id}/modify")
async def modify_shonya_position(trade_id: str, req: ModifyTradeRequest):
    """
    Allows user to dynamically modify Target 1, Target 2, and Stop Loss
    on an active trade at any time directly from the live terminal.
    """
    res = shonya_bot.modify_trade(
        trade_id=trade_id,
        target1=req.target1,
        target2=req.target2,
        stop_loss=req.stop_loss
    )
    if not res.get("success"):
        raise HTTPException(status_code=404, detail=res.get("message", "Position not found"))
    return res


@router.post("/position/{trade_id}/exit")
async def exit_shonya_position(trade_id: str, reason: str = "MANUAL_EXIT"):
    """Exits an active position immediately at market price."""
    res = shonya_bot.exit_trade(trade_id=trade_id, exit_reason=reason)
    if not res.get("success"):
        raise HTTPException(status_code=404, detail=res.get("message", "Position not found"))
    return res


@router.post("/squareoff_all")
async def squareoff_all_positions():
    """Emergency Kill Switch: Squares off all open positions immediately."""
    return shonya_bot.squareoff_all()


@router.get("/history")
async def get_shonya_history(limit: int = 100):
    """Returns the closed trade journal with realized P&L, fees, and strategy metrics."""
    trades = shonya_bot.get_trade_history(limit=limit)
    metrics = shonya_bot.get_performance_metrics()
    return {
        "success": True,
        "count": len(trades),
        "history": trades,
        "metrics": metrics
    }


@router.get("/fyers/funds")
async def get_fyers_funds():
    """Fetches real account balances and equity margins directly from Fyers API."""
    return fyers_service.get_funds()


@router.get("/ai/recommendation/{symbol}")
@router.get("/grok/recommendation/{symbol}")
async def get_grok_recommendation(symbol: str = "NIFTY"):
    """Fetches the latest MyBullAndBear AI trade recommendation for a symbol."""
    sym = symbol.upper()
    raw_chain, source = await fetch_live_chain_data(sym)
    parsed = parse_option_chain(raw_chain, sym)
    if not parsed:
        raise HTTPException(status_code=503, detail=f"Failed to fetch market data for {sym}")

    oi_data = oi_analyzer.analyze(parsed)
    decision = signal_engine.evaluate(parsed, oi_data)

    # 1. Compute Spot Hull Suite from historical candle closes
    hull_state = "NEUTRAL"
    try:
        from app.services.technical_indicators import TechnicalIndicators
        from app.db.storage import snapshot_storage
        history = snapshot_storage.get_continuous_timeseries(sym, limit=200, max_time="15:15", discard_frozen_after="15:15")
        closes = [float(r["spot"]) for r in history if r.get("spot") and float(r["spot"]) > 500]
        from app.core.market_hours import get_current_ist
        if get_current_ist().strftime("%H:%M") <= "15:15" and parsed.spot_price and parsed.spot_price > 500:
            if not closes or abs(closes[-1] - parsed.spot_price) > 0.01:
                closes.append(parsed.spot_price)
        if len(closes) >= 4:
            h_data = TechnicalIndicators.compute_hull(closes, mode="Ehma", length=34, length_mult=2.0)
            hull_state = h_data.get("curr_state", "NEUTRAL")
            parsed.spot_hull = {
                "val": round(h_data.get("curr_mhull", parsed.spot_price), 2),
                "state": hull_state,
                "shull": round(h_data.get("curr_shull", parsed.spot_price), 2)
            }
    except Exception as e:
        logger.debug(f"Spot Hull computation error in shonya_api: {e}")

    # 2. Compute Smart Money / Institutional Capital Flow
    from app.services.smart_money import smart_money_service
    sm_data = smart_money_service.compute(parsed)

    # 3. Detect Immediate Call Resistance Wall and Put Support Wall near ATM
    atm = parsed.atm_strike
    step = 50.0 if "BANK" not in sym else 100.0
    atm_strikes = [s for s in parsed.strikes if abs(s.strikePrice - atm) <= (4 * step)]
    if not atm_strikes:
        atm_strikes = parsed.strikes

    call_cands = [s for s in atm_strikes if s.strikePrice >= atm]
    put_cands = [s for s in atm_strikes if s.strikePrice <= atm]

    top_ce_row = max(call_cands, key=lambda s: s.CE.openInterest) if call_cands else max(atm_strikes, key=lambda s: s.CE.openInterest)
    top_pe_row = max(put_cands, key=lambda s: s.PE.openInterest) if put_cands else max(atm_strikes, key=lambda s: s.PE.openInterest)

    call_wall_strike = top_ce_row.strikePrice
    call_wall_oi = top_ce_row.CE.openInterest
    call_wall_chg = top_ce_row.CE.changeinOpenInterest

    put_wall_strike = top_pe_row.strikePrice
    put_wall_oi = top_pe_row.PE.openInterest
    put_wall_chg = top_pe_row.PE.changeinOpenInterest

    pressure = oi_data.get("pressure", {})
    chain_summary = {
        "pcr": round(parsed.pcr, 2),
        "pcr_atm_5": round(getattr(parsed, "pcr_atm_5", parsed.pcr), 2),
        "max_pain": parsed.max_pain,
        "dominant_pressure": pressure.get("dominant_side", "BALANCED"),
        "call_writer_pressure_pct": pressure.get("call_writer_pressure_pct", 50.0),
        "put_writer_pressure_pct": pressure.get("put_writer_pressure_pct", 50.0),
        "call_wall_strike": call_wall_strike,
        "call_wall_oi": call_wall_oi,
        "call_wall_oi_change": call_wall_chg,
        "put_wall_strike": put_wall_strike,
        "put_wall_oi": put_wall_oi,
        "put_wall_oi_change": put_wall_chg
    }

    indicators = {
        "hull_state": hull_state,
        "alphatrend_state": "BULLISH" if decision["confluence_score"] >= 60 else ("BEARISH" if decision["confluence_score"] <= 40 else "NEUTRAL"),
        "adx": 28.0,
        "confluence_score": decision["confluence_score"],
        "operational_state": decision.get("operational_state", "WATCH"),
        "market_regime": decision.get("market_regime", "RANGE-BOUND")
    }

    ai_alert = ai_advisor.get_ai_recommendation(
        symbol=sym,
        spot=parsed.spot_price,
        spot_pchange=parsed.spot_pchange,
        atm_strike=parsed.atm_strike,
        confluence_score=decision["confluence_score"],
        direction=decision["direction"],
        chain_summary=chain_summary,
        indicators=indicators,
        smart_money=sm_data
    )
    return {
        "success": True,
        "symbol": sym,
        "spot": parsed.spot_price,
        "atm_strike": parsed.atm_strike,
        "recommendation": ai_alert
    }


@router.post("/ai/execute")
@router.post("/grok/execute")
async def execute_grok_trade(req: GrokExecuteRequest):
    """Takes the current MyBullAndBear AI recommendation and places the trade directly into ShonyaBot."""
    sym = req.symbol.upper()
    grok_data = await get_grok_recommendation(sym)
    rec = grok_data.get("recommendation", {})

    if not rec or rec.get("action") == "STANDBY":
        raise HTTPException(status_code=400, detail=f"MyBullAndBear AI is in STANDBY for {sym}. No trade available.")

    opt_type = rec.get("option_type")
    strike = float(rec.get("strike", 0.0))
    entry_p = float(rec.get("entry_price", 0.0))
    t1 = float(rec.get("scalp_target1", 0.0))
    t2 = float(rec.get("runner_target2", 0.0))
    sl = float(rec.get("stop_loss", 0.0))
    thesis = rec.get("institutional_thesis", f"MyBullAndBear AI {rec.get('strategy_type')}")

    if not opt_type or strike <= 0:
        raise HTTPException(status_code=400, detail="Invalid recommendation parameters from MyBullAndBear AI.")

    res = shonya_bot.place_trade(
        symbol=sym,
        strike=strike,
        option_type=opt_type,
        lots=1,
        entry_price=entry_p,
        target1=t1,
        target2=t2,
        stop_loss=sl,
        source="MYBULLANDBEAR_AI",
        thesis=thesis
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message", "Failed to execute MyBullAndBear AI trade"))
    return res


@router.post("/ai/market_overview")
@router.get("/ai/market_overview")
async def get_multi_index_market_overview(req: Optional[MultiIndexMarketViewRequest] = None):
    """
    Returns an elite AI institutional cross-asset market overview for selected indices.
    Integrates live broker OHLC, Open Interest changes, PCR, Confluence, and Option walls.
    """
    syms = req.symbols if (req and req.symbols) else ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
    return await ai_advisor.get_multi_index_market_overview(syms)


@router.get("/matrix")
async def get_shonya_signal_matrix():
    """
    Returns the centralized 4-column strategy signal matrix for all indices:
    Column 1: Indices (Symbol, Spot Price, ATM)
    Column 2: Option Chain Signal & Strength (5m Buildup, PCR, Direction)
    Column 3: Hull Indicator (Responsive EHMA 5m Closed Trend, MHULL, SHULL)
    Column 4: What to do? Buy Call or Put? (Action Verdict, Strike, Confluence Status)
    """
    from datetime import time as dt_time
    from app.core.market_hours import get_current_ist, is_market_open
    from app.services.shonya_bot import shonya_bot, INDEX_CONFIGS
    from app.db.storage import snapshot_storage
    from app.api.market import fetch_live_chain_data
    from app.services.option_chain import parse_option_chain

    now_dt = get_current_ist()
    time_str = now_dt.strftime("%H:%M:%S IST")
    mkt_open = is_market_open()

    symbols = ["NIFTY", "BANKNIFTY", "SENSEX", "FINNIFTY", "MIDCPNIFTY"]
    matrix_rows = []

    from app.services.option_confluence_service import option_confluence_service

    for sym in symbols:
        try:
            conf = await option_confluence_service.analyze_confluence(sym, compute_strike_candles=False)
            strat = conf.get("strategy_confluence") if conf else None
            if not strat:
                continue

            open_trade = shonya_bot.get_open_trade_for_symbol(sym)
            row = dict(strat)
            if open_trade:
                row["action"] = {
                    "verdict": f"HOLDING {int(open_trade['strike'])} {open_trade['option_type']}",
                    "type": open_trade['option_type'],
                    "strike": f"Pos: ₹{open_trade['entry_price']:.1f} → ₹{open_trade['current_price']:.1f}",
                    "badge_color": "blue",
                    "sub": f"Trailing active {open_trade['execution_mode']} trade. Net P&L: ₹{open_trade.get('net_pnl', 0.0):+.1f}",
                    "is_aligned": True,
                    "is_opposed": False
                }
            row["has_open_position"] = bool(open_trade)
            row["open_trade"] = open_trade
            matrix_rows.append(row)
        except Exception as e_sym:
            logger.error(f"Error getting centralized strategy table for {sym}: {e_sym}")

    return {
        "success": True,
        "market_open": mkt_open,
        "current_time_ist": time_str,
        "bot_active": shonya_bot.is_active,
        "trading_mode": shonya_bot.trading_mode,
        "matrix": matrix_rows
    }

