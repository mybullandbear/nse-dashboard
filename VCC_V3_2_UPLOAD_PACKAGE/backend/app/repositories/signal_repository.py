"""
Signal Repository for VCC V3.2 Persistence Layer.
Manages creation, updates, and querying of SignalLifecycleModel records.
Decouples domain logic from SQLAlchemy.
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db.models import SignalLifecycleModel
from app.domain.contracts import SignalDecision


class SignalRepository:

    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    def save_signal_decision(self, decision: SignalDecision, entry_spot: float = 0.0, snapshot: Optional[Any] = None) -> int:
        db: Session = self.session_factory()
        try:
            ts_str = getattr(decision, "signal_initiated_at", None) or getattr(decision, "timestamp", None)
            if ts_str and len(ts_str) >= 10:
                trade_date = ts_str[:10]
            else:
                trade_date = datetime.now(IST).strftime("%Y-%m-%d")

            existing = db.query(SignalLifecycleModel).filter(SignalLifecycleModel.signal_id == decision.signal_id).first()
            if existing:
                existing.status = decision.operational_state
                existing.direction = decision.direction
                existing.confidence = decision.confidence
                existing.last_evaluated_at = decision.last_evaluated_at
                existing.last_updated_at = decision.last_updated_at
                existing.confirming_started_at = decision.confirming_started_at or existing.confirming_started_at
                existing.activated_at = decision.activated_at or existing.activated_at
                existing.closed_at = decision.closed_at or existing.closed_at
                existing.timestamp_status = decision.timestamp_status
                existing.signal_category = decision.signal_category
                existing.is_live = decision.is_live
                if decision.closed_at and not existing.exit_time:
                    existing.exit_time = decision.closed_at
                    existing.exit_spot = entry_spot
                db.commit()
                res_id = existing.id
            else:
                record = SignalLifecycleModel(
                    signal_id=decision.signal_id,
                    trade_date=trade_date,
                    symbol=decision.symbol.upper(),
                    strategy="VCC_CONFLUENCE_V32",
                    direction=decision.direction,
                    status=decision.operational_state,
                    entry_time=decision.signal_initiated_at or decision.timestamp,
                    entry_spot=entry_spot,
                    confidence=decision.confidence,
                    signal_initiated_at=decision.signal_initiated_at,
                    signal_initiated_at_ist=decision.signal_initiated_at_ist,
                    market_timestamp_at_initiation=decision.market_timestamp_at_initiation,
                    last_evaluated_at=decision.last_evaluated_at,
                    last_updated_at=decision.last_updated_at,
                    timestamp_status=decision.timestamp_status,
                    confirming_started_at=decision.confirming_started_at,
                    activated_at=decision.activated_at,
                    closed_at=decision.closed_at,
                    signal_category=decision.signal_category,
                    is_live=decision.is_live
                )
                db.add(record)
                db.commit()
                db.refresh(record)
                res_id = record.id

            if snapshot is not None and getattr(decision, "is_live", False):
                self._extract_and_save_provenance(decision, snapshot, entry_spot)

            return res_id
        except Exception:
            db.rollback()
            return 0
        finally:
            db.close()

    def _extract_and_save_provenance(self, decision: SignalDecision, snapshot: Any, entry_spot: float = 0.0):
        try:
            meta = getattr(snapshot, "metadata", None)
            analytics = getattr(snapshot, "analytics", None)
            smart = getattr(snapshot, "smart_money", None)
            opt_chain = getattr(snapshot, "option_chain", None)

            prov_dict = {
                "signal_id": decision.signal_id,
                "symbol": decision.symbol,
                "strategy": "VCC_CONFLUENCE_V32",
                "direction": decision.direction,
                "signal_initiated_at": decision.signal_initiated_at,
                "signal_initiated_at_ist": decision.signal_initiated_at_ist,
                "market_timestamp_at_initiation": decision.market_timestamp_at_initiation,
                "provider_timestamp_at_initiation": getattr(meta, "provider_timestamp", None) if meta else None,
                "provider": getattr(meta, "source_name", "FYERS_LIVE") if meta else "FYERS_LIVE",
                "data_status": getattr(meta, "data_status", "REAL_LIVE") if meta else "REAL_LIVE",
                "data_quality": snapshot.quality.name if hasattr(snapshot.quality, "name") else str(getattr(snapshot, "quality", "GOOD")),
                "session_state": getattr(meta, "session_state", "LIVE_MARKET") if meta else "LIVE_MARKET",
                "capture_run_id": getattr(meta, "capture_run_id", None) if meta else None,
                "spot_at_initiation": getattr(snapshot.spot, "spot_price", entry_spot) if hasattr(snapshot, "spot") else entry_spot,
                "expiry_at_initiation": getattr(opt_chain, "expiry", None) if opt_chain else None,
                "atm_at_initiation": getattr(opt_chain, "atm_strike", None) if opt_chain else None,
                "pcr": getattr(analytics, "pcr", None) if analytics else (getattr(opt_chain, "pcr", None) if opt_chain else None),
                "atm_pcr": getattr(analytics, "atm_pcr", None) if analytics else None,
                "call_wall": getattr(analytics, "call_wall", None) if analytics else None,
                "put_wall": getattr(analytics, "put_wall", None) if analytics else None,
                "call_wall_oi": getattr(analytics, "call_wall_oi", None) if analytics else None,
                "put_wall_oi": getattr(analytics, "put_wall_oi", None) if analytics else None,
                "wall_velocity": getattr(analytics, "wall_velocity", None) if analytics else None,
                "wall_velocity_status": getattr(analytics, "wall_velocity_status", None) if analytics else None,
                "spos": getattr(smart, "spos", None) if smart else None,
                "sflow": getattr(smart, "sflow", None) if smart else None,
                "put_conviction": getattr(smart, "put_conviction", None) if smart else None,
                "call_conviction": getattr(smart, "call_conviction", None) if smart else None,
                "net_bias": getattr(smart, "net_bias", None) if smart else None,
                "smart_money_status": getattr(smart, "status", None) if smart else None,
                "qualification_state": decision.operational_state,
                "is_live": decision.is_live,
                "is_real_data": getattr(meta, "is_real_data", True) if meta else True
            }
            self.save_signal_provenance(prov_dict)
        except Exception:
            pass

    def get_signal_by_id(self, signal_id: str) -> Optional[Dict[str, Any]]:
        db: Session = self.session_factory()
        try:
            rec = db.query(SignalLifecycleModel).filter(SignalLifecycleModel.signal_id == signal_id).first()
            if not rec:
                return None
            return {c.name: getattr(rec, c.name) for c in rec.__table__.columns}
        finally:
            db.close()

    def get_active_signals(self, symbol: str, trade_date: Optional[str] = None) -> List[Dict[str, Any]]:
        db: Session = self.session_factory()
        try:
            from app.services.market_hours import IST
            t_date = trade_date or datetime.now(IST).strftime("%Y-%m-%d")
            recs = (
                db.query(SignalLifecycleModel)
                .filter(
                    SignalLifecycleModel.symbol == symbol.upper(),
                    SignalLifecycleModel.trade_date == t_date,
                    SignalLifecycleModel.status.in_(["SETUP DEVELOPING", "CONFIRMED BIAS", "ENTRY READY", "ENTRY CONFIRMED", "GENERATED", "CONFIRMING", "ACTIVE"]),
                    SignalLifecycleModel.closed_at.is_(None)
                )
                .order_by(SignalLifecycleModel.id.desc())
                .all()
            )
            return [{c.name: getattr(r, c.name) for c in r.__table__.columns} for r in recs]
        finally:
            db.close()

    def get_latest_active_signal(self, symbol: str, trade_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        active = self.get_active_signals(symbol, trade_date=trade_date)
        return active[0] if active else None

    def save_signal_provenance(self, provenance_data: Dict[str, Any]) -> int:
        """
        Permanently save an immutable signal provenance record at signal birth.
        Enforces Real-Live Gate, Immutability, and Missing-Data Semantics (no None->0 coercion).
        """
        signal_id = provenance_data.get("signal_id")
        if not signal_id:
            return 0

        # 1. Real-Live Data Gate
        provider = provenance_data.get("provider", "FYERS_LIVE")
        data_status = provenance_data.get("data_status", "REAL_LIVE")
        is_live = provenance_data.get("is_live", True)
        is_real = provenance_data.get("is_real_data", True)

        if provider == "SIMULATED" or data_status in ["SIMULATED", "SYNTHETIC", "MOCK", "TEST"] or not is_live or not is_real:
            return 0  # Synthetic/test signals cannot create production provenance

        db: Session = self.session_factory()
        try:
            # 2. Immutability check (Never update existing provenance)
            from app.db.models import SignalProvenanceRecordModel
            existing = db.query(SignalProvenanceRecordModel).filter(SignalProvenanceRecordModel.signal_id == signal_id).first()
            if existing:
                return existing.id

            # 3. Create compact immutable provenance record
            rec = SignalProvenanceRecordModel(
                signal_id=signal_id,
                symbol=provenance_data.get("symbol", "").upper(),
                strategy=provenance_data.get("strategy", "VCC_CONFLUENCE_V32"),
                direction=provenance_data.get("direction", "NEUTRAL"),
                signal_initiated_at=provenance_data.get("signal_initiated_at"),
                signal_initiated_at_ist=provenance_data.get("signal_initiated_at_ist"),
                market_timestamp_at_initiation=provenance_data.get("market_timestamp_at_initiation"),
                provider_timestamp_at_initiation=provenance_data.get("provider_timestamp_at_initiation"),
                provider=provider,
                data_status=data_status,
                data_quality=provenance_data.get("data_quality", "GOOD"),
                session_state=provenance_data.get("session_state", "LIVE_MARKET"),
                capture_run_id=provenance_data.get("capture_run_id"),
                spot_at_initiation=provenance_data.get("spot_at_initiation"),
                expiry_at_initiation=provenance_data.get("expiry_at_initiation"),
                atm_at_initiation=provenance_data.get("atm_at_initiation"),
                pcr=provenance_data.get("pcr"),
                atm_pcr=provenance_data.get("atm_pcr"),
                call_wall=provenance_data.get("call_wall"),
                put_wall=provenance_data.get("put_wall"),
                call_wall_oi=provenance_data.get("call_wall_oi"),
                put_wall_oi=provenance_data.get("put_wall_oi"),
                wall_velocity=provenance_data.get("wall_velocity"),
                wall_velocity_status=provenance_data.get("wall_velocity_status"),
                spos=provenance_data.get("spos"),
                sflow=provenance_data.get("sflow"),
                put_conviction=provenance_data.get("put_conviction"),
                call_conviction=provenance_data.get("call_conviction"),
                net_bias=provenance_data.get("net_bias"),
                smart_money_status=provenance_data.get("smart_money_status"),
                qualification_state=provenance_data.get("qualification_state")
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)
            return rec.id
        except Exception:
            db.rollback()
            return 0
        finally:
            db.close()

    def get_signal_provenance(self, signal_id: str) -> Optional[Dict[str, Any]]:
        """Fetch immutable provenance snapshot by signal_id."""
        db: Session = self.session_factory()
        try:
            from app.db.models import SignalProvenanceRecordModel
            rec = db.query(SignalProvenanceRecordModel).filter(SignalProvenanceRecordModel.signal_id == signal_id).first()
            if not rec:
                return None
            return {c.name: getattr(rec, c.name) for c in rec.__table__.columns}
        finally:
            db.close()


signal_repository = SignalRepository()


