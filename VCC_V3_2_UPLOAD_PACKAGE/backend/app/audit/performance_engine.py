"""
Performance Engine for VCC V3.2 Audit Architecture.
Aggregates win rate, loss rate, MFE, MAE, expectancy, and sample classifications.
Enforces statistical governance rule: N < 30 -> INSUFFICIENT SAMPLE.
"""
from typing import Dict, List, Any, Optional
from app.domain.contracts import SignalOutcome


class PerformanceEngine:
    """
    Dedicated Performance Aggregator.
    """

    @staticmethod
    def calculate_performance_metrics(outcomes: List[SignalOutcome]) -> Dict[str, Any]:
        # Filter directional evaluated outcomes
        directional_outcomes = [
            o for o in outcomes
            if o.outcome_evaluated and o.directional_correctness_30m in ["CORRECT", "INCORRECT"]
        ]

        sample_size = len(directional_outcomes)

        if sample_size < 30:
            sample_class = "INSUFFICIENT SAMPLE"
        elif sample_size < 100:
            sample_class = "LOW SAMPLE"
        elif sample_size < 300:
            sample_class = "MODERATE SAMPLE"
        else:
            sample_class = "HIGHER SAMPLE"

        if sample_size == 0:
            return {
                "total_samples": 0,
                "sample_classification": sample_class,
                "win_rate_pct": 0.0,
                "loss_rate_pct": 0.0,
                "avg_mfe_pct": 0.0,
                "avg_mae_pct": 0.0,
                "expectancy_pct": 0.0
            }

        wins = sum(1 for o in directional_outcomes if o.directional_correctness_30m == "CORRECT")
        losses = sum(1 for o in directional_outcomes if o.directional_correctness_30m == "INCORRECT")

        win_rate = round((wins / sample_size) * 100.0, 1)
        loss_rate = round((losses / sample_size) * 100.0, 1)

        mfe_list = [o.mfe_t30_pct for o in directional_outcomes if o.mfe_t30_pct is not None]
        mae_list = [o.mae_t30_pct for o in directional_outcomes if o.mae_t30_pct is not None]

        avg_mfe = round(sum(mfe_list) / len(mfe_list), 4) if mfe_list else 0.0
        avg_mae = round(sum(mae_list) / len(mae_list), 4) if mae_list else 0.0
        expectancy = round(((win_rate / 100.0) * avg_mfe) + ((loss_rate / 100.0) * avg_mae), 4)

        return {
            "total_samples": sample_size,
            "sample_classification": sample_class,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": win_rate,
            "loss_rate_pct": loss_rate,
            "avg_mfe_pct": avg_mfe,
            "avg_mae_pct": avg_mae,
            "expectancy_pct": expectancy
        }


performance_engine = PerformanceEngine()
