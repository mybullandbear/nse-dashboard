"""
Evidence Engine for VCC V3.2 Intelligence Layer.
Generates structured, explainable EvidenceItem list from analytical metrics.
"""
from typing import Dict, List, Any, Optional
from app.domain.contracts import SignalEvidence, MarketSnapshot


class EvidenceEngine:
    """
    Evaluates 11 explainability factors and constructs structured SignalEvidence objects.
    """

    @staticmethod
    def evaluate_evidence(
        positioning_score: float,
        price_conf_score: float,
        pcr_val: float,
        pcr_5m_prev: float,
        wall_interaction_score: float,
        spot_chg_open_pct: float,
        spot_15m_chg: float,
        breakout_pressure: float,
        pe_oi_5: float,
        ce_oi_5: float,
        accel_score: float
    ) -> List[SignalEvidence]:
        evidences: List[SignalEvidence] = []

        # 1. Option Positioning
        if abs(positioning_score) >= 15:
            direction = "BULLISH" if positioning_score > 0 else "BEARISH"
            evidences.append(SignalEvidence(
                factor_name="Option Positioning",
                direction=direction,
                weight=0.35,
                contribution_score=abs(positioning_score),
                value_str=f"{positioning_score:+.0f}",
                is_supportive=True,
                explanation=f"Option positioning is {direction} with score {positioning_score:+.0f}."
            ))

        # 2. Price Confirmation
        if abs(price_conf_score) >= 10:
            direction = "BULLISH" if price_conf_score > 0 else "BEARISH"
            evidences.append(SignalEvidence(
                factor_name="Price Confirmation",
                direction=direction,
                weight=0.30,
                contribution_score=abs(price_conf_score),
                value_str=f"{price_conf_score:+.0f}",
                is_supportive=True,
                explanation=f"Spot price momentum confirmation is {direction} at {price_conf_score:+.0f}."
            ))

        # 3. PCR Level
        pcr_dir = "BULLISH" if pcr_val >= 1.0 else "BEARISH"
        evidences.append(SignalEvidence(
            factor_name="PCR Level",
            direction=pcr_dir,
            weight=0.10,
            contribution_score=70.0 if pcr_val >= 1.0 else 30.0,
            value_str=f"{pcr_val:.2f}",
            is_supportive=True,
            explanation=f"PCR level is {pcr_val:.2f} ({'Bullish Put support' if pcr_val >= 1.0 else 'Bearish Call dominance'})."
        ))

        # 4. PCR Momentum
        pcr_chg = pcr_val - pcr_5m_prev
        if abs(pcr_chg) >= 0.02:
            pcr_mom_dir = "BULLISH" if pcr_chg > 0 else "BEARISH"
            evidences.append(SignalEvidence(
                factor_name="PCR Momentum",
                direction=pcr_mom_dir,
                weight=0.05,
                contribution_score=60.0,
                value_str=f"{pcr_chg:+.2f}",
                is_supportive=True,
                explanation=f"PCR 5m change is {pcr_chg:+.2f} indicating {pcr_mom_dir} momentum."
            ))

        # 5. Wall Interaction
        if wall_interaction_score != 0:
            w_dir = "BULLISH" if wall_interaction_score > 0 else "BEARISH"
            evidences.append(SignalEvidence(
                factor_name="Wall Interaction",
                direction=w_dir,
                weight=0.15,
                contribution_score=abs(wall_interaction_score),
                value_str=f"{wall_interaction_score:+.0f}",
                is_supportive=True,
                explanation=f"Wall interaction score is {wall_interaction_score:+.0f} ({w_dir})."
            ))

        # 6. Breakout Pressure
        if breakout_pressure >= 65:
            evidences.append(SignalEvidence(
                factor_name="Breakout Pressure",
                direction="BULLISH",
                weight=0.10,
                contribution_score=breakout_pressure,
                value_str=f"{breakout_pressure}/100",
                is_supportive=True,
                explanation=f"Breakout pressure score is elevated at {breakout_pressure}/100."
            ))

        return evidences


evidence_engine = EvidenceEngine()
