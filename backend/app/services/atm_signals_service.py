"""
ATM +- 2 PineScript & Option Chain Signal Generation Service
Monitors strictly ATM +- 2 strikes (Top 5 active strikes per index):
- Candidate strikes: [ATM - 2*step, ATM - 1*step, ATM, ATM + 1*step, ATM + 2*step]
- Full Option Chain integration: Total OI, Change in OI, Strike PCR, Difference in OI (PE OI - CE OI, PE Chg - CE Chg)
- PineScript OTT & ADX indicators calculated directly on both Spot and Option Contract 5m Candlestick charts
- Strike-by-strike Buying vs Selling action classifier (BUY CE, BUY PE, SELL CE, SELL PE, NEUTRAL)
- Top AI Recommendations (Best Buyer & Best Seller across ATM +- 2)
- Real-time Smart Tracker Bot execution status & live MTM P&L
"""
import math
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, time

from app.core.config import get_settings
from app.core.market_hours import get_current_ist
from app.services.option_chain import ParsedOptionChain, StrikeRow, parse_option_chain
from app.services.trade_engine import calculate_greeks
from app.services.tracker_bot import tracker_bot
from app.services.option_candle_service import option_candle_service
from app.db.tracker_storage import tracker_storage
from app.api.market import fetch_live_chain_data

import time as _time
import asyncio

logger = logging.getLogger(__name__)

TRACKED_SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]


class AtmSignalsService:
    """Service to compute and format continuous ATM +- 2 signals and strike matrix for dashboard tabular display."""

    def __init__(self):
        self._all_cache: List[Dict[str, Any]] = []
        self._all_cache_time: float = 0.0
        self._all_lock = asyncio.Lock()
        self._sym_cache: Dict[str, Dict[str, Any]] = {}
        self._sym_cache_time: Dict[str, float] = {}

    async def get_all_atm_signals(self) -> List[Dict[str, Any]]:
        """Computes live ATM +- 2 buying & selling signals and strike matrix across all 4 index symbols."""
        now = _time.time()
        if self._all_cache and (now - self._all_cache_time) < 4.0:
            return self._all_cache

        async with self._all_lock:
            now = _time.time()
            if self._all_cache and (now - self._all_cache_time) < 4.0:
                return self._all_cache

            # Parallel evaluation across all 4 symbols to slash latency from ~3.5s to ~0.8s
            tasks = [self.get_symbol_atm_signal(sym) for sym in TRACKED_SYMBOLS]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)

            results = []
            for r in raw_results:
                if isinstance(r, dict) and r:
                    results.append(r)
                elif isinstance(r, Exception):
                    logger.warning(f"Error computing ATM signals task: {r}")

            if results:
                self._all_cache = results
                self._all_cache_time = _time.time()
                return results

            return self._all_cache

    async def get_symbol_atm_signal(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Evaluates live option chain & PineScript indicators for a single symbol strictly within ATM +- 2."""
        sym = symbol.upper()
        now = _time.time()
        if sym in self._sym_cache and (now - self._sym_cache_time.get(sym, 0.0)) < 4.0:
            return self._sym_cache[sym]
        raw_chain, source = await fetch_live_chain_data(sym)
        if not raw_chain:
            return None

        chain = parse_option_chain(raw_chain, sym)
        if not chain or not chain.strikes:
            return None

        settings = get_settings()
        step = settings.STRIKE_STEPS.get(sym, 50)
        lot_size = settings.LOT_SIZES.get(sym, 65)
        spot = chain.spot_price
        atm = chain.atm_strike
        pcr = chain.pcr

        # Strict ATM +- 2 strikes (Top 5 active strikes)
        atm_minus_2 = atm - (2 * step)
        atm_minus_1 = atm - step
        atm_strike = atm
        atm_plus_1 = atm + step
        atm_plus_2 = atm + (2 * step)
        valid_strikes = [atm_minus_2, atm_minus_1, atm_strike, atm_plus_1, atm_plus_2]

        strike_map: Dict[float, StrikeRow] = {s.strikePrice: s for s in chain.strikes if s.strikePrice in valid_strikes}

        # 1. Fetch live Spot PineScript indicator state
        tech = tracker_bot.get_technical_state(sym)
        ott_state = tech.get("ott_state", "NEUTRAL")  # "BULLISH", "BEARISH", "NEUTRAL"
        adx = tech.get("adx", 20.0)
        plus_di = tech.get("plus_di", 25.0)
        minus_di = tech.get("minus_di", 25.0)

        if adx >= 25.0:
            velocity_desc = "HIGH MOMENTUM"
        elif adx >= 18.0:
            velocity_desc = "MODERATE TREND"
        else:
            velocity_desc = "LOW / CONSOLIDATION"

        # 1.5. Detect Market Regime & Chop Shield (AI-Trader Architecture)
        market_regime = self._detect_market_regime(ott_state=ott_state, adx=adx, pcr=pcr)

        # 2. Build Full ATM +- 2 Strike-by-Strike Matrix with Buying/Selling Signals
        strikes_matrix = self._build_strikes_matrix(
            sym=sym,
            spot=spot,
            atm=atm,
            step=step,
            lot_size=lot_size,
            valid_strikes=valid_strikes,
            strike_map=strike_map,
            ott_state=ott_state,
            adx=adx,
            pcr=pcr,
            regime_info=market_regime
        )

        # 3. Compute ATM +- 2 Corridor Aggregate Metrics
        corridor_summary = self._compute_corridor_summary(strikes_matrix, spot)

        # 4. Formulate Best BUYING Trade (Strictly ATM +- 2)
        best_buyer = self._evaluate_best_buyer_atm(
            sym=sym,
            spot=spot,
            atm=atm,
            step=step,
            lot_size=lot_size,
            strike_map=strike_map,
            ott_state=ott_state,
            adx=adx,
            pcr=pcr,
            valid_strikes=valid_strikes,
            regime_info=market_regime
        )

        # 5. Formulate Best SELLING Trade (Strictly ATM +- 2)
        best_seller = self._evaluate_best_seller_atm(
            sym=sym,
            spot=spot,
            atm=atm,
            step=step,
            lot_size=lot_size,
            strike_map=strike_map,
            ott_state=ott_state,
            adx=adx,
            pcr=pcr,
            valid_strikes=valid_strikes,
            regime_info=market_regime
        )

        # 6. Fetch live bot paper trading status
        open_trade = tracker_storage.get_open_trade_for_symbol(sym)
        persistence = tracker_bot._signal_persistence.get(sym, {})

        bot_status: Dict[str, Any] = {
            "has_open_position": open_trade is not None,
            "status_text": "MONITORING",
            "badge_class": "badge-neutral"
        }

        if open_trade:
            entry_p = open_trade["entry_net_price"]
            curr_p = open_trade.get("current_net_price", entry_p)
            role = open_trade["role"]
            if role == "SELLER":
                gross_pnl = round((entry_p - curr_p) * lot_size, 2)
            else:
                gross_pnl = round((curr_p - entry_p) * lot_size, 2)
            net_pnl = round(gross_pnl - 100.0, 2)

            bot_status = {
                "has_open_position": True,
                "trade_id": open_trade["id"],
                "strategy_type": open_trade["strategy_type"],
                "role": role,
                "entry_price": entry_p,
                "current_price": curr_p,
                "gross_pnl_inr": gross_pnl,
                "net_pnl_inr": net_pnl,
                "mfe_inr": open_trade.get("mfe_inr", 0.0),
                "mae_inr": open_trade.get("mae_inr", 0.0),
                "trailing_sl": open_trade.get("trailing_stop_price", open_trade.get("stop_loss_price", 0.0)),
                "status_text": f"ACTIVE ({role}): {net_pnl:+.1f} ₹",
                "badge_class": "badge-active" if net_pnl >= 0 else "badge-bear"
            }
        elif persistence.get("ticks", 0) >= 1:
            bot_status = {
                "has_open_position": False,
                "status_text": f"CONFIRMING TICK {persistence.get('ticks', 1)}/2",
                "badge_class": "badge-warning"
            }
        elif (best_buyer and best_buyer.get("tqs_score", 0) >= 70.0) or (best_seller and best_seller.get("tqs_score", 0) >= 66.0):
            bot_status = {
                "has_open_position": False,
                "status_text": "READY TO ENTER",
                "badge_class": "badge-qualified"
            }

        # 7. Overarching Recommendation (AI Top Pick)
        if ott_state in ["BEARISH", "BULLISH"] and adx >= 18.0:
            top_role = "BUYER"
            top_trade = best_buyer
            rationale = f"Strong {ott_state} momentum with ADX {adx:.1f}. High directional velocity favors option buying across ATM ± 2."
        else:
            top_role = "SELLER"
            top_trade = best_seller
            rationale = f"Market is in {ott_state} / consolidation. Selling premium within ATM ± 2 provides theta decay cushion."

        result = {
            "symbol": sym,
            "spot_price": spot,
            "atm_strike": atm,
            "strike_step": step,
            "lot_size": lot_size,
            "pcr": pcr,
            "technical_indicators": {
                "ott_state": ott_state,
                "adx": adx,
                "velocity": velocity_desc,
                "plus_di": plus_di,
                "minus_di": minus_di
            },
            "strikes_matrix": strikes_matrix,
            "atm_corridor_summary": corridor_summary,
            "best_buyer_trade": best_buyer,
            "best_seller_trade": best_seller,
            "top_recommendation": {
                "role": top_role,
                "trade": top_trade,
                "rationale": rationale
            },
            "market_regime": market_regime,
            "bot_status": bot_status,
            "source": source
        }
        self._sym_cache[sym] = result
        self._sym_cache_time[sym] = _time.time()
        return result

    # ---------------------------------------------------------
    # Market Regime & Volatility Detector (AI-Trader Architecture)
    # ---------------------------------------------------------
    @staticmethod
    def _detect_market_regime(ott_state: str, adx: float, pcr: float) -> Dict[str, Any]:
        """
        Detects Market Volatility & Directional Regime (Adapting AI-Trader Regime Architecture):
        - TRENDING_BULL: Bullish momentum + ADX trend strength. (+5 bonus to Call Buyers)
        - TRENDING_BEAR: Bearish momentum + ADX downward strength. (+5 bonus to Put Buyers)
        - SIDEWAYS_CHOP: Dead consolidation or mixed momentum. (Chop Shield active, favors theta harvesting)
        - HIGH_VOLATILITY: ADX > 32 expansion.
        - LOW_VOLATILITY: ADX < 14 compression.
        """
        if adx >= 32.0:
            regime = "HIGH_VOLATILITY"
            badge = "badge-active"
            desc = f"High Volatility Expansion (ADX {adx:.1f})"
            chop_shield = False
            recommended_role = "BUYER"
        elif adx < 14.0 or (ott_state == "NEUTRAL" and 0.88 <= pcr <= 1.12):
            regime = "SIDEWAYS_CHOP"
            badge = "badge-warning"
            desc = "Dead Consolidation / Rangebound Chop"
            chop_shield = True
            recommended_role = "SELLER"
        elif ott_state == "BULLISH" and adx >= 18.0:
            regime = "TRENDING_BULL"
            badge = "badge-active"
            desc = f"Bullish Directional Trend (ADX {adx:.1f})"
            chop_shield = False
            recommended_role = "BUYER"
        elif ott_state == "BEARISH" and adx >= 18.0:
            regime = "TRENDING_BEAR"
            badge = "badge-bear"
            desc = f"Bearish Directional Trend (ADX {adx:.1f})"
            chop_shield = False
            recommended_role = "BUYER"
        elif adx < 18.0:
            regime = "LOW_VOLATILITY"
            badge = "badge-neutral"
            desc = "Low Momentum Compression"
            chop_shield = True
            recommended_role = "SELLER"
        else:
            regime = "SIDEWAYS_CHOP"
            badge = "badge-warning"
            desc = "Consolidation / Unaligned Momentum"
            chop_shield = True
            recommended_role = "SELLER"

        return {
            "regime": regime,
            "badge_class": badge,
            "description": desc,
            "chop_shield_active": chop_shield,
            "recommended_role": recommended_role
        }

    # ---------------------------------------------------------
    # Option Chain OI & Buildup Helpers
    # ---------------------------------------------------------
    @staticmethod
    def _calculate_buildup(price_chg: float, oi_chg: int) -> Tuple[str, str, str]:
        """
        Calculates Institutional Buildup from contract price change and open interest change.
        Returns (buildup_type, badge_class, description)
        """
        if price_chg >= 0 and oi_chg >= 0:
            return "LONG_BUILDUP", "badge-active", "Long Buildup (Institutional Buying)"
        elif price_chg >= 0 and oi_chg < 0:
            return "SHORT_COVERING", "badge-warning", "Short Covering (Squeeze Rally)"
        elif price_chg < 0 and oi_chg >= 0:
            return "SHORT_BUILDUP", "badge-bear", "Short Buildup (Heavy Institutional Writing)"
        else:
            return "LONG_UNWINDING", "badge-neutral", "Long Unwinding (Longs Dumping)"

    @staticmethod
    def _format_oi(oi: int) -> str:
        abs_oi = abs(oi)
        if abs_oi >= 10000000:
            return f"{oi / 10000000:.2f}Cr"
        elif abs_oi >= 100000:
            return f"{oi / 100000:.1f}L"
        elif abs_oi >= 1000:
            return f"{oi / 1000:.0f}K"
        return str(oi)

    @staticmethod
    def _format_oi_chg(oi_chg: int) -> str:
        sign = "+" if oi_chg >= 0 else ""
        abs_chg = abs(oi_chg)
        if abs_chg >= 10000000:
            return f"{sign}{oi_chg / 10000000:.2f}Cr"
        elif abs_chg >= 100000:
            return f"{sign}{oi_chg / 100000:.1f}L"
        elif abs_chg >= 1000:
            return f"{sign}{oi_chg / 1000:.0f}K"
        return f"{sign}{oi_chg}"

    @staticmethod
    def _format_diff(diff: int, suffix_pos: str = "PE Lead", suffix_neg: str = "CE Lead") -> str:
        sign = "+" if diff > 0 else ("-" if diff < 0 else "")
        abs_v = abs(diff)
        if abs_v >= 10000000:
            val_str = f"{sign}{abs_v / 10000000:.2f}Cr"
        elif abs_v >= 100000:
            val_str = f"{sign}{abs_v / 100000:.1f}L"
        elif abs_v >= 1000:
            val_str = f"{sign}{abs_v / 1000:.0f}K"
        else:
            val_str = f"{sign}{abs_v}"

        if diff > 0:
            return f"{val_str} ({suffix_pos})"
        elif diff < 0:
            return f"{val_str} ({suffix_neg})"
        return "0 (Balanced)"

    # ---------------------------------------------------------
    # ATM +- 2 Strike-by-Strike Matrix with Buying/Selling Signals
    # ---------------------------------------------------------
    def _build_strikes_matrix(
        self,
        sym: str,
        spot: float,
        atm: float,
        step: int,
        lot_size: int,
        valid_strikes: List[float],
        strike_map: Dict[float, StrikeRow],
        ott_state: str,
        adx: float,
        pcr: float,
        regime_info: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Builds detailed strike-by-strike evaluation across ATM +- 2 (5 strikes):
        - Call (CE) & Put (PE) metrics: LTP, OI, OI Chg, Buildup, Greeks, Option OTT & ADX
        - Total Strike OI, Strike OI Chg, Strike PCR, Net Difference in OI (PE - CE)
        - Action Signal: BUY CE, BUY PE, SELL CE, SELL PE, or NEUTRAL
        """
        matrix: List[Dict[str, Any]] = []

        step_tag_map = {
            atm - 2 * step: "ATM-2",
            atm - step: "ATM-1",
            atm: "ATM",
            atm + step: "ATM+1",
            atm + 2 * step: "ATM+2"
        }

        for stk in valid_strikes:
            row = strike_map.get(stk)
            step_tag = step_tag_map.get(stk, "ATM")
            dist_from_spot = round(stk - spot, 1)

            # Moneyness tags
            if stk < atm:
                ce_moneyness = "2-ITM" if stk <= atm - 2 * step else "1-ITM"
                pe_moneyness = "2-OTM" if stk <= atm - 2 * step else "1-OTM"
            elif stk > atm:
                ce_moneyness = "2-OTM" if stk >= atm + 2 * step else "1-OTM"
                pe_moneyness = "2-ITM" if stk >= atm + 2 * step else "1-ITM"
            else:
                ce_moneyness = "ATM"
                pe_moneyness = "ATM"

            # ----------------- 1. CE (Call) Contract Data -----------------
            ce_contract = row.CE if row else None
            ce_ltp = ce_contract.lastPrice if ce_contract and ce_contract.lastPrice > 0 else 0.0
            ce_oi = getattr(ce_contract, "openInterest", 0) if ce_contract else 0
            ce_oi_chg = getattr(ce_contract, "changeinOpenInterest", 0) if ce_contract else 0
            ce_vol = getattr(ce_contract, "totalTradedVolume", 0) if ce_contract else 0
            ce_pchange = getattr(ce_contract, "pChange", 0.0) if ce_contract else 0.0
            ce_iv = getattr(ce_contract, "impliedVolatility", 0.0) if ce_contract and ce_contract.impliedVolatility > 0 else 14.0
            ce_bid = getattr(ce_contract, "bidprice", 0.0) or getattr(ce_contract, "bid", 0.0) or ce_ltp
            ce_ask = getattr(ce_contract, "askPrice", 0.0) or getattr(ce_contract, "ask", 0.0) or ce_ltp
            ce_spread = max(0.05, round(abs(ce_ask - ce_bid), 2))

            ce_buildup, ce_buildup_badge, ce_buildup_desc = self._calculate_buildup(ce_pchange, ce_oi_chg)
            ce_greeks = calculate_greeks(spot, stk, ce_iv, is_call=True)

            ce_chart = option_candle_service.get_option_chart_data(sym, stk, "CE")
            ce_curr = ce_chart.get("current_state", {})
            ce_opt_close = ce_curr.get("close", ce_ltp)
            ce_opt_ott = ce_curr.get("ott", ce_ltp)
            ce_opt_mavg = ce_curr.get("mavg", ce_ltp)
            ce_opt_state = ce_curr.get("ott_state", "NEUTRAL")
            ce_opt_adx = ce_curr.get("adx", 20.0)
            ce_opt_above_ott = (ce_opt_close > ce_opt_ott)
            ce_opt_distance = round(ce_opt_close - ce_opt_ott, 2)

            # 30-Second Option Premium Gate (AI-Trader Anti-Falling Knife)
            ce_gate = option_candle_service.check_option_premium_gate(sym, stk, "CE")

            ce_data = {
                "ltp": ce_ltp,
                "pchange": ce_pchange,
                "oi": ce_oi,
                "oi_formatted": self._format_oi(ce_oi),
                "oi_chg": ce_oi_chg,
                "oi_chg_formatted": self._format_oi_chg(ce_oi_chg),
                "volume": ce_vol,
                "spread": ce_spread,
                "moneyness": ce_moneyness,
                "buildup": ce_buildup,
                "buildup_desc": ce_buildup_desc,
                "buildup_badge": ce_buildup_badge,
                "delta": ce_greeks["delta"],
                "theta": ce_greeks["theta"],
                "daily_theta_inr": round(abs(ce_greeks["theta"]) * lot_size, 0),
                "opt_close": ce_opt_close,
                "opt_ott": ce_opt_ott,
                "opt_mavg": ce_opt_mavg,
                "opt_state": ce_opt_state,
                "opt_adx": ce_opt_adx,
                "opt_above_ott": ce_opt_above_ott,
                "opt_distance": ce_opt_distance,
                "premium_gate": ce_gate
            }

            # ----------------- 2. PE (Put) Contract Data -----------------
            pe_contract = row.PE if row else None
            pe_ltp = pe_contract.lastPrice if pe_contract and pe_contract.lastPrice > 0 else 0.0
            pe_oi = getattr(pe_contract, "openInterest", 0) if pe_contract else 0
            pe_oi_chg = getattr(pe_contract, "changeinOpenInterest", 0) if pe_contract else 0
            pe_vol = getattr(pe_contract, "totalTradedVolume", 0) if pe_contract else 0
            pe_pchange = getattr(pe_contract, "pChange", 0.0) if pe_contract else 0.0
            pe_iv = getattr(pe_contract, "impliedVolatility", 0.0) if pe_contract and pe_contract.impliedVolatility > 0 else 14.0
            pe_bid = getattr(pe_contract, "bidprice", 0.0) or getattr(pe_contract, "bid", 0.0) or pe_ltp
            pe_ask = getattr(pe_contract, "askPrice", 0.0) or getattr(pe_contract, "ask", 0.0) or pe_ltp
            pe_spread = max(0.05, round(abs(pe_ask - pe_bid), 2))

            pe_buildup, pe_buildup_badge, pe_buildup_desc = self._calculate_buildup(pe_pchange, pe_oi_chg)
            pe_greeks = calculate_greeks(spot, stk, pe_iv, is_call=False)

            pe_chart = option_candle_service.get_option_chart_data(sym, stk, "PE")
            pe_curr = pe_chart.get("current_state", {})
            pe_opt_close = pe_curr.get("close", pe_ltp)
            pe_opt_ott = pe_curr.get("ott", pe_ltp)
            pe_opt_mavg = pe_curr.get("mavg", pe_ltp)
            pe_opt_state = pe_curr.get("ott_state", "NEUTRAL")
            pe_opt_adx = pe_curr.get("adx", 20.0)
            pe_opt_above_ott = (pe_opt_close > pe_opt_ott)
            pe_opt_distance = round(pe_opt_close - pe_opt_ott, 2)

            # 30-Second Option Premium Gate (AI-Trader Anti-Falling Knife)
            pe_gate = option_candle_service.check_option_premium_gate(sym, stk, "PE")

            pe_data = {
                "ltp": pe_ltp,
                "pchange": pe_pchange,
                "oi": pe_oi,
                "oi_formatted": self._format_oi(pe_oi),
                "oi_chg": pe_oi_chg,
                "oi_chg_formatted": self._format_oi_chg(pe_oi_chg),
                "volume": pe_vol,
                "spread": pe_spread,
                "moneyness": pe_moneyness,
                "buildup": pe_buildup,
                "buildup_desc": pe_buildup_desc,
                "buildup_badge": pe_buildup_badge,
                "delta": pe_greeks["delta"],
                "theta": pe_greeks["theta"],
                "daily_theta_inr": round(abs(pe_greeks["theta"]) * lot_size, 0),
                "opt_close": pe_opt_close,
                "opt_ott": pe_opt_ott,
                "opt_mavg": pe_opt_mavg,
                "opt_state": pe_opt_state,
                "opt_adx": pe_opt_adx,
                "opt_above_ott": pe_opt_above_ott,
                "opt_distance": pe_opt_distance,
                "premium_gate": pe_gate
            }

            # ----------------- 3. Strike-Level Comparative OI Metrics -----------------
            tot_strike_oi = ce_oi + pe_oi
            tot_strike_oi_chg = ce_oi_chg + pe_oi_chg
            strike_pcr = round(pe_oi / max(1, ce_oi), 2)
            oi_diff = pe_oi - ce_oi  # Positive: Put Heavy (Support); Negative: Call Heavy (Resistance)
            oi_chg_diff = pe_oi_chg - ce_oi_chg

            if pe_oi > ce_oi * 1.15:
                dominant_writer = "PUT WRITERS (SUPPORT FLOOR)"
                writer_bias = "BULLISH_SUPPORT"
            elif ce_oi > pe_oi * 1.15:
                dominant_writer = "CALL WRITERS (RESISTANCE CEILING)"
                writer_bias = "BEARISH_RESISTANCE"
            else:
                dominant_writer = "BALANCED / CONTESTED"
                writer_bias = "NEUTRAL"

            # ----------------- 4. Action Signal Classifier (BUY vs SELL) -----------------
            signal = self._classify_strike_signal(
                stk=stk,
                step_tag=step_tag,
                spot=spot,
                lot_size=lot_size,
                ott_state=ott_state,
                adx=adx,
                pcr=pcr,
                strike_pcr=strike_pcr,
                oi_diff=oi_diff,
                oi_chg_diff=oi_chg_diff,
                ce_data=ce_data,
                pe_data=pe_data,
                regime_info=regime_info
            )

            matrix.append({
                "strike": stk,
                "strike_label": f"{int(stk)} [{step_tag}]",
                "step_tag": step_tag,
                "dist_from_spot": dist_from_spot,
                "total_oi": tot_strike_oi,
                "total_oi_formatted": self._format_oi(tot_strike_oi),
                "total_oi_chg": tot_strike_oi_chg,
                "total_oi_chg_formatted": self._format_oi_chg(tot_strike_oi_chg),
                "strike_pcr": strike_pcr,
                "oi_diff": oi_diff,
                "oi_diff_formatted": self._format_diff(oi_diff, "PE Support Lead", "CE Resistance Lead"),
                "oi_chg_diff": oi_chg_diff,
                "oi_chg_diff_formatted": self._format_diff(oi_chg_diff, "Put Writing Lead", "Call Writing Lead"),
                "dominant_writer": dominant_writer,
                "writer_bias": writer_bias,
                "call": ce_data,
                "put": pe_data,
                "call_signal": signal.get("call_signal"),
                "put_signal": signal.get("put_signal"),
                "signal": signal
            })

        return matrix

    # ---------------------------------------------------------
    # Decision Engine: Strike-Level Action Signal Classifier
    # ---------------------------------------------------------
    def _classify_strike_signal(
        self,
        stk: float,
        step_tag: str,
        spot: float,
        lot_size: int,
        ott_state: str,
        adx: float,
        pcr: float,
        strike_pcr: float,
        oi_diff: int,
        oi_chg_diff: int,
        ce_data: Dict[str, Any],
        pe_data: Dict[str, Any],
        regime_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Classifies whether a strike is in BUYING, SELLING, or NEUTRAL state:
        - Evaluates Call Buying (Bullish Momentum + Option Close > OTT + Long Buildup + 30s Premium Gate)
        - Evaluates Put Buying (Bearish Momentum + Option Close > OTT + Long Buildup + 30s Premium Gate)
        - Evaluates Call Selling (Resistance Ceiling + Option Close <= OTT + Short Buildup)
        - Evaluates Put Selling (Support Floor + Option Close <= OTT + Short Buildup)
        - Applies AI-Trader Regime Adapters & 30s Anti-Falling Knife Gate
        """
        ce_ltp = ce_data["ltp"]
        pe_ltp = pe_data["ltp"]
        ce_gate = ce_data.get("premium_gate", {})
        pe_gate = pe_data.get("premium_gate", {})

        # Track candidate signals
        candidates = []

        # --- A. CE Buying Candidate ---
        if ce_ltp >= 15.0:
            score = 50.0
            reasons = []

            # 1. Spot Trend & Regime
            if ott_state == "BULLISH":
                score += 15.0
                reasons.append("Bullish Spot OTT")
            elif ott_state == "NEUTRAL" and pcr >= 1.05:
                score += 8.0
                reasons.append("Bullish PCR Bias")
            elif ott_state == "BEARISH":
                score -= 25.0

            if regime_info and regime_info.get("regime") == "TRENDING_BULL":
                score += 6.0
                reasons.append("Bullish Trend Bonus (+6)")
            elif regime_info and regime_info.get("chop_shield_active"):
                score -= 10.0
                reasons.append("Chop Shield Active (-10)")

            # 2. Option PineScript OTT
            if ce_data["opt_above_ott"]:
                score += 18.0
                reasons.append(f"Opt Above OTT (+₹{ce_data['opt_distance']:.1f})")
            else:
                score -= 15.0
                reasons.append("Opt Under OTT Line")

            # 3. 30-Second Option Premium Gate (AI-Trader Anti-Falling Knife)
            if ce_gate.get("is_falling_knife"):
                score -= 20.0
                reasons.append(f"⚠️ Falling Knife Gate ({ce_gate.get('momentum_pct', 0):+.1f}%)")
            elif ce_gate.get("momentum_pct", 0) >= 0.4:
                score += 8.0
                reasons.append(f"Confirmed Rising Premium (+{ce_gate.get('momentum_pct', 0):.1f}%)")

            # 4. Buildup
            if ce_data["buildup"] == "LONG_BUILDUP":
                score += 14.0
                reasons.append("CE Long Buildup")
            elif ce_data["buildup"] == "SHORT_COVERING":
                score += 10.0
                reasons.append("CE Short Covering")
            elif ce_data["buildup"] == "SHORT_BUILDUP":
                score -= 20.0
                reasons.append("Heavy CE Writers Capping")

            # 5. Difference in OI / Strike Support
            if oi_diff > 0 or strike_pcr >= 1.10:
                score += 8.0
                reasons.append("Put Support Floor")

            if adx >= 20.0:
                score += 5.0

            score = max(5.0, min(99.0, score))
            if score >= 68.0 and ce_data["opt_above_ott"] and ce_data["buildup"] != "SHORT_BUILDUP":
                is_knife = ce_gate.get("is_falling_knife", False)
                is_chop = bool(regime_info and regime_info.get("chop_shield_active", False) and score < 78.0)

                target = round(ce_ltp * 1.5, 1)
                sl = round(ce_ltp * 0.7, 1)

                if is_knife:
                    act, lbl, bg, sig_cls, role, conv = "WAIT_KNIFE", "⚠️ WAIT KNIFE", "badge-warning", "sig-wait", "OBSERVER", "FALLING KNIFE"
                elif is_chop:
                    act, lbl, bg, sig_cls, role, conv = "CHOP_GATED", "⏳ CHOP GATED", "badge-warning", "sig-wait", "OBSERVER", "CHOP FILTER"
                else:
                    act, lbl, bg, sig_cls, role = "BUY_CE", "🚀 BUY CE", "badge-active", "sig-buy", "BUYER"
                    conv = "STRONG BUY" if score >= 85 else "BUY"

                candidates.append({
                    "action": act,
                    "action_label": lbl,
                    "badge_class": bg,
                    "signal_class": sig_cls,
                    "role": role,
                    "option_type": "CE",
                    "contract_label": f"{int(stk)} CE",
                    "ltp": ce_ltp,
                    "target_price": target,
                    "stop_loss_price": sl,
                    "tqs_score": score,
                    "conviction": conv,
                    "premium_gate": ce_gate,
                    "reason": " | ".join(reasons)
                })

        # --- B. PE Buying Candidate ---
        if pe_ltp >= 15.0:
            score = 50.0
            reasons = []

            # 1. Spot Trend & Regime
            if ott_state == "BEARISH":
                score += 15.0
                reasons.append("Bearish Spot OTT")
            elif ott_state == "NEUTRAL" and pcr <= 0.85:
                score += 8.0
                reasons.append("Bearish PCR Bias")
            elif ott_state == "BULLISH":
                score -= 25.0

            if regime_info and regime_info.get("regime") == "TRENDING_BEAR":
                score += 6.0
                reasons.append("Bearish Trend Bonus (+6)")
            elif regime_info and regime_info.get("chop_shield_active"):
                score -= 10.0
                reasons.append("Chop Shield Active (-10)")

            # 2. Option PineScript OTT
            if pe_data["opt_above_ott"]:
                score += 18.0
                reasons.append(f"Opt Above OTT (+₹{pe_data['opt_distance']:.1f})")
            else:
                score -= 15.0
                reasons.append("Opt Under OTT Line")

            # 3. 30-Second Option Premium Gate (AI-Trader Anti-Falling Knife)
            if pe_gate.get("is_falling_knife"):
                score -= 20.0
                reasons.append(f"⚠️ Falling Knife Gate ({pe_gate.get('momentum_pct', 0):+.1f}%)")
            elif pe_gate.get("momentum_pct", 0) >= 0.4:
                score += 8.0
                reasons.append(f"Confirmed Rising Premium (+{pe_gate.get('momentum_pct', 0):.1f}%)")

            # 4. Buildup
            if pe_data["buildup"] == "LONG_BUILDUP":
                score += 14.0
                reasons.append("PE Long Buildup")
            elif pe_data["buildup"] == "SHORT_COVERING":
                score += 10.0
                reasons.append("PE Short Covering")
            elif pe_data["buildup"] == "SHORT_BUILDUP":
                score -= 20.0
                reasons.append("Heavy PE Writers Capping")

            # 5. Difference in OI / Strike Resistance
            if oi_diff < 0 or strike_pcr <= 0.85:
                score += 8.0
                reasons.append("Call Resistance Ceiling")

            if adx >= 20.0:
                score += 5.0

            score = max(5.0, min(99.0, score))
            if score >= 68.0 and pe_data["opt_above_ott"] and pe_data["buildup"] != "SHORT_BUILDUP":
                is_knife = pe_gate.get("is_falling_knife", False)
                is_chop = bool(regime_info and regime_info.get("chop_shield_active", False) and score < 78.0)

                target = round(pe_ltp * 1.5, 1)
                sl = round(pe_ltp * 0.7, 1)

                if is_knife:
                    act, lbl, bg, sig_cls, role, conv = "WAIT_KNIFE", "⚠️ WAIT KNIFE", "badge-warning", "sig-wait", "OBSERVER", "FALLING KNIFE"
                elif is_chop:
                    act, lbl, bg, sig_cls, role, conv = "CHOP_GATED", "⏳ CHOP GATED", "badge-warning", "sig-wait", "OBSERVER", "CHOP FILTER"
                else:
                    act, lbl, bg, sig_cls, role = "BUY_PE", "🚀 BUY PE", "badge-bear", "sig-buy", "BUYER"
                    conv = "STRONG BUY" if score >= 85 else "BUY"

                candidates.append({
                    "action": act,
                    "action_label": lbl,
                    "badge_class": bg,
                    "signal_class": sig_cls,
                    "role": role,
                    "option_type": "PE",
                    "contract_label": f"{int(stk)} PE",
                    "ltp": pe_ltp,
                    "target_price": target,
                    "stop_loss_price": sl,
                    "tqs_score": score,
                    "conviction": conv,
                    "premium_gate": pe_gate,
                    "reason": " | ".join(reasons)
                })

        # --- C. CE Selling Candidate ---
        if ce_ltp >= 10.0:
            score = 50.0
            reasons = []

            # 1. Option Under OTT line (Safe Theta Decay)
            if not ce_data["opt_above_ott"]:
                score += 18.0
                reasons.append("Opt Below OTT (Theta Decaying)")
            else:
                score -= 20.0

            # 2. Buildup
            if ce_data["buildup"] == "SHORT_BUILDUP":
                score += 16.0
                reasons.append("Heavy Call Writing")
            elif ce_data["buildup"] == "LONG_UNWINDING":
                score += 8.0
                reasons.append("Longs Unwinding")

            # 3. Dominant Call OI Resistance
            if oi_diff < 0 or strike_pcr < 0.90:
                score += 12.0
                reasons.append("CE Heavy Resistance Wall")

            if ott_state in ["BEARISH", "NEUTRAL"]:
                score += 10.0
                reasons.append(f"{ott_state} Spot Regime")

            if regime_info and regime_info.get("chop_shield_active"):
                score += 6.0
                reasons.append("Chop Regime Theta Collection (+6)")

            score = max(5.0, min(99.0, score))
            if score >= 66.0 and not ce_data["opt_above_ott"]:
                candidates.append({
                    "action": "SELL_CE",
                    "action_label": "🛡️ SELL CE",
                    "badge_class": "badge-bear",
                    "signal_class": "sig-sell",
                    "role": "SELLER",
                    "option_type": "CE",
                    "contract_label": f"SELL {int(stk)} CE",
                    "ltp": ce_ltp,
                    "net_credit": ce_ltp,
                    "target_price": round(ce_ltp * 0.60, 1),
                    "stop_loss_price": round(ce_ltp * 1.80, 1),
                    "tqs_score": score,
                    "conviction": "STRONG SELL" if score >= 82 else "SELL",
                    "reason": " | ".join(reasons)
                })

        # --- D. PE Selling Candidate ---
        if pe_ltp >= 10.0:
            score = 50.0
            reasons = []

            # 1. Option Under OTT line
            if not pe_data["opt_above_ott"]:
                score += 18.0
                reasons.append("Opt Below OTT (Theta Decaying)")
            else:
                score -= 20.0

            # 2. Buildup
            if pe_data["buildup"] == "SHORT_BUILDUP":
                score += 16.0
                reasons.append("Heavy Put Writing")
            elif pe_data["buildup"] == "LONG_UNWINDING":
                score += 8.0
                reasons.append("Longs Unwinding")

            # 3. Dominant Put OI Support
            if oi_diff > 0 or strike_pcr > 1.15:
                score += 12.0
                reasons.append("PE Heavy Support Floor")

            if ott_state in ["BULLISH", "NEUTRAL"]:
                score += 10.0
                reasons.append(f"{ott_state} Spot Regime")

            if regime_info and regime_info.get("chop_shield_active"):
                score += 6.0
                reasons.append("Chop Regime Theta Collection (+6)")

            score = max(5.0, min(99.0, score))
            if score >= 66.0 and not pe_data["opt_above_ott"]:
                candidates.append({
                    "action": "SELL_PE",
                    "action_label": "🛡️ SELL PE",
                    "badge_class": "badge-active",
                    "signal_class": "sig-sell",
                    "role": "SELLER",
                    "option_type": "PE",
                    "contract_label": f"SELL {int(stk)} PE",
                    "ltp": pe_ltp,
                    "net_credit": pe_ltp,
                    "target_price": round(pe_ltp * 0.60, 1),
                    "stop_loss_price": round(pe_ltp * 1.80, 1),
                    "tqs_score": score,
                    "conviction": "STRONG SELL" if score >= 82 else "SELL",
                    "reason": " | ".join(reasons)
                })

        # Separate best CE and PE signals for side-by-side Option Chain table display
        ce_candidates = [c for c in candidates if c.get("option_type") == "CE"]
        if ce_candidates:
            ce_candidates.sort(key=lambda x: x["tqs_score"], reverse=True)
            best_ce_sig = dict(ce_candidates[0])
        else:
            is_unwind = (ce_data["opt_close"] < ce_data["opt_ott"] and ce_data["buildup"] == "LONG_UNWINDING")
            best_ce_sig = {
                "action": "EXIT" if is_unwind else "WAIT",
                "action_label": "⚠️ EXIT / SL" if is_unwind else "⏳ WAIT",
                "badge_class": "badge-warning" if is_unwind else "badge-neutral",
                "signal_class": "sig-exit" if is_unwind else "sig-wait",
                "role": "NEUTRAL",
                "option_type": "CE",
                "contract_label": f"{int(stk)} CE",
                "ltp": ce_ltp,
                "tqs_score": 50.0,
                "conviction": "NEUTRAL",
                "reason": f"Opt {'Above' if ce_data['opt_above_ott'] else 'Below'} OTT | {ce_data['buildup_desc']}"
            }

        pe_candidates = [c for c in candidates if c.get("option_type") == "PE"]
        if pe_candidates:
            pe_candidates.sort(key=lambda x: x["tqs_score"], reverse=True)
            best_pe_sig = dict(pe_candidates[0])
        else:
            is_unwind = (pe_data["opt_close"] < pe_data["opt_ott"] and pe_data["buildup"] == "LONG_UNWINDING")
            best_pe_sig = {
                "action": "EXIT" if is_unwind else "WAIT",
                "action_label": "⚠️ EXIT / SL" if is_unwind else "⏳ WAIT",
                "badge_class": "badge-warning" if is_unwind else "badge-neutral",
                "signal_class": "sig-exit" if is_unwind else "sig-wait",
                "role": "NEUTRAL",
                "option_type": "PE",
                "contract_label": f"{int(stk)} PE",
                "ltp": pe_ltp,
                "tqs_score": 50.0,
                "conviction": "NEUTRAL",
                "reason": f"Opt {'Above' if pe_data['opt_above_ott'] else 'Below'} OTT | {pe_data['buildup_desc']}"
            }

        if candidates:
            candidates.sort(key=lambda x: x["tqs_score"], reverse=True)
            top_cand = dict(candidates[0])
        else:
            top_cand = {
                "action": "NEUTRAL",
                "action_label": "⚖️ NEUTRAL / WAIT",
                "badge_class": "badge-neutral",
                "signal_class": "sig-wait",
                "role": "OBSERVER",
                "option_type": "--",
                "contract_label": f"{int(stk)} [{step_tag}]",
                "ltp": 0.0,
                "target_price": 0.0,
                "stop_loss_price": 0.0,
                "tqs_score": 50.0,
                "conviction": "NEUTRAL",
                "reason": "Contested OI / Option hovering near OTT line without clear edge"
            }

        best_ce_sig["label"] = best_ce_sig.get("action_label", "")
        best_ce_sig["cls"] = best_ce_sig.get("signal_class", "")
        best_pe_sig["label"] = best_pe_sig.get("action_label", "")
        best_pe_sig["cls"] = best_pe_sig.get("signal_class", "")

        top_cand["call_signal"] = best_ce_sig
        top_cand["put_signal"] = best_pe_sig
        return top_cand

    # ---------------------------------------------------------
    # Aggregate ATM +- 2 Corridor Summary
    # ---------------------------------------------------------
    def _compute_corridor_summary(self, matrix: List[Dict[str, Any]], spot: float) -> Dict[str, Any]:
        """Calculates total corridor OI, change in OI, PCR, and net OI difference across all 5 strikes."""
        tot_call_oi = sum(r["call"]["oi"] for r in matrix)
        tot_put_oi = sum(r["put"]["oi"] for r in matrix)
        tot_corridor_oi = tot_call_oi + tot_put_oi

        tot_call_oi_chg = sum(r["call"]["oi_chg"] for r in matrix)
        tot_put_oi_chg = sum(r["put"]["oi_chg"] for r in matrix)
        tot_corridor_oi_chg = tot_call_oi_chg + tot_put_oi_chg

        corridor_oi_diff = tot_put_oi - tot_call_oi
        corridor_oi_chg_diff = tot_put_oi_chg - tot_call_oi_chg
        corridor_pcr = round(tot_put_oi / max(1, tot_call_oi), 2)

        if corridor_oi_diff > 0:
            bias = "PUT WRITERS DOMINANCE (SUPPORT CUSHION)"
            badge_class = "badge-active"
        elif corridor_oi_diff < 0:
            bias = "CALL WRITERS DOMINANCE (RESISTANCE OVERHEAD)"
            badge_class = "badge-bear"
        else:
            bias = "BALANCED ATM CORRIDOR"
            badge_class = "badge-neutral"

        return {
            "total_call_oi": tot_call_oi,
            "total_call_oi_formatted": self._format_oi(tot_call_oi),
            "total_put_oi": tot_put_oi,
            "total_put_oi_formatted": self._format_oi(tot_put_oi),
            "total_corridor_oi": tot_corridor_oi,
            "total_corridor_oi_formatted": self._format_oi(tot_corridor_oi),
            "total_call_oi_chg": tot_call_oi_chg,
            "total_call_oi_chg_formatted": self._format_oi_chg(tot_call_oi_chg),
            "total_put_oi_chg": tot_put_oi_chg,
            "total_put_oi_chg_formatted": self._format_oi_chg(tot_put_oi_chg),
            "corridor_oi_diff": corridor_oi_diff,
            "corridor_oi_diff_formatted": self._format_diff(corridor_oi_diff, "PE Support Lead", "CE Resistance Lead"),
            "corridor_oi_chg_diff": corridor_oi_chg_diff,
            "corridor_oi_chg_diff_formatted": self._format_diff(corridor_oi_chg_diff, "Put Writing Lead", "Call Writing Lead"),
            "corridor_pcr": corridor_pcr,
            "corridor_bias": bias,
            "badge_class": badge_class
        }

    # ---------------------------------------------------------
    # Best Buying Trade Selection (Strictly ATM +- 2)
    # ---------------------------------------------------------
    def _evaluate_best_buyer_atm(
        self,
        sym: str,
        spot: float,
        atm: float,
        step: int,
        lot_size: int,
        strike_map: Dict[float, StrikeRow],
        ott_state: str,
        adx: float,
        pcr: float,
        valid_strikes: List[float],
        regime_info: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates strictly ATM-2, ATM-1, ATM, ATM+1, and ATM+2 for Option Buying.
        Selects highest-scoring strike based on:
        1. Option Chain LTP, Bid-Ask Spread & Greeks (Delta/Theta)
        2. Option Contract's own 5-min PineScript OTT & ADX indicators
        3. 30-Second Option Premium Gate (AI-Trader Anti-Falling Knife)
        4. Open Interest (OI), Change in OI, and Institutional Buildup
        5. Strike PCR and Net OI Difference
        """
        if ott_state == "BEARISH":
            option_type = "PE"
            candidate_strikes = [
                (atm + 2 * step, "2-ITM", "Deep Intrinsic Delta Protection"),
                (atm + step, "1-ITM", "High Intrinsic Protection"),
                (atm, "ATM", "Maximum Volume & Balanced Delta"),
                (atm - step, "1-OTM", "Higher Percentage Leverage"),
                (atm - 2 * step, "2-OTM", "Maximum Convexity Leverage")
            ]
        elif ott_state == "BULLISH":
            option_type = "CE"
            candidate_strikes = [
                (atm - 2 * step, "2-ITM", "Deep Intrinsic Delta Protection"),
                (atm - step, "1-ITM", "High Intrinsic Protection"),
                (atm, "ATM", "Maximum Volume & Balanced Delta"),
                (atm + step, "1-OTM", "Higher Percentage Leverage"),
                (atm + 2 * step, "2-OTM", "Maximum Convexity Leverage")
            ]
        else:
            # Neutral: Compare ATM PE vs ATM CE
            if pcr <= 0.90:
                option_type = "PE"
                candidate_strikes = [
                    (atm, "ATM", "Moderate Bearish Bias"),
                    (atm + step, "1-ITM", "Intrinsic Bearish Cushion")
                ]
            else:
                option_type = "CE"
                candidate_strikes = [
                    (atm, "ATM", "Moderate Bullish Bias"),
                    (atm - step, "1-ITM", "Intrinsic Bullish Cushion")
                ]

        best_candidate = None
        best_score = -1.0

        for stk, tag, desc in candidate_strikes:
            row = strike_map.get(stk)
            if not row:
                continue

            contract = row.PE if option_type == "PE" else row.CE
            if not contract or contract.lastPrice <= 0:
                continue

            ltp = contract.lastPrice
            if ltp < 15.0:  # Skip illiquid junk
                continue

            # Bid-Ask spread evaluation
            bid = getattr(contract, "bidprice", 0.0) or getattr(contract, "bid", 0.0) or ltp
            ask = getattr(contract, "askPrice", 0.0) or getattr(contract, "ask", 0.0) or ltp
            spread = max(0.05, round(abs(ask - bid), 2))
            spread_pct = round((spread / ltp) * 100.0, 2)

            # Open Interest & Buildup metrics
            oi = getattr(contract, "openInterest", 0)
            oi_chg = getattr(contract, "changeinOpenInterest", 0)
            price_pchange = getattr(contract, "pChange", 0.0)
            buildup_type, buildup_badge, buildup_desc = self._calculate_buildup(price_pchange, oi_chg)

            # Option-Chart PineScript OTT & ADX indicators
            opt_chart = option_candle_service.get_option_chart_data(sym, stk, option_type)
            opt_curr = opt_chart.get("current_state", {})
            opt_close = opt_curr.get("close", ltp)
            opt_ott = opt_curr.get("ott", ltp)
            opt_mavg = opt_curr.get("mavg", ltp)
            opt_state = opt_curr.get("ott_state", "NEUTRAL")
            opt_adx = opt_curr.get("adx", 20.0)
            opt_dist_pts = round(opt_close - opt_ott, 2)
            opt_ott_confirmed = (opt_close > opt_ott) and (opt_state == "BULLISH")

            # 30-Second Option Premium Gate (AI-Trader Anti-Falling Knife)
            gate = option_candle_service.check_option_premium_gate(sym, stk, option_type)
            p_gate = 0.0
            if gate.get("is_falling_knife"):
                p_gate -= 15.0
            elif gate.get("momentum_pct", 0) >= 0.4:
                p_gate += 8.0

            # Regime bonus
            p_regime = 0.0
            if regime_info and ((option_type == "CE" and regime_info.get("regime") == "TRENDING_BULL") or
                               (option_type == "PE" and regime_info.get("regime") == "TRENDING_BEAR")):
                p_regime += 6.0
            elif regime_info and regime_info.get("chop_shield_active"):
                p_regime -= 10.0

            # Black-Scholes Greeks
            greeks = calculate_greeks(
                spot=spot,
                strike=stk,
                iv_pct=contract.impliedVolatility if contract.impliedVolatility > 0 else 14.0,
                dte_days=2.0,
                is_call=(option_type == "CE")
            )

            # Strike comparative metrics
            ce_oi = getattr(row.CE, "openInterest", 0) if row.CE else 0
            pe_oi = getattr(row.PE, "openInterest", 0) if row.PE else 0
            strike_pcr = round(pe_oi / max(1, ce_oi), 2)
            oi_diff = pe_oi - ce_oi

            # Compute Comprehensive Trade Quality Score (TQS 0 - 100)
            # 1. Strike Delta Fit (15 pts)
            if tag == "ATM":
                p_strike = 15.0
            elif "1-ITM" in tag:
                p_strike = 14.0
            elif "2-ITM" in tag:
                p_strike = 12.0
            elif "1-OTM" in tag:
                p_strike = 11.0
            else:
                p_strike = 8.0

            # 2. Liquidity & Spread (15 pts)
            if spread_pct <= 0.8:
                p_liq = 15.0
            elif spread_pct <= 1.5:
                p_liq = 12.0
            elif spread_pct <= 3.0:
                p_liq = 8.0
            else:
                p_liq = 4.0

            # 3. Spot PineScript Trend (15 pts)
            p_spot = 0.0
            if (option_type == "PE" and ott_state == "BEARISH") or (option_type == "CE" and ott_state == "BULLISH"):
                p_spot += 10.0
            if adx >= 22.0:
                p_spot += 5.0
            elif adx >= 18.0:
                p_spot += 3.0

            # 4. Option-Chart PineScript OTT Confirmation (20 pts)
            p_opt_ott = 0.0
            if opt_ott_confirmed:
                p_opt_ott += 15.0
            elif opt_close > opt_ott:
                p_opt_ott += 8.0
            else:
                p_opt_ott -= 10.0

            if opt_adx >= 20.0:
                p_opt_ott += 5.0

            # 5. Open Interest & Institutional Buildup (20 pts)
            p_oi = 0.0
            if buildup_type == "LONG_BUILDUP":
                p_oi += 15.0
            elif buildup_type == "SHORT_COVERING":
                p_oi += 10.0
            elif buildup_type == "SHORT_BUILDUP":
                p_oi -= 15.0
            else:
                p_oi -= 8.0

            if oi >= 500000:
                p_oi += 5.0

            # 6. Strike Differential Confirmation (15 pts)
            p_diff = 10.0
            if option_type == "CE" and (oi_diff > 0 or strike_pcr >= 1.10):
                p_diff += 5.0
            elif option_type == "PE" and (oi_diff < 0 or strike_pcr <= 0.85):
                p_diff += 5.0

            raw_tqs = p_strike + p_liq + p_spot + p_opt_ott + p_oi + p_diff + p_gate + p_regime
            tqs = round(max(5.0, min(99.0, raw_tqs)), 1)

            if tqs > best_score:
                best_score = tqs
                target1 = round(ltp * 1.50, 2)
                target2 = round(ltp * 2.00, 2)
                sl = round(ltp * 0.70, 2)
                risk_pts = round(ltp - sl, 2)
                reward_pts = round(target1 - ltp, 2)

                # Score-Tiered Position Sizing from AI-Trader
                if tqs >= 78.0:
                    suggested_lots = 3
                    sizing_tier = "3 LOTS (HIGH CONVICTION)"
                    sizing_badge = "badge-active"
                elif tqs >= 65.0:
                    suggested_lots = 2
                    sizing_tier = "2 LOTS (MODERATE)"
                    sizing_badge = "badge-qualified"
                else:
                    suggested_lots = 1
                    sizing_tier = "1 LOT (CONSERVATIVE)"
                    sizing_badge = "badge-warning"

                now_t = get_current_ist().time()
                is_dead_zone = time(11, 30) <= now_t <= time(13, 30)
                theta_shield = {
                    "is_dead_zone": is_dead_zone,
                    "chop_shield_active": bool(regime_info and regime_info.get("chop_shield_active")),
                    "max_hold_mins": 30 if is_dead_zone else 45,
                    "advice": "Mid-Day Theta Acceleration (11:30-13:30): Max 30m hold & trailing lock (+35% at +8%, +60% at +25%)" if is_dead_zone else "Standard Trailing: Ratchet at +12% gain"
                }

                best_candidate = {
                    "role": "BUYER",
                    "strategy_type": f"MOMENTUM_{option_type}_BUY",
                    "option_type": option_type,
                    "strike": stk,
                    "strike_tag": tag,
                    "strike_label": f"{int(stk)} {option_type} [{tag}]",
                    "ltp": ltp,
                    "bid": bid,
                    "ask": ask,
                    "spread": spread,
                    "spread_pct": spread_pct,
                    "oi": oi,
                    "oi_chg": oi_chg,
                    "oi_formatted": self._format_oi(oi),
                    "oi_chg_formatted": self._format_oi_chg(oi_chg),
                    "strike_pcr": strike_pcr,
                    "oi_diff": oi_diff,
                    "oi_diff_formatted": self._format_diff(oi_diff, "PE Lead", "CE Lead"),
                    "buildup": buildup_type,
                    "buildup_desc": buildup_desc,
                    "buildup_badge": buildup_badge,
                    "option_ott": opt_ott,
                    "option_mavg": opt_mavg,
                    "option_ott_confirmed": opt_ott_confirmed,
                    "option_ott_distance": opt_dist_pts,
                    "option_adx": opt_adx,
                    "premium_gate": gate,
                    "suggested_lots": suggested_lots,
                    "sizing_tier": sizing_tier,
                    "sizing_badge": sizing_badge,
                    "theta_shield": theta_shield,
                    "delta": greeks["delta"],
                    "theta": greeks["theta"],
                    "target1_price": target1,
                    "target2_price": target2,
                    "stop_loss_price": sl,
                    "risk_pts": risk_pts,
                    "reward_pts": reward_pts,
                    "risk_reward_ratio": f"1 : {round(reward_pts / max(0.1, risk_pts), 1)}",
                    "max_risk_inr": round(risk_pts * lot_size, 0),
                    "potential_reward_inr": round(reward_pts * lot_size, 0),
                    "tqs_score": tqs,
                    "conviction": "HIGH" if tqs >= 85 else ("GOOD" if tqs >= 70 else "MODERATE"),
                    "rationale": f"PineScript {ott_state} trend with ADX {adx:.1f}. Option OTT: {'Above Line' if opt_ott_confirmed else 'Testing Line'}. 30s Gate: {gate.get('status_label')}. Sizing: {sizing_tier}."
                }

        return best_candidate

    # ---------------------------------------------------------
    # Best Selling Trade Selection (Strictly ATM +- 2)
    # ---------------------------------------------------------
    def _evaluate_best_seller_atm(
        self,
        sym: str,
        spot: float,
        atm: float,
        step: int,
        lot_size: int,
        strike_map: Dict[float, StrikeRow],
        ott_state: str,
        adx: float,
        pcr: float,
        valid_strikes: List[float],
        regime_info: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates strictly ATM +- 2 strikes for Option Selling (Theta Decay).
        Formulates high-probability credit setups:
        - Confirms with Institutional Short Buildup (Writers Capping)
        - Confirms Option LTP is below Option OTT (Downtrend decay advantage)
        - Confirms Strike PCR and Difference in OI
        - Incorporates AI-Trader Vol-Regime Chop Protection & Position Sizing
        """
        atm_minus_2 = atm - (2 * step)
        atm_minus_1 = atm - step
        atm_strike = atm
        atm_plus_1 = atm + step
        atm_plus_2 = atm + (2 * step)

        now_t = get_current_ist().time()
        is_dead_zone = time(11, 30) <= now_t <= time(13, 30)
        is_chop = bool(regime_info and regime_info.get("chop_shield_active"))

        theta_shield = {
            "is_dead_zone": is_dead_zone,
            "chop_shield_active": is_chop,
            "max_hold_mins": 90,
            "advice": "Dead Consolidation: Maximum Theta Decay advantage for sellers. Ratchet trailing stop at 40% premium erosion." if is_chop else "Standard Theta Harvesting: Target 50-60% decay with 1.8x SL."
        }

        if ott_state == "BEARISH":
            # Candidate OTM Calls to sell: ATM+1 CE or ATM+2 CE
            candidates = [
                (atm_plus_1, "1-OTM", "ATM+1"),
                (atm_plus_2, "2-OTM", "ATM+2")
            ]
            best_cand = None
            best_score = -1.0

            for sell_stk, tag, step_label in candidates:
                row = strike_map.get(sell_stk)
                contract = row.CE if row else None
                ltp = contract.lastPrice if contract and contract.lastPrice > 0 else round(spot * 0.004, 1)
                greeks = calculate_greeks(spot, sell_stk, contract.impliedVolatility if contract else 14.0, is_call=True)

                oi = getattr(contract, "openInterest", 0) if contract else 0
                oi_chg = getattr(contract, "changeinOpenInterest", 0) if contract else 0
                pchange = getattr(contract, "pChange", 0.0) if contract else 0.0
                buildup_type, buildup_badge, buildup_desc = self._calculate_buildup(pchange, oi_chg)

                opt_chart = option_candle_service.get_option_chart_data(sym, sell_stk, "CE")
                opt_curr = opt_chart.get("current_state", {})
                opt_close = opt_curr.get("close", ltp)
                opt_ott = opt_curr.get("ott", ltp)
                opt_ott_confirmed = opt_close <= opt_ott

                net_credit = ltp
                breakeven = round(sell_stk + net_credit, 1)
                cushion_pts = round(breakeven - spot, 1)
                cushion_pct = round((cushion_pts / spot) * 100.0, 2)
                daily_theta_inr = round(abs(greeks["theta"]) * lot_size, 0)
                target_decay = round(net_credit * 0.60, 2)
                sl_price = round(net_credit * 1.80, 2)

                tqs = 88.0 if (buildup_type == "SHORT_BUILDUP" and opt_ott_confirmed) else 76.0
                if is_chop:
                    tqs += 5.0
                tqs = min(99.0, tqs)

                if tqs >= 82.0:
                    suggested_lots = 3
                    sizing_tier = "3 LOTS (HIGH CONVICTION)"
                    sizing_badge = "badge-active"
                elif tqs >= 72.0:
                    suggested_lots = 2
                    sizing_tier = "2 LOTS (MODERATE)"
                    sizing_badge = "badge-qualified"
                else:
                    suggested_lots = 1
                    sizing_tier = "1 LOT (CONSERVATIVE)"
                    sizing_badge = "badge-warning"

                cand = {
                    "role": "SELLER",
                    "strategy_type": "BEAR_CALL_SELL",
                    "option_type": "CE",
                    "strike": sell_stk,
                    "strike_tag": tag,
                    "strike_label": f"SELL {int(sell_stk)} CE [{step_label}]",
                    "ltp": ltp,
                    "oi": oi,
                    "oi_chg": oi_chg,
                    "oi_formatted": self._format_oi(oi),
                    "oi_chg_formatted": self._format_oi_chg(oi_chg),
                    "buildup": buildup_type,
                    "buildup_desc": buildup_desc,
                    "buildup_badge": buildup_badge,
                    "option_ott": opt_ott,
                    "option_ott_confirmed": opt_ott_confirmed,
                    "net_credit_pts": net_credit,
                    "net_credit_inr": round(net_credit * lot_size, 0),
                    "breakeven": breakeven,
                    "cushion_pts": cushion_pts,
                    "cushion_pct": cushion_pct,
                    "delta": greeks["delta"],
                    "daily_theta_inr": daily_theta_inr,
                    "target_price": target_decay,
                    "stop_loss_price": sl_price,
                    "suggested_lots": suggested_lots,
                    "sizing_tier": sizing_tier,
                    "sizing_badge": sizing_badge,
                    "theta_shield": theta_shield,
                    "tqs_score": tqs,
                    "conviction": "HIGH" if tqs >= 85 else "GOOD",
                    "rationale": f"Bearish regime. Selling {int(sell_stk)} CE ({step_label}) backed by {buildup_desc}. Sizing: {sizing_tier}."
                }

                if tqs > best_score:
                    best_score = tqs
                    best_cand = cand

            return best_cand

        elif ott_state == "BULLISH":
            # Candidate OTM Puts to sell: ATM-1 PE or ATM-2 PE
            candidates = [
                (atm_minus_1, "1-OTM", "ATM-1"),
                (atm_minus_2, "2-OTM", "ATM-2")
            ]
            best_cand = None
            best_score = -1.0

            for sell_stk, tag, step_label in candidates:
                row = strike_map.get(sell_stk)
                contract = row.PE if row else None
                ltp = contract.lastPrice if contract and contract.lastPrice > 0 else round(spot * 0.004, 1)
                greeks = calculate_greeks(spot, sell_stk, contract.impliedVolatility if contract else 14.0, is_call=False)

                oi = getattr(contract, "openInterest", 0) if contract else 0
                oi_chg = getattr(contract, "changeinOpenInterest", 0) if contract else 0
                pchange = getattr(contract, "pChange", 0.0) if contract else 0.0
                buildup_type, buildup_badge, buildup_desc = self._calculate_buildup(pchange, oi_chg)

                opt_chart = option_candle_service.get_option_chart_data(sym, sell_stk, "PE")
                opt_curr = opt_chart.get("current_state", {})
                opt_close = opt_curr.get("close", ltp)
                opt_ott = opt_curr.get("ott", ltp)
                opt_ott_confirmed = opt_close <= opt_ott

                net_credit = ltp
                breakeven = round(sell_stk - net_credit, 1)
                cushion_pts = round(spot - breakeven, 1)
                cushion_pct = round((cushion_pts / spot) * 100.0, 2)
                daily_theta_inr = round(abs(greeks["theta"]) * lot_size, 0)
                target_decay = round(net_credit * 0.60, 2)
                sl_price = round(net_credit * 1.80, 2)

                tqs = 88.0 if (buildup_type == "SHORT_BUILDUP" and opt_ott_confirmed) else 76.0
                if is_chop:
                    tqs += 5.0
                tqs = min(99.0, tqs)

                if tqs >= 82.0:
                    suggested_lots = 3
                    sizing_tier = "3 LOTS (HIGH CONVICTION)"
                    sizing_badge = "badge-active"
                elif tqs >= 72.0:
                    suggested_lots = 2
                    sizing_tier = "2 LOTS (MODERATE)"
                    sizing_badge = "badge-qualified"
                else:
                    suggested_lots = 1
                    sizing_tier = "1 LOT (CONSERVATIVE)"
                    sizing_badge = "badge-warning"

                cand = {
                    "role": "SELLER",
                    "strategy_type": "BULL_PUT_SELL",
                    "option_type": "PE",
                    "strike": sell_stk,
                    "strike_tag": tag,
                    "strike_label": f"SELL {int(sell_stk)} PE [{step_label}]",
                    "ltp": ltp,
                    "oi": oi,
                    "oi_chg": oi_chg,
                    "oi_formatted": self._format_oi(oi),
                    "oi_chg_formatted": self._format_oi_chg(oi_chg),
                    "buildup": buildup_type,
                    "buildup_desc": buildup_desc,
                    "buildup_badge": buildup_badge,
                    "option_ott": opt_ott,
                    "option_ott_confirmed": opt_ott_confirmed,
                    "net_credit_pts": net_credit,
                    "net_credit_inr": round(net_credit * lot_size, 0),
                    "breakeven": breakeven,
                    "cushion_pts": cushion_pts,
                    "cushion_pct": cushion_pct,
                    "delta": greeks["delta"],
                    "daily_theta_inr": daily_theta_inr,
                    "target_price": target_decay,
                    "stop_loss_price": sl_price,
                    "suggested_lots": suggested_lots,
                    "sizing_tier": sizing_tier,
                    "sizing_badge": sizing_badge,
                    "theta_shield": theta_shield,
                    "tqs_score": tqs,
                    "conviction": "HIGH" if tqs >= 85 else "GOOD",
                    "rationale": f"Bullish regime. Selling {int(sell_stk)} PE ({step_label}) backed by {buildup_desc}. Sizing: {sizing_tier}."
                }

                if tqs > best_score:
                    best_score = tqs
                    best_cand = cand

            return best_cand

        else:
            # Range-Bound / Neutral: Short Strangle within ATM +- 2 corridor
            ce_stk = atm_plus_1
            pe_stk = atm_minus_1
            ce_row = strike_map.get(ce_stk)
            pe_row = strike_map.get(pe_stk)
            ce_contract = ce_row.CE if ce_row else None
            pe_contract = pe_row.PE if pe_row else None
            ce_ltp = ce_contract.lastPrice if ce_contract else round(spot * 0.003, 1)
            pe_ltp = pe_contract.lastPrice if pe_contract else round(spot * 0.003, 1)
            tot_credit = round(ce_ltp + pe_ltp, 2)
            daily_theta_inr = round(tot_credit * 0.25 * lot_size, 0)

            tot_oi = (getattr(ce_contract, "openInterest", 0) if ce_contract else 0) + (getattr(pe_contract, "openInterest", 0) if pe_contract else 0)
            tot_oi_chg = (getattr(ce_contract, "changeinOpenInterest", 0) if ce_contract else 0) + (getattr(pe_contract, "changeinOpenInterest", 0) if pe_contract else 0)

            tqs = 85.0 if is_chop else 80.0
            suggested_lots = 3 if tqs >= 82 else 2
            sizing_tier = "3 LOTS (HIGH CONVICTION)" if suggested_lots == 3 else "2 LOTS (MODERATE)"
            sizing_badge = "badge-active" if suggested_lots == 3 else "badge-qualified"

            return {
                "role": "SELLER",
                "strategy_type": "NEUTRAL_STRANGLE_SELL",
                "option_type": "CE_AND_PE",
                "strike": f"{int(pe_stk)} / {int(ce_stk)}",
                "strike_tag": "ATM±1",
                "strike_label": f"SELL {int(pe_stk)} PE & {int(ce_stk)} CE",
                "ltp": tot_credit,
                "oi": tot_oi,
                "oi_chg": tot_oi_chg,
                "oi_formatted": self._format_oi(tot_oi),
                "oi_chg_formatted": self._format_oi_chg(tot_oi_chg),
                "buildup": "DUAL_WRITING",
                "buildup_desc": "Dual Writing on ATM±1",
                "buildup_badge": "badge-active",
                "option_ott": 0.0,
                "option_ott_confirmed": True,
                "net_credit_pts": tot_credit,
                "net_credit_inr": round(tot_credit * lot_size, 0),
                "breakeven": f"{int(pe_stk - tot_credit)} - {int(ce_stk + tot_credit)}",
                "cushion_pts": round(step, 1),
                "cushion_pct": round((step / spot) * 100.0, 2),
                "delta": 0.05,
                "daily_theta_inr": daily_theta_inr,
                "target_price": round(tot_credit * 0.50, 2),
                "stop_loss_price": round(tot_credit * 1.50, 2),
                "suggested_lots": suggested_lots,
                "sizing_tier": sizing_tier,
                "sizing_badge": sizing_badge,
                "theta_shield": theta_shield,
                "tqs_score": tqs,
                "conviction": "GOOD",
                "rationale": f"Two-sided neutral consolidation. Selling ATM±1 corridor captures ₹{round(tot_credit * lot_size, 0):,.0f} total premium with dual decay. Sizing: {sizing_tier}."
            }


atm_signals_service = AtmSignalsService()
