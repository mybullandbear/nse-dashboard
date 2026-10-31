"""
Option Candlestick Chart & PineScript Router
Provides REST API endpoints for interactive Option Candlestick Charts with PineScript OTT & ADX overlays.
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.services.option_candle_service import option_candle_service
from app.api.market import fetch_live_chain_data
from app.services.option_chain import parse_option_chain

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/option-chart", tags=["option-chart"])


@router.get("/candles/{symbol}")
async def get_option_chart_candles(
    symbol: str,
    strike: Optional[float] = Query(None, description="Strike price (defaults to ATM)"),
    option_type: str = Query("CE", pattern="^(CE|PE)$", description="Option contract type"),
    ott_length: int = Query(2, ge=1, le=50, description="OTT Moving Average length"),
    ott_percent: float = Query(0.30, ge=0.05, le=5.0, description="OTT percentage envelope"),
    adx_length: int = Query(9, ge=2, le=50, description="ADX smoothing length")
):
    """
    Returns 5-minute candlestick chart data for an option contract with computed PineScript indicators:
    - 5-Minute OHLCV candles
    - PineScript OTT & Moving Average overlay series
    - PineScript ADX, +DI, -DI momentum series
    - Buy & Exit signal crossover markers
    - Live trigger status (BUY_CONFIRMED, EXIT_SIGNAL, NEUTRAL_HOLD)
    """
    sym = symbol.upper()

    # If strike not provided, determine ATM strike from live chain
    if strike is None or strike <= 0:
        raw_chain, _ = await fetch_live_chain_data(sym)
        if raw_chain:
            parsed = parse_option_chain(raw_chain, sym)
            if parsed:
                strike = parsed.atm_strike
        if not strike:
            strike = 23100.0 if sym == "NIFTY" else (55500.0 if sym == "BANKNIFTY" else 25000.0)

    # Record current tick if live chain is available
    try:
        raw_chain, _ = await fetch_live_chain_data(sym)
        if raw_chain:
            parsed = parse_option_chain(raw_chain, sym)
            if parsed:
                option_candle_service.record_chain_ticks(parsed)
    except Exception as e:
        logger.debug(f"Tick record error: {e}")

    chart_data = option_candle_service.get_option_chart_data(
        symbol=sym,
        strike=strike,
        option_type=option_type,
        ott_length=ott_length,
        ott_percent=ott_percent,
        adx_length=adx_length
    )

    return {
        "success": True,
        "data": chart_data
    }


@router.get("/active-strikes/{symbol}")
async def get_active_strikes_status(symbol: str):
    """
    Returns live PineScript OTT & ADX state for the ATM +- 2 strikes (Top 5 strikes)
    for both CE and PE contracts of the given index symbol.
    """
    sym = symbol.upper()
    raw_chain, _ = await fetch_live_chain_data(sym)
    if not raw_chain:
        raise HTTPException(status_code=503, detail=f"Failed to fetch option chain for {sym}")

    chain = parse_option_chain(raw_chain, sym)
    if not chain or not chain.strikes:
        raise HTTPException(status_code=503, detail=f"Failed to parse option chain for {sym}")

    # Record latest ticks
    option_candle_service.record_chain_ticks(chain)

    spot = chain.spot_price
    atm = chain.atm_strike
    step = get_settings().STRIKE_STEPS.get(sym, 50)

    # 5 active strikes: ATM-2, ATM-1, ATM, ATM+1, ATM+2
    strike_tags = [
        (atm - (2 * step), "ATM-2"),
        (atm - step, "ATM-1"),
        (atm, "ATM"),
        (atm + step, "ATM+1"),
        (atm + (2 * step), "ATM+2")
    ]

    strike_map = {s.strikePrice: s for s in chain.strikes}
    contracts_status = []

    # Get spot trend
    spot_ott = "NEUTRAL"
    try:
        from app.services.tracker_bot import tracker_bot
        tech = tracker_bot.get_technical_state(sym)
        spot_ott = tech.get("ott_state", "NEUTRAL")
    except Exception:
        pass

    for stk, tag in strike_tags:
        row = strike_map.get(stk)

        # CE Status
        ce_chart = option_candle_service.get_option_chart_data(sym, stk, "CE")
        ce_curr = ce_chart.get("current_state", {})
        ce_ltp = row.CE.lastPrice if row and row.CE else ce_curr.get("close", 0.0)
        ce_oi = row.CE.openInterest if row and row.CE else ce_curr.get("oi", 0)
        ce_oi_chg = row.CE.changeinOpenInterest if row and row.CE else ce_curr.get("oi_chg", 0)
        ce_pchg = row.CE.pChange if row and row.CE else 0.0

        ce_sig = option_candle_service.classify_strike_signal(
            symbol=sym,
            strike=stk,
            option_type="CE",
            spot=spot,
            atm=atm,
            ltp=ce_ltp,
            pchange=ce_pchg,
            oi=ce_oi,
            oi_chg=ce_oi_chg,
            chart_data=ce_chart,
            spot_ott_state=spot_ott
        )

        contracts_status.append({
            "strike": stk,
            "strike_tag": tag,
            "option_type": "CE",
            "label": f"{int(stk)} CE [{tag}]",
            "ltp": ce_ltp,
            "ott": ce_curr.get("ott", 0.0),
            "mavg": ce_curr.get("mavg", 0.0),
            "ott_state": ce_curr.get("ott_state", "NEUTRAL"),
            "adx": ce_curr.get("adx", 0.0),
            "signal_trigger": ce_curr.get("signal_trigger", "NEUTRAL_HOLD"),
            "action": ce_sig.get("action", "HOLD"),
            "signal_badge": ce_sig.get("badge", "HOLD"),
            "signal_cls": ce_sig.get("cls", "sig-hold"),
            "buildup": ce_sig.get("buildup", "NEUTRAL"),
            "reason": ce_sig.get("reason", "Consolidation"),
            "oi": ce_oi,
            "oi_chg": ce_oi_chg,
            "pChange": ce_pchg
        })

        # PE Status
        pe_chart = option_candle_service.get_option_chart_data(sym, stk, "PE")
        pe_curr = pe_chart.get("current_state", {})
        pe_ltp = row.PE.lastPrice if row and row.PE else pe_curr.get("close", 0.0)
        pe_oi = row.PE.openInterest if row and row.PE else pe_curr.get("oi", 0)
        pe_oi_chg = row.PE.changeinOpenInterest if row and row.PE else pe_curr.get("oi_chg", 0)
        pe_pchg = row.PE.pChange if row and row.PE else 0.0

        pe_sig = option_candle_service.classify_strike_signal(
            symbol=sym,
            strike=stk,
            option_type="PE",
            spot=spot,
            atm=atm,
            ltp=pe_ltp,
            pchange=pe_pchg,
            oi=pe_oi,
            oi_chg=pe_oi_chg,
            chart_data=pe_chart,
            spot_ott_state=spot_ott
        )

        contracts_status.append({
            "strike": stk,
            "strike_tag": tag,
            "option_type": "PE",
            "label": f"{int(stk)} PE [{tag}]",
            "ltp": pe_ltp,
            "ott": pe_curr.get("ott", 0.0),
            "mavg": pe_curr.get("mavg", 0.0),
            "ott_state": pe_curr.get("ott_state", "NEUTRAL"),
            "adx": pe_curr.get("adx", 0.0),
            "signal_trigger": pe_curr.get("signal_trigger", "NEUTRAL_HOLD"),
            "action": pe_sig.get("action", "HOLD"),
            "signal_badge": pe_sig.get("badge", "HOLD"),
            "signal_cls": pe_sig.get("cls", "sig-hold"),
            "buildup": pe_sig.get("buildup", "NEUTRAL"),
            "reason": pe_sig.get("reason", "Consolidation"),
            "oi": pe_oi,
            "oi_chg": pe_oi_chg,
            "pChange": pe_pchg
        })

    atm2_matrix = option_candle_service.get_atm2_matrix(sym, chain, spot_ott)

    return {
        "success": True,
        "symbol": sym,
        "spot_price": spot,
        "atm_strike": atm,
        "strike_step": step,
        "active_contracts": contracts_status,
        "atm_2_matrix": atm2_matrix
    }
