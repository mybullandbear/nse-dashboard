"""
Deterministic Multi-Factor Confluence & Signal Generation Engine
Combines Positioning, Price Confirmation, Defense Walls, and Straddle Decay
to generate institutional option seller trading recommendations.
"""
import logging
from typing import Dict, Any, List
from app.core.config import get_settings
from app.services.data_quality import UNSAFE_SOURCES

logger = logging.getLogger(__name__)
from app.services.option_chain import ParsedOptionChain
from app.services.trade_engine import trade_engine


class SignalEngine:
    """Computes multi-factor confluence score (0-100) and actionable option seller strategies."""

    def evaluate(self, chain: ParsedOptionChain, oi_analytics: Dict[str, Any]) -> Dict[str, Any]:
        if not chain:
            return self._default_neutral_signal()

        if chain.source in UNSAFE_SOURCES:
            return {**self._default_neutral_signal(), "symbol": chain.symbol, "operational_state": "DATA UNAVAILABLE", "data_quality": chain.data_quality}

        sym = chain.symbol.upper()
        spot = chain.spot_price
        atm = chain.atm_strike
        pcr = chain.pcr
        spot_pchange = getattr(chain, "spot_pchange", 0.0) or 0.0
        spot_change = getattr(chain, "spot_change", 0.0) or 0.0
        walls = oi_analytics.get("walls", {})
        pressure = oi_analytics.get("pressure", {})
        straddle = oi_analytics.get("straddle", {})

        step = get_settings().STRIKE_STEPS.get(sym, 50)

        # 1. Positioning Score (-100 to +100)
        # PCR > 1.2 is bullish, PCR < 0.8 is bearish
        pcr_score = min(100.0, max(-100.0, (pcr - 1.0) * 150.0))
        
        # Put Writer Pressure vs Call Writer Pressure
        put_press = pressure.get("put_writer_pressure_pct", 50.0)
        call_press = pressure.get("call_writer_pressure_pct", 50.0)
        press_score = (put_press - call_press) * 2.0  # -100 to +100

        pos_score = (0.5 * pcr_score) + (0.5 * press_score)

        # 2. Price Confirmation Score (-100 to +100)
        # If day percentage change is available, scale velocity:
        # e.g., ±0.5% = ±35, ±1.0% = ±70, ±1.3% = ±90, ±1.5%+ = ±100
        if spot_pchange != 0.0:
            trend_score = min(100.0, max(-100.0, spot_pchange * 70.0))
            spot_atm_dist = spot - atm
            micro_align = min(15.0, max(-15.0, (spot_atm_dist / step) * 15.0))
            price_conf_score = min(100.0, max(-100.0, (trend_score * 0.85) + micro_align))
        else:
            spot_atm_dist = spot - atm
            price_conf_score = min(100.0, max(-100.0, (spot_atm_dist / (spot * 0.005)) * 50.0))

        # 3. Wall Interaction & Channel Dynamics Score (-100 to +100)
        sup_strike = walls.get("support_strike") or (atm - 2 * step)
        res_strike = walls.get("resistance_strike") or (atm + 2 * step)

        if spot_pchange >= 0.25 or pos_score >= 25.0:
            # Bullish Trending: Approaching or crossing resistance is a breakout / wall squeeze
            if spot >= res_strike:
                wall_score = 90.0  # Call Resistance Wall Breached / Short-Covering Squeeze
            else:
                wall_score = 65.0  # Bullish Expansion towards Resistance supported by Put Floor
        elif spot_pchange <= -0.25 or pos_score <= -25.0:
            # Bearish Trending: Approaching or crossing support is a breakdown / long dump
            if spot <= sup_strike:
                wall_score = -90.0  # Put Support Wall Breached / Long Liquidation Breakdown
            else:
                wall_score = -65.0  # Bearish Plunge towards Support capped by Call Ceiling
        else:
            # Sideways / Range-Bound: Mean-reversion defense rules
            dist_to_sup = abs(spot - sup_strike)
            dist_to_res = abs(res_strike - spot)
            if dist_to_sup < dist_to_res:
                wall_score = 30.0  # Floor defense bounce
            elif dist_to_res < dist_to_sup:
                wall_score = -30.0  # Ceiling defense fade
            else:
                wall_score = 0.0

        # 4. Straddle Decay Score (0 to 100)
        decay_pct = straddle.get("decay_pct") or 0.0
        decay_score = min(100.0, max(0.0, 50.0 + decay_pct * 4.0))

        # Normalized weights:
        pos_norm = (pos_score + 100.0) / 2.0        # 0 to 100
        price_norm = (price_conf_score + 100.0) / 2.0  # 0 to 100
        wall_norm = (wall_score + 100.0) / 2.0        # 0 to 100

        # When market is clearly trending, directional momentum factors dominate
        if abs(spot_pchange) >= 0.35 or abs(pos_score) >= 30.0:
            final_confluence = round(
                (0.40 * pos_norm) +
                (0.40 * price_norm) +
                (0.20 * wall_norm),
                1
            )
        else:
            final_confluence = round(
                (0.35 * pos_norm) +
                (0.30 * price_norm) +
                (0.15 * wall_norm) +
                (0.20 * decay_score),
                1
            )
        final_confluence = max(5.0, min(98.0, final_confluence))

        # Direction Classification
        if final_confluence >= 68.0:
            direction = "BULLISH"
            operational_state = "ENTRY CONFIRMED (HIGH CONVICTION)" if final_confluence >= 75.0 else "ENTRY READY"
            regime = "STRONG BULLISH CONFLUENCE" if final_confluence >= 75.0 else "BULLISH CONFLUENCE"
            sentiment = "Put Writers Defending & Expanding (Strong Bullish Momentum)"
        elif final_confluence <= 34.0:
            direction = "BEARISH"
            operational_state = "ENTRY CONFIRMED (HIGH CONVICTION)" if final_confluence <= 25.0 else "ENTRY READY"
            regime = "STRONG BEARISH CONFLUENCE" if final_confluence <= 25.0 else "BEARISH CONFLUENCE"
            sentiment = "Call Writers Capping & Dumping (Strong Bearish Momentum)"
        else:
            direction = "NEUTRAL"
            operational_state = "WATCH"
            regime = "RANGE-BOUND / TWO-SIDED"
            sentiment = "Balanced Defense Walls at ATM"

        # Model Confidence
        confidence = round(max(40.0, min(95.0, 65.0 + abs(final_confluence - 50.0) * 0.7)), 1)

        # Evaluate Dual-Regime Trade Recommendations (Seller Decay vs Buyer Momentum)
        trade_eval = trade_engine.evaluate_trades(chain, oi_analytics, final_confluence, operational_state)
        top_rec = trade_eval.get("top_recommendation", {})
        top_strategy = top_rec.get("strategy", {})

        decision = {
            "model_version": "confluence-v2-observed-decay",
            "confidence_kind": "HEURISTIC_STRENGTH_NOT_CALIBRATED_PROBABILITY",
            "data_quality": chain.data_quality,
            "symbol": sym,
            "direction": direction,
            "bias": direction,
            "confluence_score": final_confluence,
            "confidence_pct": confidence,
            "operational_state": operational_state,
            "market_regime": regime,
            "sentiment_summary": sentiment,
            "pcr": pcr,
            "spot_price": spot,
            "spot_change": spot_change,
            "spot_pchange": spot_pchange,
            "walls": {
                "support_strike": sup_strike,
                "resistance_strike": res_strike,
                "call_wall": res_strike,
                "put_wall": sup_strike,
                "wall_range_pts": walls.get("wall_range_pts", abs(res_strike - sup_strike)),
                "support_oi": walls.get("support_oi", 0),
                "resistance_oi": walls.get("resistance_oi", 0),
            },
            "resistance_wall": res_strike,
            "support_wall": sup_strike,
            "active_regime": trade_eval.get("active_regime", "SELLER_REGIME"),
            "regime_title": trade_eval.get("regime_title", "SELLER REGIME"),
            "regime_description": trade_eval.get("regime_description", ""),
            "market_certainty_pct": trade_eval.get("market_certainty_pct", 50.0),
            "lot_size": trade_eval.get("lot_size", 75),
            "top_recommendation": top_rec,
            "seller_strategy": trade_eval.get("seller_strategy", {}),
            "buyer_strategy": trade_eval.get("buyer_strategy", {}),
            "factors": {
                "positioning_score": round(pos_norm, 1),
                "price_action_score": round(price_norm, 1),
                "wall_proximity_score": round(wall_norm, 1),
                "straddle_decay_score": round(decay_score, 1),
            },
            "strategy": top_strategy or self._generate_seller_strategy(sym, direction, spot, atm, sup_strike, res_strike)
        }

        try:
            from app.db.storage import snapshot_storage
            snapshot_storage.save_signal_decision(decision, {"source":chain.source,"spot":spot,"atm":atm,"pcr":pcr,"spot_change":spot_change,"spot_pchange":spot_pchange,"walls":walls,"pressure":pressure,"straddle":straddle,"snapshot_timestamp":chain.timestamp})
        except Exception:
            logger.exception("Decision audit persistence failed for %s", sym)
        return decision

    def _generate_seller_strategy(self, symbol: str, direction: str, spot: float, atm: float, sup: float, res: float) -> Dict[str, Any]:
        """Formulates institutional high-probability spread recommendations for option sellers."""
        step = get_settings().STRIKE_STEPS.get(symbol, 50)
        
        if direction == "BULLISH":
            sell_strike = atm - step
            hedge_strike = sell_strike - (2 * step)
            return {
                "name": f"BULL PUT CREDIT SPREAD",
                "bias": "BULLISH",
                "action": f"SELL {int(sell_strike)} PE | BUY {int(hedge_strike)} PE",
                "sell_strike": sell_strike,
                "hedge_strike": hedge_strike,
                "max_profit": "Net Premium Received",
                "breakeven": round(sell_strike - 35.0, 1),
                "stop_loss": round(spot - (1.5 * step), 1),
                "target": "80% - 100% Premium Decay",
                "conviction": "HIGH CONVICTION"
            }
        elif direction == "BEARISH":
            sell_strike = atm + step
            hedge_strike = sell_strike + (2 * step)
            return {
                "name": f"BEAR CALL CREDIT SPREAD",
                "bias": "BEARISH",
                "action": f"SELL {int(sell_strike)} CE | BUY {int(hedge_strike)} CE",
                "sell_strike": sell_strike,
                "hedge_strike": hedge_strike,
                "max_profit": "Net Premium Received",
                "breakeven": round(sell_strike + 35.0, 1),
                "stop_loss": round(spot + (1.5 * step), 1),
                "target": "80% - 100% Premium Decay",
                "conviction": "HIGH CONVICTION"
            }
        else:
            # Range bound / Iron Condor
            ce_sell = max(atm + (2 * step), res)
            pe_sell = min(atm - (2 * step), sup)
            return {
                "name": "SHORT IRON CONDOR / DELTA NEUTRAL",
                "bias": "NEUTRAL",
                "action": f"SELL {int(ce_sell)} CE & SELL {int(pe_sell)} PE",
                "sell_strike": f"{int(pe_sell)} PE / {int(ce_sell)} CE",
                "hedge_strike": f"{int(pe_sell - 2*step)} PE / {int(ce_sell + 2*step)} CE",
                "max_profit": "Full Premium Extinction",
                "breakeven": f"{int(pe_sell - 30)} - {int(ce_sell + 30)}",
                "stop_loss": "Break of Support or Resistance Wall",
                "target": "60% - 80% Combined Decay",
                "conviction": "RANGE BOUND"
            }

    def _default_neutral_signal(self) -> Dict[str, Any]:
        empty = trade_engine._empty_recommendation("NIFTY")
        return {
            "symbol": "NIFTY",
            "direction": "NEUTRAL",
            "confluence_score": 50.0,
            "confidence_pct": 50.0,
            "operational_state": "WATCH",
            "market_regime": "AWAITING DATA",
            "sentiment_summary": "Neutral / Initializing",
            "active_regime": empty["active_regime"],
            "regime_title": empty["regime_title"],
            "regime_description": empty["regime_description"],
            "market_certainty_pct": empty["market_certainty_pct"],
            "lot_size": empty["lot_size"],
            "top_recommendation": empty["top_recommendation"],
            "seller_strategy": empty["seller_strategy"],
            "buyer_strategy": empty["buyer_strategy"],
            "factors": {
                "positioning_score": 50.0,
                "price_action_score": 50.0,
                "wall_proximity_score": 50.0,
                "straddle_decay_score": 50.0,
            },
            "strategy": empty["top_recommendation"]["strategy"]
        }


signal_engine = SignalEngine()
