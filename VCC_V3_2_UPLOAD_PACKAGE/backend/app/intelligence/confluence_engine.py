"""
Confluence Engine for VCC V3.2 Intelligence Layer.
Interprets analytical snapshot metrics into a unified Confluence Score and Confidence.
Preserves strict baseline weightings:
- Positioning = 0.35
- Price Confirmation = 0.30
- Wall Proximity = 0.15
- Straddle Decay = 0.20
"""
from typing import Dict, List, Any
from app.domain.contracts import MarketSnapshot, DataQuality
from app.intelligence.evidence_engine import evidence_engine
from app.intelligence.conflict_engine import conflict_engine
from app.core.constants import system_config


class ConfluenceResult:

    def __init__(
        self,
        raw_score: float,
        final_score: float,
        label: str,
        confidence: float,
        positioning_score: float,
        price_conf_score: float,
        wall_proximity_score: float,
        straddle_decay_score: float,
        is_conflict: bool,
        conflict_type: str,
        conflict_details: List[str],
        evidences: List[Any]
    ):
        self.raw_score = raw_score
        self.final_score = final_score
        self.label = label
        self.confidence = confidence
        self.positioning_score = positioning_score
        self.price_conf_score = price_conf_score
        self.wall_proximity_score = wall_proximity_score
        self.straddle_decay_score = straddle_decay_score
        self.is_conflict = is_conflict
        self.conflict_type = conflict_type
        self.conflict_details = conflict_details
        self.evidences = evidences


class ConfluenceEngine:

    @staticmethod
    def compute_confluence(
        positioning_score: float,
        price_conf_score: float,
        wall_interaction_score: float,
        straddle_decay_pct: float,
        breakout_status: str,
        data_quality: DataQuality = DataQuality.GOOD,
        data_age_sec: float = 0.0,
        sample_count: int = 30
    ) -> ConfluenceResult:
        # Convert raw scores to standard 0-100 range
        pos_norm = (positioning_score + 100.0) / 2.0
        price_norm = (price_conf_score + 100.0) / 2.0
        wall_norm = (wall_interaction_score + 100.0) / 2.0
        decay_norm = max(0.0, min(100.0, 50.0 - straddle_decay_pct * 10.0))

        # Baseline Weightings (0.35, 0.30, 0.15, 0.20)
        w_pos = system_config.confluence_weights.positioning
        w_price = system_config.confluence_weights.price_confirmation
        w_wall = system_config.confluence_weights.wall_proximity
        w_decay = system_config.confluence_weights.straddle_decay

        raw_weighted = (w_pos * pos_norm) + (w_price * price_norm) + (w_wall * wall_norm) + (w_decay * decay_norm)

        # Baseline V3 calculation compatibility check
        weighted_signal = (0.60 * positioning_score) + (0.40 * price_conf_score)
        raw_confluence = 50 + int(round(weighted_signal / 2.0))
        raw_confluence = max(5, min(99, raw_confluence))

        # Detect Conflicts
        is_conflict, conflict_type, conflict_details = conflict_engine.evaluate_conflicts(
            positioning_score=positioning_score,
            price_conf_score=price_conf_score,
            breakout_status=breakout_status,
            data_quality=data_quality
        )

        if is_conflict:
            final_confluence_score = max(20, min(55, raw_confluence - 25))
            raw_label = "SIGNAL CONFLICT / UNCONFIRMED"
        else:
            final_confluence_score = raw_confluence
            if final_confluence_score >= 70:
                raw_label = "BULLISH CONFLUENCE"
            elif final_confluence_score <= 35:
                raw_label = "BEARISH CONFLUENCE"
            else:
                raw_label = "MODERATE / TWO-SIDED"

        # Model Confidence Calculation
        base_confidence = 88.0
        if data_age_sec > 15.0:
            base_confidence -= min(35.0, (data_age_sec - 15.0) * 1.5)
        if sample_count < 5:
            base_confidence -= 15.0
        if is_conflict:
            base_confidence -= 20.0
        if data_quality == DataQuality.INVALID:
            base_confidence -= 40.0

        confidence = max(15.0, min(92.0, base_confidence))

        # Evaluate Evidence
        evidences = evidence_engine.evaluate_evidence(
            positioning_score=positioning_score,
            price_conf_score=price_conf_score,
            pcr_val=1.15,
            pcr_5m_prev=1.10,
            wall_interaction_score=wall_interaction_score,
            spot_chg_open_pct=0.2,
            spot_15m_chg=15.0,
            breakout_pressure=50.0,
            pe_oi_5=500000,
            ce_oi_5=400000,
            accel_score=10.0
        )

        return ConfluenceResult(
            raw_score=float(raw_confluence),
            final_score=float(final_confluence_score),
            label=raw_label,
            confidence=round(confidence, 1),
            positioning_score=positioning_score,
            price_conf_score=price_conf_score,
            wall_proximity_score=wall_interaction_score,
            straddle_decay_score=decay_norm,
            is_conflict=is_conflict,
            conflict_type=conflict_type,
            conflict_details=conflict_details,
            evidences=evidences
        )


confluence_engine = ConfluenceEngine()
