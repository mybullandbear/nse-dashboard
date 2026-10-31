"""
SQLAlchemy Repository Implementation for VCC V3.2.
Encapsulates SQL and ORM queries away from core analytical and signal logic.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.repositories.base import (
    SignalRepository,
    AuditRepository,
    OutcomeRepository,
    PerformanceRepository
)
from app.db.database import SessionLocal
from app.db.models import VCCLiveSignalAuditModel, DailyMarketSnapshotModel
from app.domain.contracts import SignalDecision, SignalOutcome


class SQLAlchemyAuditRepository(AuditRepository):

    def save_audit_snapshot(self, audit_dict: Dict[str, Any]) -> str:
        db = SessionLocal()
        try:
            snapshot_id = audit_dict.get("snapshot_id") or f"SNAP_{audit_dict.get('symbol')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            audit_dict["snapshot_id"] = snapshot_id

            # Filter fields matching VCCLiveSignalAuditModel columns
            valid_cols = {c.name for c in VCCLiveSignalAuditModel.__table__.columns}
            filtered_data = {k: v for k, v in audit_dict.items() if k in valid_cols}

            existing = db.query(VCCLiveSignalAuditModel).filter(VCCLiveSignalAuditModel.snapshot_id == snapshot_id).first()
            if not existing:
                record = VCCLiveSignalAuditModel(**filtered_data)
                db.add(record)
                db.commit()
            return snapshot_id
        except Exception:
            db.rollback()
            return audit_dict.get("snapshot_id", "")
        finally:
            db.close()

    def get_audit_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            rec = db.query(VCCLiveSignalAuditModel).filter(VCCLiveSignalAuditModel.snapshot_id == snapshot_id).first()
            if not rec:
                return None
            return {c.name: getattr(rec, c.name) for c in rec.__table__.columns}
        finally:
            db.close()

    def get_unevaluated_snapshots(self, symbol: str) -> List[Dict[str, Any]]:
        db = SessionLocal()
        try:
            recs = (
                db.query(VCCLiveSignalAuditModel)
                .filter(
                    VCCLiveSignalAuditModel.symbol == symbol.upper(),
                    VCCLiveSignalAuditModel.outcome_evaluated == 0
                )
                .order_by(VCCLiveSignalAuditModel.timestamp.asc())
                .all()
            )
            return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in recs]
        finally:
            db.close()


class SQLAlchemyOutcomeRepository(OutcomeRepository):

    def save_outcome(self, outcome: SignalOutcome) -> None:
        self.update_audit_outcome(outcome.snapshot_id, outcome.model_dump())

    def update_audit_outcome(self, snapshot_id: str, outcome_dict: Dict[str, Any]) -> None:
        db = SessionLocal()
        try:
            rec = db.query(VCCLiveSignalAuditModel).filter(VCCLiveSignalAuditModel.snapshot_id == snapshot_id).first()
            if rec:
                rec.outcome_evaluated = 1
                for k, v in outcome_dict.items():
                    if hasattr(rec, k) and v is not None:
                        setattr(rec, k, v)
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()


class SQLAlchemyPerformanceRepository(PerformanceRepository):

    def get_performance_stats(self, symbol: str) -> Dict[str, Any]:
        db = SessionLocal()
        try:
            sym = symbol.upper()
            all_recs = db.query(VCCLiveSignalAuditModel).filter(VCCLiveSignalAuditModel.symbol == sym).all() if sym != "ALL" else db.query(VCCLiveSignalAuditModel).all()
            
            total_all = len(all_recs)
            valid_count = sum(1 for r in all_recs if getattr(r, "data_quality_status", "GOOD") != "INVALID")
            invalid_count = total_all - valid_count
            
            eval_recs = [r for r in all_recs if getattr(r, "outcome_evaluated", 0) == 1]
            total_eval = len(eval_recs)
            pending_count = total_all - total_eval
            
            avg_conf = (sum(r.model_confidence for r in all_recs if r.model_confidence) / max(1, len(all_recs))) if all_recs else 50.0
            
            wins = sum(1 for r in eval_recs if r.directional_correctness_30m == "CORRECT")
            losses = sum(1 for r in eval_recs if r.directional_correctness_30m == "INCORRECT")
            neutral_count = sum(1 for r in eval_recs if r.directional_correctness_30m in ["EXCLUDED_NON_DIRECTIONAL", "NEUTRAL", "PENDING"])
            
            directional_total = wins + losses
            win_rate = round((wins / directional_total) * 100.0, 1) if directional_total > 0 else 0.0
            
            if directional_total < 30:
                sample_class = "INSUFFICIENT SAMPLE"
            elif directional_total < 100:
                sample_class = "LOW SAMPLE"
            elif directional_total < 300:
                sample_class = "MODERATE SAMPLE"
            else:
                sample_class = "HIGHER SAMPLE"
                
            t5_wins = sum(1 for r in eval_recs if getattr(r, "directional_correctness_5m", None) == "CORRECT")
            t5_losses = sum(1 for r in eval_recs if getattr(r, "directional_correctness_5m", None) == "INCORRECT")
            t5_eval = t5_wins + t5_losses
            t5_acc = round((t5_wins / t5_eval) * 100.0, 1) if t5_eval > 0 else 0.0
            
            t15_wins = sum(1 for r in eval_recs if getattr(r, "directional_correctness_15m", None) == "CORRECT")
            t15_losses = sum(1 for r in eval_recs if getattr(r, "directional_correctness_15m", None) == "INCORRECT")
            t15_eval = t15_wins + t15_losses
            t15_acc = round((t15_wins / t15_eval) * 100.0, 1) if t15_eval > 0 else 0.0
            
            mfe_vals = [r.mfe_t30_pct for r in eval_recs if getattr(r, "mfe_t30_pct", None) is not None]
            mae_vals = [r.mae_t30_pct for r in eval_recs if getattr(r, "mae_t30_pct", None) is not None]
            
            avg_mfe = round(sum(mfe_vals) / len(mfe_vals), 4) if mfe_vals else 0.0
            avg_mae = round(sum(mae_vals) / len(mae_vals), 4) if mae_vals else 0.0
            
            return {
                "symbol": sym,
                "total_samples": directional_total,
                "total_signals": total_all,
                "valid_signals": valid_count,
                "invalid_signals": invalid_count,
                "evaluated_signals": total_eval,
                "pending_signals": pending_count,
                "correct_signals": wins,
                "false_signals": losses,
                "neutral_signals": neutral_count,
                "win_rate_pct": win_rate,
                "accuracy_pct": win_rate,
                "reliability_pct": win_rate,
                "sample_classification": sample_class,
                "min_governance_threshold": 30,
                "t5_stats": {"evaluated": t5_eval, "correct": t5_wins, "false": t5_losses, "accuracy_pct": t5_acc},
                "t15_stats": {"evaluated": t15_eval, "correct": t15_wins, "false": t15_losses, "accuracy_pct": t15_acc},
                "t30_stats": {"evaluated": directional_total, "correct": wins, "false": losses, "accuracy_pct": win_rate},
                "mfe_avg_pct": avg_mfe,
                "mae_avg_pct": avg_mae,
                "confidence_calibration": {
                    "avg_model_confidence": round(avg_conf, 1),
                    "analytical_certainty_label": "MODEL ANALYTICAL CERTAINTY (NOT WIN PROBABILITY)"
                }
            }
        finally:
            db.close()


audit_repository = SQLAlchemyAuditRepository()
outcome_repository = SQLAlchemyOutcomeRepository()
performance_repository = SQLAlchemyPerformanceRepository()
