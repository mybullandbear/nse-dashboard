"""
Five-Pillar Trade Quality Score (TQS) Calculator
Independent, quantitative institutional evaluation of option buying trade candidates.
Decoupled from raw Option Confluence Score.

Formulation:
    TQS (0 to 100) = P1_Signal (25) + P2_Strike (20) + P3_Liquidity (20) + P4_Momentum (20) + P5_RiskReward (15)

Thresholds:
    - Buyer Minimum TQS: 70.0 (High-conviction directional breakout)
    - Seller Minimum TQS: 66.0 (Defensive premium decay)
"""
import logging
from typing import Dict, Any, Optional, Tuple
from app.services.option_chain import ParsedOptionChain, StrikeRow
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class TradeQualityScoreService:
    """
    Computes independent, multi-factor Trade Quality Score (TQS)
    for option contracts across 5 distinct quantitative pillars.
    """

    BUYER_MIN_TQS: float = 70.0
    SELLER_MIN_TQS: float = 66.0

    @classmethod
    def compute_tqs(
        cls,
        symbol: str,
        chain: ParsedOptionChain,
        contract_row: Optional[StrikeRow],
        option_type: str,
        role: str = "BUYER",
        confluence_score: float = 50.0,
        technical_state: Optional[Dict[str, Any]] = None,
        target_pts: float = 0.0,
        risk_pts: float = 0.0
    ) -> Tuple[float, Dict[str, float]]:
        """
        Computes 5-pillar TQS score and component breakdown.
        Guarantees that missing data does not silently receive positive bias.
        """
        spot = chain.spot_price if chain else 0.0
        atm = chain.atm_strike if chain else 0.0
        pcr = chain.pcr if chain else 1.0
        step = get_settings().STRIKE_STEPS.get(symbol.upper(), 50)

        # -------------------------------------------------------------
        # Pillar 1: Signal Confluence Disparity (0 to 25 pts)
        # Measures distance from neutral 50 anchor.
        # Extreme conviction (>= 75 or <= 25) receives max score.
        # -------------------------------------------------------------
        p1 = 0.0
        if confluence_score is not None and 0.0 <= confluence_score <= 100.0:
            dist = abs(confluence_score - 50.0)
            if dist >= 25.0:       # >= 75 or <= 25
                p1 = 25.0
            elif dist >= 18.0:     # >= 68 or <= 32
                p1 = 20.0
            elif dist >= 12.0:     # >= 62 or <= 38
                p1 = 15.0
            elif dist >= 3.0:
                p1 = 4.0
            else:
                p1 = 0.0           # Dead neutral chop (dist < 3.0) has 0 conviction
        else:
            p1 = 0.0

        # -------------------------------------------------------------
        # Pillar 2: Strike Quality & Moneyness Fit (0 to 20 pts)
        # Option buyers require delta sweet spot: ATM (0.50) or 1-ITM (0.55-0.65).
        # Far OTM contracts (< 0.30 delta) bleed theta and receive minimal score.
        # -------------------------------------------------------------
        p2 = 0.0
        if contract_row and spot > 0 and atm > 0:
            stk = contract_row.strikePrice
            diff_steps = round(abs(stk - atm) / step, 1)

            if role == "BUYER":
                if diff_steps <= 0.2:      # Exactly ATM
                    p2 = 20.0
                elif diff_steps <= 1.1:    # 1-step ITM or 1-step OTM
                    # Prefer 1-ITM over 1-OTM for buyers
                    is_itm = (option_type == "CE" and stk < atm) or (option_type == "PE" and stk > atm)
                    p2 = 18.0 if is_itm else 14.0
                elif diff_steps <= 2.1:    # 2-step
                    is_itm = (option_type == "CE" and stk < atm) or (option_type == "PE" and stk > atm)
                    p2 = 12.0 if is_itm else 8.0
                else:                      # Far OTM / Deep ITM
                    p2 = 4.0
            else:  # SELLER
                if 0.8 <= diff_steps <= 1.5:  # 1-1.5 step OTM short strike
                    p2 = 20.0
                elif diff_steps <= 2.0:
                    p2 = 15.0
                else:
                    p2 = 8.0
        else:
            p2 = 0.0

        # -------------------------------------------------------------
        # Pillar 3: Liquidity, Volume & Spread Depth (0 to 20 pts)
        # Prevents illiquid contracts with wide bid-ask spread slippage.
        # Missing OI or Volume gets 0 pts (never silently passed).
        # -------------------------------------------------------------
        p3 = 0.0
        if contract_row:
            contract = contract_row.CE if option_type == "CE" else contract_row.PE
            if contract:
                oi = contract.openInterest or 0
                vol = contract.totalTradedVolume or 0
                ltp = contract.lastPrice or 0.0

                # 3A. Open Interest (0 to 8 pts)
                if oi >= 100000:
                    p3_oi = 8.0
                elif oi >= 50000:
                    p3_oi = 6.0
                elif oi >= 20000:
                    p3_oi = 4.0
                elif oi >= 5000:
                    p3_oi = 2.0
                else:
                    p3_oi = 0.0

                # 3B. Traded Volume (0 to 6 pts)
                if vol >= 60000:
                    p3_vol = 6.0
                elif vol >= 25000:
                    p3_vol = 4.0
                elif vol >= 10000:
                    p3_vol = 2.0
                elif vol >= 2000:
                    p3_vol = 1.0
                else:
                    p3_vol = 0.0

                # 3C. Spread & Quote Depth Proxy (0 to 6 pts)
                # If active volume supports the contract and premium is >= 25, tight spread is assured.
                if ltp >= 50.0 and vol >= 10000:
                    p3_spread = 6.0
                elif ltp >= 25.0 and vol >= 5000:
                    p3_spread = 4.0
                elif ltp >= 15.0 and vol >= 1000:
                    p3_spread = 2.0
                else:
                    p3_spread = 0.0  # Zero volume or cheap contracts have huge % spread

                p3 = p3_oi + p3_vol + p3_spread
        else:
            p3 = 0.0

        # -------------------------------------------------------------
        # Pillar 4: Underlying & Option Momentum Alignment (0 to 20 pts)
        # Confirms technical trend: PineScript AlphaTrend, ADX velocity, spot alignment.
        # -------------------------------------------------------------
        p4 = 0.0
        tech = technical_state or {}
        ott_state = tech.get("ott_state", "NEUTRAL")
        adx = float(tech.get("adx", 0.0) or 0.0)
        td_strength = float(tech.get("trend_dir_strength", 0.0) or 0.0)

        if role == "BUYER":
            if option_type == "CE":
                # CE Buyer requires Bullish Trend
                if ott_state == "BULLISH":
                    p4 += 8.0
                elif ott_state == "NEUTRAL":
                    p4 += 2.0

                if adx >= 22.0:
                    p4 += 6.0
                elif adx >= 18.0:
                    p4 += 4.0

                if spot > atm or td_strength > 0:
                    p4 += 6.0
            else:  # PE
                # PE Buyer requires Bearish Trend
                if ott_state == "BEARISH":
                    p4 += 8.0
                elif ott_state == "NEUTRAL":
                    p4 += 2.0

                if adx >= 22.0:
                    p4 += 6.0
                elif adx >= 18.0:
                    p4 += 4.0

                if spot < atm or td_strength < 0:
                    p4 += 6.0
        else:  # SELLER
            if 0.85 <= pcr <= 1.15:
                p4 += 10.0
            if adx < 22.0:
                p4 += 10.0  # Low trend velocity is ideal for decay capture
            else:
                p4 += 5.0

        # -------------------------------------------------------------
        # Pillar 5: Risk/Reward Potential (0 to 15 pts)
        # Evaluates reward-to-risk ratio based on target and stop.
        # -------------------------------------------------------------
        p5 = 0.0
        if risk_pts > 0 and target_pts > 0:
            rr = target_pts / risk_pts
            if rr >= 1.7:
                p5 = 15.0
            elif rr >= 1.4:
                p5 = 11.0
            elif rr >= 1.1:
                p5 = 8.0
            elif rr >= 0.9:
                p5 = 5.0
            else:
                p5 = 2.0
        else:
            p5 = 0.0

        raw_tqs = p1 + p2 + p3 + p4 + p5
        total_tqs = round(max(0.0, min(100.0, raw_tqs)), 1)

        breakdown = {
            "p1_signal": round(p1, 1),
            "p2_strike": round(p2, 1),
            "p3_liquidity": round(p3, 1),
            "p4_momentum": round(p4, 1),
            "p5_risk_reward": round(p5, 1),
            "total": total_tqs
        }

        return total_tqs, breakdown


tqs_service = TradeQualityScoreService()
