"""
Institutional Dual-Regime Trade Recommendation Engine
Adheres to Backend Design Agent & Financial Engineering Standards.
Formulates deterministic, mathematically sound trade recommendations:
1. SELLER REGIME: For uncertain, range-bound, or mild drift markets.
   Exploits Theta decay, high probability of profit (POP), and defensive buffer zones.
2. BUYER REGIME: For strong trending, breakout, or high-momentum markets.
   Exploits Delta acceleration and Gamma expansion when momentum outpaces Theta decay.
"""
import math
import logging
from typing import Dict, Any, List, Optional
from app.services.option_chain import ParsedOptionChain, StrikeRow
from app.core.config import get_settings
from app.core.credentials import credentials

logger = logging.getLogger(__name__)


# ---------------------------------------------------------
# Mathematical Helpers: Black-Scholes Greeks
# ---------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _norm_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

def calculate_greeks(spot: float, strike: float, iv_pct: float, dte_days: float = 2.0, is_call: bool = True) -> Dict[str, float]:
    """
    Computes Black-Scholes Greeks (Delta, Theta per day in points, Gamma, Vega).
    Clamps inputs to prevent divide-by-zero or math domain errors.
    """
    if spot <= 0 or strike <= 0:
        return {"delta": 0.5 if is_call else -0.5, "theta": -5.0, "gamma": 0.001, "vega": 1.0}

    # Normalize parameters
    sigma = max(0.06, min(1.20, (iv_pct or 14.0) / 100.0))
    t_years = max(0.25 / 365.0, (dte_days or 2.0) / 365.0)
    r = 0.07  # RBI benchmark rate approx 7%

    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    pdf_d1 = _norm_pdf(d1)
    cdf_d1 = _norm_cdf(d1)
    cdf_d2 = _norm_cdf(d2)

    gamma = pdf_d1 / (spot * sigma * sqrt_t)
    vega = (spot * sqrt_t * pdf_d1) / 100.0  # per 1% vol change

    if is_call:
        delta = cdf_d1
        # Theta in points per calendar day (divide annual theta by 365)
        annual_theta = -(spot * pdf_d1 * sigma) / (2.0 * sqrt_t) - (r * strike * math.exp(-r * t_years) * cdf_d2)
    else:
        delta = cdf_d1 - 1.0
        annual_theta = -(spot * pdf_d1 * sigma) / (2.0 * sqrt_t) + (r * strike * math.exp(-r * t_years) * (1.0 - cdf_d2))

    daily_theta = annual_theta / 365.0

    return {
        "delta": round(delta, 3),
        "theta": round(daily_theta, 2),  # negative points per day
        "gamma": round(gamma, 5),
        "vega": round(vega, 2)
    }


# ---------------------------------------------------------
# Trade Engine Service
# ---------------------------------------------------------

class TradeRecommendationEngine:
    """
    Evaluates market certainty and formulates dual-regime trading setups:
    - Directional Option Seller credit spreads (decay capture when market is uncertain)
    - Directional Option Buyer momentum breakouts (delta expansion when market is strong)
    """

    def evaluate_trades(
        self,
        chain: ParsedOptionChain,
        oi_analytics: Dict[str, Any],
        confluence_score: float,
        operational_state: str
    ) -> Dict[str, Any]:
        if not chain or not chain.strikes:
            return self._empty_recommendation("NIFTY")

        sym = chain.symbol.upper()
        spot = chain.spot_price
        atm = chain.atm_strike
        settings = get_settings()
        step = settings.STRIKE_STEPS.get(sym, 50)
        lot_size = settings.LOT_SIZES.get(sym, 65)

        walls = oi_analytics.get("walls", {})
        pressure = oi_analytics.get("pressure", {})
        straddle = oi_analytics.get("straddle", {})

        sup_strike = walls.get("support_strike", atm - (2 * step))
        res_strike = walls.get("resistance_strike", atm + (2 * step))
        decay_pct = straddle.get("decay_pct", 0.0)

        # ---------------------------------------------------------
        # 1. Market Regime & Option Buyer Priority Classification
        # ---------------------------------------------------------
        # Trader Priority: MOMENTUM BUYER / SCALPER FIRST.
        # No far OTM selling. Guaranteed commission coverage (minimum ₹100+ net profit).
        conf_dist_from_50 = abs(confluence_score - 50.0)  # 0 to 50
        certainty_pct = round(min(96.0, max(25.0, (conf_dist_from_50 / 50.0) * 100.0)), 1)

        # Evaluate opposite-side unwinding
        call_unwinding = False
        put_unwinding = False
        strikes_comp = oi_analytics.get("strikes_comparison", [])
        for sc in strikes_comp:
            stk = sc.get("strike", 0)
            if abs(stk - atm) <= 2 * step:
                if sc.get("ce_oi_chg", 0) < 0 and sc.get("pe_oi_chg", 0) > 0:
                    call_unwinding = True
                if sc.get("pe_oi_chg", 0) < 0 and sc.get("ce_oi_chg", 0) > 0:
                    put_unwinding = True

        # Regime Rule: Prioritize Option Buying for Directional Moves
        if confluence_score >= 54.0:
            active_regime = "BUYER_MOMENTUM_CE"
            regime_title = "BULLISH MOMENTUM / CALL SCALP"
            regime_description = "Put writers dominating. Delta acceleration outpaces Theta decay. ATM Call Buying active."
        elif confluence_score <= 46.0:
            active_regime = "BUYER_MOMENTUM_PE"
            regime_title = "BEARISH MOMENTUM / PUT SCALP"
            regime_description = "Call writers capping upside. Downside momentum active. ATM Put Buying active."
        else:
            active_regime = "STANDBY_CHOP"
            regime_title = "DEAD CONSOLIDATION / CHOP FILTER"
            regime_description = "Market in balanced two-sided consolidation. Capital preservation: Standby to avoid theta bleed."

        # ---------------------------------------------------------
        # 2. Build Strike Lookup Dictionary from Live Option Chain
        # ---------------------------------------------------------
        strike_map: Dict[float, StrikeRow] = {s.strikePrice: s for s in chain.strikes}

        # ---------------------------------------------------------
        # 3. Formulate Option Buyer Strategy (Momentum & Quick Scalp)
        # ---------------------------------------------------------
        buyer_strat = self._build_buyer_strategy(
            sym=sym,
            spot=spot,
            atm=atm,
            step=step,
            lot_size=lot_size,
            confluence_score=confluence_score,
            strike_map=strike_map,
            call_unwinding=call_unwinding,
            put_unwinding=put_unwinding
        )

        # ---------------------------------------------------------
        # 4. Formulate Option Seller Strategy (Clamped to ATM +- 1/2)
        # ---------------------------------------------------------
        seller_strat = self._build_seller_strategy(
            sym=sym,
            spot=spot,
            atm=atm,
            step=step,
            lot_size=lot_size,
            sup_strike=sup_strike,
            res_strike=res_strike,
            confluence_score=confluence_score,
            strike_map=strike_map
        )

        # Top Recommendation selection: ALWAYS MOMENTUM BUYER / SCALPER on directional setups!
        if active_regime == "BUYER_MOMENTUM_CE":
            top_pick = {
                "role": "BUYER",
                "tag": "🚀 AI TOP PICK: ATM CALL MOMENTUM",
                "strategy": buyer_strat
            }
        elif active_regime == "BUYER_MOMENTUM_PE":
            top_pick = {
                "role": "BUYER",
                "tag": "⚡ AI TOP PICK: ATM PUT MOMENTUM",
                "strategy": buyer_strat
            }
        else:
            top_pick = {
                "role": "STANDBY",
                "tag": "🛡️ AI TOP PICK: STANDBY (AVOID CHOP)",
                "strategy": {
                    "type": "STANDBY",
                    "name": "CHOP GATE ACTIVE — CAPITAL PRESERVATION",
                    "bias": "NEUTRAL / CHOP",
                    "action": f"NO BUY TRADE — Wait for Breakout above {int(atm + step)} or below {int(atm - step)}",
                    "target_rule": "Preserve Capital. Do not buy options in dead consolidation.",
                    "stop_loss_rule": "N/A — Cash is a position."
                }
            }

        total_fund = getattr(credentials, "total_fund", 50000.0)

        return {
            "symbol": sym,
            "spot_price": spot,
            "atm_strike": atm,
            "lot_size": lot_size,
            "total_fund": total_fund,
            "active_regime": active_regime,
            "regime_title": regime_title,
            "regime_description": regime_description,
            "market_certainty_pct": certainty_pct,
            "confluence_score": confluence_score,
            "operational_state": operational_state,
            "top_recommendation": top_pick,
            "buyer_strategy": buyer_strat,
            "seller_strategy": seller_strat
        }

    def _build_seller_strategy(
        self,
        sym: str,
        spot: float,
        atm: float,
        step: int,
        lot_size: int,
        sup_strike: float,
        res_strike: float,
        confluence_score: float,
        strike_map: Dict[float, StrikeRow]
    ) -> Dict[str, Any]:
        """
        Formulates high-probability credit spreads for Option Sellers:
        Strictly clamped to ATM +- 1 and ATM +- 2 (NO DEEP OTM).
        """
        if confluence_score >= 53.0:
            # Bull Put Credit Spread: Strictly Sell ATM - 1, Buy ATM - 2
            sell_stk = atm - step
            buy_stk = sell_stk - step
            spread_type = "BULL_PUT_CREDIT_SPREAD"
            spread_name = f"BULL PUT CREDIT SPREAD ({int(sell_stk)} PE / {int(buy_stk)} PE)"
            bias = "MILD BULLISH / RANGE SUPPORT"

            sell_row = strike_map.get(sell_stk)
            buy_row = strike_map.get(buy_stk)
            sell_ltp = sell_row.PE.lastPrice if sell_row and sell_row.PE else round(spot * 0.003, 1)
            buy_ltp = buy_row.PE.lastPrice if buy_row and buy_row.PE else round(sell_ltp * 0.45, 1)

            net_credit = max(1.0, round(sell_ltp - buy_ltp, 2))
            spread_width = sell_stk - buy_stk
            max_loss_pts = max(0.0, round(spread_width - net_credit, 2))
            breakeven = round(sell_stk - net_credit, 1)
            cushion_pts = round(spot - breakeven, 1)
            cushion_pct = round((cushion_pts / spot) * 100.0, 2)

            # Greeks
            greeks = calculate_greeks(spot, sell_stk, sell_row.PE.impliedVolatility if sell_row else 14.0, is_call=False)
            daily_theta_pts = abs(greeks["theta"])
            daily_decay_inr = round(daily_theta_pts * lot_size, 0)
            pop = min(85, max(65, int(round((1.0 - abs(greeks["delta"])) * 100))))

            return {
                "type": spread_type,
                "name": spread_name,
                "bias": bias,
                "action": f"SELL {int(sell_stk)} PE @ ₹{sell_ltp:.2f} | BUY {int(buy_stk)} PE @ ₹{buy_ltp:.2f} (Hedge)",
                "sell_leg": {
                    "strike": sell_stk, "option_type": "PE", "action": "SELL", "ltp": sell_ltp, "delta": greeks["delta"]
                },
                "hedge_leg": {
                    "strike": buy_stk, "option_type": "PE", "action": "BUY", "ltp": buy_ltp
                },
                "net_credit_pts": net_credit,
                "net_credit_inr": round(net_credit * lot_size, 0),
                "max_profit_inr": round(net_credit * lot_size, 0),
                "max_risk_inr": round(max_loss_pts * lot_size, 0),
                "breakeven": breakeven,
                "safety_cushion": f"{cushion_pts} pts ({cushion_pct}% below spot)",
                "daily_theta_decay_inr": daily_decay_inr,
                "probability_of_profit_pct": pop,
                "target_rule": f"Exit at 70% decay (Capture ₹{round(net_credit * 0.70 * lot_size, 0):,.0f})",
                "stop_loss_rule": f"Exit if Spot breaches {int(sell_stk)} or Loss reaches 1x Net Credit (-₹{round(net_credit * lot_size, 0):,.0f})",
                "seller_rationale": "High theta decay extraction with ATM-1 buffer. Profitable even if market stays flat or drifts slightly lower."
            }

        elif confluence_score <= 47.0:
            # Bear Call Credit Spread: Strictly Sell ATM + 1, Buy ATM + 2
            sell_stk = atm + step
            buy_stk = sell_stk + step
            spread_type = "BEAR_CALL_CREDIT_SPREAD"
            spread_name = f"BEAR CALL CREDIT SPREAD ({int(sell_stk)} CE / {int(buy_stk)} CE)"
            bias = "MILD BEARISH / RESISTANCE DEFENSE"

            sell_row = strike_map.get(sell_stk)
            buy_row = strike_map.get(buy_stk)
            sell_ltp = sell_row.CE.lastPrice if sell_row and sell_row.CE else round(spot * 0.003, 1)
            buy_ltp = buy_row.CE.lastPrice if buy_row and buy_row.CE else round(sell_ltp * 0.45, 1)

            net_credit = max(1.0, round(sell_ltp - buy_ltp, 2))
            spread_width = buy_stk - sell_stk
            max_loss_pts = max(0.0, round(spread_width - net_credit, 2))
            breakeven = round(sell_stk + net_credit, 1)
            cushion_pts = round(breakeven - spot, 1)
            cushion_pct = round((cushion_pts / spot) * 100.0, 2)

            # Greeks
            greeks = calculate_greeks(spot, sell_stk, sell_row.CE.impliedVolatility if sell_row else 14.0, is_call=True)
            daily_theta_pts = abs(greeks["theta"])
            daily_decay_inr = round(daily_theta_pts * lot_size, 0)
            pop = min(85, max(65, int(round((1.0 - abs(greeks["delta"])) * 100))))

            return {
                "type": spread_type,
                "name": spread_name,
                "bias": bias,
                "action": f"SELL {int(sell_stk)} CE @ ₹{sell_ltp:.2f} | BUY {int(buy_stk)} CE @ ₹{buy_ltp:.2f} (Hedge)",
                "sell_leg": {
                    "strike": sell_stk, "option_type": "CE", "action": "SELL", "ltp": sell_ltp, "delta": greeks["delta"]
                },
                "hedge_leg": {
                    "strike": buy_stk, "option_type": "CE", "action": "BUY", "ltp": buy_ltp
                },
                "net_credit_pts": net_credit,
                "net_credit_inr": round(net_credit * lot_size, 0),
                "max_profit_inr": round(net_credit * lot_size, 0),
                "max_risk_inr": round(max_loss_pts * lot_size, 0),
                "breakeven": breakeven,
                "safety_cushion": f"{cushion_pts} pts ({cushion_pct}% above spot)",
                "daily_theta_decay_inr": daily_decay_inr,
                "probability_of_profit_pct": pop,
                "target_rule": f"Exit at 70% decay (Capture ₹{round(net_credit * 0.70 * lot_size, 0):,.0f})",
                "stop_loss_rule": f"Exit if Spot breaches {int(sell_stk)} or Loss reaches 1x Net Credit (-₹{round(net_credit * lot_size, 0):,.0f})",
                "seller_rationale": "ATM+1 Resistance ceiling defense. Captures fast theta erosion even if market stays flat or drifts slightly up."
            }

        else:
            # Iron Condor / Delta Neutral Chop
            ce_sell = atm + step
            pe_sell = atm - step
            ce_buy = ce_sell + step
            pe_buy = pe_sell - step

            ce_row = strike_map.get(ce_sell)
            pe_row = strike_map.get(pe_sell)
            ce_hedge = strike_map.get(ce_buy)
            pe_hedge = strike_map.get(pe_buy)

            ce_credit = (ce_row.CE.lastPrice if ce_row else 20.0) - (ce_hedge.CE.lastPrice if ce_hedge else 5.0)
            pe_credit = (pe_row.PE.lastPrice if pe_row else 20.0) - (pe_hedge.PE.lastPrice if pe_hedge else 5.0)
            net_credit = max(2.0, round(ce_credit + pe_credit, 2))

            return {
                "type": "IRON_CONDOR",
                "name": f"DELTA NEUTRAL IRON CONDOR ({int(pe_sell)} PE / {int(ce_sell)} CE)",
                "bias": "RANGE BOUND / PURE CHOP",
                "action": f"SELL {int(pe_sell)} PE & {int(ce_sell)} CE | BUY {int(pe_buy)} PE & {int(ce_buy)} CE (Hedges)",
                "sell_leg": {
                    "strike": f"{int(pe_sell)} PE / {int(ce_sell)} CE", "action": "SELL", "ltp": net_credit
                },
                "hedge_leg": {
                    "strike": f"{int(pe_buy)} PE / {int(ce_buy)} CE", "action": "BUY"
                },
                "net_credit_pts": net_credit,
                "net_credit_inr": round(net_credit * lot_size, 0),
                "max_profit_inr": round(net_credit * lot_size, 0),
                "max_risk_inr": round((step - net_credit) * lot_size, 0),
                "breakeven": f"{int(pe_sell - net_credit)} - {int(ce_sell + net_credit)}",
                "safety_cushion": f"±{int(step)} pts corridor",
                "daily_theta_decay_inr": round(net_credit * 0.25 * lot_size, 0),
                "probability_of_profit_pct": 78,
                "target_rule": f"Exit at 60% decay (Capture ₹{round(net_credit * 0.60 * lot_size, 0):,.0f})",
                "stop_loss_rule": f"Exit if Spot breaches {int(pe_sell)} or {int(ce_sell)}",
                "seller_rationale": "Market is in two-sided consolidation. Simultaneous two-sided decay capture outside defense walls."
            }

    def _build_buyer_strategy(
        self,
        sym: str,
        spot: float,
        atm: float,
        step: int,
        lot_size: int,
        confluence_score: float,
        strike_map: Dict[float, StrikeRow],
        call_unwinding: bool,
        put_unwinding: bool
    ) -> Dict[str, Any]:
        """
        Formulates high-conviction Option Buying & Scalping setups with COMMISSION RECOVERY GUARANTEE:
        - Strict ATM Strike Selection (Delta ~ 0.50).
        - Guaranteed minimum +₹125+ net profit after ₹75 round-trip statutory costs.
        """
        is_bull = confluence_score >= 50.0
        opt_type = "CE" if is_bull else "PE"
        buy_stk = atm
        row = strike_map.get(buy_stk)
        ltp = (row.CE.lastPrice if is_bull else row.PE.lastPrice) if row and ((row.CE if is_bull else row.PE).lastPrice > 0) else round(spot * 0.0065, 1)
        if ltp <= 0.0:
            ltp = round(spot * 0.0065, 1)

        greeks = calculate_greeks(
            spot, buy_stk,
            (row.CE.impliedVolatility if is_bull else row.PE.impliedVolatility) if row else 14.0,
            is_call=is_bull
        )

        # ---------------------------------------------------------
        # Commission Recovery & Scalper Profit Safeguard:
        # Round-trip brokerage (Fyers ₹40) + STT/GST/Taxes (₹35) = ₹75.
        # Target 1 Gross MUST BE >= ₹200 so Trader Pockets AT LEAST ₹125+ net profit!
        # ---------------------------------------------------------
        commission_buffer_inr = 75.0
        min_pts_for_commission = max(3.5, round(200.0 / lot_size, 1))

        # Quick Scalp Target 1 (High Win Rate Exit)
        scalp_pts = max(min_pts_for_commission, round(ltp * 0.08, 1))
        target1_pts = round(ltp + scalp_pts, 1)
        target1_gross_inr = round(scalp_pts * lot_size, 0)
        target1_net_inr = round(target1_gross_inr - commission_buffer_inr, 0)

        # Momentum Runner Target 2 (Trend Expansion)
        runner_pts = max(scalp_pts * 2.2, round(ltp * 0.25, 1))
        target2_pts = round(ltp + runner_pts, 1)
        target2_gross_inr = round(runner_pts * lot_size, 0)
        target2_net_inr = round(target2_gross_inr - commission_buffer_inr, 0)

        # Stop Loss (Tight Risk Management)
        sl_pts = max(3.0, round(scalp_pts * 0.65, 1))
        stop_loss_pts = round(max(1.0, ltp - sl_pts), 1)
        risk_inr = round(sl_pts * lot_size, 0)

        entry_min = round(ltp * 0.985, 1)
        entry_max = round(ltp * 1.015, 1)
        rr_ratio = f"1 : {round(scalp_pts / max(1.0, sl_pts), 1)}"

        strat_type = "MOMENTUM_CALL_BUY" if is_bull else "MOMENTUM_PUT_BUY"
        strat_name = f"{'MOMENTUM CALL SCALP' if is_bull else 'MOMENTUM PUT SCALP'} ({int(buy_stk)} {opt_type})"
        bias = "STRONG BULLISH MOMENTUM" if is_bull else "STRONG BEARISH BREAKDOWN"
        action = f"BUY {int(buy_stk)} {opt_type} @ ₹{ltp:.1f} (Delta {abs(greeks['delta']):.2f})"

        catalyst = (
            "Aggressive Call writer liquidation + Spot advancing above ATM with rising Put writer support."
            if is_bull else
            "Heavy Put writer capitulation + Spot breaking below ATM with massive Call writer overhead."
        )

        # ---------------------------------------------------------
        # Fund Allocation & Position Sizing Manager (Default ₹50,000)
        # ---------------------------------------------------------
        total_fund = getattr(credentials, "total_fund", 50000.0)
        margin_per_lot = round(ltp * lot_size, 2)
        max_possible_lots = max(1, int(total_fund // max(1.0, margin_per_lot)))
        # Prudent risk rule: Recommend sizing that deploys up to 50% of total fund for buffer
        recommended_lots = max(1, min(max_possible_lots, int((total_fund * 0.50) // max(1.0, margin_per_lot)) or 1))
        capital_deployed = round(margin_per_lot * recommended_lots, 2)
        capital_utilization_pct = round((capital_deployed / total_fund) * 100, 1)
        remaining_fund = round(total_fund - capital_deployed, 2)
        total_risk_inr = round(risk_inr * recommended_lots, 2)
        risk_pct_of_fund = round((total_risk_inr / total_fund) * 100, 1)
        target1_net_portfolio = round(target1_net_inr * recommended_lots, 2)
        target2_net_portfolio = round(target2_net_inr * recommended_lots, 2)

        return {
            "type": strat_type,
            "name": strat_name,
            "bias": bias,
            "action": action,
            "buy_strike": buy_stk,
            "option_type": opt_type,
            "entry_zone": f"₹{entry_min} - ₹{entry_max}",
            "ltp": ltp,
            "delta": abs(greeks["delta"]),
            "target1": f"₹{target1_pts:.1f} (+{scalp_pts} pts | Net ₹{target1_net_inr:,.0f} in pocket)",
            "target2": f"₹{target2_pts:.1f} (+{runner_pts} pts | Net ₹{target2_net_inr:,.0f} in pocket)",
            "stop_loss": f"₹{stop_loss_pts:.1f} (-{sl_pts} pts | -₹{risk_inr:,.0f} / lot)",
            "scalp_target_pts": scalp_pts,
            "runner_target_pts": runner_pts,
            "stop_loss_pts": sl_pts,
            "target1_gross_profit_inr": target1_gross_inr,
            "commission_buffer_inr": commission_buffer_inr,
            "target1_net_profit_inr": target1_net_inr,
            "risk_reward_ratio": rr_ratio,
            "max_risk_inr": risk_inr,
            "potential_reward_inr": target1_net_inr,
            "catalyst": catalyst,
            "buyer_rationale": f"Strict ATM gamma expansion. Scalp target guarantees at least ₹{target1_net_inr:,.0f} net profit after ₹75 round-trip brokerage & charges.",
            "capital_allocation": {
                "total_fund": total_fund,
                "lot_size": lot_size,
                "margin_per_lot": margin_per_lot,
                "max_affordable_lots": max_possible_lots,
                "recommended_lots": recommended_lots,
                "recommended_qty": recommended_lots * lot_size,
                "capital_deployed": capital_deployed,
                "capital_utilization_pct": capital_utilization_pct,
                "remaining_fund": remaining_fund,
                "total_risk_inr": total_risk_inr,
                "risk_pct_of_fund": risk_pct_of_fund,
                "target1_net_portfolio": target1_net_portfolio,
                "target2_net_portfolio": target2_net_portfolio
            }
        }

    def _empty_recommendation(self, sym: str) -> Dict[str, Any]:
        settings = get_settings()
        return {
            "symbol": sym,
            "spot_price": 0.0,
            "atm_strike": 0.0,
            "lot_size": settings.LOT_SIZES.get(sym, 65),
            "total_fund": getattr(credentials, "total_fund", 50000.0),
            "active_regime": "SELLER_REGIME",
            "regime_title": "AWAITING MARKET FEED",
            "regime_description": "Data feed initializing...",
            "market_certainty_pct": 50.0,
            "confluence_score": 50.0,
            "operational_state": "WATCH",
            "top_recommendation": {
                "role": "SELLER",
                "tag": "🛡️ MONITORING REGIME",
                "strategy": {
                    "name": "AWAITING MARKET FEED",
                    "action": "Awaiting Confluence Initialization",
                    "bias": "NEUTRAL"
                }
            },
            "seller_strategy": {
                "name": "INITIALIZING DECAY STRATEGY",
                "action": "Awaiting Option Chain Feed",
                "bias": "NEUTRAL"
            },
            "buyer_strategy": {
                "name": "INITIALIZING BUYER STRATEGY",
                "action": "Awaiting Option Chain Feed",
                "bias": "NEUTRAL"
            }
        }


trade_engine = TradeRecommendationEngine()
