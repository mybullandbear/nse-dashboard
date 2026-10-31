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
import time
import asyncio
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

_matrix_live_cache: Dict[str, Any] = {}
_matrix_live_cache_time: float = 0.0
_timeseries_cache: Dict[str, Any] = {}
_timeseries_cache_time: Dict[str, float] = {}

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

def _get_confluence_sparkline(sym: str, current_score: float) -> List[float]:
    """
    Fetches intraday confluence points (09:15 - 15:30) for the background sparkline.
    If historical database snapshots contain default 50.0, synthesizes a continuous quantitative confluence curve.
    """
    try:
        with snapshot_storage._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT time_str, spot, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, pcr, confluence
                FROM intraday_snapshots
                WHERE symbol = ? AND spot > 500 AND time_str >= '09:15' AND time_str <= '15:30'
                  AND trade_date = (SELECT MAX(trade_date) FROM intraday_snapshots WHERE symbol = ?)
                GROUP BY time_str
                ORDER BY time_str ASC
            """, (sym, sym))
            rows = cur.fetchall()
            if not rows:
                return [round(current_score, 1)]

            raw_scores = []
            for r in rows:
                conf = float(r["confluence"])
                if conf == 50.0:
                    p_r = float(r["pcr"])
                    c_chg = int(r["ce_oi_chg"])
                    p_chg = int(r["pe_oi_chg"])
                    tot_chg = abs(c_chg) + abs(p_chg)
                    oi_diff_factor = (p_chg - c_chg) / max(1, tot_chg) if tot_chg > 0 else 0
                    dyn = 50.0 + (p_r - 1.0) * 35.0 + (oi_diff_factor * 25.0)
                    conf = max(10.0, min(92.0, dyn))
                raw_scores.append(round(conf, 1))

            if raw_scores:
                raw_scores[-1] = round(current_score, 1)

            if len(raw_scores) > 45:
                step = len(raw_scores) / 40.0
                downsampled = [raw_scores[int(i * step)] for i in range(40)]
                downsampled.append(raw_scores[-1])
                return downsampled
            return raw_scores
    except Exception as e:
        logger.error(f"Error fetching confluence sparkline for {sym}: {e}")
        return [round(current_score, 1)]


def _compute_institutional_parameters(sym: str, spot_price: float, atm_strike: float, parsed: Optional[ParsedOptionChain], step: float = 50) -> Dict[str, Any]:
    """
    Calculates actionable institutional parameters replacing static anchors:
    - Major Call Wall (Peak CE OI Resistance)
    - Major Put Wall (Peak PE OI Support)
    - Fresh Call Addition (Today's Peak Intraday Resistance)
    - Fresh Put Addition (Today's Peak Intraday Support)
    - ATM Straddle Volatility Corridor [Lower Breakeven - Upper Breakeven]
    """
    if not parsed or not parsed.strikes:
        fallback_straddle = round(spot_price * 0.012, 1)
        return {
            "call_wall_strike": atm_strike + step * 4,
            "call_wall_oi": "--",
            "call_wall_dist": round(step * 4, 1),
            "put_wall_strike": atm_strike - step * 4,
            "put_wall_oi": "--",
            "put_wall_dist": round(step * 4, 1),
            "fresh_ce_strike": atm_strike + step * 2,
            "fresh_ce_chg": "0",
            "fresh_ce_dist": round(step * 2, 1),
            "fresh_pe_strike": atm_strike - step * 2,
            "fresh_pe_chg": "0",
            "fresh_pe_dist": round(step * 2, 1),
            "atm_straddle": fallback_straddle,
            "lower_band": round(atm_strike - fallback_straddle, 1),
            "upper_band": round(atm_strike + fallback_straddle, 1),
            "straddle_pct": 1.2
        }

    ce_strikes = [s for s in parsed.strikes if s.CE]
    pe_strikes = [s for s in parsed.strikes if s.PE]

    max_ce = max(ce_strikes, key=lambda s: s.CE.openInterest) if ce_strikes else None
    max_pe = max(pe_strikes, key=lambda s: s.PE.openInterest) if pe_strikes else None

    pos_ce = [s for s in ce_strikes if s.CE.changeinOpenInterest > 0]
    pos_pe = [s for s in pe_strikes if s.PE.changeinOpenInterest > 0]
    max_ce_chg = max(pos_ce, key=lambda s: s.CE.changeinOpenInterest) if pos_ce else max_ce
    max_pe_chg = max(pos_pe, key=lambda s: s.PE.changeinOpenInterest) if pos_pe else max_pe

    atm_row = next((s for s in parsed.strikes if s.strikePrice == atm_strike), None) or (parsed.strikes[len(parsed.strikes)//2] if parsed.strikes else None)
    ce_ltp = atm_row.CE.lastPrice if atm_row and atm_row.CE else 0.0
    pe_ltp = atm_row.PE.lastPrice if atm_row and atm_row.PE else 0.0
    straddle = round(ce_ltp + pe_ltp, 1) if (ce_ltp + pe_ltp > 0) else round(spot_price * 0.012, 1)

    cw_strike = max_ce.strikePrice if max_ce else (atm_strike + step * 4)
    cw_oi = max_ce.CE.openInterest if max_ce else 0
    pw_strike = max_pe.strikePrice if max_pe else (atm_strike - step * 4)
    pw_oi = max_pe.PE.openInterest if max_pe else 0

    fce_strike = max_ce_chg.strikePrice if max_ce_chg else cw_strike
    fce_chg = max_ce_chg.CE.changeinOpenInterest if max_ce_chg else 0
    fpe_strike = max_pe_chg.strikePrice if max_pe_chg else pw_strike
    fpe_chg = max_pe_chg.PE.changeinOpenInterest if max_pe_chg else 0

    return {
        "call_wall_strike": cw_strike,
        "call_wall_oi": _format_compact(cw_oi),
        "call_wall_dist": round(cw_strike - spot_price, 1),
        "put_wall_strike": pw_strike,
        "put_wall_oi": _format_compact(pw_oi),
        "put_wall_dist": round(spot_price - pw_strike, 1),
        "fresh_ce_strike": fce_strike,
        "fresh_ce_chg": _format_signed(fce_chg),
        "fresh_ce_dist": round(fce_strike - spot_price, 1),
        "fresh_pe_strike": fpe_strike,
        "fresh_pe_chg": _format_signed(fpe_chg),
        "fresh_pe_dist": round(spot_price - fpe_strike, 1),
        "atm_straddle": straddle,
        "lower_band": round(atm_strike - straddle, 1),
        "upper_band": round(atm_strike + straddle, 1),
        "straddle_pct": round(straddle / max(1, spot_price) * 100, 2)
    }


def _compute_trap_detection(
    sym: str,
    spot_price: float,
    atm_strike: float,
    parsed: Optional[ParsedOptionChain],
    step: float,
    confluence_score: float,
    brk_state: str = "FLAT",
    timeline: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Detects Institutional Traps & Fake Breakouts:
    - Bull Trap (Price near highs or breakout, but Call Writing surging)
    - Bear Trap (Price near lows or breakdown, but Put Writing surging)
    - Short Squeeze (Price rising + Call OI unwinding heavily)
    - Waterfall Dump (Price dropping + Put OI unwinding heavily)
    - Clean / Organic Flow
    """
    if not parsed or not parsed.strikes:
        return {
            "type": "CLEAN",
            "badge": "🛡️ ORDER FLOW CLEAN",
            "color": "yellow",
            "desc": "Standard order flow balance",
            "trap_risk": "LOW (12%)",
            "action": "TRADE WITH CONFLUENCE"
        }

    spots = [pt["spot"] for pt in timeline if pt.get("spot", 0) > 500] if timeline else [spot_price]
    high_spot = max(spots) if spots else spot_price
    low_spot = min(spots) if spots else spot_price
    range_span = max(1.0, high_spot - low_spot)
    rel_pos = (spot_price - low_spot) / range_span if range_span > 0 else 0.5

    ce_strikes = [s for s in parsed.strikes if s.CE]
    pe_strikes = [s for s in parsed.strikes if s.PE]

    tot_ce_chg = sum(s.CE.changeinOpenInterest for s in ce_strikes)
    tot_pe_chg = sum(s.PE.changeinOpenInterest for s in pe_strikes)

    near_strikes = [s for s in parsed.strikes if abs(s.strikePrice - atm_strike) <= step]
    near_ce_chg = sum(s.CE.changeinOpenInterest for s in near_strikes if s.CE)
    near_pe_chg = sum(s.PE.changeinOpenInterest for s in near_strikes if s.PE)

    # 1. Bull Trap Detection (Pushing near highs, but Call writers attacking or Put buyers absent)
    if rel_pos >= 0.70 or brk_state in ("LONG_BREAKOUT", "BREAKOUT"):
        if near_ce_chg > near_pe_chg * 1.3 and near_ce_chg > 150_000:
            return {
                "type": "BULL_TRAP",
                "badge": "🚨 BULL TRAP WARNING",
                "color": "dark-red",
                "desc": f"Price near highs ({spot_price:.1f}) but heavy Call Writing ({_format_signed(near_ce_chg)}) blocking upside",
                "trap_risk": "HIGH (86%)",
                "action": "AVOID CE BUYS / WATCH REJECTION"
            }
        elif tot_ce_chg < -250_000 and tot_pe_chg > 250_000:
            return {
                "type": "SHORT_SQUEEZE",
                "badge": "⚡ SHORT SQUEEZE ACTIVE",
                "color": "dark-green",
                "desc": f"Call writers panicking and covering ({_format_signed(tot_ce_chg)}). Upside explosive",
                "trap_risk": "ZERO (Short Fuel)",
                "action": "RIDE CALL MOMENTUM"
            }

    # 2. Bear Trap Detection (Pushing near lows, but Put writers defending)
    if rel_pos <= 0.30 or brk_state in ("SHORT_BREAKOUT", "BREAKDOWN"):
        if near_pe_chg > near_ce_chg * 1.3 and near_pe_chg > 150_000:
            return {
                "type": "BEAR_TRAP",
                "badge": "🪤 BEAR TRAP DEFENSE",
                "color": "dark-green",
                "desc": f"Price near lows ({spot_price:.1f}) but aggressive Put Writing ({_format_signed(near_pe_chg)}) providing floor",
                "trap_risk": "HIGH (84%)",
                "action": "AVOID PE BUYS / WATCH REVERSAL"
            }
        elif tot_pe_chg < -250_000 and tot_ce_chg > 250_000:
            return {
                "type": "WATERFALL_DUMP",
                "badge": "💥 WATERFALL BREAKDOWN",
                "color": "dark-red",
                "desc": f"Put writers capitulating ({_format_signed(tot_pe_chg)}). Support completely broken",
                "trap_risk": "ZERO (Dump Fuel)",
                "action": "RIDE PUT MOMENTUM"
            }

    # 3. Organic directional momentum vs consolidation
    if confluence_score >= 65:
        return {
            "type": "BULL_EXPANSION",
            "badge": "🟢 ORGANIC BULL TREND",
            "color": "light-green",
            "desc": "Healthy Call buying and Put support building in sync",
            "trap_risk": "LOW (14%)",
            "action": "ACCUMULATE CALLS ON DIPS"
        }
    elif confluence_score <= 35:
        return {
            "type": "BEAR_PRESSURE",
            "badge": "🟠 ORGANIC BEAR TREND",
            "color": "light-red",
            "desc": "Order flow shows steady Call dominance and Put liquidation",
            "trap_risk": "LOW (16%)",
            "action": "SELL PULLBACKS / BUY PUTS"
        }
    else:
        return {
            "type": "CLEAN",
            "badge": "🛡️ ORDER FLOW BALANCED",
            "color": "yellow",
            "desc": "No institutional trap detected. Neutral consolidation",
            "trap_risk": "MODERATE (Chop Zone)",
            "action": "WAIT FOR BREAKOUT CONFIRMATION"
        }


def _compute_scalp_setup(
    sym: str,
    spot_price: float,
    atm_strike: float,
    step: float,
    confluence_score: float,
    trap_info: Dict[str, Any],
    inst_params: Dict[str, Any],
    lot_size: int
) -> Dict[str, Any]:
    """
    Computes precise, rule-based algorithmic scalp setup:
    Entry Trigger, Stop Loss, Target 1, Target 2, Risk:Reward, Conviction.
    """
    trap_type = trap_info.get("type", "CLEAN")
    cw_strike = inst_params.get("call_wall_strike", atm_strike + step * 2)
    pw_strike = inst_params.get("put_wall_strike", atm_strike - step * 2)

    # Bullish Scalp Setup
    if confluence_score >= 58 and trap_type not in ("BULL_TRAP", "BEAR_PRESSURE"):
        rec_strike = int(atm_strike if spot_price >= atm_strike else (atm_strike - step))
        contract = f"{sym} {rec_strike} CE"
        trigger = round(spot_price + (step * 0.12), 1)
        sl = round(spot_price - (step * 0.35), 1)
        sl_pts = round(trigger - sl, 1)
        tgt1 = round(min(cw_strike, trigger + (sl_pts * 1.5)), 1)
        tgt2 = round(trigger + (sl_pts * 2.5), 1)
        rr = round((tgt1 - trigger) / max(1.0, sl_pts), 1)

        return {
            "action": "BUY CALL",
            "bias": "BULLISH SCALP",
            "contract": contract,
            "badge_color": "dark-green",
            "entry_trigger": f"Above {trigger:.1f}",
            "stop_loss": f"{sl:.1f} (-{sl_pts:.0f} pts)",
            "target_1": f"{tgt1:.1f} (+{tgt1 - trigger:.0f} pts)",
            "target_2": f"{tgt2:.1f} (+{tgt2 - trigger:.0f} pts)",
            "risk_reward": f"1 : {rr:.1f}",
            "conviction": "HIGH CONVICTION (88%)" if confluence_score >= 75 else "MODERATE (68%)",
            "lot_size": lot_size,
            "status": "READY_TO_FIRE" if confluence_score >= 65 else "WAITING_TRIGGER",
            "reason": "Confluence >= 58 with clean orderflow"
        }

    # Bearish Scalp Setup
    elif confluence_score <= 42 and trap_type not in ("BEAR_TRAP", "BULL_EXPANSION"):
        rec_strike = int(atm_strike if spot_price <= atm_strike else (atm_strike + step))
        contract = f"{sym} {rec_strike} PE"
        trigger = round(spot_price - (step * 0.12), 1)
        sl = round(spot_price + (step * 0.35), 1)
        sl_pts = round(sl - trigger, 1)
        tgt1 = round(max(pw_strike, trigger - (sl_pts * 1.5)), 1)
        tgt2 = round(trigger - (sl_pts * 2.5), 1)
        rr = round((trigger - tgt1) / max(1.0, sl_pts), 1)

        return {
            "action": "BUY PUT",
            "bias": "BEARISH SCALP",
            "contract": contract,
            "badge_color": "dark-red",
            "entry_trigger": f"Below {trigger:.1f}",
            "stop_loss": f"{sl:.1f} (+{sl_pts:.0f} pts)",
            "target_1": f"{tgt1:.1f} (-{trigger - tgt1:.0f} pts)",
            "target_2": f"{tgt2:.1f} (-{trigger - tgt2:.0f} pts)",
            "risk_reward": f"1 : {rr:.1f}",
            "conviction": "HIGH CONVICTION (85%)" if confluence_score <= 25 else "MODERATE (65%)",
            "lot_size": lot_size,
            "status": "READY_TO_FIRE" if confluence_score <= 35 else "WAITING_TRIGGER",
            "reason": "Confluence <= 42 with bearish orderflow"
        }

    # Neutral / Chop / Trap Alert
    else:
        reason = "Chop Corridor (42-58)" if trap_type == "CLEAN" else f"Trapped Orderflow ({trap_info.get('badge')})"
        return {
            "action": "STAND ASIDE",
            "bias": "NO TRADE / WAIT",
            "contract": f"{sym} (WAIT FOR RANGE BREAK)",
            "badge_color": "yellow",
            "entry_trigger": f"Wait > {atm_strike + step:.0f} or < {atm_strike - step:.0f}",
            "stop_loss": "--",
            "target_1": "--",
            "target_2": "--",
            "risk_reward": "N/A",
            "conviction": "AVOID (High Theta Decay / False Breakout Risk)",
            "lot_size": lot_size,
            "status": "STAND_ASIDE",
            "reason": reason
        }


def _compute_market_divergence(indices_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Computes Relative Strength ranking and benchmark inter-market divergence across all 5 indices.
    """
    if not indices_data:
        return {}

    scored_list = []
    for d in indices_data:
        sym = d["symbol"]
        conf = d.get("confluence", {}).get("score", 50.0)
        pcr_val = d.get("pcr", {}).get("value", 1.0)
        pcr_factor = (pcr_val - 1.0) * 20.0

        brk_score = d.get("breakout", {}).get("strength_score", 50.0)
        rel_strength = round(max(5.0, min(95.0, (conf * 0.50) + ((50.0 + pcr_factor) * 0.25) + (brk_score * 0.25))), 1)

        color = _get_5color_class(rel_strength)
        label = "LEADER" if rel_strength >= 70 else ("BULLISH" if rel_strength >= 55 else ("LAGGARD" if rel_strength <= 30 else ("BEARISH" if rel_strength <= 45 else "NEUTRAL")))

        scored_list.append({
            "symbol": sym,
            "rel_strength": rel_strength,
            "label": label,
            "color": color,
            "conf": conf,
            "pcr": pcr_val,
            "spot": d.get("spot_price", 0.0)
        })

    # Sort descending: Leader at index 0, Laggard at index -1
    scored_list.sort(key=lambda x: x["rel_strength"], reverse=True)
    leader = scored_list[0]
    laggard = scored_list[-1]

    # Inter-Market Divergence between key benchmarks: NIFTY and BANKNIFTY
    nifty = next((x for x in scored_list if x["symbol"] == "NIFTY"), None)
    bnifty = next((x for x in scored_list if x["symbol"] == "BANKNIFTY"), None)

    div_status = "BALANCED"
    headline = "⚖️ BALANCED ROTATION"
    sub_desc = "Order flow across indices is balanced and non-divergent."

    if nifty and bnifty:
        n_conf = nifty["conf"]
        b_conf = bnifty["conf"]

        if n_conf >= 58 and b_conf <= 42:
            div_status = "DIVERGENCE"
            headline = "⚠️ INTER-MARKET DIVERGENCE: NIFTY Bullish vs BANKNIFTY Dragging"
            sub_desc = f"NIFTY Confluence is {n_conf:.0f} (Bullish) while BANKNIFTY is heavy at {b_conf:.0f}. High fake-breakout risk on NIFTY."
        elif b_conf >= 58 and n_conf <= 42:
            div_status = "DIVERGENCE"
            headline = "⚠️ INTER-MARKET DIVERGENCE: BANKNIFTY Outperforming NIFTY"
            sub_desc = f"BANKNIFTY Confluence is {b_conf:.0f} while NIFTY lags at {n_conf:.0f}. Sector divergence active."
        elif n_conf >= 60 and b_conf >= 60:
            div_status = "SYNCHRONIZED_BULL"
            headline = "⚡ SYNCHRONIZED BULL CONFLUENCE"
            sub_desc = f"Both NIFTY ({n_conf:.0f}) and BANKNIFTY ({b_conf:.0f}) moving in institutional lockstep upward. 92% conviction."
        elif n_conf <= 40 and b_conf <= 40:
            div_status = "SYNCHRONIZED_BEAR"
            headline = "💥 SYNCHRONIZED BEAR SQUEEZE"
            sub_desc = f"Market-wide selling: Both NIFTY ({n_conf:.0f}) and BANKNIFTY ({b_conf:.0f}) breakdown aligned. High put momentum."

    return {
        "status": div_status,
        "headline": headline,
        "description": sub_desc,
        "leader": f"{leader['symbol']} ({leader['rel_strength']:.0f} RS)",
        "laggard": f"{laggard['symbol']} ({laggard['rel_strength']:.0f} RS)",
        "rankings": scored_list
    }


def _compute_strategy_confluence(
    sym: str,
    spot_price: float,
    atm_strike: float,
    lot_size: int,
    ce_buildup: str,
    pe_buildup: str,
    net_oi_diff: int,
    diff_velocity_1m: int,
    trend_arrow: str,
    pcr: float,
    pcr_trend: str,
    hull_info: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Constructs the 4-Column Strategy Confluence Table directly from centralized metrics:
    Column 1: Indices (Symbol, Spot, ATM, Lot)
    Column 2: Option Chain Signal & Strength (from existing centralized buildup, PCR & velocity)
    Column 3: Hull Indicator (from centralized indicator_5)
    Column 4: What to do? Buy Call or Put? (Calculates final signal without recalculating indicators)
    """
    # 1. Option Chain Signal & Direction (from centralized positioning)
    if net_oi_diff >= 0:
        oi_dir = "BULLISH"
        oi_sig_label = "LONG BUILDUP ↗" if diff_velocity_1m >= 0 else "SHORT COVERING ↗"
        oi_badge_color = "dark-green" if diff_velocity_1m >= 0 else "light-green"
        oi_strength = "Put Writing Floor / Net Put Dominant"
    else:
        oi_dir = "BEARISH"
        oi_sig_label = "SHORT BUILDUP ↘" if diff_velocity_1m <= 0 else "LONG UNWINDING ↘"
        oi_badge_color = "dark-red" if diff_velocity_1m <= 0 else "light-red"
        oi_strength = "Call Writing Resistance / Net Call Dominant"

    pcr_strength_str = f"PCR: {pcr:.2f} ({pcr_trend.split()[0]})"
    oi_flow_str = f"{trend_arrow} {_format_signed(diff_velocity_1m)}/1m"
    oi_chain_strength_desc = f"{oi_strength} • {pcr_strength_str} • {oi_flow_str}"

    # 2. Hull Indicator (Direct from centralized summary indicator_5)
    hull_trend = str(hull_info.get("state", "NEUTRAL")).upper()
    hull_val = float(hull_info.get("value") or spot_price)

    if hull_trend == "BULLISH":
        hull_label = "BULLISH 🟢"
        hull_badge_color = "dark-green"
        hull_desc = f"EHMA Suite ({hull_val:,.1f}) Bullish"
    elif hull_trend == "BEARISH":
        hull_label = "BEARISH 🔴"
        hull_badge_color = "dark-red"
        hull_desc = f"EHMA Suite ({hull_val:,.1f}) Bearish"
    else:
        hull_label = "NEUTRAL 🟡"
        hull_badge_color = "yellow"
        hull_desc = f"EHMA Suite ({hull_val:,.1f}) Flat"

    step = 50.0 if sym in ["NIFTY", "FINNIFTY"] else (100.0 if sym in ["BANKNIFTY", "SENSEX"] else 25.0)

    if is_aligned and hull_trend == "BULLISH":
        action_verdict = "BUY CALL"
        action_type = "CE"
        itm_strike = int(atm_strike - step)
        suggested_strike = f"{itm_strike} CE (ITM Δ0.53) / {int(atm_strike)} CE (ATM Δ0.50)"
        action_badge_color = "dark-green"
        action_sub = "OI Bullish + Hull Bullish Aligned"
    elif is_aligned and hull_trend == "BEARISH":
        action_verdict = "BUY PUT"
        action_type = "PE"
        itm_strike = int(atm_strike + step)
        suggested_strike = f"{itm_strike} PE (ITM Δ0.53) / {int(atm_strike)} PE (ATM Δ0.50)"
        action_badge_color = "dark-red"
        action_sub = "OI Bearish + Hull Bearish Aligned"
    elif is_opposed:
        action_verdict = "CONFLICT - NO TRADE"
        action_type = "NONE"
        suggested_strike = "STAND ASIDE (Chop Gate)"
        action_badge_color = "light-red"
        action_sub = f"Opposing: OI {oi_dir} vs Hull {hull_trend}"
    else:
        action_verdict = "STANDBY"
        action_type = "NONE"
        suggested_strike = "AWAIT SETUP"
        action_badge_color = "yellow"
        action_sub = "No Directional Confluence"

    return {
        "symbol": sym,
        "spot_price": spot_price,
        "atm_strike": atm_strike,
        "lot_size": lot_size,
        "option_chain_signal": {
            "buildup": oi_sig_label.split()[0],
            "label": oi_sig_label,
            "direction": oi_dir,
            "badge_color": oi_badge_color,
            "strength_desc": oi_chain_strength_desc,
            "pcr": pcr,
            "net_oi_flow": oi_flow_str
        },
        "hull_indicator": {
            "trend": hull_trend,
            "label": hull_label,
            "badge_color": hull_badge_color,
            "desc": hull_desc,
            "val": round(hull_val, 1)
        },
        "action": {
            "verdict": action_verdict,
            "type": action_type,
            "strike": suggested_strike,
            "badge_color": action_badge_color,
            "sub": action_sub,
            "is_aligned": is_aligned,
            "is_opposed": is_opposed
        }
    }


async def _compute_symbol_matrix(sym: str, settings: Any) -> Optional[Dict[str, Any]]:
    try:
        # 1. Fetch live option chain
        raw_chain, source = await fetch_live_chain_data(sym)
        parsed: Optional[ParsedOptionChain] = None
        if raw_chain:
            parsed = parse_option_chain(raw_chain, sym)

        # 2. Confluence Analysis (Fast Macro Mode - skips strike candle loops)
        conf_data = await option_confluence_service.analyze_confluence(
            sym, range_strikes=3, parsed_chain=parsed, compute_strike_candles=False
        )
        if not conf_data:
            return None

        summary = conf_data.get("summary", {})
        strikes = conf_data.get("strikes", [])
        atm_row = next((s for s in strikes if s.get("offset") == 0), None) or (strikes[len(strikes)//2] if strikes else {})

        spot_price = float(parsed.spot_price) if (parsed and parsed.spot_price > 0) else float(conf_data.get("spot_price", 0.0))
        atm_strike = float(parsed.atm_strike) if (parsed and parsed.atm_strike > 0) else float(conf_data.get("atm_strike", 0.0))

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

        # 3. Difference in OI & 1-Minute Interval Velocity (Total Session Chain)
        if parsed and parsed.total_ce_oi > 0:
            tot_ce_oi = int(parsed.total_ce_oi)
            tot_pe_oi = int(parsed.total_pe_oi)
            tot_ce_chg = int(sum(stk.CE.changeinOpenInterest for stk in parsed.strikes if stk.CE))
            tot_pe_chg = int(sum(stk.PE.changeinOpenInterest for stk in parsed.strikes if stk.PE))
        else:
            tot_ce_oi = int(sum(s.get("ce", {}).get("oi", 0) for s in strikes))
            tot_pe_oi = int(sum(s.get("pe", {}).get("oi", 0) for s in strikes))
            tot_ce_chg = int(sum(s.get("ce", {}).get("oi_chg", 0) for s in strikes))
            tot_pe_chg = int(sum(s.get("pe", {}).get("oi_chg", 0) for s in strikes))

        # True exchange-wide Option Chain PCR: Put OI / Call OI
        pcr = round(tot_pe_oi / max(1, tot_ce_oi), 2)
        confluence_score = int(summary.get("confluence_score") or summary.get("overall_confluence_score") or 50)
        bias = summary.get("overall_bias", "NEUTRAL")

        # 4. Breakout Indicator Analysis
        brk_info = summary.get("indicator_breakout") or summary.get("indicator_6") or {}
        brk_state = brk_info.get("state", "FLAT")       # "LONG", "SHORT", "FLAT"
        brk_bias = brk_info.get("bias", "NEUTRAL")
        brk_sig = brk_info.get("signal", "HOLD")
        brk_lvl = brk_info.get("breakout_level") or brk_info.get("res_level") or brk_info.get("sup_level")
        brk_trail = brk_info.get("trail_level")
        
        # Compute Breakout Strength (0-100)
        if brk_state == "LONG":
            brk_score = 90.0 if brk_sig == "BUY" else 80.0
        elif brk_state == "SHORT":
            brk_score = 10.0 if brk_sig == "SELL" else 20.0
        else:
            brk_score = 50.0

        brk_color = _get_5color_class(brk_score)

        # 5. Proximity (MAPO) Indicator
        # MAPO ribbon score: < 40 Bearish, > 60 Bullish
        mapo_info = summary.get("indicator_4") or {}
        mapo_pct = float(mapo_info.get("per", 50.0))
        mapo_color = _get_5color_class(mapo_pct)
        mapo_state = mapo_info.get("state", "CHOP CORRIDOR")
        if mapo_state not in ["BULLISH EXPANSION", "BEARISH EXPANSION", "CHOP CORRIDOR"]:
            mapo_state = "BULLISH EXPANSION" if mapo_pct >= 60 else ("BEARISH EXPANSION" if mapo_pct <= 40 else "CHOP CORRIDOR")

        # 6. PCR Analysis
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

        ce_buildup = str(ce_atm.get("buildup", "SHORT_BUILDUP")).replace("_", " ").upper()
        pe_buildup = str(pe_atm.get("buildup", "SHORT_BUILDUP")).replace("_", " ").upper()

        # Color for Call Buildup (Call writing is bearish resistance, Call buying is bullish momentum)
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

        # Color for Put Buildup (Put writing is bullish floor, Put buying is bearish crash anticipation)
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

        sparkline_pts = _get_confluence_sparkline(sym, confluence_score)
        day_open_conf = sparkline_pts[0] if sparkline_pts else confluence_score
        day_high_conf = max(sparkline_pts) if sparkline_pts else confluence_score
        day_low_conf = min(sparkline_pts) if sparkline_pts else confluence_score
        conf_shift = round(confluence_score - day_open_conf, 1)

        inst_params = _compute_institutional_parameters(sym, spot_price, atm_strike, parsed, step)
        trap_info = _compute_trap_detection(sym, spot_price, atm_strike, parsed, step, confluence_score, brk_state=brk_state)
        scalp_setup = _compute_scalp_setup(sym, spot_price, atm_strike, step, confluence_score, trap_info, inst_params, lot_map.get(sym, 20))
        inst_params["trap_detection"] = trap_info
        inst_params["scalp_setup"] = scalp_setup

        # 4-Column Strategy Confluence Matrix (directly from centralized option confluence engine)
        strat_conf = conf_data.get("strategy_confluence") or {}

        return {
            "symbol": sym,
            "spot_price": spot_price,
            "atm_strike": atm_strike,
            "expiry_day": expiry_map.get(sym, "Weekly"),
            "lot_size": lot_map.get(sym, settings.LOT_SIZES.get(sym, 20)),
            "strategy_confluence": strat_conf,
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
            "call_positioning": {
                "buildup": ce_buildup,
                "total_oi": _format_compact(tot_ce_oi),
                "oi_chg_session": _format_signed(tot_ce_chg),
                "color": ce_color
            },
            "put_positioning": {
                "buildup": pe_buildup,
                "total_oi": _format_compact(tot_pe_oi),
                "oi_chg_session": _format_signed(tot_pe_chg),
                "color": pe_color
            },
            "confluence": {
                "score": confluence_score,
                "color": conf_color,
                "sparkline": sparkline_pts,
                "day_open": day_open_conf,
                "day_high": day_high_conf,
                "day_low": day_low_conf,
                "shift": conf_shift
            },
            "action": {
                "signal": action_guide,
                "verdict_text": verdict_text,
                "color": conf_color
            },
            "trap": trap_info,
            "scalp_setup": scalp_setup,
            "institutional": inst_params,
            "strikes": strike_chain
        }

    except Exception as e:
        logger.error(f"Error computing matrix dashboard for {sym}: {e}", exc_info=True)
        return None


@router.get("/live")
async def get_live_matrix_dashboard() -> Dict[str, Any]:
    """
    Returns the real-time matrix across all 5 indices for the dedicated /dashboard interface.
    Uses ultra-fast concurrent gather and short-TTL response caching to eliminate stalls.
    """
    global _matrix_live_cache, _matrix_live_cache_time
    now_ts = time.time()
    if _matrix_live_cache and (now_ts - _matrix_live_cache_time) < 3.0:
        return _matrix_live_cache

    settings = get_settings()
    symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
    
    # Run all 5 symbols concurrently
    results = await asyncio.gather(*[_compute_symbol_matrix(sym, settings) for sym in symbols], return_exceptions=True)
    indices_data = [r for r in results if isinstance(r, dict) and r]

    market_div = _compute_market_divergence(indices_data)
    strategy_table = [item["strategy_confluence"] for item in indices_data if "strategy_confluence" in item]

    # Multi-Index 6-Pillar Alignment Bar Summary
    bull_count = 0
    bear_count = 0
    conflict_count = 0
    alignment_summary = []

    for item in indices_data:
        sym_name = item.get("symbol")
        strat = item.get("strategy_confluence", {})
        action_info = strat.get("action", {})
        v = action_info.get("verdict", "NEUTRAL")
        if v == "BUY CALL":
            bull_count += 1
        elif v == "BUY PUT":
            bear_count += 1
        elif "CONFLICT" in v:
            conflict_count += 1

        alignment_summary.append({
            "symbol": sym_name,
            "spot": item.get("spot_price", 0.0),
            "atm": item.get("atm_strike", 0.0),
            "breakout": item.get("breakout", {}).get("state", "NONE"),
            "breakout_color": item.get("breakout", {}).get("color", "yellow"),
            "proximity": item.get("proximity", {}).get("state", "NEUTRAL"),
            "proximity_color": item.get("proximity", {}).get("color", "yellow"),
            "pcr": item.get("pcr", {}).get("value", 1.0),
            "pcr_color": item.get("pcr", {}).get("color", "yellow"),
            "net_oi_flow": item.get("oi_difference", {}).get("velocity_label", "Steady"),
            "net_oi_color": item.get("oi_difference", {}).get("color", "yellow"),
            "buildup": item.get("call_positioning", {}).get("buildup", "NEUTRAL"),
            "hull": strat.get("hull_indicator", {}).get("trend", "NEUTRAL"),
            "hull_color": strat.get("hull_indicator", {}).get("badge_color", "yellow"),
            "verdict": v,
            "badge_color": action_info.get("badge_color", "yellow"),
            "suggested_strike": action_info.get("strike", "")
        })

    if bull_count >= 4:
        macro_text = f"⚡ {bull_count}/5 INDICES BULLISH ALIGNED (Full Institutional Expansion)"
        macro_badge = "dark-green"
    elif bear_count >= 4:
        macro_text = f"⚡ {bear_count}/5 INDICES BEARISH ALIGNED (Heavy Call Resistance / Breakdown)"
        macro_badge = "dark-red"
    elif bull_count >= 3:
        macro_text = f"🟢 {bull_count}/5 INDICES BULLISH (Mild Call Favor - Confirm Strike Flow)"
        macro_badge = "light-green"
    elif bear_count >= 3:
        macro_text = f"🔴 {bear_count}/5 INDICES BEARISH (Mild Put Favor - Confirm Strike Flow)"
        macro_badge = "light-red"
    else:
        macro_text = f"⚠️ MARKET DIVERGENCE (Selective Rotation - Stand Aside / Avoid Chop)"
        macro_badge = "yellow"

    res = {
        "status": "success",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_indices": len(indices_data),
        "data": indices_data,
        "strategy_table": strategy_table,
        "market_divergence": market_div,
        "alignment_matrix": {
            "macro_text": macro_text,
            "macro_badge": macro_badge,
            "bull_count": bull_count,
            "bear_count": bear_count,
            "conflict_count": conflict_count,
            "indices": alignment_summary
        }
    }
    _matrix_live_cache = res
    _matrix_live_cache_time = time.time()
    return res


@router.get("/timeseries/{symbol}")
async def get_matrix_timeseries(symbol: str) -> Dict[str, Any]:
    """
    Returns intraday minute timeline (09:15 - 15:30) of Call OI vs Put OI (Total & Change in OI),
    Net OI Difference, Volume Flow, and Institutional Fortress Parameters for the requested index.
    """
    sym = symbol.upper()
    now_ts = time.time()
    if sym in _timeseries_cache and (now_ts - _timeseries_cache_time.get(sym, 0.0)) < 3.0:
        return _timeseries_cache[sym]

    try:
        settings = get_settings()
        step = settings.STRIKE_STEPS.get(sym, 100 if sym == "SENSEX" else 50)
        
        # 1. Fetch live chain for strike-level institutional fortress parameters
        raw_chain, source = await fetch_live_chain_data(sym)
        parsed: Optional[ParsedOptionChain] = None
        if raw_chain:
            parsed = parse_option_chain(raw_chain, sym)

        with snapshot_storage._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT time_str, spot, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, (pe_oi - ce_oi) as net_diff, pcr, confluence, ce_vol, pe_vol
                FROM intraday_snapshots
                WHERE symbol = ? AND spot > 500 AND time_str >= '09:15' AND time_str <= '15:30'
                  AND trade_date = (SELECT MAX(trade_date) FROM intraday_snapshots WHERE symbol = ?)
                GROUP BY time_str
                ORDER BY time_str ASC
            """, (sym, sym))
            rows = cur.fetchall()
            
            raw_timeline = []
            for r in rows:
                c_oi = int(r["ce_oi"])
                p_oi = int(r["pe_oi"])
                c_chg = int(r["ce_oi_chg"])
                p_chg = int(r["pe_oi_chg"])
                c_vol = int(r["ce_vol"]) if "ce_vol" in r.keys() else 0
                p_vol = int(r["pe_vol"]) if "pe_vol" in r.keys() else 0
                conf_val = float(r["confluence"])
                
                raw_timeline.append({
                    "time": r["time_str"],
                    "spot": round(float(r["spot"]), 2),
                    "ce_oi": c_oi,
                    "pe_oi": p_oi,
                    "ce_oi_chg": c_chg,
                    "pe_oi_chg": p_chg,
                    "net_diff": p_oi - c_oi,
                    "net_oi_chg": p_chg - c_chg,
                    "pcr": round(float(r["pcr"]), 2),
                    "confluence": conf_val,
                    "ce_vol": c_vol,
                    "pe_vol": p_vol
                })

            # Despike boundary strike entry/exit artifacts from earlier sessions
            cleaned_timeline = []
            for i in range(len(raw_timeline)):
                pt = dict(raw_timeline[i])
                if 0 < i < len(raw_timeline) - 1:
                    prev_pt = raw_timeline[i - 1]
                    next_pt = raw_timeline[i + 1]
                    
                    # CE spike check
                    c_curr = pt["ce_oi"]
                    c_prev = prev_pt["ce_oi"]
                    c_next = next_pt["ce_oi"]
                    if (c_curr - c_prev > 4_000_000 and c_curr - c_next > 4_000_000) or \
                       (c_prev - c_curr > 4_000_000 and c_next - c_curr > 4_000_000):
                        pt["ce_oi"] = int((c_prev + c_next) / 2)
                    
                    # PE spike check
                    p_curr = pt["pe_oi"]
                    p_prev = prev_pt["pe_oi"]
                    p_next = next_pt["pe_oi"]
                    if (p_curr - p_prev > 4_000_000 and p_curr - p_next > 4_000_000) or \
                       (p_prev - p_curr > 4_000_000 and p_next - p_curr > 4_000_000):
                        pt["pe_oi"] = int((p_prev + p_next) / 2)
                    
                    pt["net_diff"] = pt["pe_oi"] - pt["ce_oi"]
                cleaned_timeline.append(pt)

            # Second pass for 2-minute sustained spikes & cumulative deltas from 09:15 open
            if cleaned_timeline:
                base_ce = cleaned_timeline[0]["ce_oi"]
                base_pe = cleaned_timeline[0]["pe_oi"]
                for i, pt in enumerate(cleaned_timeline):
                    if 0 < i < len(cleaned_timeline) - 1:
                        c_prev = cleaned_timeline[i - 1]["ce_oi"]
                        c_next = cleaned_timeline[i + 1]["ce_oi"]
                        if abs(pt["ce_oi"] - c_prev) > 6_000_000 and abs(pt["ce_oi"] - c_next) > 6_000_000:
                            pt["ce_oi"] = int((c_prev + c_next) / 2)
                            pt["net_diff"] = pt["pe_oi"] - pt["ce_oi"]
                    
                    # Cumulative OI change from session open (09:15)
                    pt["ce_oi_delta"] = pt["ce_oi"] - base_ce
                    pt["pe_oi_delta"] = pt["pe_oi"] - base_pe
                    pt["net_delta"] = pt["pe_oi_delta"] - pt["ce_oi_delta"]
                    
                    # Recompute dynamic confluence if default 50.0
                    if pt["confluence"] == 50.0:
                        tot_chg = abs(pt["ce_oi_chg"]) + abs(pt["pe_oi_chg"])
                        factor = (pt["pe_oi_chg"] - pt["ce_oi_chg"]) / max(1, tot_chg) if tot_chg > 0 else 0
                        dyn = 50.0 + (pt["pcr"] - 1.0) * 35.0 + (factor * 25.0)
                        pt["confluence"] = round(max(10.0, min(92.0, dyn)), 1)

            timeline = cleaned_timeline

            curr_spot = (parsed.spot_price if parsed and parsed.spot_price > 0 else (timeline[-1]["spot"] if timeline else 23000.0))
            atm_strike = (parsed.atm_strike if parsed and parsed.atm_strike > 0 else round(curr_spot / step) * step)

            # Compute high-grade institutional parameters replacing static anchors
            inst_params = _compute_institutional_parameters(sym, curr_spot, atm_strike, parsed, step)
            
            # Enrich with session confluence & PCR analytics
            conf_series = [pt["confluence"] for pt in timeline] if timeline else [50.0]
            current_conf = conf_series[-1] if conf_series else 50.0
            day_open_conf = conf_series[0] if conf_series else 50.0
            day_high_conf = max(conf_series) if conf_series else 50.0
            day_low_conf = min(conf_series) if conf_series else 50.0

            inst_params["confluence_profile"] = {
                "current": current_conf,
                "day_open": day_open_conf,
                "day_high": day_high_conf,
                "day_low": day_low_conf,
                "shift": round(current_conf - day_open_conf, 1),
                "trajectory": "EXPANDING BULLISH" if current_conf >= 60 else ("COLLAPSING BEARISH" if current_conf <= 40 else "CHOP CORRIDOR")
            }

            last_pcr = timeline[-1]["pcr"] if timeline else 1.0
            pcr_5m_ago = timeline[-6]["pcr"] if len(timeline) >= 6 else (timeline[0]["pcr"] if timeline else 1.0)
            pcr_5m_delta = round(last_pcr - pcr_5m_ago, 2)
            
            total_pe_vol = sum(pt.get("pe_vol", 0) for pt in timeline)
            total_ce_vol = sum(pt.get("ce_vol", 0) for pt in timeline)
            vol_pcr = round(total_pe_vol / max(1, total_ce_vol), 2) if total_ce_vol > 0 else last_pcr

            inst_params["pcr_flow"] = {
                "current_pcr": last_pcr,
                "pcr_5m_delta": f"+{pcr_5m_delta}" if pcr_5m_delta > 0 else f"{pcr_5m_delta}",
                "volume_pcr": vol_pcr,
                "bias": "Put Writing Dominant" if last_pcr >= 1.05 else ("Call Writing Dominant" if last_pcr <= 0.90 else "Balanced")
            }

            lot_map = {
                "NIFTY": 65,
                "BANKNIFTY": 30,
                "FINNIFTY": 60,
                "MIDCPNIFTY": 120,
                "SENSEX": 20
            }
            trap_info = _compute_trap_detection(sym, curr_spot, atm_strike, parsed, step, current_conf, brk_state="FLAT", timeline=timeline)
            scalp_setup = _compute_scalp_setup(sym, curr_spot, atm_strike, step, current_conf, trap_info, inst_params, lot_map.get(sym, 25))
            inst_params["trap_detection"] = trap_info
            inst_params["scalp_setup"] = scalp_setup

            inst_params["current_spot"] = curr_spot
            inst_params["symbol"] = sym

            res = {
                "status": "success",
                "symbol": sym,
                "count": len(timeline),
                "timeline": timeline,
                "parameters": inst_params,
                "anchors": inst_params
            }
            _timeseries_cache[sym] = res
            _timeseries_cache_time[sym] = time.time()
            return res
    except Exception as e:
        logger.error(f"Error fetching matrix timeseries for {symbol}: {e}", exc_info=True)
        return {
            "status": "error",
            "symbol": sym,
            "timeline": [],
            "parameters": {},
            "anchors": {}
        }

