"""
Audit Repository for VCC V3.2 Persistence Layer.
Manages creation, immutable queries, and governance checks on VCCLiveSignalAuditModel records.
Decouples domain logic from SQLAlchemy.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models import VCCLiveSignalAuditModel


class AuditRepository:

    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    def save_audit_snapshot(self, audit_dict: Dict[str, Any]) -> str:
        db: Session = self.session_factory()
        try:
            snapshot_id = audit_dict.get("snapshot_id") or f"SNAP_{audit_dict.get('symbol')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            audit_dict["snapshot_id"] = snapshot_id

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
        db: Session = self.session_factory()
        try:
            rec = db.query(VCCLiveSignalAuditModel).filter(VCCLiveSignalAuditModel.snapshot_id == snapshot_id).first()
            if not rec:
                return None
            return {c.name: getattr(rec, c.name) for c in rec.__table__.columns}
        finally:
            db.close()

    def get_unevaluated_snapshots(self, symbol: str) -> List[Dict[str, Any]]:
        db: Session = self.session_factory()
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

    def get_today_audit_history(self, symbol: str, trade_date: str) -> List[Dict[str, Any]]:
        db: Session = self.session_factory()
        try:
            recs = (
                db.query(VCCLiveSignalAuditModel)
                .filter(
                    VCCLiveSignalAuditModel.symbol == symbol.upper(),
                    VCCLiveSignalAuditModel.trade_date == trade_date
                )
                .order_by(VCCLiveSignalAuditModel.timestamp.asc())
                .all()
            )
            return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in recs]
        finally:
            db.close()


audit_repository = AuditRepository()
