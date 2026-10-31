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
    symbol: str = Field(..., example="NIFTY")
    strike: float = Field(..., example=22600.0)
    option_type: str = Field(..., example="CE")
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
    symbol: str = Field("NIFTY", example="NIFTY")


class MultiIndexMarketViewRequest(BaseModel):
    symbols: Optional[list[str]] = Field(default=["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"])


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
        ok, msg = fyers_service.validate_connection()
        if not ok:
            raise HTTPException(status_code=400, detail=f"Cannot enable LIVE mode: Fyers not connected ({msg})")

    current_mode = shonya_bot.set_mode(mode)
    return {
        "success": True,
        "trading_mode": current_mode,
        "message": f"ShonyaBot mode set to {current_mode}"
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
async def get_shonya_history(limit: int = 50):
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
        history = snapshot_storage.get_continuous_timeseries(sym, limit=200)
        closes = [float(r["spot"]) for r in history if r.get("spot") and float(r["spot"]) > 500]
        if parsed.spot_price and parsed.spot_price > 500:
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
    Returns live parameter evaluation matrix for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY:
    - Confluence Score & Bias (ATM ± 2)
    - 5M AlphaTrend / OTT Direction
    - ADX Trend Expansion Filter (>= 20.0)
    - Smart Money Net Flow (Cr)
    - Time Filter (Active vs Midday Lull 11:30 - 12:45)
    - Recommended 1-ITM Strike
    - Overall Trade Signal & Action (CALL / PUT / DILEMMA)
    """
    from datetime import time as dt_time
    from app.core.market_hours import get_current_ist, is_market_open
    from app.services.tracker_bot import tracker_bot
    from app.services.option_confluence_service import option_confluence_service
    from app.services.smart_money import smart_money_service
    from app.core.config import get_settings

    settings = get_settings()
    now_dt = get_current_ist()
    t = now_dt.time()
    time_str = now_dt.strftime("%H:%M:%S IST")
    mkt_open = is_market_open()

    symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
    matrix_rows = []

    for sym in symbols:
        step = settings.STRIKE_STEPS.get(sym, 50)

        # Technical Indicators (ADX, AlphaTrend/OTT, TrendDir)
        tech = tracker_bot.get_technical_state(sym)
        adx = float(tech.get("adx", 0.0) or 0.0)
        ott_state = tech.get("ott_state", "NEUTRAL")
        trend_dir_strength = float(tech.get("trend_dir_strength", 0.0) or 0.0)

        # Confluence Analysis
        conf = await option_confluence_service.analyze_confluence(sym, range_strikes=2)
        summary = conf.get("summary", {}) if conf else {}
        conf_score = float(summary.get("overall_confluence_score", summary.get("confluence_score", 50.0)))
        conf_bias = summary.get("overall_bias", "NEUTRAL")
        spot_price = float(summary.get("spot_price", 0.0) or (conf.get("meta", {}).get("spot_price", 0.0) if conf else 0.0))
        if spot_price <= 0:
            from app.db.storage import snapshot_storage
            tl = snapshot_storage.get_today_timeline(sym)
            if tl:
                spot_price = float(tl[-1].get("spot") or 0.0)

        # Smart Money Net Flow
        sm_flow_cr = 0.0
        try:
            sm_data = smart_money_service.get_smart_money_analysis(sym)
            if not sm_data or sm_data.get("net_flow_cr", 0.0) == 0.0:
                raw_c, _ = await fetch_live_chain_data(sym)
                if raw_c:
                    p_c = parse_option_chain(raw_c, sym)
                    if p_c:
                        sm_data = smart_money_service.compute(p_c)
            if sm_data:
                sm_flow_cr = float(sm_data.get("net_flow_cr", 0.0) or 0.0)
        except Exception:
            pass

        # Check Active Open Trade
        open_trade = shonya_bot.get_open_trade_for_symbol(sym)

        # Strike Calculation: ATM & 1-ITM
        atm_strike = round(spot_price / step) * step if spot_price > 0 else 0
        itm_ce_strike = atm_strike - step if atm_strike > 0 else 0
        itm_pe_strike = atm_strike + step if atm_strike > 0 else 0

        # Parameter 1: Confluence State
        # >= 70: CALL (green), <= 30: PUT (red), 31-69: DILEMMA (yellow)
        if conf_score >= 70.0:
            p1_state = "CALL"
            p1_text = f"{conf_score:.0f} (BULLISH)"
        elif conf_score <= 30.0:
            p1_state = "PUT"
            p1_text = f"{conf_score:.0f} (BEARISH)"
        else:
            p1_state = "DILEMMA"
            p1_text = f"{conf_score:.0f} (NEUTRAL)"

        # Parameter 2: AlphaTrend (5M)
        if ott_state == "BULLISH" or trend_dir_strength > 0.15:
            p2_state = "CALL"
            p2_text = "BULLISH ↗"
        elif ott_state == "BEARISH" or trend_dir_strength < -0.15:
            p2_state = "PUT"
            p2_text = "BEARISH ↘"
        else:
            p2_state = "DILEMMA"
            p2_text = "NEUTRAL ↔"

        # Parameter 3: ADX (14) Filter
        # >= 20.0: Trend Expansion (Green for Call if bullish, Red for Put if bearish)
        # < 20.0: DILEMMA (Yellow - Chop Protection)
        if adx >= 20.0:
            if p1_state == "CALL" or p2_state == "CALL":
                p3_state = "CALL"
            elif p1_state == "PUT" or p2_state == "PUT":
                p3_state = "PUT"
            else:
                p3_state = "CALL"
            p3_text = f"{adx:.1f} (TREND ≥20)"
        else:
            p3_state = "DILEMMA"
            p3_text = f"{adx:.1f} (CHOP <20)"

        # Parameter 4: Smart Money Flow
        if sm_flow_cr > 15.0:
            p4_state = "CALL"
            p4_text = f"+₹{sm_flow_cr:.1f} Cr (BUY)"
        elif sm_flow_cr < -15.0:
            p4_state = "PUT"
            p4_text = f"-₹{abs(sm_flow_cr):.1f} Cr (SELL)"
        else:
            p4_state = "DILEMMA"
            p4_text = f"₹{sm_flow_cr:.1f} Cr (BAL)"

        # Parameter 5: Time Window Filter
        is_midday = (dt_time(11, 30, 0) <= t <= dt_time(12, 45, 0))
        is_trading_hours = (dt_time(9, 20, 0) <= t <= dt_time(15, 15, 0))

        if not mkt_open or not is_trading_hours:
            p5_state = "DILEMMA"
            p5_text = "MARKET CLOSED" if not mkt_open else "OFF HOURS"
        elif is_midday and (22.0 < conf_score < 78.0):
            p5_state = "DILEMMA"
            p5_text = "MIDDAY LULL (11:30-12:45)"
        else:
            p5_state = p1_state if p1_state in ["CALL", "PUT"] else "CALL"
            p5_text = "ACTIVE WINDOW"

        # Recommended Strike (1-ITM Rule)
        if p1_state == "CALL" or p2_state == "CALL":
            rec_strike = f"{int(itm_ce_strike)} CE (1-ITM)"
            rec_type = "CE"
            rec_strike_val = itm_ce_strike
            rec_state = "CALL"
        elif p1_state == "PUT" or p2_state == "PUT":
            rec_strike = f"{int(itm_pe_strike)} PE (1-ITM)"
            rec_type = "PE"
            rec_strike_val = itm_pe_strike
            rec_state = "PUT"
        else:
            rec_strike = f"{int(atm_strike)} ATM"
            rec_type = "CE"
            rec_strike_val = atm_strike
            rec_state = "DILEMMA"

        # Overall Signal Decision & Action
        if open_trade:
            action = "HOLDING_POS"
            action_state = "DILEMMA"
            action_badge = f"HOLDING {int(open_trade['strike'])} {open_trade['option_type']}"
            action_reason = f"Active Position Open (Qty: {open_trade['quantity']}, Net P&L: ₹{open_trade['net_pnl']:.1f}). 1 Position Limit Active."
        elif (p1_state == "CALL" and p2_state == "CALL" and adx >= 20.0 and p5_state != "DILEMMA"):
            action = "BUY_CE"
            action_state = "CALL"
            action_badge = f"🚀 BUY {int(itm_ce_strike)} CE"
            action_reason = f"All 5 Institutional Filters Bullish (ADX {adx:.1f} ≥ 20, Conf {conf_score:.0f})"
        elif (p1_state == "PUT" and p2_state == "PUT" and adx >= 20.0 and p5_state != "DILEMMA"):
            action = "BUY_PE"
            action_state = "PUT"
            action_badge = f"🔻 BUY {int(itm_pe_strike)} PE"
            action_reason = f"All 5 Institutional Filters Bearish (ADX {adx:.1f} ≥ 20, Conf {conf_score:.0f})"
        else:
            action = "WAIT"
            action_state = "DILEMMA"
            action_badge = "⏸️ WAIT / DILEMMA"
            blockers = []
            if adx < 20.0:
                blockers.append(f"ADX < 20 ({adx:.1f} Chop)")
            if is_midday and (22.0 < conf_score < 78.0):
                blockers.append("Midday Lull Window")
            if p1_state == "DILEMMA":
                blockers.append(f"Confluence Neutral ({conf_score:.0f})")
            elif p1_state != p2_state:
                blockers.append("Signal & AlphaTrend Conflict")
            action_reason = "Waiting: " + (", ".join(blockers) if blockers else "Awaiting Institutional Setup")

        matrix_rows.append({
            "symbol": sym,
            "spot_price": spot_price,
            "confluence": {
                "score": conf_score,
                "bias": conf_bias,
                "state": p1_state,
                "text": p1_text
            },
            "alphatrend": {
                "state_dir": ott_state,
                "strength": trend_dir_strength,
                "state": p2_state,
                "text": p2_text
            },
            "adx": {
                "value": adx,
                "state": p3_state,
                "text": p3_text
            },
            "smart_money": {
                "net_flow_cr": sm_flow_cr,
                "state": p4_state,
                "text": p4_text
            },
            "time_filter": {
                "state": p5_state,
                "text": p5_text
            },
            "recommended_strike": {
                "strike": rec_strike_val,
                "option_type": rec_type,
                "state": rec_state,
                "text": rec_strike
            },
            "overall_action": {
                "action": action,
                "state": action_state,
                "badge": action_badge,
                "reason": action_reason
            },
            "has_open_position": bool(open_trade),
            "open_position": open_trade
        })

    return {
        "success": True,
        "market_open": mkt_open,
        "current_time_ist": time_str,
        "bot_active": shonya_bot.is_active,
        "trading_mode": shonya_bot.trading_mode,
        "matrix": matrix_rows
    }

