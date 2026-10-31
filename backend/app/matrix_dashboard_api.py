"""
Matrix Dashboard API Router
Provides comprehensive institutional metrics for the dedicated /dashboard view:
- All 4 indices in one unified matrix
- Breakout indicator strength & trailing status
- Proximity (MAPO) ribbon strength
- PCR & PCR 1-min velocity
- Net OI Difference (Put OI - Call OI) with 1-minute delta (Increasing vs Decreasing)
- Call & Put Option Chain Positioning (Short/Long Buildup, Short Covering, Long Unwinding)
- Confluence Score & Actionable Signal Verdict
- 5-Color Tier Categorization (dark-red, light-red, yellow, light-green, dark-green)
"""

import math
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.api.market import fetch_live_chain_data
from app.services.option_chain import parse_option_chain, ParsedOptionChain
from app.services.option_confluence_service import option_confluence_service
from app.services.technical_indicators import TechnicalIndicators
from app.db.storage import snapshot_storage

logger = logging.getLogger("matrix_dashboard_api")
router = APIRouter(prefix="/api/matrix", tags=["matrix-dashboard"])

def _format_compact(val: Optional[float], decimals: int = 1) -> str:
    if val is None or math.isnan(val) or val == 0:
        return "0"
    abs_v = abs(val)
    if abs_v >= 10_000_000:
        return f"{val / 10_000_000:.2f}Cr"
    if abs_v >= 100_000:
        return f"{val / 100_000:.{decimals}f}L"
    if abs_v >= 1_000:
        return f"{val / 1_000:.{decimals}f}K"
    return f"{val:.{decimals}f}"

def _format_signed(val: Optional[float], decimals: int = 1) -> str:
    if val is None or math.isnan(val) or val == 0:
        return "0"
    formatted = _format_compact(val, decimals)
    return f"+{formatted}" if val > 0 else formatted

def _get_5color_class(score: float, is_bearish_inverted: bool = False) -> str:
    """
    Returns one of the 5 requested colors:
    - dark-green (Extreme Bullish >= 75)
    - light-green (Mild Bullish 58 - 74)
    - yellow (Neutral 43 - 57)
    - light-red (Mild Bearish 26 - 42)
    - dark-red (Extreme Bearish <= 25)
    """
    s = 100.0 - score if is_bearish_inverted else score
    if s >= 75.0:
        return "dark-green"
    elif s >= 58.0:
        return "light-green"
    elif s >= 43.0:
        return "yellow"
    elif s >= 26.0:
        return "light-red"
    else:
        return "dark-red"

@router.get("/live")
async def get_live_matrix_dashboard() -> Dict[str, Any]:
    """
    Returns the real-time matrix across all 4 indices for the dedicated /dashboard interface.
    """
    settings = get_settings()
    symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
    indices_data = []

    for sym in symbols:
        try:
            # 1. Fetch live option chain
            raw_chain, source = await fetch_live_chain_data(sym)
            parsed: Optional[ParsedOptionChain] = None
            if raw_chain:
                parsed = parse_option_chain(raw_chain, sym)

            # 2. Confluence Analysis
            conf_data = await option_confluence_service.analyze_confluence(sym, range_strikes=3, parsed_chain=parsed)
            if not conf_data:
                continue

            summary = conf_data.get("summary", {})
            spot_tech = conf_data.get("spot_tech", {})
            strikes = conf_data.get("strikes", [])
            atm_row = next((s for s in strikes if s.get("offset") == 0), None) or (strikes[len(strikes)//2] if strikes else {})

            spot_price = float(summary.get("spot", 0.0))
            atm_strike = float(summary.get("atm", 0.0))

            # Database fallback if spot is 0.0 (off-market hours)
            if spot_price <= 0:
                try:
                    with snapshot_storage._get_connection() as conn:
                        c = conn.cursor()
                        c.execute("SELECT spot FROM intraday_snapshots WHERE symbol = ? AND spot > 0 ORDER BY id DESC LIMIT 1", (sym,))
                        r = c.fetchone()
                        if r:
                            spot_price = float(r["spot"])
                except Exception:
                    pass

            if spot_price <= 0:
                from app.services.simulator import BASE_SPOTS
                spot_price = float(BASE_SPOTS.get(sym, 81520.50 if sym == "SENSEX" else 23000.0))

            step = settings.STRIKE_STEPS.get(sym, 100 if sym == "SENSEX" else 50)
            if atm_strike <= 0 and spot_price > 0:
                atm_strike = round(spot_price / step) * step

            pcr = float(summary.get("pcr", 1.0))
            confluence_score = int(summary.get("confluence_score", 50))
            bias = summary.get("bias", "NEUTRAL")

            # 3. Breakout Indicator Analysis
            brk_state = spot_tech.get("brk_state", "FLAT")       # "LONG", "SHORT", "FLAT"
            brk_bias = spot_tech.get("brk_bias", "NEUTRAL")
            brk_sig = spot_tech.get("brk_signal", "HOLD")
            brk_lvl = spot_tech.get("brk_level")
            brk_trail = spot_tech.get("brk_trail")
            
            # Compute Breakout Strength (0-100)
            if brk_state == "LONG":
                brk_score = 85.0 if brk_sig == "BUY" else 70.0
            elif brk_state == "SHORT":
                brk_score = 15.0 if brk_sig == "SELL" else 30.0
            else:
                brk_score = 50.0

            brk_color = _get_5color_class(brk_score)

            # 4. Proximity (MAPO) Indicator
            # MAPO ribbon score: < 40 Bearish, > 60 Bullish
            mapo_pct = float(spot_tech.get("prox_pct", 50.0))
            mapo_color = _get_5color_class(mapo_pct)
            mapo_state = "BULLISH EXPANSION" if mapo_pct >= 60 else ("BEARISH EXPANSION" if mapo_pct <= 40 else "CHOP CORRIDOR")

            # 5. PCR Analysis
            # PCR > 1.25 Dark Green, 1.05 - 1.25 Light Green, 0.90 - 1.05 Yellow, 0.75 - 0.90 Light Red, < 0.75 Dark Red
            if pcr >= 1.25:
                pcr_color = "dark-green"
                pcr_trend = "BULLISH ACCUMULATION"
            elif pcr >= 1.05:
                pcr_color = "light-green"
                pcr_trend = "MILD BULLISH"
            elif pcr >= 0.90:
                pcr_color = "yellow"
                pcr_trend = "BALANCED / NEUTRAL"
            elif pcr >= 0.75:
                pcr_color = "light-red"
                pcr_trend = "MILD BEARISH"
            else:
                pcr_color = "dark-red"
                pcr_trend = "HEAVY BEARISH WRITING"

            # 6. Difference in OI & 1-Minute Interval Velocity
            tot_ce_oi = int(summary.get("total_ce_oi", 0))
            tot_pe_oi = int(summary.get("total_pe_oi", 0))
            tot_ce_chg = int(summary.get("total_ce_chg", 0))
            tot_pe_chg = int(summary.get("total_pe_chg", 0))

            net_oi_diff = tot_pe_oi - tot_ce_oi   # Positive: Put Heavy (Bullish floor), Negative: Call Heavy (Bearish wall)
            
            # Fetch previous 1-minute snapshot to determine increasing or decreasing difference
            prev_diff = net_oi_diff
            diff_velocity_1m = 0
            is_increasing_favor = False
            trend_arrow = "—"
            velocity_label = "Neutral"

            try:
                with snapshot_storage._get_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT pe_oi, ce_oi, (pe_oi - ce_oi) as oi_diff
                        FROM intraday_snapshots
                        WHERE symbol = ?
                        ORDER BY id DESC LIMIT 2
                    """, (sym,))
                    rows = cur.fetchall()
                    if len(rows) >= 2:
                        prev_diff = int(rows[1]["oi_diff"])
                        diff_velocity_1m = net_oi_diff - prev_diff
                    elif len(rows) == 1:
                        diff_velocity_1m = tot_pe_chg - tot_ce_chg
            except Exception as e_db:
                diff_velocity_1m = tot_pe_chg - tot_ce_chg

            if net_oi_diff >= 0:
                # Bullish regime (Put > Call)
                if diff_velocity_1m > 0:
                    is_increasing_favor = True
                    trend_arrow = "▲"
                    velocity_label = "INCREASING IN FAVOR"
                    diff_color = "dark-green"
                elif diff_velocity_1m < 0:
                    is_increasing_favor = False
                    trend_arrow = "▼"
                    velocity_label = "DECREASING IN FAVOR"
                    diff_color = "light-green"
                else:
                    trend_arrow = "►"
                    velocity_label = "STEADY"
                    diff_color = "light-green"
            else:
                # Bearish regime (Call > Put)
                if diff_velocity_1m < 0: # Call OI growing faster than Put OI
                    is_increasing_favor = True
                    trend_arrow = "▲"
                    velocity_label = "INCREASING IN FAVOR"
                    diff_color = "dark-red"
                elif diff_velocity_1m > 0:
                    is_increasing_favor = False
                    trend_arrow = "▼"
                    velocity_label = "DECREASING IN FAVOR"
                    diff_color = "light-red"
                else:
                    trend_arrow = "►"
                    velocity_label = "STEADY"
                    diff_color = "light-red"

            # 7. Call & Put Option Chain Positioning Parameters
            ce_atm = atm_row.get("ce", {})
            pe_atm = atm_row.get("pe", {})

            ce_buildup = ce_atm.get("buildup", "SHORT BUILDUP")
            pe_buildup = pe_atm.get("buildup", "SHORT BUILDUP")

            # Color for Call Buildup (Call writing is bearish, Call buying is bullish)
            if "SHORT BUILDUP" in ce_buildup:
                ce_color = "dark-red"       # Aggressive Call Writing (Resistance)
            elif "LONG BUILDUP" in ce_buildup:
                ce_color = "dark-green"     # Aggressive Call Buying (Momentum)
            elif "SHORT COVERING" in ce_buildup:
                ce_color = "light-green"    # Call Shorts Exiting (Bullish fuel)
            elif "LONG UNWINDING" in ce_buildup:
                ce_color = "light-red"      # Call Buyers Dumping (Weakness)
            else:
                ce_color = "yellow"

            # Color for Put Buildup (Put writing is bullish, Put buying is bearish)
            if "SHORT BUILDUP" in pe_buildup:
                pe_color = "dark-green"     # Aggressive Put Writing (Support Floor)
            elif "LONG BUILDUP" in pe_buildup:
                pe_color = "dark-red"       # Aggressive Put Buying (Crash Anticipation)
            elif "SHORT COVERING" in pe_buildup:
                pe_color = "light-red"      # Put Writers Panicking / Exiting
            elif "LONG UNWINDING" in pe_buildup:
                pe_color = "light-green"    # Put Buyers Booking Profit
            else:
                pe_color = "yellow"

            # 8. Final Confluence Score & 5-Color
            conf_color = _get_5color_class(confluence_score)

            # 9. Action Signal: What to do
            verdict_text = summary.get("verdict_title") or summary.get("headline", "HOLD")
            action_guide = "HOLD / CONSOLIDATION"
            if confluence_score >= 80:
                action_guide = "🚀 STRONG BUY CALL (MOMENTUM EXPANSION)"
            elif confluence_score >= 60:
                action_guide = "🟢 MILD BUY CALL (ACCUMULATION ON DIPS)"
            elif confluence_score <= 20:
                action_guide = "💥 STRONG BUY PUT (BREAKDOWN SQUEEZE)"
            elif confluence_score <= 40:
                action_guide = "🟠 MILD BUY PUT (PULLBACK SELL)"
            else:
                action_guide = "🟡 HOLD / WAIT (CHOP RANGE BOUND)"

            # Strike Breakdown Matrix (ATM +- 3)
            strike_chain = []
            for stk in strikes:
                stk_val = stk.get("strike", 0.0)
                stk_offset = stk.get("offset", 0)
                ce_d = stk.get("ce", {})
                pe_d = stk.get("pe", {})
                v_d = stk.get("verdict", {})

                strike_chain.append({
                    "strike": stk_val,
                    "offset": stk_offset,
                    "is_atm": (stk_offset == 0),
                    "dist_pts": round(stk_val - spot_price, 1),
                    "ce_ltp": ce_d.get("ltp", 0.0),
                    "ce_oi": _format_compact(ce_d.get("oi", 0)),
                    "ce_chg": _format_signed(ce_d.get("oi_chg", 0)),
                    "ce_buildup": ce_d.get("buildup", "--"),
                    "pe_buildup": pe_d.get("buildup", "--"),
                    "pe_chg": _format_signed(pe_d.get("oi_chg", 0)),
                    "pe_oi": _format_compact(pe_d.get("oi", 0)),
                    "pe_ltp": pe_d.get("ltp", 0.0),
                    "verdict": v_d.get("bias", "NEUTRAL"),
                    "verdict_score": v_d.get("score", 50)
                })

            expiry_map = {
                "NIFTY": "Tuesday (Weekly/Monthly)",
                "BANKNIFTY": "Last Tuesday (Monthly)",
                "FINNIFTY": "Last Tuesday (Monthly)",
                "MIDCPNIFTY": "Last Tuesday (Monthly)",
                "SENSEX": "Thursday (Weekly/Monthly)"
            }
            lot_map = {
                "NIFTY": 65,
                "BANKNIFTY": 30,
                "FINNIFTY": 60,
                "MIDCPNIFTY": 120,
                "SENSEX": 20
            }

            indices_data.append({
                "symbol": sym,
                "spot_price": spot_price,
                "atm_strike": atm_strike,
                "expiry_day": expiry_map.get(sym, "Weekly"),
                "lot_size": lot_map.get(sym, settings.LOT_SIZES.get(sym, 20)),
                "breakout": {
                    "state": brk_state,
                    "signal": brk_sig,
                    "level": brk_lvl,
                    "trail": brk_trail,
                    "strength_score": brk_score,
                    "color": brk_color
                },
                "proximity": {
                    "mapo_pct": mapo_pct,
                    "state": mapo_state,
                    "color": mapo_color
                },
                "pcr": {
                    "value": round(pcr, 2),
                    "trend": pcr_trend,
                    "color": pcr_color
                },
                "oi_difference": {
                    "net_diff_raw": net_oi_diff,
                    "net_diff_formatted": _format_signed(net_oi_diff),
                    "diff_velocity_1m": _format_signed(diff_velocity_1m),
                    "trend_arrow": trend_arrow,
                    "velocity_label": velocity_label,
                    "is_increasing_favor": is_increasing_favor,
                    "color": diff_color
                },
                "call_oi": {
                    "buildup": ce_buildup,
                    "total_oi": _format_compact(tot_ce_oi),
                    "oi_chg_session": _format_signed(tot_ce_chg),
                    "color": ce_color
                },
                "put_oi": {
                    "buildup": pe_buildup,
                    "total_oi": _format_compact(tot_pe_oi),
                    "oi_chg_session": _format_signed(tot_pe_chg),
                    "color": pe_color
                },
                "confluence": {
                    "score": confluence_score,
                    "color": conf_color
                },
                "action": {
                    "signal": action_guide,
                    "verdict_text": verdict_text,
                    "color": conf_color
                },
                "strikes": strike_chain
            })

        except Exception as e:
            logger.error(f"Error computing matrix dashboard for {sym}: {e}", exc_info=True)

    return {
        "status": "success",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_indices": len(indices_data),
        "data": indices_data
    }
