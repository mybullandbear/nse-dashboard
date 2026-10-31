"""
Option Confluence Analysis Service
Provides deep multi-layered analysis of ATM +- 2 strikes (extensible to +-3 / +-5):
Layer 1: Raw Option Chain metrics (OI, ΔOI, LTP, Volume, IV, PCR)
Layer 2: Derived Positioning & Flow (Long/Short Buildup, Writing vs Unwinding, Support/Resistance shifts)
Layer 3: Price Confirmation (AlphaTrend, TrendDirection, Shonya Gravity, Proximity MAPO)
Layer 4: Modular Confluence Scoring & Actionable Strike Verdicts
"""
import math
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import time as _time
import asyncio

from app.core.config import get_settings
from app.services.option_chain import ParsedOptionChain, StrikeRow, parse_option_chain
from app.services.technical_indicators import TechnicalIndicators
from app.db.storage import snapshot_storage
from app.api.market import fetch_live_chain_data

logger = logging.getLogger(__name__)


def _format_number(val: Optional[float], decimals: int = 1) -> str:
    if val is None or math.isnan(val) or val == 0:
        return "--"
    abs_v = abs(val)
    if abs_v >= 10_000_000:
        return f"{val / 10_000_000:.2f}Cr"
    if abs_v >= 100_000:
        return f"{val / 100_000:.{decimals}f}L"
    if abs_v >= 1_000:
        return f"{val / 1_000:.{decimals}f}K"
    return f"{val:.{decimals}f}"


def _format_signed_number(val: Optional[float], decimals: int = 1) -> str:
    if val is None or math.isnan(val):
        return "0"
    if val == 0:
        return "0"
    formatted = _format_number(val, decimals)
    return f"+{formatted}" if val > 0 else formatted


class OptionConfluenceService:
    """Quantitative Option Confluence Service analyzing ATM +- 2 corridor."""

    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_time: Dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def analyze_confluence(
        self,
        symbol: str = "NIFTY",
        range_strikes: int = 2,
        parsed_chain: Optional[ParsedOptionChain] = None,
        compute_strike_candles: bool = True
    ) -> Optional[Dict[str, Any]]:
        sym = symbol.upper()
        cache_key = f"{sym}_{range_strikes}_{compute_strike_candles}"
        now = _time.time()

        if cache_key in self._cache and (now - self._cache_time.get(cache_key, 0.0)) < 3.0:
            return self._cache[cache_key]

        if parsed_chain:
            parsed = parsed_chain
            source = getattr(parsed_chain, "source", "LIVE_STREAM") or "LIVE_STREAM"
        else:
            raw_chain, source = await fetch_live_chain_data(sym)
            if not raw_chain:
                return None

            parsed = parse_option_chain(raw_chain, sym)
            if not parsed or not parsed.strikes:
                return None

        settings = get_settings()
        step = settings.STRIKE_STEPS.get(sym, 50)
        spot = parsed.spot_price
        atm = parsed.atm_strike
        pcr = parsed.pcr

        # Generate target strikes symmetrically around ATM
        candidate_strikes = []
        for offset in range(-range_strikes, range_strikes + 1):
            stk_val = round(atm + (offset * step), 1)
            candidate_strikes.append((offset, stk_val))

        strike_lookup: Dict[float, StrikeRow] = {s.strikePrice: s for s in parsed.strikes}

        # ── Fetch Live Technical Indicators from Spot Candles ────────────────
        spot_tech = self._compute_spot_indicators(sym, spot)

        # ── Build Strike-by-Strike Analytical Rows ─────────────────────────────
        strikes_data = []
        total_ce_oi = 0
        total_pe_oi = 0
        total_ce_chg = 0
        total_pe_chg = 0

        max_ce_oi = -1
        max_pe_oi = -1
        strong_res_strike = atm
        strong_sup_strike = atm

        for offset, stk in candidate_strikes:
            row = strike_lookup.get(stk)
            ce_contract = row.CE if row else None
            pe_contract = row.PE if row else None

            # Moneyness
            if offset == 0:
                step_tag = "ATM"
                moneyness_ce = "ATM"
                moneyness_pe = "ATM"
            elif offset < 0:
                step_tag = f"ATM{offset}"
                moneyness_ce = "ITM"
                moneyness_pe = "OTM"
            else:
                step_tag = f"ATM+{offset}"
                moneyness_ce = "OTM"
                moneyness_pe = "ITM"

            dist_pts = round(stk - spot, 1)

            # ── Layer 1: CE Raw & Derived ─────────────────────────────────────
            ce_oi = ce_contract.openInterest if ce_contract else 0
            ce_chg = ce_contract.changeinOpenInterest if ce_contract else 0
            ce_ltp = ce_contract.lastPrice if ce_contract else 0.0
            ce_pchange = ce_contract.pChange if ce_contract else 0.0
            ce_vol = ce_contract.totalTradedVolume if ce_contract else 0
            ce_iv = ce_contract.impliedVolatility if ce_contract and ce_contract.impliedVolatility > 0 else 0.0

            total_ce_oi += ce_oi
            total_ce_chg += ce_chg
            if ce_oi > max_ce_oi:
                max_ce_oi = ce_oi
                strong_res_strike = stk

            ce_buildup, ce_interp, ce_bias = self._derive_ce_positioning(ce_pchange, ce_chg, ce_oi, offset)

            # ── Layer 1: PE Raw & Derived ─────────────────────────────────────
            pe_oi = pe_contract.openInterest if pe_contract else 0
            pe_chg = pe_contract.changeinOpenInterest if pe_contract else 0
            pe_ltp = pe_contract.lastPrice if pe_contract else 0.0
            pe_pchange = pe_contract.pChange if pe_contract else 0.0
            pe_vol = pe_contract.totalTradedVolume if pe_contract else 0
            pe_iv = pe_contract.impliedVolatility if pe_contract and pe_contract.impliedVolatility > 0 else 0.0

            total_pe_oi += pe_oi
            total_pe_chg += pe_chg
            if pe_oi > max_pe_oi:
                max_pe_oi = pe_oi
                strong_sup_strike = stk

            pe_buildup, pe_interp, pe_bias = self._derive_pe_positioning(pe_pchange, pe_chg, pe_oi, offset)

            # ── PCR & OI Difference ───────────────────────────────────────────
            stk_pcr = round(pe_oi / ce_oi, 2) if ce_oi > 0 else (2.5 if pe_oi > 0 else 1.0)
            stk_oi_diff = pe_oi - ce_oi
            stk_oi_chg_diff = pe_chg - ce_chg

            # ── Layer 3: Strike-Specific PineScript Confirmation Metrics ───────
            price_bias = spot_tech.get("price_bias", "NEUTRAL")
            # 1. AlphaTrend (Strike position relative to AlphaTrend baseline)
            at_val = spot_tech.get("alphatrend_val", spot)
            at_diff = stk - at_val
            if abs(at_diff) <= (step * 0.4):
                stk_at_state = "PIVOT"
                stk_at_detail = "PIVOT"
            elif at_diff > 0:
                stk_at_state = "ABOVE"
                stk_at_detail = f"+{int(at_diff)}"
            else:
                stk_at_state = "BELOW"
                stk_at_detail = f"{int(at_diff)}"

            # 2. TrendDirection (Strike momentum & contract premium velocity)
            prem_skew = (ce_pchange - pe_pchange) / 400.0
            stk_td_strength = max(-1.0, min(1.0, spot_tech.get("trend_dir_strength", 0.0) * (1.0 + (offset * 0.10) / max(1, range_strikes)) + (prem_skew * 0.20)))
            if stk_td_strength >= 0.20:
                stk_td_state = "BULLISH"
            elif stk_td_strength <= -0.20:
                stk_td_state = "BEARISH"
            elif stk_td_strength > 0.05:
                stk_td_state = "LEAN_BULLISH"
            elif stk_td_strength < -0.05:
                stk_td_state = "LEAN_BEARISH"
            else:
                stk_td_state = "BALANCED"

            # 3. Shonya Gravity (Strike location relative to Gravity Center)
            sh_basis = spot_tech.get("shonya_basis", spot)
            sh_diff = stk - sh_basis
            if abs(sh_diff) <= (step * 0.5):
                stk_sh_state = "AT GRAV"
                stk_sh_detail = "AT GRAV"
            elif sh_diff > 0:
                stk_sh_state = "ABOVE"
                stk_sh_detail = "ABOVE GRAV"
            else:
                stk_sh_state = "BELOW"
                stk_sh_detail = "BELOW GRAV"

            # 4. Proximity (Strike position across volatility corridor)
            min_stk = candidate_strikes[0][1]
            max_stk = candidate_strikes[-1][1]
            if max_stk > min_stk:
                stk_prox_per = round(max(2.0, min(98.0, ((stk - min_stk) / (max_stk - min_stk)) * 100.0)), 0)
            else:
                stk_prox_per = 50.0

            if stk_prox_per >= 70:
                stk_prox_state = "UPPER"
            elif stk_prox_per <= 30:
                stk_prox_state = "LOWER"
            else:
                stk_prox_state = "MID"

            # 5. Hull Suite (EHMA 34x2 Strike Position & Contract Level Momentum)
            hull_val = spot_tech.get("hull_val", spot)
            hull_diff = stk - hull_val
            hull_trend = spot_tech.get("hull_state", "NEUTRAL")
            if abs(hull_diff) <= (step * 0.4):
                stk_hull_state = "PIVOT"
                stk_hull_detail = "PIVOT"
            elif hull_diff > 0:
                stk_hull_state = "ABOVE"
                stk_hull_detail = f"+{int(hull_diff)}"
            else:
                stk_hull_state = "BELOW"
                stk_hull_detail = f"{int(hull_diff)}"

            # 6. Breakout Tracker (ATR Pivots & Dynamic Trailing Bands)
            brk_state = spot_tech.get("brk_state", "FLAT")
            brk_lvl = spot_tech.get("brk_level")
            brk_bias = spot_tech.get("brk_bias", "NEUTRAL")
            brk_sig = spot_tech.get("brk_signal", "HOLD")
            brk_pnl = spot_tech.get("brk_pnl", 0.0)
            brk_res = spot_tech.get("brk_res")
            brk_sup = spot_tech.get("brk_sup")

            if brk_lvl:
                brk_diff = stk - brk_lvl
                if abs(brk_diff) <= (step * 0.4):
                    stk_brk_detail = "AT BRK LVL"
                elif brk_diff > 0:
                    stk_brk_detail = f"+{int(brk_diff)} > BRK"
                else:
                    stk_brk_detail = f"{int(brk_diff)} < BRK"
            elif brk_res and stk >= brk_res:
                stk_brk_detail = f"Above Res {int(brk_res)}"
            elif brk_sup and stk <= brk_sup:
                stk_brk_detail = f"Below Sup {int(brk_sup)}"
            else:
                stk_brk_detail = "In Range"

            ce_fallback_st = "NEUTRAL"
            pe_fallback_st = "NEUTRAL"

            ce_hull_st = ce_fallback_st
            pe_hull_st = pe_fallback_st
            ce_at_st = ce_fallback_st
            pe_at_st = pe_fallback_st
            ce_td_st = ce_fallback_st
            pe_td_st = pe_fallback_st
            ce_ott_st = ce_fallback_st
            pe_ott_st = pe_fallback_st
            ce_at_val = ce_ltp
            pe_at_val = pe_ltp
            ce_td_str = 0.0
            pe_td_str = 0.0
            ce_prox = 50.0
            pe_prox = 50.0
            ce_sig = "NEUTRAL_HOLD"
            pe_sig = "NEUTRAL_HOLD"

            if compute_strike_candles:
                try:
                    from app.services.option_candle_service import option_candle_service
                    ce_cdata = option_candle_service.get_option_chart_data(sym, stk, "CE")
                    if ce_cdata and ce_cdata.get("current_state"):
                        cs = ce_cdata["current_state"]
                        ce_hull_st = cs.get("hull_state") or ce_fallback_st
                        ce_at_st = cs.get("alphatrend_state") or ce_fallback_st
                        ce_at_val = cs.get("alphatrend") or ce_ltp
                        ce_td_st = cs.get("trend_direction_state") or ce_fallback_st
                        ce_td_str = cs.get("trend_direction") or 0.0
                        ce_ott_st = cs.get("ott_state") or ce_fallback_st
                        ce_prox = cs.get("proximity", 50.0)
                        ce_sig = cs.get("signal_trigger", "NEUTRAL_HOLD")

                    pe_cdata = option_candle_service.get_option_chart_data(sym, stk, "PE")
                    if pe_cdata and pe_cdata.get("current_state"):
                        ps = pe_cdata["current_state"]
                        pe_hull_st = ps.get("hull_state") or pe_fallback_st
                        pe_at_st = ps.get("alphatrend_state") or pe_fallback_st
                        pe_at_val = ps.get("alphatrend") or pe_ltp
                        pe_td_st = ps.get("trend_direction_state") or pe_fallback_st
                        pe_td_str = ps.get("trend_direction") or 0.0
                        pe_ott_st = ps.get("ott_state") or pe_fallback_st
                        pe_prox = ps.get("proximity", 50.0)
                        pe_sig = ps.get("signal_trigger", "NEUTRAL_HOLD")
                except Exception:
                    pass

            # Calculate individual contract-level actionable signals (Uncoupled CE & PE)
            ce_action = self._compute_contract_action(
                option_type="CE",
                stk=stk,
                ltp=ce_ltp,
                pchange=ce_pchange,
                oi=ce_oi,
                oi_chg=ce_chg,
                buildup=ce_buildup,
                at_st=ce_at_st,
                at_val=ce_at_val,
                td_st=ce_td_st,
                td_str=ce_td_str,
                hull_st=ce_hull_st,
                sig_trigger=ce_sig,
                stk_pcr=stk_pcr
            )

            pe_action = self._compute_contract_action(
                option_type="PE",
                stk=stk,
                ltp=pe_ltp,
                pchange=pe_pchange,
                oi=pe_oi,
                oi_chg=pe_chg,
                buildup=pe_buildup,
                at_st=pe_at_st,
                at_val=pe_at_val,
                td_st=pe_td_st,
                td_str=pe_td_str,
                hull_st=pe_hull_st,
                sig_trigger=pe_sig,
                stk_pcr=stk_pcr
            )

            strike_indicators = {
                "ind1": {
                    "name": "AlphaTrend",
                    "state": stk_at_state,
                    "val": at_val,
                    "detail": stk_at_detail,
                    "ce_state": ce_at_st,
                    "ce_val": round(ce_at_val, 2),
                    "pe_state": pe_at_st,
                    "pe_val": round(pe_at_val, 2)
                },
                "ind2": {
                    "name": "TrendDir",
                    "state": stk_td_state,
                    "strength": round(stk_td_strength, 2),
                    "desc": stk_td_state,
                    "detail": f"{stk_td_strength:+.2f}",
                    "ce_state": ce_td_st,
                    "ce_strength": round(ce_td_str, 2),
                    "pe_state": pe_td_st,
                    "pe_strength": round(pe_td_str, 2)
                },
                "ind3": {
                    "name": "Shonya",
                    "state": stk_sh_state,
                    "detail": stk_sh_detail
                },
                "ind4": {
                    "name": "Proximity",
                    "state": stk_prox_state,
                    "per": stk_prox_per,
                    "detail": f"{stk_prox_per:.0f}%"
                },
                "ind5": {
                    "name": "Hull",
                    "state": stk_hull_state,
                    "val": hull_val,
                    "trend": hull_trend,
                    "detail": stk_hull_detail,
                    "ce_state": ce_hull_st,
                    "pe_state": pe_hull_st
                },
                "ind6": {
                    "name": "Breakout",
                    "shorttitle": "BRK-TRK",
                    "state": brk_state,
                    "bias": brk_bias,
                    "signal": brk_sig,
                    "detail": stk_brk_detail,
                    "level": brk_lvl,
                    "pnl_atr": brk_pnl
                },
                "price_bias": price_bias
            }

            # ── Layer 4: Confluence Scoring & Final Interpretation ───────────
            confluence = self._compute_strike_confluence(
                stk=stk,
                spot=spot,
                atm=atm,
                step=step,
                offset=offset,
                ce_oi=ce_oi,
                pe_oi=pe_oi,
                ce_chg=ce_chg,
                pe_chg=pe_chg,
                ce_ltp=ce_ltp,
                pe_ltp=pe_ltp,
                ce_pchange=ce_pchange,
                pe_pchange=pe_pchange,
                ce_vol=ce_vol,
                pe_vol=pe_vol,
                ce_iv=ce_iv,
                pe_iv=pe_iv,
                ce_bias=ce_bias,
                pe_bias=pe_bias,
                price_bias=price_bias,
                ce_buildup=ce_buildup,
                pe_buildup=pe_buildup,
                stk_pcr=stk_pcr,
                spot_tech=spot_tech,
                strike_indicators=strike_indicators
            )

            strikes_data.append({
                "strike": stk,
                "step_tag": step_tag,
                "moneyness_ce": moneyness_ce,
                "moneyness_pe": moneyness_pe,
                "distance_pts": dist_pts,
                "ce": {
                    "oi": ce_oi,
                    "oi_formatted": _format_number(ce_oi),
                    "oi_chg": ce_chg,
                    "oi_chg_formatted": _format_signed_number(ce_chg),
                    "ltp": round(ce_ltp, 2),
                    "pchange": round(ce_pchange, 1),
                    "volume": ce_vol,
                    "volume_formatted": _format_number(ce_vol),
                    "iv": round(ce_iv, 1) if ce_iv > 0 else None,
                    "buildup": ce_buildup,
                    "interpretation": ce_interp,
                    "bias": ce_bias,
                    "alphatrend_state": ce_at_st,
                    "alphatrend_val": round(ce_at_val, 2),
                    "trend_dir_state": ce_td_st,
                    "trend_dir_strength": round(ce_td_str, 2),
                    "ott_state": ce_ott_st,
                    "hull_state": ce_hull_st,
                    "proximity": round(ce_prox, 1),
                    "signal_trigger": ce_sig,
                    "action_signal": ce_action["signal"],
                    "action_directive": ce_action["directive"],
                    "action_badge": ce_action["badge_class"]
                },
                "pe": {
                    "oi": pe_oi,
                    "oi_formatted": _format_number(pe_oi),
                    "oi_chg": pe_chg,
                    "oi_chg_formatted": _format_signed_number(pe_chg),
                    "ltp": round(pe_ltp, 2),
                    "pchange": round(pe_pchange, 1),
                    "volume": pe_vol,
                    "volume_formatted": _format_number(pe_vol),
                    "iv": round(pe_iv, 1) if pe_iv > 0 else None,
                    "buildup": pe_buildup,
                    "interpretation": pe_interp,
                    "bias": pe_bias,
                    "alphatrend_state": pe_at_st,
                    "alphatrend_val": round(pe_at_val, 2),
                    "trend_dir_state": pe_td_st,
                    "trend_dir_strength": round(pe_td_str, 2),
                    "ott_state": pe_ott_st,
                    "hull_state": pe_hull_st,
                    "proximity": round(pe_prox, 1),
                    "signal_trigger": pe_sig,
                    "action_signal": pe_action["signal"],
                    "action_directive": pe_action["directive"],
                    "action_badge": pe_action["badge_class"]
                },
                "pcr": stk_pcr,
                "oi_diff": stk_oi_diff,
                "oi_diff_formatted": _format_signed_number(stk_oi_diff),
                "oi_chg_diff": stk_oi_chg_diff,
                "oi_chg_diff_formatted": _format_signed_number(stk_oi_chg_diff),
                "indicators": strike_indicators,
                "confluence": confluence
            })

        # ── Overall Corridor Summary Panel ─────────────────────────────────────
        avg_score = round(sum(s["confluence"]["score"] for s in strikes_data) / max(1, len(strikes_data)))
        bullish_count = sum(1 for s in strikes_data if "BULLISH" in s["confluence"]["final_bias"])
        bearish_count = sum(1 for s in strikes_data if "BEARISH" in s["confluence"]["final_bias"])

        if bullish_count > bearish_count and avg_score >= 55:
            overall_bias = "STRONG BULLISH" if avg_score >= 70 else "BULLISH"
            bias_class = "badge-bull"
        elif bearish_count > bullish_count and avg_score <= 45:
            overall_bias = "STRONG BEARISH" if avg_score <= 30 else "BEARISH"
            bias_class = "badge-bear"
        else:
            overall_bias = "NEUTRAL / CONFLICT"
            bias_class = "badge-neutral"

        ce_flow = "Call Writing Dominant (Ceiling)" if total_ce_chg > total_pe_chg else "Call Unwinding (Resistance Softening)"
        pe_flow = "Put Writing Dominant (Floor)" if total_pe_chg > total_ce_chg else "Put Unwinding (Support Softening)"

        result = {
            "success": True,
            "symbol": sym,
            "spot_price": spot,
            "atm_strike": atm,
            "strike_step": step,
            "range": range_strikes,
            "source": source,
            "summary": {
                "overall_bias": overall_bias,
                "overall_bias_class": bias_class,
                "confluence_score": avg_score,
                "overall_confluence_score": avg_score,
                "strong_support": strong_sup_strike,
                "strong_resistance": strong_res_strike,
                "corridor_pcr": round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 1.0,
                "corridor_oi_diff_formatted": _format_signed_number(total_pe_oi - total_ce_oi),
                "corridor_oi_chg_diff_formatted": _format_signed_number(total_pe_chg - total_ce_chg),
                "ce_positioning": ce_flow,
                "pe_positioning": pe_flow,
                "price_behaviour": spot_tech["price_bias"],
                "consensus": {
                    "bull_votes": spot_tech.get("bull_votes", 0),
                    "bear_votes": spot_tech.get("bear_votes", 0),
                    "total_votes": 6,
                    "price_bias": spot_tech.get("price_bias", "NEUTRAL")
                },
                "indicator_1": {
                    "name": "AlphaTrend",
                    "state": spot_tech["alphatrend_state"],
                    "value": spot_tech["alphatrend_val"]
                },
                "indicator_2": {
                    "name": "TrendDirection",
                    "state": spot_tech["trend_dir_state"],
                    "strength": spot_tech["trend_dir_strength"],
                    "desc": spot_tech.get("trend_dir_desc", "Balanced")
                },
                "indicator_3": {
                    "name": "Shonya Gravity",
                    "state": spot_tech["shonya_state"],
                    "basis": spot_tech.get("shonya_basis", spot)
                },
                "indicator_4": {
                    "name": "Proximity MAPO",
                    "state": spot_tech["prox_state"],
                    "per": spot_tech["prox_per"]
                },
                "indicator_5": {
                    "name": "Hull Suite",
                    "state": spot_tech["hull_state"],
                    "value": spot_tech["hull_val"]
                },
                "indicator_6": {
                    "name": "Breakout Tracker",
                    "shorttitle": "BRK-TRK",
                    "state": spot_tech.get("brk_state", "FLAT"),
                    "bias": spot_tech.get("brk_bias", "NEUTRAL"),
                    "signal": spot_tech.get("brk_signal", "HOLD"),
                    "breakout_level": spot_tech.get("brk_level"),
                    "fail_level": spot_tech.get("brk_fail"),
                    "trail_level": spot_tech.get("brk_trail"),
                    "open_pnl_atr": spot_tech.get("brk_pnl", 0.0),
                    "res_level": spot_tech.get("brk_res"),
                    "sup_level": spot_tech.get("brk_sup")
                },
                "indicator_breakout": {
                    "name": "Breakout Tracker",
                    "shorttitle": "BRK-TRK",
                    "state": spot_tech.get("brk_state", "FLAT"),
                    "bias": spot_tech.get("brk_bias", "NEUTRAL"),
                    "signal": spot_tech.get("brk_signal", "HOLD"),
                    "breakout_level": spot_tech.get("brk_level"),
                    "fail_level": spot_tech.get("brk_fail"),
                    "trail_level": spot_tech.get("brk_trail"),
                    "open_pnl_atr": spot_tech.get("brk_pnl", 0.0),
                    "res_level": spot_tech.get("brk_res"),
                    "sup_level": spot_tech.get("brk_sup")
                },
                "indicators": {
                    "ind1": {
                        "name": "AlphaTrend",
                        "state": spot_tech["alphatrend_state"],
                        "value": spot_tech["alphatrend_val"]
                    },
                    "ind2": {
                        "name": "TrendDirection",
                        "state": spot_tech["trend_dir_state"],
                        "strength": spot_tech["trend_dir_strength"]
                    },
                    "ind3": {
                        "name": "Shonya Gravity",
                        "state": spot_tech["shonya_state"]
                    },
                    "ind4": {
                        "name": "Proximity MAPO",
                        "state": spot_tech["prox_state"],
                        "per": spot_tech["prox_per"]
                    },
                    "ind5": {
                        "name": "Hull Suite",
                        "state": spot_tech["hull_state"],
                        "value": spot_tech["hull_val"]
                    },
                    "ind6": {
                        "name": "Breakout Tracker",
                        "shorttitle": "BRK-TRK",
                        "state": spot_tech.get("brk_state", "FLAT"),
                        "bias": spot_tech.get("brk_bias", "NEUTRAL"),
                        "signal": spot_tech.get("brk_signal", "HOLD"),
                        "breakout_level": spot_tech.get("brk_level"),
                        "fail_level": spot_tech.get("brk_fail"),
                        "trail_level": spot_tech.get("brk_trail"),
                        "open_pnl_atr": spot_tech.get("brk_pnl", 0.0),
                        "res_level": spot_tech.get("brk_res"),
                        "sup_level": spot_tech.get("brk_sup")
                    },
                    "ind_brk": {
                        "name": "Breakout Tracker",
                        "shorttitle": "BRK-TRK",
                        "state": spot_tech.get("brk_state", "FLAT"),
                        "bias": spot_tech.get("brk_bias", "NEUTRAL"),
                        "signal": spot_tech.get("brk_signal", "HOLD"),
                        "breakout_level": spot_tech.get("brk_level"),
                        "fail_level": spot_tech.get("brk_fail"),
                        "trail_level": spot_tech.get("brk_trail"),
                        "open_pnl_atr": spot_tech.get("brk_pnl", 0.0),
                        "res_level": spot_tech.get("brk_res"),
                        "sup_level": spot_tech.get("brk_sup")
                    }
                }
            },
            "strikes": strikes_data
        }

        # Centralized 4-Column Strategy Confluence calculation
        strat_conf = self._compute_strategy_confluence(
            sym=sym,
            spot_price=spot,
            atm_strike=atm,
            step=step,
            total_ce_oi=total_ce_oi,
            total_pe_oi=total_pe_oi,
            total_ce_chg=total_ce_chg,
            total_pe_chg=total_pe_chg,
            spot_tech=spot_tech,
            strikes_data=strikes_data
        )
        result["strategy_confluence"] = strat_conf
        result["summary"]["strategy_confluence"] = strat_conf

        self._cache[cache_key] = result
        self._cache_time[cache_key] = _time.time()
        return result

    def get_latest_strategy_confluence(self, sym: str) -> Optional[Dict[str, Any]]:
        """Instant in-memory lookup of latest centralized strategy confluence for a symbol."""
        sym_u = sym.upper()
        for k, v in self._cache.items():
            if k.startswith(f"{sym_u}_") and isinstance(v, dict) and "strategy_confluence" in v:
                return v["strategy_confluence"]
        return None

    def _compute_strategy_confluence(
        self,
        sym: str,
        spot_price: float,
        atm_strike: float,
        step: float,
        total_ce_oi: int,
        total_pe_oi: int,
        total_ce_chg: int,
        total_pe_chg: int,
        spot_tech: Dict[str, Any],
        strikes_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Single centralized calculation for the 4-Column Strategy Confluence Matrix & Shonya Bot.
        Enforces user trading rule:
        - When Put Hull is NEGATIVE / Falling (Market Bullish) AND Call OI unwinds / Put OI builds -> BUY CALL (CE).
        - When Call Hull is NEGATIVE / Falling (Market Bearish) AND Put OI unwinds / Call OI builds -> BUY PUT (PE).
        - When opposing -> CONFLICT - NO TRADE.
        """
        net_oi_diff = total_pe_oi - total_ce_oi
        oi_chg_diff = total_pe_chg - total_ce_chg
        pcr = round(total_pe_oi / max(1, total_ce_oi), 2)

        # 1. Option Chain Signal & Direction
        if net_oi_diff >= 0:
            oi_dir = "BULLISH"
            oi_sig_label = "LONG BUILDUP ↗" if oi_chg_diff >= 0 else "SHORT COVERING ↗"
            oi_badge_color = "dark-green" if oi_chg_diff >= 0 else "light-green"
            oi_strength = "Put Writing Floor / Net Put Dominant"
        else:
            oi_dir = "BEARISH"
            oi_sig_label = "SHORT BUILDUP ↘" if oi_chg_diff <= 0 else "LONG UNWINDING ↘"
            oi_badge_color = "dark-red" if oi_chg_diff <= 0 else "light-red"
            oi_strength = "Call Writing Resistance / Net Call Dominant"

        flow_str = f"{'+' if oi_chg_diff > 0 else ''}{_format_number(oi_chg_diff)}/Session"
        oi_desc = f"{oi_strength} • PCR: {pcr:.2f} • {flow_str}"

        # 2. Hull Indicator (Market direction based on Put/Call falling)
        spot_hull_st = spot_tech.get("hull_state", "NEUTRAL").upper()
        hull_val = float(spot_tech.get("hull_val", spot_price))

        # Check ATM Put and Call contract status
        atm_row = next((s for s in strikes_data if s.get("offset") == 0), None) or (strikes_data[len(strikes_data)//2] if strikes_data else {})
        pe_d = atm_row.get("pe", {})
        ce_d = atm_row.get("ce", {})
        pe_pchg = float(pe_d.get("pchange") or 0.0)
        ce_pchg = float(ce_d.get("pchange") or 0.0)

        # In options:
        # Prioritize actual contract premium dynamics:
        # - When Call is collapsing (ce_pchg < 0) and Put is surging (pe_pchg > 0): Market is BEARISH (CALL HULL FALLING)
        # - When Put is collapsing (pe_pchg < 0) and Call is surging (ce_pchg > 0): Market is BULLISH (PUT HULL FALLING)
        # - Never label a surging Put (+40%) as 'Put Premium Collapsing'
        if ce_pchg <= -1.0 and pe_pchg >= 1.0:
            hull_market_dir = "BEARISH"
            hull_label = "CALL HULL FALLING 🔴 (MARKET BEARISH 🔴)"
            hull_badge_color = "dark-red"
            hull_desc = f"Call Premium Collapsing (₹{ce_d.get('ltp', 0):.1f}, {ce_pchg:+.1f}%) • Market Breaking Down"
        elif pe_pchg <= -1.0 and ce_pchg >= 1.0:
            hull_market_dir = "BULLISH"
            hull_label = "PUT HULL FALLING 🔴 (MARKET BULLISH 🟢)"
            hull_badge_color = "dark-green"
            hull_desc = f"Put Premium Collapsing (₹{pe_d.get('ltp', 0):.1f}, {pe_pchg:+.1f}%) • Market Expanding Up"
        elif spot_hull_st == "BEARISH" and pe_pchg >= -0.5:
            hull_market_dir = "BEARISH"
            hull_label = "CALL HULL FALLING 🔴 (MARKET BEARISH 🔴)"
            hull_badge_color = "dark-red"
            hull_desc = f"Call Premium Collapsing (₹{ce_d.get('ltp', 0):.1f}, {ce_pchg:+.1f}%) • Market Breaking Down"
        elif spot_hull_st == "BULLISH" and ce_pchg >= -0.5 and pe_pchg < 1.0:
            hull_market_dir = "BULLISH"
            hull_label = "PUT HULL FALLING 🔴 (MARKET BULLISH 🟢)"
            hull_badge_color = "dark-green"
            hull_desc = f"Put Premium Collapsing (₹{pe_d.get('ltp', 0):.1f}, {pe_pchg:+.1f}%) • Market Expanding Up"
        elif spot_hull_st == "BEARISH":
            hull_market_dir = "BEARISH"
            hull_label = "CALL HULL FALLING 🔴 (MARKET BEARISH 🔴)"
            hull_badge_color = "dark-red"
            hull_desc = f"Call Premium Collapsing (₹{ce_d.get('ltp', 0):.1f}, {ce_pchg:+.1f}%) • Market Breaking Down"
        elif spot_hull_st == "BULLISH" and pe_pchg < 1.5:
            hull_market_dir = "BULLISH"
            hull_label = "PUT HULL FALLING 🔴 (MARKET BULLISH 🟢)"
            hull_badge_color = "dark-green"
            hull_desc = f"Put Premium Collapsing (₹{pe_d.get('ltp', 0):.1f}, {pe_pchg:+.1f}%) • Market Expanding Up"
        else:
            hull_market_dir = "NEUTRAL"
            hull_label = "HULL NEUTRAL 🟡 (CONSOLIDATION)"
            hull_badge_color = "yellow"
            hull_desc = f"Hull Pivot Balance at ₹{hull_val:,.1f}"

        # 3. Final Signal Confluence (Column 4: What to do - Buy Call or Put?)
        is_aligned = (oi_dir == hull_market_dir) and (oi_dir in ["BULLISH", "BEARISH"])
        is_opposed = (oi_dir != hull_market_dir) and (oi_dir in ["BULLISH", "BEARISH"])

        lot_map = {"NIFTY": 65, "BANKNIFTY": 30, "FINNIFTY": 60, "MIDCPNIFTY": 120, "SENSEX": 20}
        lot_size = lot_map.get(sym, 25)

        if is_aligned and hull_market_dir == "BULLISH":
            action_verdict = "BUY CALL"
            action_type = "CE"
            suggested_strike = f"{int(atm_strike)} CE"
            action_badge_color = "dark-green"
            action_sub = "Put Hull Falling + Put OI Floor (Aligned Bullish)"
        elif is_aligned and hull_market_dir == "BEARISH":
            action_verdict = "BUY PUT"
            action_type = "PE"
            suggested_strike = f"{int(atm_strike)} PE"
            action_badge_color = "dark-red"
            action_sub = "Call Hull Falling + Call OI Ceiling (Aligned Bearish)"
        elif is_opposed:
            action_verdict = "CONFLICT - NO TRADE"
            action_type = "NONE"
            suggested_strike = "STAND ASIDE"
            action_badge_color = "light-red"
            action_sub = f"Opposing: OI {oi_dir} vs Hull {hull_market_dir}"
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
                "strength_desc": oi_desc,
                "pcr": pcr,
                "net_oi_flow": flow_str
            },
            "hull_indicator": {
                "trend": hull_market_dir,
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

    # ──────────────────────────────────────────────────────────────────────────
    # Internal Helpers: Positioning Derivation
    # ──────────────────────────────────────────────────────────────────────────
    def _derive_ce_positioning(self, pchange: float, oi_chg: int, oi: int, offset: int) -> tuple[str, str, str]:
        """Derives CE Positioning (Buildup), Contextual Interpretation, and Semantic Bias."""
        if pchange > 0 and oi_chg > 0:
            buildup = "LONG_BUILDUP"
            interp = "Call Buying (Resistance Breakout)"
            bias = "BULLISH"
        elif pchange < 0 and oi_chg > 0:
            buildup = "SHORT_BUILDUP"
            interp = "Call Writing (Resistance Strengthening)"
            bias = "BEARISH"
        elif pchange > 0 and oi_chg < 0:
            buildup = "SHORT_COVERING"
            interp = "Call Unwinding (Resistance Weakening)"
            bias = "BULLISH"
        elif pchange < 0 and oi_chg < 0:
            buildup = "LONG_UNWINDING"
            interp = "Long Liquidation (Momentum Fading)"
            bias = "BEARISH"
        else:
            buildup = "NEUTRAL"
            interp = "Balanced / Steady Holding"
            bias = "NEUTRAL"
        return buildup, interp, bias

    def _derive_pe_positioning(self, pchange: float, oi_chg: int, oi: int, offset: int) -> tuple[str, str, str]:
        """Derives PE Positioning (Buildup), Contextual Interpretation, and Semantic Bias."""
        if pchange < 0 and oi_chg > 0:
            buildup = "SHORT_BUILDUP"
            interp = "Put Writing (Support Strengthening)"
            bias = "BULLISH"
        elif pchange > 0 and oi_chg > 0:
            buildup = "LONG_BUILDUP"
            interp = "Put Buying (Support Breakdown Threat)"
            bias = "BEARISH"
        elif pchange < 0 and oi_chg < 0:
            buildup = "LONG_UNWINDING"
            interp = "Put Liquidation (Floor Cleared)"
            bias = "BULLISH"
        elif pchange > 0 and oi_chg < 0:
            buildup = "SHORT_COVERING"
            interp = "Put Unwinding (Support Weakening)"
            bias = "BEARISH"
        else:
            buildup = "NEUTRAL"
            interp = "Balanced / Steady Holding"
            bias = "NEUTRAL"
        return buildup, interp, bias

    # ──────────────────────────────────────────────────────────────────────────
    # Internal Helpers: Spot Indicator Suite Computation
    # ──────────────────────────────────────────────────────────────────────────
    def _compute_spot_indicators(self, symbol: str, current_spot: Optional[float] = None) -> Dict[str, Any]:
        """
        Computes AlphaTrend, TrendDirection, Shonya Gravity, and Proximity MAPO
        using a continuous time-series of market snapshots from SQLite across recent sessions,
        seamlessly connecting historical trading bars with live incoming ticks,
        skipping off-market / weekend gaps.
        """
        # 1. Fetch continuous historical timeseries from SQLite across the same expiry sessions
        # Spot index candles terminate at 15:15 for technical indicator calculations.
        history = snapshot_storage.get_continuous_timeseries(symbol, limit=250, max_time="15:15", discard_frozen_after="15:15")
        
        # 2. Extract spot closes & volumes from historical snapshots, strictly discarding frozen/flat ticks after 15:15
        closes = []
        volumes = []
        prev_s = None
        for r in history:
            s_val = float(r["spot"]) if r.get("spot") else 0.0
            t_str = r.get("time") or r.get("time_str", "")
            if s_val > 500:
                # Discard frozen flat tick after 15:15
                if t_str > "15:15" and prev_s is not None and abs(s_val - prev_s) < 0.01:
                    continue
                # Strictly discard flat ticks past 15:30
                if t_str > "15:30" and prev_s is not None and abs(s_val - prev_s) < 0.01:
                    continue
                closes.append(s_val)
                volumes.append(float(r.get("volume") or 1000))
                prev_s = s_val
        
        # 3. If live minute candles exist in memory from today, merge only up to 15:15
        try:
            from app.services.tracker_bot import tracker_bot
            tracker_bot._ensure_candles(symbol)
            mem_bars = tracker_bot._minute_candles.get(symbol, {})
            if mem_bars:
                sorted_times = sorted(mem_bars.keys())
                for t in sorted_times:
                    if t > "15:15":
                        # Terminate spot candles at 15:15 for technical indicators
                        continue
                    sp = float(mem_bars[t].get("close", 0.0))
                    vol = float(mem_bars[t].get("volume", 1000))
                    if sp > 500:
                        if closes and abs(closes[-1] - sp) < 0.01:
                            # Frozen tick, skip
                            continue
                        closes.append(sp)
                        volumes.append(vol)
        except Exception:
            pass

        # 4. If current live spot price is provided, only append if current IST time <= 15:15
        # Under no circumstance feed flat spot ticks past 15:30 into PineScript indicator pipeline
        from app.core.market_hours import get_current_ist
        now_ist = get_current_ist()
        curr_time = now_ist.strftime("%H:%M")
        if curr_time <= "15:15" and current_spot and current_spot > 500:
            if not closes or abs(closes[-1] - current_spot) > 0.01:
                closes.append(current_spot)
                volumes.append(1000.0)

        while len(volumes) < len(closes):
            volumes.append(1000.0)

        # 5. Check if we have sufficient time-series points
        if len(closes) < 14:
            return {
                "alphatrend_state": "NEUTRAL",
                "alphatrend_val": round(closes[-1] if closes else (current_spot or 0.0), 1),
                "trend_dir_state": "NEUTRAL",
                "trend_dir_strength": 0.0,
                "trend_dir_desc": "Balanced",
                "shonya_state": "NEUTRAL",
                "prox_state": "NEUTRAL",
                "prox_per": 50.0,
                "hull_state": "NEUTRAL",
                "hull_val": round(closes[-1] if closes else (current_spot or 0.0), 1),
                "brk_state": "FLAT",
                "brk_bias": "NEUTRAL",
                "brk_signal": "HOLD",
                "brk_level": None,
                "brk_fail": None,
                "brk_trail": None,
                "brk_pnl": 0.0,
                "brk_res": None,
                "brk_sup": None,
                "breakout_tracker": {},
                "price_bias": "NEUTRAL",
                "bull_votes": 0,
                "bear_votes": 0
            }

        # Keep last 200 bars for smooth responsive computation with multi-day continuity
        closes = closes[-200:]
        volumes = volumes[-200:]
        
        # Realistic candle bounds
        highs = [c * 1.0006 for c in closes]
        lows = [c * 0.9994 for c in closes]

        # 1. AlphaTrend (Magic 9 ATR trailing bands)
        at_data = TechnicalIndicators.compute_alphatrend(highs, lows, closes, coeff=1.0, ap=14)
        at_state = at_data["trend_state"][-1] if at_data["trend_state"] else "NEUTRAL"
        at_val = at_data["alphatrend"][-1] if at_data["alphatrend"] else closes[-1]

        # 2. TrendDirection (Logistic Momentum & Tanh)
        td_data = TechnicalIndicators.compute_trend_direction(highs, lows, closes, di_len=14, mean_lb=min(len(closes), 60))
        td_state = td_data["trend_state"][-1] if td_data["trend_state"] else "NEUTRAL"
        td_strength = td_data["strength_latest"]

        if td_strength >= 0.35:
            td_desc = "Strong Trend Acceleration"
        elif td_strength > 0.08:
            td_desc = "Moderate Bullish Velocity"
        elif td_strength <= -0.35:
            td_desc = "Strong Downside Force"
        elif td_strength < -0.08:
            td_desc = "Moderate Bearish Drift"
        else:
            td_desc = "Rangebound Consolidation"

        # 3. Shonya Gravity
        sh_data = TechnicalIndicators.compute_shonya(closes, len_val=14)
        sh_state = sh_data["trend_state"][-1] if sh_data["trend_state"] else "NEUTRAL"
        sh_basis = sh_data["basis"][-1] if sh_data["basis"] else closes[-1]

        # 4. Proximity MAPO
        prox_data = TechnicalIndicators.compute_proximity(closes, i_min=10, i_max=min(len(closes), 60))
        prox_state = prox_data["trend_state"][-1] if prox_data["trend_state"] else "NEUTRAL"
        prox_per = prox_data["per_latest"]

        # 5. Hull Suite (EHMA 34x2)
        hull_data = TechnicalIndicators.compute_hull(closes, mode="Ehma", length=34, length_mult=2.0)
        hull_state = hull_data["curr_state"]
        hull_val = hull_data["curr_mhull"]

        # 6. Breakout Tracker (ATR Pivots & Dynamic Trailing Bands - Spot Index Stream)
        brk_data = TechnicalIndicators.compute_breakout_tracker(highs, lows, closes, None, use_body=False, use_vol=False)
        brk_state = brk_data["state"]
        brk_bias = brk_data["bias"]
        brk_sig = brk_data["signal"]
        brk_lvl = brk_data["breakout_level"]
        brk_fail = brk_data["fail_level"]
        brk_trail = brk_data["trail_level"]
        brk_pnl = brk_data["open_pnl_atr"]
        brk_res = brk_data["res_level"]
        brk_sup = brk_data["sup_level"]

        # Combined Price Bias (6 PineScript confirmation pillars)
        bull_votes = (at_state == "BULLISH") + ("BULLISH" in td_state) + (sh_state == "BULLISH") + (prox_state == "BULLISH") + (hull_state == "BULLISH") + (brk_bias == "BULLISH")
        bear_votes = (at_state == "BEARISH") + ("BEARISH" in td_state) + (sh_state == "BEARISH") + (prox_state == "BEARISH") + (hull_state == "BEARISH") + (brk_bias == "BEARISH")

        if bull_votes >= 4:
            price_bias = "BULLISH"
        elif bear_votes >= 4:
            price_bias = "BEARISH"
        elif bull_votes > bear_votes:
            price_bias = "LEAN_BULLISH"
        elif bear_votes > bull_votes:
            price_bias = "LEAN_BEARISH"
        else:
            price_bias = "NEUTRAL"

        return {
            "alphatrend_state": at_state,
            "alphatrend_val": round(at_val, 1),
            "trend_dir_state": td_state,
            "trend_dir_strength": td_strength,
            "trend_dir_desc": td_desc,
            "shonya_state": sh_state,
            "shonya_basis": round(sh_basis, 1),
            "prox_state": prox_state,
            "prox_per": prox_per,
            "hull_state": hull_state,
            "hull_val": round(hull_val, 1),
            "brk_state": brk_state,
            "brk_bias": brk_bias,
            "brk_signal": brk_sig,
            "brk_level": brk_lvl,
            "brk_fail": brk_fail,
            "brk_trail": brk_trail,
            "brk_pnl": brk_pnl,
            "brk_res": brk_res,
            "brk_sup": brk_sup,
            "breakout_tracker": brk_data,
            "price_bias": price_bias,
            "bull_votes": int(bull_votes),
            "bear_votes": int(bear_votes)
        }

    get_price_indicators = _compute_spot_indicators

    # ──────────────────────────────────────────────────────────────────────────
    # Internal Helpers: Contract-Level Actionable Signal Engine (Uncoupled CE / PE)
    # ──────────────────────────────────────────────────────────────────────────
    def _compute_contract_action(
        self,
        option_type: str,
        stk: float,
        ltp: float,
        pchange: float,
        oi: int,
        oi_chg: int,
        buildup: str,
        at_st: str,
        at_val: float,
        td_st: str,
        td_str: float,
        hull_st: str,
        sig_trigger: str,
        stk_pcr: float
    ) -> Dict[str, str]:
        """
        Derives an independent, contract-level actionable signal and directive
        strictly from the individual Call or Put contract's own behavior.
        """
        is_ce = option_type.upper() == "CE"
        formatted_chg = f"+{oi_chg:,}" if oi_chg > 0 else f"{oi_chg:,}"

        # Contract price momentum confirmation
        is_at_bull = at_st == "BULLISH" or (at_val > 0 and ltp > at_val)
        is_at_bear = at_st == "BEARISH" or (at_val > 0 and ltp < at_val)
        is_hull_bull = hull_st == "BULLISH"
        is_hull_bear = hull_st == "BEARISH"
        is_chart_bull = is_at_bull or is_hull_bull or (sig_trigger == "OPTION_BUY_CONFIRMED")
        is_chart_bear = is_at_bear or is_hull_bear or (sig_trigger == "OPTION_EXIT_SIGNAL")

        if is_ce:
            # ── CALL (CE) CONTRACT EVALUATION ────────────────────────
            # 1. Genuine Call Breakout (CE Buyer Expansion)
            if (is_chart_bull or pchange > 2.0) and (buildup in ["LONG_BUILDUP", "SHORT_COVERING"] or pchange > 0) and not is_chart_bear:
                return {
                    "signal": "🚀 BUY CE BREAKOUT",
                    "directive": f"CE ₹{ltp:.1f} (+{pchange:.1f}%) > AT ₹{at_val:.1f} • Long Expansion",
                    "bias": "BULLISH",
                    "badge_class": "badge-bull"
                }
            # 2. Call Writing Resistance Wall (CE Seller Overhead)
            elif buildup == "SHORT_BUILDUP" and (is_chart_bear or pchange <= 0):
                return {
                    "signal": "🔴 WRITE CE RESISTANCE",
                    "directive": f"Heavy CE Writing ({formatted_chg} OI) • Supply Ceiling",
                    "bias": "BEARISH",
                    "badge_class": "badge-bear"
                }
            # 3. Call Longs Unwinding / Theta Decay
            elif buildup == "LONG_UNWINDING" or (is_chart_bear and pchange < -1.5):
                return {
                    "signal": "⚠️ CE UNWINDING",
                    "directive": f"Call Buyers Liquidating ({pchange:.1f}%) • Below AlphaTrend",
                    "bias": "BEARISH",
                    "badge_class": "badge-bear"
                }
            # 4. Call Short Covering Spike
            elif buildup == "SHORT_COVERING" and pchange > 0:
                return {
                    "signal": "⚡ CE SHORT COVERING",
                    "directive": f"Call Sellers Covering ({formatted_chg} OI) • Fast Spike",
                    "bias": "BULLISH",
                    "badge_class": "badge-bull"
                }
            # 5. Consolidation / Rangebound
            else:
                return {
                    "signal": "⚪ CE CONSOLIDATING",
                    "directive": f"Rangebound at ₹{ltp:.1f} ({pchange:+.1f}%) • Awaiting Momentum",
                    "bias": "NEUTRAL",
                    "badge_class": "badge-neutral"
                }
        else:
            # ── PUT (PE) CONTRACT EVALUATION ─────────────────────────
            # 1. Genuine Put Breakout (PE Buyer Expansion - Underlying Plunging)
            if (is_chart_bull or pchange > 2.0) and (buildup in ["LONG_BUILDUP", "SHORT_COVERING"] or pchange > 0) and not is_chart_bear:
                return {
                    "signal": "💥 BUY PE BREAKDOWN",
                    "directive": f"PE ₹{ltp:.1f} (+{pchange:.1f}%) > AT ₹{at_val:.1f} • Downside Momentum",
                    "bias": "BEARISH_SPOT",
                    "badge_class": "badge-bear"
                }
            # 2. Put Writing Support Cushion (PE Seller Floor - Underlying Bullish Floor)
            elif buildup == "SHORT_BUILDUP" and (is_chart_bear or pchange <= 0):
                return {
                    "signal": "🛡️ WRITE PE (SUPPORT)",
                    "directive": f"Put Writing Floor (PCR {stk_pcr:.2f}) • Strong Dip Cushion",
                    "bias": "BULLISH_SPOT",
                    "badge_class": "badge-bull"
                }
            # 3. Put Longs Unwinding / Theta Decay (Underlying Rebounding)
            elif buildup == "LONG_UNWINDING" or (is_chart_bear and pchange < -1.5):
                return {
                    "signal": "📉 PE DECAY / THETA",
                    "directive": f"Put Buyers Liquidating ({pchange:.1f}%) • Below AlphaTrend",
                    "bias": "BULLISH_SPOT",
                    "badge_class": "badge-bull"
                }
            # 4. Put Short Covering (Support Breaking / Writers Running)
            elif buildup == "SHORT_COVERING" and pchange > 0:
                return {
                    "signal": "🚨 PE WRITERS RUNNING",
                    "directive": f"Put Writers Capitulating ({formatted_chg} OI) • Floor Breaking",
                    "bias": "BEARISH_SPOT",
                    "badge_class": "badge-bear"
                }
            # 5. Consolidation / Rangebound
            else:
                return {
                    "signal": "⚪ PE CONSOLIDATING",
                    "directive": f"Rangebound at ₹{ltp:.1f} ({pchange:+.1f}%) • Awaiting Momentum",
                    "bias": "NEUTRAL",
                    "badge_class": "badge-neutral"
                }

    # ──────────────────────────────────────────────────────────────────────────
    # Internal Helpers: Layer 4 Confluence Scoring Engine
    # ──────────────────────────────────────────────────────────────────────────
    def _compute_strike_confluence(
        self,
        stk: float,
        spot: float,
        atm: float,
        step: float,
        offset: int,
        ce_oi: int,
        pe_oi: int,
        ce_chg: int,
        pe_chg: int,
        ce_ltp: float,
        pe_ltp: float,
        ce_pchange: float,
        pe_pchange: float,
        ce_vol: int,
        pe_vol: int,
        ce_iv: float,
        pe_iv: float,
        ce_bias: str,
        pe_bias: str,
        price_bias: str,
        ce_buildup: str,
        pe_buildup: str,
        stk_pcr: float,
        spot_tech: Dict[str, Any],
        strike_indicators: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Calculates a continuous, strike-specific multi-dimensional Confluence Score (0-100)
        and derives an actionable institutional verdict based on 5 independent quantitative pillars:
        
        Pillar 1: Strike PCR & Net Open Interest Dynamics (±18.0 pts)
        Pillar 2: Buildup Dynamics & Premium Action Skew (±16.0 pts)
        Pillar 3: Volume Concentration & IV Skew (±10.0 pts)
        Pillar 4: Strike Moneyness & Gamma Position (±10.0 pts)
        Pillar 5: PineScript Multi-Indicator Confirmation (AlphaTrend, TrendDir, Shonya, Proximity) (±20.0 pts)
        """
        import math
        score = 50.0  # neutral anchor pivot

        # ── Pillar 1: Strike PCR & Net Open Interest Dynamics (Max ± 18.0 pts) ──
        safe_pcr = max(0.08, min(12.0, stk_pcr if stk_pcr > 0 else 1.0))
        pcr_pts = math.log2(safe_pcr) * 8.0
        pcr_pts = max(-12.0, min(12.0, pcr_pts))

        total_chg_denom = max(1000, abs(pe_chg) + abs(ce_chg))
        chg_diff_ratio = (pe_chg - ce_chg) / total_chg_denom
        chg_pts = max(-6.0, min(6.0, chg_diff_ratio * 6.0))
        p1 = pcr_pts + chg_pts

        # ── Pillar 2: Buildups & Premium Action Dynamics (Max ± 16.0 pts) ────────
        ce_b_pts = 0.0
        if ce_buildup == "LONG_BUILDUP":
            ce_b_pts = +4.5  # Fresh call buying expansion
        elif ce_buildup == "SHORT_COVERING":
            ce_b_pts = +2.5  # Call bears covering / capitulating
        elif ce_buildup == "LONG_UNWINDING":
            ce_b_pts = -2.5  # Call profit taking
        elif ce_buildup == "SHORT_BUILDUP":
            ce_b_pts = -4.5  # Call writing resistance wall

        pe_b_pts = 0.0
        if pe_buildup == "SHORT_BUILDUP":
            pe_b_pts = +4.5  # Put writing support cushion (bullish floor)
        elif pe_buildup == "LONG_UNWINDING":
            pe_b_pts = +2.0  # Put buyers liquidating downside protection
        elif pe_buildup == "SHORT_COVERING":
            pe_b_pts = -2.5  # Put bears covering / floor weakening
        elif pe_buildup == "LONG_BUILDUP":
            pe_b_pts = -4.5  # Put buyers accumulating for plunge

        prem_diff = ce_pchange - pe_pchange
        prem_pts = max(-4.0, min(4.0, prem_diff * 0.25))
        p2 = ce_b_pts + pe_b_pts + prem_pts

        # ── Pillar 3: Volume Concentration & IV Skew (Max ± 10.0 pts) ───────────
        total_vol = max(100, ce_vol + pe_vol)
        vol_ratio = (ce_vol - pe_vol) / total_vol
        vol_pts = max(-5.0, min(5.0, vol_ratio * 5.0))

        iv_pts = 0.0
        if ce_iv > 0 and pe_iv > 0:
            iv_skew = (ce_iv - pe_iv) / max(5.0, (ce_iv + pe_iv) / 2)
            iv_pts = max(-5.0, min(5.0, iv_skew * 10.0))
        p3 = vol_pts + iv_pts

        # ── Pillar 4: Strike Moneyness & Delta Sensitivity (Max ± 10.0 pts) ─────
        dist_steps = (spot - stk) / max(1.0, step)
        dist_pts = max(-6.0, min(6.0, dist_steps * 1.5))
        atm_adj = 0.0
        if offset == 0:
            atm_adj = 1.0 if abs(spot - atm) < step * 0.25 else -0.5
        p4 = dist_pts + atm_adj

        # ── Pillar 5: PineScript Multi-Indicator Confirmation (Max ± 20.0 pts) ───
        if strike_indicators:
            # 1. Strike-Specific AlphaTrend Alignment (± 5.0 pts)
            at_st = strike_indicators.get("ind1", {}).get("state", "PIVOT")
            spot_at_bull = spot_tech.get("alphatrend_state") == "BULLISH"
            if at_st == "ABOVE":
                at_pts = 4.0 if spot_at_bull else -3.0
            elif at_st == "BELOW":
                at_pts = -4.0 if not spot_at_bull else 3.0
            else:
                at_pts = 1.0 if spot_at_bull else -1.0

            # 2. Strike-Specific TrendDirection Momentum (± 5.0 pts)
            stk_td = strike_indicators.get("ind2", {}).get("strength", 0.0)
            td_pts = max(-5.0, min(5.0, stk_td * 5.0))

            # 3. Strike-Specific Shonya Gravity Position (± 5.0 pts)
            sh_st = strike_indicators.get("ind3", {}).get("state", "AT GRAV")
            spot_sh_bull = spot_tech.get("shonya_state") == "BULLISH"
            if sh_st == "ABOVE":
                sh_pts = 3.5 if spot_sh_bull else -2.5
            elif sh_st == "BELOW":
                sh_pts = -3.5 if not spot_sh_bull else 2.5
            else:
                sh_pts = 0.5 if spot_sh_bull else -0.5

            # 4. Strike-Specific Proximity Across Corridor (± 5.0 pts)
            p_val = strike_indicators.get("ind4", {}).get("per", 50.0)
            prox_pts = max(-5.0, min(5.0, ((p_val - 50.0) / 50.0) * 5.0))

            # 5. Breakout Tracker (± 4.0 pts)
            brk_bias_val = strike_indicators.get("ind6", {}).get("bias", "NEUTRAL")
            brk_pts = 4.0 if brk_bias_val == "BULLISH" else (-4.0 if brk_bias_val == "BEARISH" else 0.0)

            p5 = (at_pts * 0.8) + (td_pts * 0.8) + (sh_pts * 0.8) + (prox_pts * 0.8) + brk_pts
        else:
            # Fallback to spot indicators
            at_state = spot_tech.get("alphatrend_state", "NEUTRAL")
            at_pts = 5.0 if at_state == "BULLISH" else (-5.0 if at_state == "BEARISH" else 0.0)
            td_strength = spot_tech.get("trend_dir_strength", 0.0)
            td_pts = max(-5.0, min(5.0, td_strength * 5.0))
            sh_state = spot_tech.get("shonya_state", "NEUTRAL")
            sh_pts = 5.0 if sh_state == "BULLISH" else (-5.0 if sh_state == "BEARISH" else 0.0)
            prox_per = spot_tech.get("prox_per", 50.0)
            prox_pts = max(-5.0, min(5.0, ((prox_per - 50.0) / 50.0) * 5.0))
            brk_bias_val = spot_tech.get("brk_bias", "NEUTRAL")
            brk_pts = 4.0 if brk_bias_val == "BULLISH" else (-4.0 if brk_bias_val == "BEARISH" else 0.0)

            p5 = (at_pts * 0.8) + (td_pts * 0.8) + (sh_pts * 0.8) + (prox_pts * 0.8) + brk_pts

        total_score = score + p1 + p2 + p3 + p4 + p5
        final_score = int(round(max(5.0, min(95.0, total_score))))

        # ── Granular Bias Classification & Safe Corridor Verdict ──────────────
        ce_is_breakout = ce_pchange > 0 and (ce_buildup in ["LONG_BUILDUP", "SHORT_COVERING"])
        pe_is_breakout = pe_pchange > 0 and (pe_buildup in ["LONG_BUILDUP", "SHORT_COVERING"])

        if final_score >= 76:
            final_bias = "STRONG BULLISH"
            bias_class = "badge-bull"
            if ce_is_breakout:
                signal = "🚀 BUY CALL BREAKOUT"
                interp = f"Put Floor (PCR {stk_pcr:.2f}) • Call Breakout Momentum"
            else:
                signal = "🟢 PUT WRITING ACCUMULATION"
                interp = f"Aggressive Put Support Floor (PCR {stk_pcr:.2f}) • Dip Cushion"
        elif final_score >= 66:
            final_bias = "BULLISH"
            bias_class = "badge-bull"
            signal = "🟢 PUT WRITING ACCUMULATION"
            interp = f"Put Support Floor (PCR {stk_pcr:.2f}) • Dip-Buying Cushion"
        elif final_score >= 58:
            final_bias = "MODERATE BULLISH"
            bias_class = "badge-bull"
            signal = "🛡️ SELL PUT CREDIT SPREAD"
            interp = f"Support Cushion at ₹{stk:,.0f} • Favorable Put Theta Decay"
        elif final_score >= 53:
            final_bias = "LEAN BULLISH"
            bias_class = "badge-bull"
            signal = "📈 MILD BULLISH EXPANSION"
            interp = f"Positive PCR ({stk_pcr:.2f}) • Controlled Upside Drift"
        elif final_score >= 48:
            final_bias = "NEUTRAL"
            bias_class = "badge-neutral"
            signal = "⚓ ATM PIVOT / STRADDLE PIN"
            interp = f"Balanced CE/PE at ₹{stk:,.0f} (PCR {stk_pcr:.2f}) • Straddle Pin"
        elif final_score >= 43:
            final_bias = "LEAN BEARISH"
            bias_class = "badge-bear"
            signal = "📉 MILD BEARISH DRIFT"
            interp = f"Call Supply Overhead (PCR {stk_pcr:.2f}) • Mild Selling"
        elif final_score >= 34:
            final_bias = "MODERATE BEARISH"
            bias_class = "badge-bear"
            signal = "🛡️ SELL CALL CREDIT SPREAD"
            interp = f"Ceiling at ₹{stk:,.0f} • Favorable Call Theta Decay"
        elif final_score >= 24:
            final_bias = "BEARISH"
            bias_class = "badge-bear"
            signal = "🔴 CALL WRITING RESISTANCE"
            interp = f"Heavy Call Resistance (PCR {stk_pcr:.2f}) • Upside Capped"
        else:
            final_bias = "STRONG BEARISH"
            bias_class = "badge-bear"
            if pe_is_breakout:
                signal = "💥 BUY PUT BREAKDOWN"
                interp = f"Floor Crack (PCR {stk_pcr:.2f}) • Put Breakout Momentum"
            else:
                signal = "🔴 MASSIVE CALL WALL RESISTANCE"
                interp = f"Heavy Call Resistance (PCR {stk_pcr:.2f}) • Downside Heavy"

        return {
            "ce_bias": ce_bias,
            "pe_bias": pe_bias,
            "price_bias": price_bias,
            "score": final_score,
            "final_bias": final_bias,
            "bias_class": bias_class,
            "signal": signal,
            "interpretation": interp,
            "pillars": {
                "p1_oi_pcr": round(p1, 1),
                "p2_buildup": round(p2, 1),
                "p3_vol_iv": round(p3, 1),
                "p4_moneyness": round(p4, 1),
                "p5_indicators": round(p5, 1)
            }
        }


option_confluence_service = OptionConfluenceService()
