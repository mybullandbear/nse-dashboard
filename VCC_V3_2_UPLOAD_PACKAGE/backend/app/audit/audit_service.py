"""
Immutable Audit Service for VCC V3.2.
Persists immutable signal snapshots representing system knowledge at time T.
"""
from typing import Dict, Any, Optional
from datetime import datetime
from app.domain.contracts import MarketSnapshot, SignalDecision, DataQuality
from app.repositories.sqlalchemy_repository import audit_repository
from app.services.market_hours import IST


class ImmutableAuditService:

    @staticmethod
    def record_signal_snapshot(
        snapshot: MarketSnapshot,
        decision: SignalDecision,
        positioning_score: float,
        price_conf_score: float,
        net_flow_lakhs: float,
        pcr: float,
        support_wall: float,
        resistance_wall: float,
        breakout_status: str,
        now_dt: Optional[datetime] = None
    ) -> str:
        from app.config import get_settings
        from app.services.market_hours import is_market_open
        from app.domain.contracts import DataStatus
        settings = get_settings()

        is_sim_mode = settings.VCC_SIMULATION_MODE
        is_real_data = getattr(snapshot.metadata, "is_real_data", False)
        data_status = getattr(snapshot.metadata, "data_status", DataStatus.UNKNOWN)

        is_valid_live = (
            is_market_open()
            and is_real_data
            and data_status in [DataStatus.REAL_LIVE, DataStatus.REAL_RECENT]
            and snapshot.quality != DataQuality.INVALID
        )

        if snapshot.metadata.source_name == "SIMULATED" or not is_real_data or snapshot.quality == DataQuality.INVALID:
            # Reject persisting audit snapshots from synthetic/simulated/invalid data
            return ""

        if not is_sim_mode and not is_valid_live:
            # Reject persisting audit snapshots outside live market hours or stale data
            return ""

        dt = now_dt or datetime.now(IST)
        timestamp_str = dt.isoformat()
        date_str = dt.strftime("%Y-%m-%d")
        snapshot_id = f"SNAP_{snapshot.symbol}_{dt.strftime('%Y%m%d_%H%M%S_%f')[:22]}"

        audit_dict = {
            "snapshot_id": snapshot_id,
            "trade_date": date_str,
            "timestamp": timestamp_str,
            "symbol": snapshot.symbol.upper(),
            "session_slot": "09:15-15:45",
            "spot_price": snapshot.spot.spot_price,
            "option_chain_timestamp": snapshot.metadata.option_timestamp or timestamp_str,
            "spot_timestamp": snapshot.metadata.spot_timestamp or timestamp_str,
            "option_data_age_sec": snapshot.metadata.option_data_age_sec,
            "spot_data_age_sec": snapshot.metadata.spot_data_age_sec,
            "data_quality_status": snapshot.quality.value,
            "positioning_score": positioning_score,
            "price_confirmation_score": price_conf_score,
            "final_confluence_score": decision.confluence_score,
            "confluence_label": decision.market_regime,
            "directional_flow_label": f"{'+' if net_flow_lakhs >= 0 else ''}{net_flow_lakhs:.1f}L {'BULLISH' if net_flow_lakhs >= 0 else 'BEARISH'}",
            "net_flow_lakhs": net_flow_lakhs,
            "pe_flow_lakhs": max(0.0, net_flow_lakhs),
            "ce_flow_lakhs": min(0.0, net_flow_lakhs),
            "total_activity_lakhs": abs(net_flow_lakhs),
            "pcr": pcr,
            "atm_straddle_premium": 0.0,
            "support_wall": support_wall,
            "resistance_wall": resistance_wall,
            "wall_migration_direction": "STABLE",
            "breakout_status": breakout_status,
            "range_compression_status": "NORMAL",
            "atm_pressure_score": 0.0,
            "operational_state": decision.operational_state,
            "market_regime": decision.market_regime,
            "signal_direction": decision.direction,
            "signal_lifecycle_stage": "CREATED",
            "lifetime_sec": 0.0,
            "evidence_count": len(decision.evidences),
            "conflict_count": len(decision.conflicts),
            "model_confidence": decision.confidence,
            "persistence_pct": decision.persistence_pct,
            "historical_sample_size": 30,
            "historical_reliability_pct": 85.0,
            "outcome_evaluated": 0,
            "created_at": datetime.now()
        }

        audit_repository.save_audit_snapshot(audit_dict)
        return snapshot_id


audit_service = ImmutableAuditService()
