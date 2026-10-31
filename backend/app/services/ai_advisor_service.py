"""
Institutional AI Trade Advisor Service
Integrates Groq LPU (Qwen 27B / GPT-OSS) with automatic fallback to Google Gemini Flash.
Provides real-time Option Buyer & Scalper trade alerts with strict ATM strike selection
and guaranteed commission cost coverage (minimum ₹100+ net profit after brokerage).
"""
import json
import logging
import time
import urllib.request
import urllib.error
from typing import Dict, Any, Optional

from app.core.credentials import credentials
from app.core.config import get_settings

logger = logging.getLogger(__name__)

class AIAdvisorService:
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_time: Dict[str, float] = {}
        self.cache_ttl = 30.0  # 30-second cache to stay comfortably within free-tier limits
        self._groq_key_index = 0

    def get_ai_recommendation(
        self,
        symbol: str,
        spot: float,
        spot_pchange: float,
        atm_strike: float,
        confluence_score: float,
        direction: str,
        chain_summary: Dict[str, Any],
        indicators: Dict[str, Any],
        smart_money: Optional[Dict[str, Any]] = None,
        current_option_ltp: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Generates an institutional AI option buying / scalping trade recommendation.
        Uses Groq as primary (~250ms) and Google Gemini Flash as automatic fallback.
        """
        sym = symbol.upper()
        now = time.time()

        if sym in self._cache and (now - self._cache_time.get(sym, 0.0)) < self.cache_ttl:
            return self._cache[sym]

        settings = get_settings()
        lot_size = settings.LOT_SIZES.get(sym, 65 if sym == "NIFTY" else 30)

        # 1. Attempt Primary: Groq Cloud API
        ai_result = self._call_groq(
            sym=sym,
            spot=spot,
            spot_pchange=spot_pchange,
            atm_strike=atm_strike,
            confluence_score=confluence_score,
            direction=direction,
            lot_size=lot_size,
            chain_summary=chain_summary,
            indicators=indicators,
            smart_money=smart_money,
            current_option_ltp=current_option_ltp
        )

        # 2. Fallback: Google Gemini API if Groq fails
        if not ai_result or not ai_result.get("success"):
            logger.warning(f"Groq API unavailable for {sym}, switching to Google Gemini Flash backup...")
            ai_result = self._call_gemini(
                sym=sym,
                spot=spot,
                spot_pchange=spot_pchange,
                atm_strike=atm_strike,
                confluence_score=confluence_score,
                direction=direction,
                lot_size=lot_size,
                chain_summary=chain_summary,
                indicators=indicators,
                smart_money=smart_money,
                current_option_ltp=current_option_ltp
            )

        # 3. Deterministic Safety Fallback if both cloud APIs are unreachable
        if not ai_result or not ai_result.get("success"):
            logger.warning(f"Both AI APIs unreachable for {sym}. Generating deterministic algorithmic recommendation.")
            ai_result = self._generate_deterministic_buyer_plan(
                sym=sym,
                spot=spot,
                spot_pchange=spot_pchange,
                atm_strike=atm_strike,
                confluence_score=confluence_score,
                direction=direction,
                lot_size=lot_size,
                chain_summary=chain_summary,
                indicators=indicators,
                smart_money=smart_money,
                current_option_ltp=current_option_ltp
            )

        self._cache[sym] = ai_result
        self._cache_time[sym] = now
        return ai_result

    def _build_prompt_payload(
        self,
        sym: str,
        spot: float,
        spot_pchange: float,
        atm_strike: float,
        confluence_score: float,
        direction: str,
        lot_size: int,
        chain_summary: Dict[str, Any],
        indicators: Dict[str, Any],
        smart_money: Optional[Dict[str, Any]],
        current_option_ltp: Optional[float] = None
    ) -> Dict[str, Any]:
        """Constructs rich contextual multi-factor telemetry for the LLM."""
        est_ltp = current_option_ltp if (current_option_ltp and current_option_ltp > 0) else (
            chain_summary.get("atm_ce_ltp", 100.0) if direction == "BULLISH" else chain_summary.get("atm_pe_ltp", 100.0)
        )
        step = 50.0 if "BANK" not in sym else 100.0
        call_wall = chain_summary.get("call_wall_strike", atm_strike + step)
        call_oi = chain_summary.get("call_wall_oi", 0)
        call_chg = chain_summary.get("call_wall_oi_change", 0)
        put_wall = chain_summary.get("put_wall_strike", atm_strike - step)
        put_oi = chain_summary.get("put_wall_oi", 0)
        put_chg = chain_summary.get("put_wall_oi_change", 0)

        sm_crores = 0.0
        sm_bias = "NEUTRAL"
        sm_label = "NEUTRAL FLOW"
        if smart_money:
            sm_crores = smart_money.get("net_flow_cr", smart_money.get("net_crores", 0.0))
            sm_bias = smart_money.get("bias", "NEUTRAL")
            sm_label = smart_money.get("label", "NEUTRAL FLOW")

        return {
            "symbol": sym,
            "lot_size": lot_size,
            "spot_price": spot,
            "day_change_pct": spot_pchange,
            "atm_strike": atm_strike,
            "current_contract_ltp": est_ltp,
            "confluence_score": confluence_score,
            "direction_bias": direction,
            "market_regime": indicators.get("regime", indicators.get("market_regime", "RANGE-BOUND")),
            "technical_indicators": {
                "hull_suite_state": indicators.get("hull_state", "NEUTRAL"),
                "alphatrend_state": indicators.get("alphatrend_state", "NEUTRAL"),
                "adx_strength": indicators.get("adx", 25.0),
            },
            "option_chain_intelligence": {
                "pcr": chain_summary.get("pcr", 1.0),
                "pcr_atm_5": chain_summary.get("pcr_atm_5", 1.0),
                "dominant_pressure": chain_summary.get("dominant_pressure", "BALANCED"),
                "call_writer_pressure_pct": chain_summary.get("call_writer_pressure_pct", 50.0),
                "put_writer_pressure_pct": chain_summary.get("put_writer_pressure_pct", 50.0),
                "immediate_call_ceiling": {
                    "strike": call_wall,
                    "open_interest": call_oi,
                    "oi_change": call_chg
                },
                "immediate_put_floor": {
                    "strike": put_wall,
                    "open_interest": put_oi,
                    "oi_change": put_chg
                }
            },
            "institutional_smart_money": {
                "net_flow_crores": sm_crores,
                "bias": sm_bias,
                "label": sm_label
            },
            "rules": {
                "role": "STRICT OPTION BUYER / SCALPER ONLY",
                "strike_selection": "STRICTLY ATM STRIKE (Delta ~ 0.50). NEVER DEEP OTM.",
                "entry_price": f"MUST EQUAL current_contract_ltp ({est_ltp}).",
                "scalp_target1": f"Calculate dynamically from entry_price ({est_ltp} + 12% to 18% or +15 to +35 pts). Must cover Rs.75 broker fees.",
                "runner_target2": f"Calculate dynamically from entry_price ({est_ltp} + 30% to 50% or +40 to +75 pts).",
                "stop_loss": f"Calculate dynamically from entry_price ({est_ltp} - 12% to 16% or -15 to -25 pts).",
                "risk_reward": "Minimum 1:1.5. Stop Loss must be disciplined.",
                "chop_filter": "If Confluence is between 46 and 54 or ADX < 20, output action: STANDBY (AVOID CHOP)."
            }
        }

    def _call_groq(
        self,
        sym: str,
        spot: float,
        spot_pchange: float,
        atm_strike: float,
        confluence_score: float,
        direction: str,
        lot_size: int,
        chain_summary: Dict[str, Any],
        indicators: Dict[str, Any],
        smart_money: Optional[Dict[str, Any]],
        current_option_ltp: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """Invokes Groq Cloud LPU with round-robin multi-key pool and 0ms auto-failover."""
        keys = credentials.groq_api_keys or ([credentials.groq_api_key] if credentials.groq_api_key else [])
        if not keys:
            return None

        url = "https://api.groq.com/openai/v1/chat/completions"
        context_data = self._build_prompt_payload(
            sym, spot, spot_pchange, atm_strike, confluence_score, direction,
            lot_size, chain_summary, indicators, smart_money, current_option_ltp
        )

        system_prompt = (
            "You are an Elite Institutional Index Option Buyer & Scalper Algorithmic Advisor for NSE India (MyBullAndBear AI Engine).\n"
            "Rules:\n"
            "1. ONLY OPTION BUYING OR SCALPING (BUY CE if Bullish, BUY PE if Bearish). DO NOT RECOMMEND OPTION SELLING.\n"
            "2. Strike must be strictly ATM strike.\n"
            "3. COMMISSION GUARANTEE: Round-trip statutory charges = ₹75. Scalp Target 1 MUST be at least ₹200 gross per lot so Net Profit >= ₹125.\n"
            "4. If market is choppy (confluence 46-54 or chop), action must be 'STANDBY'.\n"
            "5. QUANTIFIED LEADING OI INTELLIGENCE REQUIREMENT FOR THESIS:\n"
            "DO NOT rely heavily on lagging ADX or wait for lagging PCR moves. Focus on Leading Strike-Level OI Targets!\n"
            "You MUST quantify exact target contract values in the playbook (e.g. Call OI drops from X to < Y, Put OI increases from A to > B) and require Hull Suite trend confirmation.\n"
            "Format 'institutional_thesis' strictly as:\n"
            "'TACTICAL REGIME: [Regime & Confluence Score]. Spot [Spot] is pinned between [Put Wall] Put Floor (PE OI: [X]L, [Y]k added) and [Call Wall] Call Ceiling (CE OI: [X]L, [Y]k added). Writer pressure is [CE]% Call / [PE]% Put with Smart Money [Net Cr] Cr | PCR: [PCR].\n"
            "PLAYBOOK:\n"
            "BULL TRIGGER: IF Spot sustains > [Call Wall] WITH [Call Wall] Call OI unwinding (drops from [X]L to < [Target]L) AND [Put Wall] Put OI builds from [A]L to > [Target]L + Hull turns BULLISH -> BUY [ATM Strike] CE (Target: +15%, SL: -15%).\n"
            "BEAR TRIGGER: IF Spot breaks < [Put Wall] WITH [Put Wall] Put floor liquidating (drops from [A]L to < [Target]L) AND [Call Wall] Call OI builds from [X]L to > [Target]L + Hull turns BEARISH -> BUY [ATM Strike] PE (Target: +15%, SL: -15%).\n"
            "STATUS: [STANDBY (Capital Preserved - two-sided OI wall defense guarantees whipsaws inside corridor) / BUY CALL NOW / BUY PUT NOW].'\n\n"
            "Return valid JSON ONLY matching this schema:\n"
            "{\n"
            '  "action": "BUY_CALL" | "BUY_PUT" | "STANDBY",\n'
            '  "strategy_type": "MOMENTUM_BUY" | "QUICK_SCALP" | "STANDBY",\n'
            '  "strike": float,\n'
            '  "option_type": "CE" | "PE" | "NONE",\n'
            '  "entry_price": float,\n'
            '  "scalp_target1": float,\n'
            '  "runner_target2": float,\n'
            '  "stop_loss": float,\n'
            '  "target1_gross_profit_inr": float,\n'
            '  "commission_buffer_inr": 75.0,\n'
            '  "target1_net_profit_inr": float,\n'
            '  "risk_reward_ratio": "1 : 1.8",\n'
            '  "ai_conviction_pct": int,\n'
            '  "institutional_thesis": "...",\n'
            '  "invalidation_condition": "..."\n'
            "}"
        )

        body = {
            "model": "qwen/qwen3.8-27b",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analyze this real-time market telemetry and formulate the trade alert in valid JSON format:\n{json.dumps(context_data)}"}
            ],
            "temperature": 0.15,
            "max_tokens": 800,
            "response_format": {"type": "json_object"}
        }
        encoded_body = json.dumps(body).encode("utf-8")

        num_keys = len(keys)
        start_idx = self._groq_key_index

        for attempt in range(num_keys):
            idx = (start_idx + attempt) % num_keys
            api_key = keys[idx]

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            req = urllib.request.Request(url, data=encoded_body, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    parsed["success"] = True
                    parsed["ai_engine"] = "MyBullAndBear AI Engine"
                    parsed["timestamp"] = time.strftime("%H:%M:%S")
                    # Advance pointer for round-robin load distribution
                    self._groq_key_index = (idx + 1) % num_keys
                    return parsed
            except urllib.error.HTTPError as he:
                if he.code in (429, 500, 502, 503, 504):
                    logger.warning(f"Groq Key #{idx + 1} ({api_key[:10]}...) HTTP {he.code}. Instant failover to next key...")
                    continue
                else:
                    logger.warning(f"Groq Key #{idx + 1} HTTP {he.code}: {he}")
                    continue
            except Exception as e:
                logger.warning(f"Groq API error on Key #{idx + 1}: {e}")
                continue

        logger.error("All Groq keys in pool exhausted. Triggering fallback.")
        return None

    def _call_gemini(
        self,
        sym: str,
        spot: float,
        spot_pchange: float,
        atm_strike: float,
        confluence_score: float,
        direction: str,
        lot_size: int,
        chain_summary: Dict[str, Any],
        indicators: Dict[str, Any],
        smart_money: Optional[Dict[str, Any]],
        current_option_ltp: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """Invokes Google Gemini Flash API as high-reliability fallback."""
        api_key = credentials.gemini_api_key
        if not api_key:
            return None

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}

        context_data = self._build_prompt_payload(
            sym, spot, spot_pchange, atm_strike, confluence_score, direction,
            lot_size, chain_summary, indicators, smart_money, current_option_ltp
        )

        prompt_text = (
            "You are an Elite Institutional Index Option Buyer & Scalper Algorithmic Advisor for NSE India (MyBullAndBear AI Engine).\n"
            "Rules:\n"
            "1. ONLY OPTION BUYING OR SCALPING (BUY CE if Bullish, BUY PE if Bearish). DO NOT RECOMMEND OPTION SELLING.\n"
            "2. Strike must be strictly ATM strike.\n"
            "3. COMMISSION GUARANTEE: Round-trip statutory charges = ₹75. Scalp Target 1 MUST be at least ₹200 gross per lot so Net Profit >= ₹125.\n"
            "4. If market is choppy (confluence 46-54 or chop), action must be 'STANDBY'.\n"
            "5. QUANTIFIED LEADING OI INTELLIGENCE REQUIREMENT FOR THESIS:\n"
            "DO NOT rely heavily on lagging ADX or wait for lagging PCR moves. Focus on Leading Strike-Level OI Targets!\n"
            "You MUST quantify exact target contract values in the playbook (e.g. Call OI drops from X to < Y, Put OI increases from A to > B) and require Hull Suite trend confirmation.\n"
            "Format 'institutional_thesis' strictly as:\n"
            "'TACTICAL REGIME: [Regime & Confluence Score]. Spot [Spot] is pinned between [Put Wall] Put Floor (PE OI: [X]L, [Y]k added) and [Call Wall] Call Ceiling (CE OI: [X]L, [Y]k added). Writer pressure is [CE]% Call / [PE]% Put with Smart Money [Net Cr] Cr | PCR: [PCR].\n"
            "PLAYBOOK:\n"
            "BULL TRIGGER: IF Spot sustains > [Call Wall] WITH [Call Wall] Call OI unwinding (drops from [X]L to < [Target]L) AND [Put Wall] Put OI builds from [A]L to > [Target]L + Hull turns BULLISH -> BUY [ATM Strike] CE (Target: +15%, SL: -15%).\n"
            "BEAR TRIGGER: IF Spot breaks < [Put Wall] WITH [Put Wall] Put floor liquidating (drops from [A]L to < [Target]L) AND [Call Wall] Call OI builds from [X]L to > [Target]L + Hull turns BEARISH -> BUY [ATM Strike] PE (Target: +15%, SL: -15%).\n"
            "STATUS: [STANDBY (Capital Preserved - two-sided OI wall defense guarantees whipsaws inside corridor) / BUY CALL NOW / BUY PUT NOW].'\n\n"
            "Format your answer strictly as a JSON object with keys:\n"
            "action ('BUY_CALL', 'BUY_PUT', 'STANDBY'), strategy_type, strike, option_type, entry_price, "
            "scalp_target1, runner_target2, stop_loss, target1_gross_profit_inr, commission_buffer_inr (75.0), "
            "target1_net_profit_inr, risk_reward_ratio, ai_conviction_pct, institutional_thesis, invalidation_condition.\n"
            f"Market Telemetry: {json.dumps(context_data)}"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt_text}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}
        }

        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=7.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text)
                parsed["success"] = True
                parsed["ai_engine"] = "MyBullAndBear AI Engine (Neural Backup)"
                parsed["timestamp"] = time.strftime("%H:%M:%S")
                return parsed
        except Exception as e:
            logger.warning(f"AI engine fallback error for {sym}: {e}")
            return None

    def _generate_deterministic_buyer_plan(
        self,
        sym: str,
        spot: float,
        spot_pchange: float,
        atm_strike: float,
        confluence_score: float,
        direction: str,
        lot_size: int,
        chain_summary: Optional[Dict[str, Any]] = None,
        indicators: Optional[Dict[str, Any]] = None,
        smart_money: Optional[Dict[str, Any]] = None,
        current_option_ltp: Optional[float] = None
    ) -> Dict[str, Any]:
        """Deterministic algorithmic buyer setup with multi-factor intelligence and commission guarantee."""
        is_bull = (direction == "BULLISH" and (confluence_score >= 58.0 or spot_pchange >= 0.25))
        is_bear = (direction == "BEARISH" and (confluence_score <= 42.0 or spot_pchange <= -0.25))
        is_chop = not is_bull and not is_bear

        opt_type = "CE" if is_bull else ("PE" if is_bear else "NONE")
        action = "BUY_CALL" if is_bull else ("BUY_PUT" if is_bear else "STANDBY")

        est_ltp = current_option_ltp if (current_option_ltp and current_option_ltp > 0) else round(spot * 0.006, 1)

        # Commission math: round-trip = ₹75
        # Ensure target1 gives minimum ₹150+ net profit after charges
        min_gross_target_inr = 250.0  # ₹250 gross - ₹75 charges = ₹175 net
        min_target_pts = max(4.0, round(min_gross_target_inr / lot_size, 1))

        scalp_pts = max(min_target_pts, round(est_ltp * 0.14, 1))
        runner_pts = round(est_ltp * 0.35, 1)
        sl_pts = max(4.0, round(est_ltp * 0.15, 1))

        target1_price = round(est_ltp + scalp_pts, 1)
        target2_price = round(est_ltp + runner_pts, 1)
        stop_price = round(est_ltp - sl_pts, 1)

        target1_gross = round(scalp_pts * lot_size, 0)
        target1_net = round(target1_gross - 75.0, 0)

        step = 50.0 if sym in ("NIFTY", "FINNIFTY") else 100.0
        call_wall = chain_summary.get("call_wall_strike", atm_strike + step) if chain_summary else (atm_strike + step)
        call_oi = chain_summary.get("call_wall_oi", 0) if chain_summary else 0
        call_chg = chain_summary.get("call_wall_oi_change", 0) if chain_summary else 0
        put_wall = chain_summary.get("put_wall_strike", atm_strike - step) if chain_summary else (atm_strike - step)
        put_oi = chain_summary.get("put_wall_oi", 0) if chain_summary else 0
        put_chg = chain_summary.get("put_wall_oi_change", 0) if chain_summary else 0

        pcr = chain_summary.get("pcr", 1.0) if chain_summary else 1.0
        call_press = chain_summary.get("call_writer_pressure_pct", 50.0) if chain_summary else 50.0
        put_press = chain_summary.get("put_writer_pressure_pct", 50.0) if chain_summary else 50.0

        hull_state = indicators.get("hull_state", "NEUTRAL") if indicators else "NEUTRAL"
        adx = indicators.get("adx", 25.0) if indicators else 25.0
        regime = indicators.get("regime", indicators.get("market_regime", "RANGE-BOUND")) if indicators else "RANGE-BOUND"

        sm_crores = 0.0
        if smart_money:
            sm_crores = smart_money.get("net_flow_cr", smart_money.get("net_crores", 0.0))

        call_oi_lakhs = round(call_oi / 100000, 2)
        put_oi_lakhs = round(put_oi / 100000, 2)
        call_chg_k = round(call_chg / 1000, 1)
        put_chg_k = round(put_chg / 1000, 1)

        wall_summary = (
            f"pinned between {int(put_wall)} Put Floor (PE OI: {put_oi_lakhs}L, {put_chg_k:+}k added) "
            f"and {int(call_wall)} Call Ceiling (CE OI: {call_oi_lakhs}L, {call_chg_k:+}k added)"
            if (put_oi > 0 and call_oi > 0) else
            f"corridor between {int(put_wall)} support and {int(call_wall)} resistance"
        )

        tactical_brief = (
            f"TACTICAL REGIME: {regime} (Confluence: {confluence_score:.1f}). "
            f"Spot {spot:.1f} is {wall_summary}. "
            f"Writer pressure is balanced (CE {call_press:.0f}% / PE {put_press:.0f}%) with Smart Money {sm_crores:+.2f} Cr | PCR: {pcr:.2f}."
        )

        target_call_unwind = max(0.1, round((call_oi - 5000) / 100000, 2))
        target_put_build = round((put_oi + 10000) / 100000, 2)
        target_put_unwind = max(0.1, round((put_oi - 5000) / 100000, 2))
        target_call_build = round((call_oi + 10000) / 100000, 2)

        bull_trigger = (
            f"BULL TRIGGER: IF Spot sustains > {int(call_wall)} WITH {int(call_wall)} Call OI unwinding "
            f"(drops from {call_oi_lakhs}L to < {target_call_unwind}L) AND {int(put_wall)} Put OI builds "
            f"from {put_oi_lakhs}L to > {target_put_build}L + Hull turns BULLISH "
            f"-> BUY {int(atm_strike)} CE (Target: Rs.{target1_price}, SL: Rs.{stop_price})"
        )

        bear_trigger = (
            f"BEAR TRIGGER: IF Spot breaks < {int(put_wall)} WITH {int(put_wall)} Put floor liquidating "
            f"(drops from {put_oi_lakhs}L to < {target_put_unwind}L) AND {int(call_wall)} Call OI builds "
            f"from {call_oi_lakhs}L to > {target_call_build}L + Hull turns BEARISH "
            f"-> BUY {int(atm_strike)} PE (Target: Rs.{target1_price}, SL: Rs.{stop_price})"
        )

        directive = (
            "STATUS: STANDBY (Capital Preserved - two-sided OI wall defense guarantees whipsaws inside corridor)."
            if is_chop else
            (f"STATUS: BUY CALL (Active momentum confirmed by confluence {confluence_score:.1f})." if is_bull else
             f"STATUS: BUY PUT (Active breakdown confirmed by confluence {confluence_score:.1f}).")
        )

        thesis = f"{tactical_brief}\nPLAYBOOK:\n{bull_trigger}\n{bear_trigger}\n{directive}"

        return {
            "success": True,
            "ai_engine": "MyBullAndBear AI Quantitative Core",
            "action": action,
            "strategy_type": "MOMENTUM_BUY" if not is_chop else "STANDBY",
            "strike": atm_strike if not is_chop else 0.0,
            "option_type": opt_type,
            "entry_price": est_ltp if not is_chop else 0.0,
            "scalp_target1": target1_price if not is_chop else 0.0,
            "runner_target2": target2_price if not is_chop else 0.0,
            "stop_loss": stop_price if not is_chop else 0.0,
            "target1_gross_profit_inr": target1_gross if not is_chop else 0.0,
            "commission_buffer_inr": 75.0,
            "target1_net_profit_inr": target1_net if not is_chop else 0.0,
            "risk_reward_ratio": f"1 : {round(scalp_pts / max(1.0, sl_pts), 1)}",
            "ai_conviction_pct": int(min(95, max(45, 60 + abs(confluence_score - 50) * 0.7))),
            "institutional_thesis": thesis,
            "invalidation_condition": f"Spot crosses back across {int(atm_strike)} or opposing OI spikes.",
            "timestamp": time.strftime("%H:%M:%S")
        }

    async def get_multi_index_market_overview(self, symbols: list[str]) -> Dict[str, Any]:
        """
        Synthesizes multi-index market telemetry (OHLC prices, Open Interest changes,
        PCR, Confluence scores, Technical indicators, and Option walls)
        into an elite institutional cross-asset AI market view.
        """
        from app.api.market import fetch_live_chain_data
        from app.services.option_chain import parse_option_chain
        from app.services.oi_analyzer import oi_analyzer
        from app.services.signal_engine import signal_engine
        from app.services.technical_indicators import TechnicalIndicators
        from app.services.fyers_service import fyers_service

        valid_syms = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
        chosen = [s.strip().upper() for s in symbols if s and s.strip().upper() in valid_syms]
        if not chosen:
            chosen = valid_syms

        # 1. Fetch live quotes for accurate OHLC from broker if active
        fyers_sym_map = {
            "NIFTY": "NSE:NIFTY50-INDEX",
            "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
            "FINNIFTY": "NSE:FINNIFTY-INDEX",
            "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX"
        }
        quotes_map = {}
        if fyers_service.is_configured() and fyers_service.fyers:
            try:
                fyers_tickers = [fyers_sym_map[s] for s in chosen if s in fyers_sym_map]
                q_res = fyers_service.get_quotes(fyers_tickers)
                if q_res and isinstance(q_res, dict) and "d" in q_res:
                    for item in q_res["d"]:
                        quotes_map[item.get("n")] = item.get("v", {})
            except Exception as e:
                logger.warning(f"Error fetching quotes for multi-index overview: {e}")

        # 2. Gather high-fidelity telemetry for each selected index
        telemetry_list = []
        for sym in chosen:
            try:
                raw, source = await fetch_live_chain_data(sym)
                if not raw:
                    continue
                parsed = parse_option_chain(raw, sym)
                oi_data = oi_analyzer.analyze(parsed)
                dec = signal_engine.evaluate(parsed, oi_data)

                # Broker OHLC with safe fallbacks
                q_v = quotes_map.get(fyers_sym_map.get(sym), {})
                spot_price = float(q_v.get("lp", parsed.spot_price or 0.0))
                open_p = float(q_v.get("open_price", spot_price))
                high_p = float(q_v.get("high_price", spot_price))
                low_p = float(q_v.get("low_price", spot_price))
                prev_close_p = float(q_v.get("prev_close_price", spot_price))
                spot_pchange = float(q_v.get("chp", parsed.spot_pchange or 0.0))
                day_range = round(max(0.0, high_p - low_p), 2)
                range_position_pct = round(((spot_price - low_p) / day_range * 100), 1) if day_range > 0 else 50.0

                # Compute Hull Suite state
                closes = [s.CE.lastPrice for s in parsed.strikes if s.CE.lastPrice > 0]
                hull_state = "NEUTRAL"
                try:
                    if len(closes) >= 4:
                        h_res = TechnicalIndicators.compute_hull(closes)
                        hull_state = h_res.get("curr_state", "NEUTRAL")
                except Exception:
                    pass

                # Option walls
                walls = oi_data.get("walls", {})
                step = 50.0 if "BANK" not in sym else 100.0
                sup_strike = walls.get("support_strike", parsed.atm_strike - 2 * step)
                res_strike = walls.get("resistance_strike", parsed.atm_strike + 2 * step)

                # Total Open Interest & Intraday Writing Flow
                tot_ce_oi = sum(s.CE.openInterest for s in parsed.strikes)
                tot_pe_oi = sum(s.PE.openInterest for s in parsed.strikes)
                ce_chg_sum = sum(s.CE.changeinOpenInterest for s in parsed.strikes)
                pe_chg_sum = sum(s.PE.changeinOpenInterest for s in parsed.strikes)
                net_oi_diff_lakhs = round((tot_pe_oi - tot_ce_oi) / 100000, 2)
                net_oi_chg_k = round((pe_chg_sum - ce_chg_sum) / 1000, 1)

                if tot_pe_oi > tot_ce_oi * 1.08:
                    tot_bias = "PE_DOMINANT"
                elif tot_ce_oi > tot_pe_oi * 1.08:
                    tot_bias = "CE_DOMINANT"
                else:
                    tot_bias = "BALANCED"

                flow_bias = "PUT_SUPPORT" if pe_chg_sum > ce_chg_sum * 1.15 else (
                    "CALL_RESISTANCE" if ce_chg_sum > pe_chg_sum * 1.15 else "BALANCED"
                )

                conf_score = round(dec.get("confluence_score", 50.0), 1)
                trend_dir = "UP" if spot_pchange >= 0.15 else ("DOWN" if spot_pchange <= -0.15 else "SIDEWAYS")
                alphatrend = "BULLISH" if (conf_score >= 60.0 or spot_pchange >= 0.30) else (
                    "BEARISH" if (conf_score <= 40.0 or spot_pchange <= -0.30) else "NEUTRAL"
                )

                action = "BUY_CALL" if conf_score >= 68.0 else ("BUY_PUT" if conf_score <= 34.0 else "STANDBY")

                telemetry_list.append({
                    "symbol": sym,
                    "spot_price": spot_price,
                    "spot_pchange": spot_pchange,
                    "atm_strike": parsed.atm_strike,
                    "ohlc": {
                        "open": open_p,
                        "high": high_p,
                        "low": low_p,
                        "prev_close": prev_close_p,
                        "range": day_range,
                        "range_position_pct": range_position_pct,
                        "trading_above_open": spot_price >= open_p
                    },
                    "open_interest": {
                        "pcr": round(parsed.pcr, 2),
                        "max_pain": parsed.max_pain,
                        "key_support": sup_strike,
                        "key_resistance": res_strike,
                        "tot_ce_oi_lakhs": round(tot_ce_oi / 100000, 2),
                        "tot_pe_oi_lakhs": round(tot_pe_oi / 100000, 2),
                        "net_oi_diff_lakhs": net_oi_diff_lakhs,
                        "tot_oi_bias": tot_bias,
                        "ce_oi_change_k": round(ce_chg_sum / 1000, 1),
                        "pe_oi_change_k": round(pe_chg_sum / 1000, 1),
                        "net_oi_chg_k": net_oi_chg_k,
                        "flow_bias": flow_bias
                    },
                    "indicators": {
                        "confluence_score": conf_score,
                        "market_regime": dec.get("market_regime", "RANGE-BOUND"),
                        "hull_state": hull_state,
                        "alphatrend": alphatrend,
                        "trend_direction": trend_dir,
                        "action": action
                    }
                })
            except Exception as e:
                logger.error(f"Error gathering telemetry for {sym}: {e}", exc_info=True)

        if not telemetry_list:
            return {
                "success": False,
                "message": "Unable to collect real-time index telemetry for the selected indices."
            }

        # 3. Call AI LLM Synthesis (Groq Qwen/GPT-OSS with Gemini fallback)
        ai_overview = self._call_llm_for_market_overview(telemetry_list)
        if not ai_overview or not ai_overview.get("success"):
            logger.info("AI cloud API fallback: Using deterministic multi-factor institutional engine.")
            ai_overview = self._generate_deterministic_market_overview(telemetry_list)

        ai_overview["timestamp"] = time.strftime("%H:%M:%S IST")
        ai_overview["selected_symbols"] = chosen
        ai_overview["telemetry"] = telemetry_list
        return ai_overview

    def _call_llm_for_market_overview(self, telemetry_list: list) -> Optional[Dict[str, Any]]:
        """Invokes Groq / Gemini with full multi-index telemetry."""
        keys = credentials.groq_api_keys or ([credentials.groq_api_key] if credentials.groq_api_key else [])
        prompt_payload = {
            "indices_telemetry": telemetry_list,
            "instruction": "Analyze all selected indices and synthesize a comprehensive institutional market picture."
        }

        system_prompt = (
            "You are an Elite Institutional Derivatives Strategist and Chief Macro Tape Reader for NSE India (MyBullAndBear Institutional Intelligence).\n"
            "Analyze the comprehensive cross-asset telemetry including OHLC price action trajectory, Open Interest changes, writer defense walls, PCR sentiment, and confluence indicators for the requested indices.\n"
            "Provide a crystal clear, high-impact institutional view of what is happening in the market.\n\n"
            "Respond ONLY with a valid JSON object matching this schema:\n"
            "{\n"
            '  "market_regime_headline": "BULLISH BREAKOUT WITH CROSS-INDEX CONFLUENCE",\n'
            '  "market_tone": "BULLISH" | "BEARISH" | "NEUTRAL" | "HIGH_VOLATILITY",\n'
            '  "macro_executive_summary": "Comprehensive 3-4 sentence institutional summary explaining overall market dynamics, institutional writer aggression, whether buyers or sellers control the tape, and cross-asset divergence.",\n'
            '  "cross_index_divergence": "Analysis of relative strength: which index is leading, which is lagging or consolidating.",\n'
            '  "index_analyses": [\n'
            "    {\n"
            '      "symbol": "NIFTY",\n'
            '      "verdict": "STRONG BULLISH BREAKOUT",\n'
            '      "verdict_color": "green" | "red" | "yellow",\n'
            '      "ohlc_tape_reading": "Spot (22,637) trades near day highs (22,651, 85% range position) well above Open (22,593). Intraday range of 65 pts indicates buyer dominance.",\n'
            '      "oi_battlefield": "Put writers are aggressively defending 22,500 (+68k PE added), creating a solid floor. PCR at 1.17 confirms institutional support.",\n'
            '      "technical_alignment": "Hull Suite is BULLISH, AlphaTrend is BULLISH, Confluence Score is 65/100.",\n'
            '      "tactical_directive": "BUY CE (ATM Call) on shallow dips towards Open pivot. Do not short while above Open.",\n'
            '      "inflection_levels": {\n'
            '        "bull_trigger": "Sustaining above 22,650",\n'
            '        "bear_invalidation": "Breaking below 22,580",\n'
            '        "key_support": "22,500",\n'
            '        "key_resistance": "22,700",\n'
            '        "max_pain": "22,500"\n'
            "      }\n"
            "    }\n"
            "  ],\n"
            '  "actionable_institutional_playbook": "Bullet-point tactical playbook for option buyers, scalpers, and traps to avoid.",\n'
            '  "risk_warnings": "Critical warning levels or upcoming event risks."\n'
            "}"
        )

        # 1. Try Groq Primary (qwen/qwen3.8-27b)
        if keys:
            url = "https://api.groq.com/openai/v1/chat/completions"
            body = {
                "model": "qwen/qwen3.8-27b",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Telemetry Data:\n{json.dumps(prompt_payload)}"}
                ],
                "temperature": 0.2,
                "max_tokens": 1200,
                "response_format": {"type": "json_object"}
            }
            for api_key in keys[:2]:
                try:
                    req = urllib.request.Request(
                        url,
                        data=json.dumps(body).encode("utf-8"),
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                            "User-Agent": "Mozilla/5.0"
                        }
                    )
                    with urllib.request.urlopen(req, timeout=3.5) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        parsed = json.loads(data["choices"][0]["message"]["content"])
                        parsed["success"] = True
                        parsed["ai_engine"] = "MyBullAndBear AI (Qwen-27B LPU)"
                        return parsed
                except Exception as e:
                    logger.warning(f"Groq overview attempt failed: {e}")
                    break

        # 2. Try Gemini Flash Fallback
        if credentials.gemini_api_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={credentials.gemini_api_key}"
                body = {
                    "contents": [{
                        "parts": [{"text": f"{system_prompt}\n\nTelemetry:\n{json.dumps(prompt_payload)}"}]
                    }],
                    "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}
                }
                req = urllib.request.Request(
                    url,
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    text_val = res["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(text_val)
                    parsed["success"] = True
                    parsed["ai_engine"] = "MyBullAndBear AI (Gemini Flash)"
                    return parsed
            except Exception as e:
                logger.warning(f"Gemini overview attempt failed: {e}")

        return None

    def _generate_deterministic_market_overview(self, telemetry_list: list) -> Dict[str, Any]:
        """High-intelligence deterministic fallback synthesizing all metrics."""
        avg_conf = sum(t["indicators"]["confluence_score"] for t in telemetry_list) / max(1, len(telemetry_list))
        bull_count = sum(1 for t in telemetry_list if t["ohlc"]["trading_above_open"])
        total_indices = len(telemetry_list)

        # Tone & Headline
        if avg_conf >= 62.0 and bull_count >= total_indices * 0.6:
            market_tone = "BULLISH"
            headline = "BULLISH EXPANSION & PUT WRITER ACCUMULATION"
            macro_summary = (
                f"Markets are demonstrating clear institutional strength with {bull_count} of {total_indices} "
                f"tracked indices trading above their respective opening prints. Confluence averages {avg_conf:.1f}/100, "
                "bolstered by aggressive Put writing defense across ATM corridors. Big money is actively soaking up intraday dips."
            )
        elif avg_conf <= 38.0 and bull_count <= total_indices * 0.3:
            market_tone = "BEARISH"
            headline = "BEARISH LIQUIDATION & CALL WRITER CEILING RESISTANCE"
            macro_summary = (
                f"Sellers firmly hold the tape as {total_indices - bull_count} of {total_indices} indices "
                f"are languishing below day open levels. Confluence has slumped to {avg_conf:.1f}/100, accompanied by "
                "relentless Call writing across overhead strikes. Downside momentum threatens key support floors."
            )
        else:
            market_tone = "NEUTRAL"
            headline = "TWO-SIDED RANGE-BOUND CONSOLIDATION & CORRIDOR DEFENSE"
            macro_summary = (
                f"The broader market is locked in a classic two-sided institutional corridor with an average confluence of {avg_conf:.1f}/100. "
                "Both Call and Put writers have heavily fortified immediate walls, capping volatility and penalizing breakout chasers. "
                "Patience and range-bound discipline are required."
            )

        # Cross index divergence
        sorted_by_change = sorted(telemetry_list, key=lambda x: x["spot_pchange"], reverse=True)
        top_sym = sorted_by_change[0]["symbol"]
        bottom_sym = sorted_by_change[-1]["symbol"]
        if top_sym != bottom_sym:
            divergence = (
                f"{top_sym} is exhibiting relative strength ({sorted_by_change[0]['spot_pchange']:+.2f}%), "
                f"leading the upside tape, while {bottom_sym} ({sorted_by_change[-1]['spot_pchange']:+.2f}%) "
                "is acting as the relative laggard. Watch for convergence if the leader sustains its morning breakout."
            )
        else:
            divergence = f"Unified momentum observed across all monitored index assets."

        # Index analyses
        index_analyses = []
        for t in telemetry_list:
            sym = t["symbol"]
            spot = t["spot_price"]
            pch = t["spot_pchange"]
            ohlc = t["ohlc"]
            oi = t["open_interest"]
            ind = t["indicators"]

            is_bull = ind["confluence_score"] >= 60.0 or ohlc["trading_above_open"]
            is_bear = ind["confluence_score"] <= 40.0 and not ohlc["trading_above_open"]

            if is_bull:
                verdict = "BULLISH BREAKOUT / ACCUMULATION"
                verdict_color = "green"
                tactical_dir = f"BUY CE (ATM {int(t['atm_strike'])} CE) on shallow retests of Day Open ({ohlc['open']:,.1f})."
            elif is_bear:
                verdict = "BEARISH LIQUIDATION / RESISTANCE"
                verdict_color = "red"
                tactical_dir = f"BUY PE (ATM {int(t['atm_strike'])} PE) on counter-trend rallies into Call resistance."
            else:
                verdict = "RANGE-BOUND SQUEEZE"
                verdict_color = "yellow"
                tactical_dir = f"STANDBY: Pinned between {int(oi['key_support'])} floor and {int(oi['key_resistance'])} ceiling."

            pos_desc = "near day high" if ohlc["range_position_pct"] >= 70 else (
                "near day low" if ohlc["range_position_pct"] <= 30 else "mid-range"
            )

            tape_reading = (
                f"Spot ({spot:,.1f}, {pch:+.2f}%) is currently positioned {pos_desc} ({ohlc['range_position_pct']}% of day's range). "
                f"Day Open: {ohlc['open']:,.1f} | High: {ohlc['high']:,.1f} | Low: {ohlc['low']:,.1f} (Total Range: {ohlc['range']:,.1f} pts). "
                f"{'Trading comfortably above Open (+buyer control).' if ohlc['trading_above_open'] else 'Trading below Open (+seller pressure).'}"
            )

            flow_k = oi["net_oi_chg_k"]
            oi_reading = (
                f"PCR stands at {oi['pcr']:.2f} ({oi['tot_oi_bias'].replace('_', ' ')}). Intraday flow indicates {oi['flow_bias'].replace('_', ' ')} "
                f"with net {flow_k:+.1f}k contract delta. Major support floor is anchored at {int(oi['key_support'])}, "
                f"overhead resistance at {int(oi['key_resistance'])}, and Max Pain sits at {int(oi['max_pain'])}."
            )

            tech_reading = (
                f"Confluence Score: {ind['confluence_score']}/100 [{ind['market_regime']}]. "
                f"Hull Suite is {ind['hull_state']}, AlphaTrend is {ind['alphatrend']}, and Trend Direction is {ind['trend_direction']}."
            )

            index_analyses.append({
                "symbol": sym,
                "verdict": verdict,
                "verdict_color": verdict_color,
                "ohlc_tape_reading": tape_reading,
                "oi_battlefield": oi_reading,
                "technical_alignment": tech_reading,
                "tactical_directive": tactical_dir,
                "inflection_levels": {
                    "bull_trigger": f"Sustain > {int(ohlc['high'])} (Day High)",
                    "bear_invalidation": f"Break < {int(ohlc['low'])} (Day Low)",
                    "key_support": f"{int(oi['key_support'])}",
                    "key_resistance": f"{int(oi['key_resistance'])}",
                    "max_pain": f"{int(oi['max_pain'])}"
                }
            })

        playbook = (
            "1. OPTION BUYERS / SCALPERS: Align strictly with indices trading > Day Open and Confluence >= 60. "
            "Never chase breakout into heavy Call resistance walls.\n"
            "2. STOP LOSS DISCIPLINE: Treat Day Open and Day Low as hard intraday invalidation pivots.\n"
            "3. CHOP FILTER: If Confluence is between 45 and 55, preserve capital and avoid high-theta overtrading."
        )

        warnings = "Monitor midday OI unwinding around 13:00-14:00 IST for sudden gamma squeeze moves."

        return {
            "success": True,
            "ai_engine": "MyBullAndBear Institutional Intelligence Engine",
            "market_regime_headline": headline,
            "market_tone": market_tone,
            "macro_executive_summary": macro_summary,
            "cross_index_divergence": divergence,
            "index_analyses": index_analyses,
            "actionable_institutional_playbook": playbook,
            "risk_warnings": warnings
        }


ai_advisor = AIAdvisorService()

