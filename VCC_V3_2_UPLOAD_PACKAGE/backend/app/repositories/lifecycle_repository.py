"""
Lifecycle Repository for VCC V3.2 Persistence Layer.
Manages lifecycle transitions and tracking state.
Decouples domain logic from SQLAlchemy.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models import SignalLifecycleModel


class LifecycleRepository:

    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    def update_lifecycle_stage(
        self,
        signal_id: str,
        new_stage: str,
        exit_spot: Optional[float] = None,
        exit_reason: Optional[str] = None
    ) -> bool:
        db: Session = self.session_factory()
        try:
            rec = db.query(SignalLifecycleModel).filter(SignalLifecycleModel.signal_id == signal_id).first()
            if rec:
                rec.status = new_stage
                if exit_spot is not None:
                    rec.exit_spot = exit_spot
                    rec.exit_time = datetime.now().isoformat()
                if exit_reason:
                    rec.exit_reason = exit_reason
                db.commit()
                return True
            return False
        except Exception:
            db.rollback()
            return False
        finally:
            db.close()


lifecycle_repository = LifecycleRepository()
