"""
Conflict Engine for VCC V3.2 Intelligence Layer.
Explicitly detects contradictory evidence between analytical models and data quality.
"""
from typing import Dict, List, Any, Tuple
from app.domain.contracts import DataQuality


class ConflictEngine:
    """
    Detects analytical conflicts and data quality violations.
    """

    @staticmethod
    def evaluate_conflicts(
        positioning_score: float,
        price_conf_score: float,
        breakout_status: str,
        data_quality: DataQuality
    ) -> Tuple[bool, str, List[str]]:
        is_conflict = False
        conflict_type = "NONE"
        conflict_details: List[str] = []

        # 1. Positioning vs Price Conflict
        if positioning_score >= 20 and price_conf_score <= -15:
            is_conflict = True
            conflict_type = "POSITIONING vs PRICE CONFLICT"
            conflict_details.append(
                f"Option positioning is Bullish (+{positioning_score:.0f}), but Spot price momentum is Bearish ({price_conf_score:.0f})."
            )
        elif positioning_score <= -20 and price_conf_score >= 15:
            is_conflict = True
            conflict_type = "POSITIONING vs PRICE CONFLICT"
            conflict_details.append(
                f"Option positioning is Bearish ({positioning_score:.0f}), but Spot price momentum is Bullish (+{price_conf_score:.0f})."
            )

        # 2. Breakout Signal vs Invalid Data Quality Conflict
        if breakout_status in ["UPSIDE BREAKOUT CONFIRMED", "DOWNSIDE BREAKDOWN CONFIRMED"] and data_quality == DataQuality.INVALID:
            is_conflict = True
            conflict_type = "BREAKOUT vs STALE DATA CONFLICT"
            conflict_details.append(
                "Breakout status reported while data quality is INVALID (stale feed or missing quotes)."
            )

        return is_conflict, conflict_type, conflict_details


conflict_engine = ConflictEngine()
