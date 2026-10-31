"""
Smart Money Repository for VCC V3.2 Persistence Layer.
Manages database records for SmartMoneyShiftModel.
Decouples domain logic from SQLAlchemy.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models import SmartMoneyShiftModel


class SmartMoneyRepository:

    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    def save_shift(self, shift_dict: Dict[str, Any]) -> int:
        db: Session = self.session_factory()
        try:
            valid_cols = {c.name for c in SmartMoneyShiftModel.__table__.columns}
            filtered_data = {k: v for k, v in shift_dict.items() if k in valid_cols}
            record = SmartMoneyShiftModel(**filtered_data)
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id
        except Exception:
            db.rollback()
            return 0
        finally:
            db.close()

    def get_today_shifts(self, symbol: str, trade_date: str) -> List[Dict[str, Any]]:
        db: Session = self.session_factory()
        try:
            recs = (
                db.query(SmartMoneyShiftModel)
                .filter(
                    SmartMoneyShiftModel.symbol == symbol.upper(),
                    SmartMoneyShiftModel.trade_date == trade_date
                )
                .order_by(SmartMoneyShiftModel.timestamp.desc())
                .all()
            )
            return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in recs]
        finally:
            db.close()


    def get_available_dates(self) -> List[str]:
        db: Session = self.session_factory()
        try:
            recs = (
                db.query(SmartMoneyShiftModel.trade_date)
                .distinct()
                .order_by(SmartMoneyShiftModel.trade_date.desc())
                .all()
            )
            return [r[0] for r in recs if r[0]]
        finally:
            db.close()



smart_money_repository = SmartMoneyRepository()

