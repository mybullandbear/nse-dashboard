"""
Outcome Repository for VCC V3.2 Persistence Layer.
Manages updates and queries for retrospective outcome evaluation records.
Decouples domain logic from SQLAlchemy.
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models import VCCLiveSignalAuditModel, SignalOutcomeRecordModel
from app.domain.contracts import SignalOutcome


class OutcomeRepository:

    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    def save_outcome(self, outcome: SignalOutcome) -> None:
        self.update_audit_outcome(outcome.snapshot_id, outcome.model_dump())

    def update_audit_outcome(self, snapshot_id: str, outcome_dict: Dict[str, Any]) -> bool:
        db: Session = self.session_factory()
        try:
            rec = db.query(VCCLiveSignalAuditModel).filter(VCCLiveSignalAuditModel.snapshot_id == snapshot_id).first()
            if rec:
                rec.outcome_evaluated = 1
                for k, v in outcome_dict.items():
                    if hasattr(rec, k) and v is not None:
                        setattr(rec, k, v)
                db.commit()
                return True
            return False
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()


outcome_repository = OutcomeRepository()
