"""
Signal Engine for VCC V3.2 Signal Layer.
Makes final trading signal decisions based strictly on analytical results and confluence evaluation.
Does NOT access network APIs, database sessions, or frontend objects.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime
from app.domain.contracts import SignalDecision, MarketSnapshot, DataQuality, MarketSession
from app.intelligence.confluence_engine import ConfluenceResult
from app.services.market_hours import IST, is_signal_generation_allowed


class SignalLifecycleTracker:
    """
    Manages immutable initiation timestamps, signal_ids, deduplication,
    state transitions, and Phase 4 Live vs Historical signal separation.
    """

    def __init__(self):
        self._active_signals: Dict[str, Dict[str, Any]] = {}

    def _recover_active_signal_from_storage(self, symbol: str, current_trade_date: str) -> Optional[Dict[str, Any]]:
        """
        Loads active signal state from DB if available upon server startup / cache miss.
        Preserves original signal_id and initiation timestamp ONLY IF it belongs to current trade_date.
        Prevents previous-day signals from being resurrected as today's active live signals.
        """
        try:
            from app.repositories.signal_repository import signal_repository
            rec = signal_repository.get_latest_active_signal(symbol, trade_date=current_trade_date)
            if not rec:
                return None

            rec_trade_date = rec.get("trade_date")
            if rec_trade_date and rec_trade_date != current_trade_date:
                # Do NOT recover yesterday's active signal as live today! Close it.
                try:
                    c_time = rec.get("last_evaluated_at") or rec.get("entry_time") or ""
                    class DummyDecision:
                        signal_id = rec["signal_id"]
                        symbol = symbol.upper()
                        timestamp = c_time
                        operational_state = "CLOSED"
                        direction = rec.get("direction", "NEUTRAL")
                        confidence = 0.0
                        last_evaluated_at = c_time
                        last_updated_at = c_time
                        confirming_started_at = rec.get("confirming_started_at")
                        activated_at = rec.get("activated_at")
                        closed_at = c_time
                        timestamp_status = rec.get("timestamp_status", "VERIFIED")
                        signal_category = "HISTORICAL_SIGNAL"
                        is_live = False
                    signal_repository.save_signal_decision(DummyDecision(), entry_spot=0.0)
                except Exception:
                    pass
                return None

            if rec and rec.get("status") in ["SETUP DEVELOPING", "CONFIRMED BIAS", "ENTRY READY", "ENTRY CONFIRMED"]:
                init_time = rec.get("signal_initiated_at") or rec.get("entry_time") or ""
                init_ist = rec.get("signal_initiated_at_ist") or (f"{init_time[:19].replace('T', ' ')} IST" if init_time else "")
                mkt_init = rec.get("market_timestamp_at_initiation") or init_time
                ts_status = rec.get("timestamp_status") or ("VERIFIED" if init_time else "TIMESTAMP_UNVERIFIED")

                c_at = rec.get("created_at")
                if isinstance(c_at, datetime):
                    c_at_str = c_at.isoformat()
                elif c_at:
                    c_at_str = str(c_at)
                else:
                    c_at_str = init_time

                return {
                    "signal_id": rec["signal_id"],
                    "symbol": symbol.upper(),
                    "trade_date": rec_trade_date or current_trade_date,
                    "direction": rec.get("direction", "NEUTRAL"),
                    "operational_state": rec.get("status", "NO SIGNAL"),
                    "signal_initiated_at": init_time,
                    "signal_initiated_at_ist": init_ist,
                    "market_timestamp_at_initiation": mkt_init,
                    "created_at": c_at_str,
                    "confirming_started_at": rec.get("confirming_started_at"),
                    "activated_at": rec.get("activated_at"),
                    "closed_at": None,
                    "last_evaluated_at": rec.get("last_evaluated_at") or init_time,
                    "last_updated_at": rec.get("last_updated_at") or init_time,
                    "timestamp_status": ts_status,
                    "is_recovered": True
                }
        except Exception:
            pass
        return None

    def get_or_create_lifecycle(
        self,
        symbol: str,
        candidate_direction: str,
        candidate_state: str,
        market_timestamp: str,
        is_real_data: bool = True,
        data_age_seconds: float = 0.0,
        is_stale: bool = False,
        source_name: str = "FYERS_LIVE"
    ) -> Dict[str, Any]:
        sym = symbol.upper()

        if not market_timestamp:
            market_timestamp = datetime.now(IST).isoformat()

        try:
            m_dt = datetime.fromisoformat(market_timestamp)
            if m_dt.tzinfo is None:
                m_dt = m_dt.replace(tzinfo=IST)
            ist_str = f"{m_dt.strftime('%Y-%m-%d %H:%M:%S')} IST"
            current_trade_date = m_dt.strftime("%Y-%m-%d")
        except Exception:
            current_trade_date = datetime.now(IST).strftime("%Y-%m-%d")
            ist_str = f"{market_timestamp[:19].replace('T', ' ')} IST"

        timestamp_status = "VERIFIED" if (is_real_data and market_timestamp and source_name != "SIMULATED") else "TIMESTAMP_UNVERIFIED"

        active_states = ["SETUP DEVELOPING", "CONFIRMED BIAS", "ENTRY READY", "ENTRY CONFIRMED", "SETUP_DEVELOPING", "CONFIRMED_BIAS", "ENTRY_READY", "ENTRY_CONFIRMED"]
        is_candidate_active = (candidate_direction in ["BULLISH", "BEARISH"]) and (candidate_state in active_states)

        existing = self._active_signals.get(sym)
        if not existing:
            existing = self._recover_active_signal_from_storage(sym, current_trade_date)
            if existing:
                self._active_signals[sym] = existing
        else:
            # Detect Market Open / Trade Date transition
            existing_trade_date = existing.get("trade_date") or (existing.get("signal_initiated_at") or "")[:10]
            if existing_trade_date and existing_trade_date != current_trade_date:
                # Market session changed to new trade date! Close yesterday's active signal.
                existing["closed_at"] = market_timestamp
                existing["last_evaluated_at"] = market_timestamp
                existing["operational_state"] = "CLOSED"
                try:
                    from app.repositories.signal_repository import signal_repository
                    class DummyDecision:
                        signal_id = existing["signal_id"]
                        symbol = sym
                        timestamp = market_timestamp
                        operational_state = "CLOSED"
                        direction = existing["direction"]
                        confidence = 0.0
                        last_evaluated_at = market_timestamp
                        last_updated_at = market_timestamp
                        confirming_started_at = existing.get("confirming_started_at")
                        activated_at = existing.get("activated_at")
                        closed_at = market_timestamp
                        timestamp_status = existing.get("timestamp_status", "VERIFIED")
                        signal_category = "CLOSED_SIGNAL"
                        is_live = False
                    signal_repository.save_signal_decision(DummyDecision(), entry_spot=0.0)
                except Exception:
                    pass
                del self._active_signals[sym]
                existing = None

        # Evaluate Authoritative LIVE Market Session (09:15:00 - 15:15:00 IST)
        try:
            m_dt_obj = datetime.fromisoformat(market_timestamp)
        except Exception:
            m_dt_obj = datetime.now(IST)
        is_session_live = is_signal_generation_allowed(now_dt=m_dt_obj)

        is_same_day = (current_trade_date == datetime.now(IST).strftime("%Y-%m-%d")) or (current_trade_date == market_timestamp[:10])
        is_synthetic = (source_name == "SIMULATED") or (not is_real_data)

        is_live = (
            is_same_day
            and is_session_live
            and is_real_data
            and (not is_stale)
            and (data_age_seconds <= 30.0)
            and is_candidate_active
            and (timestamp_status == "VERIFIED")
            and (not is_synthetic)
        )

        if is_live:
            if existing and existing.get("is_recovered"):
                signal_category = "RECOVERED_SIGNAL"
            else:
                signal_category = "LIVE_SIGNAL"
        else:
            if not is_session_live:
                signal_category = "CLOSED_SIGNAL" if existing else "INVALID_UNVERIFIED_EVENT"
            elif is_synthetic or is_stale or data_age_seconds > 30.0 or timestamp_status == "TIMESTAMP_UNVERIFIED":
                signal_category = "INVALID_UNVERIFIED_EVENT"
            elif not is_candidate_active and existing:
                signal_category = "CLOSED_SIGNAL"
            elif not is_same_day:
                signal_category = "HISTORICAL_SIGNAL"
            else:
                signal_category = "INVALID_UNVERIFIED_EVENT"

        # CASE 1: Candidate is INACTIVE (WATCH, NO_VALID_DATA, DATA_UNAVAILABLE, SIGNAL CONFLICT, NO SIGNAL, NEUTRAL)
        if not is_candidate_active:
            if existing:
                existing["closed_at"] = market_timestamp
                existing["last_evaluated_at"] = market_timestamp
                existing["operational_state"] = "CLOSED"
                existing["signal_category"] = "CLOSED_SIGNAL"
                existing["is_live"] = False
                try:
                    from app.repositories.signal_repository import signal_repository
                    class DummyDecision:
                        signal_id = existing["signal_id"]
                        symbol = sym
                        timestamp = market_timestamp
                        operational_state = "CLOSED"
                        direction = existing["direction"]
                        confidence = 0.0
                        last_evaluated_at = market_timestamp
                        last_updated_at = market_timestamp
                        confirming_started_at = existing.get("confirming_started_at")
                        activated_at = existing.get("activated_at")
                        closed_at = market_timestamp
                        timestamp_status = existing.get("timestamp_status", "VERIFIED")
                        signal_category = "CLOSED_SIGNAL"
                        is_live = False
                    signal_repository.save_signal_decision(DummyDecision(), entry_spot=0.0)
                except Exception:
                    pass
                del self._active_signals[sym]

            idle_id = f"SIG_{sym}_IDLE"
            return {
                "signal_id": idle_id,
                "symbol": sym,
                "trade_date": current_trade_date,
                "signal_initiated_at": market_timestamp,
                "signal_initiated_at_ist": ist_str,
                "market_timestamp_at_initiation": market_timestamp,
                "last_evaluated_at": market_timestamp,
                "last_updated_at": market_timestamp,
                "timestamp_status": timestamp_status,
                "created_at": None,
                "confirming_started_at": None,
                "activated_at": None,
                "closed_at": None,
                "signal_category": signal_category,
                "is_live": False
            }

        # CASE 2: Candidate is ACTIVE, but NO active signal exists or direction flipped
        if not existing or existing["direction"] != candidate_direction:
            if existing:
                existing["closed_at"] = market_timestamp
                try:
                    from app.repositories.signal_repository import signal_repository
                    class DummyDecision:
                        signal_id = existing["signal_id"]
                        symbol = sym
                        timestamp = market_timestamp
                        operational_state = "CLOSED"
                        direction = existing["direction"]
                        confidence = 0.0
                        last_evaluated_at = market_timestamp
                        last_updated_at = market_timestamp
                        confirming_started_at = existing.get("confirming_started_at")
                        activated_at = existing.get("activated_at")
                        closed_at = market_timestamp
                        timestamp_status = existing.get("timestamp_status", "VERIFIED")
                        signal_category = "CLOSED_SIGNAL"
                        is_live = False
                    signal_repository.save_signal_decision(DummyDecision(), entry_spot=0.0)
                except Exception:
                    pass

            try:
                m_dt = datetime.fromisoformat(market_timestamp)
                code_ts = m_dt.strftime("%Y%m%d_%H%M%S")
            except Exception:
                code_ts = datetime.now(IST).strftime("%Y%m%d_%H%M%S")

            sig_id = f"SIG_{sym}_{code_ts}"

            confirming_ts = market_timestamp if candidate_state == "CONFIRMED BIAS" else None
            activated_ts = market_timestamp if candidate_state in ["ENTRY READY", "ENTRY CONFIRMED"] else None

            new_sig = {
                "signal_id": sig_id,
                "symbol": sym,
                "trade_date": current_trade_date,
                "direction": candidate_direction,
                "operational_state": candidate_state,
                "signal_initiated_at": market_timestamp,
                "signal_initiated_at_ist": ist_str,
                "market_timestamp_at_initiation": market_timestamp,
                "created_at": market_timestamp,
                "confirming_started_at": confirming_ts,
                "activated_at": activated_ts,
                "closed_at": None,
                "last_evaluated_at": market_timestamp,
                "last_updated_at": market_timestamp,
                "timestamp_status": timestamp_status,
                "signal_category": signal_category,
                "is_live": is_live,
                "is_recovered": False
            }
            self._active_signals[sym] = new_sig
            return new_sig

        # CASE 3: Candidate is ACTIVE and matches existing active signal direction (RECALCULATION / POLL / REFRESH)
        existing["last_evaluated_at"] = market_timestamp
        existing["signal_category"] = signal_category
        existing["is_live"] = is_live

        state_changed = existing["operational_state"] != candidate_state
        if state_changed:
            existing["last_updated_at"] = market_timestamp
            existing["operational_state"] = candidate_state

            if candidate_state == "CONFIRMED BIAS" and not existing.get("confirming_started_at"):
                existing["confirming_started_at"] = market_timestamp
            elif candidate_state in ["ENTRY READY", "ENTRY CONFIRMED"] and not existing.get("activated_at"):
                existing["activated_at"] = market_timestamp

        return existing


class SignalEngine:
    """
    Final decision maker for VCC trading signals.
    Enforces authoritative Data Gate checks, immutable signal initiation timestamps,
    and Phase 4 Live vs Historical signal separation.
    """

    def __init__(self):
        self.lifecycle_tracker = SignalLifecycleTracker()

    def decide_signal(
        self,
        snapshot: MarketSnapshot,
        confluence_res: ConfluenceResult,
        breakout_status: str,
        now_dt: Optional[datetime] = None
    ) -> SignalDecision:
        from app.domain.quality import data_quality_evaluator
        if now_dt is None:
            try:
                ts_candidate = snapshot.metadata.market_timestamp or snapshot.metadata.provider_timestamp or snapshot.timestamp
                if ts_candidate:
                    m_parsed = datetime.fromisoformat(ts_candidate)
                    dt = m_parsed if m_parsed.tzinfo else m_parsed.replace(tzinfo=IST)
                else:
                    dt = datetime.now(IST)
            except Exception:
                dt = datetime.now(IST)
        else:
            dt = now_dt

        market_ts = (
            snapshot.metadata.market_timestamp
            or snapshot.metadata.provider_timestamp
            or snapshot.timestamp
            or dt.isoformat()
        )
        is_real = getattr(snapshot.metadata, "is_real_data", False) and snapshot.metadata.source_name != "SIMULATED"

        # Enforce Hard Real-Data Gate
        is_eligible, gate_reason = data_quality_evaluator.is_signal_eligible(snapshot, now_dt=dt)

        if not is_eligible:
            direction = "NEUTRAL"
            market_regime = "DATA UNHEALTHY"
            if gate_reason in ["MISSING_REQUIRED_DATA", "INVALID_SPOT_PRICE"]:
                operational_state = "DATA_UNAVAILABLE"
            elif gate_reason == "SYNTHETIC_DATA_PROHIBITED":
                operational_state = "NO_VALID_DATA"
            else:
                operational_state = "WATCH"

            lifecycle = self.lifecycle_tracker.get_or_create_lifecycle(
                symbol=snapshot.symbol,
                candidate_direction=direction,
                candidate_state=operational_state,
                market_timestamp=market_ts,
                is_real_data=False,
                data_age_seconds=snapshot.metadata.data_age_seconds,
                is_stale=snapshot.metadata.is_stale,
                source_name=snapshot.metadata.source_name
            )

            return SignalDecision(
                signal_id=lifecycle["signal_id"],
                symbol=snapshot.symbol.upper(),
                direction=direction,
                operational_state=operational_state,
                confluence_score=confluence_res.final_score if confluence_res else 50.0,
                confidence=0.0,
                evidences=[],
                conflicts=[gate_reason],
                market_regime=market_regime,
                timestamp=market_ts,
                data_quality=snapshot.quality,
                reason_codes=[gate_reason],
                signal_initiated_at=lifecycle["signal_initiated_at"],
                signal_initiated_at_ist=lifecycle["signal_initiated_at_ist"],
                market_timestamp_at_initiation=lifecycle["market_timestamp_at_initiation"],
                last_evaluated_at=lifecycle["last_evaluated_at"],
                last_updated_at=lifecycle["last_updated_at"],
                timestamp_status=lifecycle["timestamp_status"],
                created_at=lifecycle.get("created_at"),
                confirming_started_at=lifecycle.get("confirming_started_at"),
                activated_at=lifecycle.get("activated_at"),
                closed_at=lifecycle.get("closed_at"),
                signal_category=lifecycle.get("signal_category", "INVALID_UNVERIFIED_EVENT"),
                is_live=lifecycle.get("is_live", False)
            )

        # 1. Evaluate Direction
        if confluence_res.is_conflict:
            direction = "NEUTRAL"
            market_regime = "SIGNAL CONFLICT"
        elif confluence_res.final_score >= 70:
            direction = "BULLISH"
            market_regime = "BULLISH CONFLUENCE"
        elif confluence_res.final_score <= 35:
            direction = "BEARISH"
            market_regime = "BEARISH CONFLUENCE"
        else:
            direction = "NEUTRAL"
            market_regime = "MODERATE / TWO-SIDED"

        # 2. Evaluate Operational State
        if snapshot.quality == DataQuality.INVALID:
            operational_state = "WATCH"
            reason_codes = ["DATA_QUALITY_INVALID", "STALE_OR_MISSING_FEED"]
        elif confluence_res.is_conflict:
            operational_state = "SIGNAL CONFLICT"
            reason_codes = ["POSITIONING_PRICE_MISMATCH", confluence_res.conflict_type]
        elif confluence_res.final_score < 35:
            operational_state = "NO SIGNAL"
            reason_codes = ["LOW_CONFLUENCE_SCORE"]
        elif confluence_res.final_score < 50:
            operational_state = "WATCH"
            reason_codes = ["WAITING_FOR_CONFLUENCE_BUILDUP"]
        elif confluence_res.final_score < 60:
            operational_state = "SETUP DEVELOPING"
            reason_codes = ["CONFLUENCE_BUILDING"]
        elif confluence_res.final_score < 70:
            operational_state = "CONFIRMED BIAS"
            reason_codes = ["STRONG_DIRECTIONAL_BIAS"]
        else:
            # Score >= 70
            if confluence_res.price_conf_score >= 50 and breakout_status in [
                "UPSIDE BREAKOUT CONFIRMED",
                "DOWNSIDE BREAKDOWN CONFIRMED"
            ]:
                operational_state = "ENTRY CONFIRMED"
                reason_codes = ["HIGH_CONFLUENCE", "PRICE_CONFIRMED", "BREAKOUT_VALIDATED"]
            elif confluence_res.price_conf_score >= 50:
                operational_state = "ENTRY READY"
                reason_codes = ["HIGH_CONFLUENCE", "PRICE_CONFIRMED"]
            else:
                operational_state = "CONFIRMED BIAS"
                reason_codes = ["HIGH_CONFLUENCE", "AWAITING_PRICE_CONFIRMATION"]

        lifecycle = self.lifecycle_tracker.get_or_create_lifecycle(
            symbol=snapshot.symbol,
            candidate_direction=direction,
            candidate_state=operational_state,
            market_timestamp=market_ts,
            is_real_data=is_real,
            data_age_seconds=snapshot.metadata.data_age_seconds,
            is_stale=snapshot.metadata.is_stale,
            source_name=snapshot.metadata.source_name
        )

        return SignalDecision(
            signal_id=lifecycle["signal_id"],
            symbol=snapshot.symbol.upper(),
            direction=direction,
            operational_state=operational_state,
            confluence_score=confluence_res.final_score,
            confidence=confluence_res.confidence,
            evidences=confluence_res.evidences,
            conflicts=confluence_res.conflict_details if confluence_res.is_conflict else [],
            market_regime=market_regime,
            timestamp=market_ts,
            data_quality=snapshot.quality,
            reason_codes=reason_codes,
            signal_initiated_at=lifecycle["signal_initiated_at"],
            signal_initiated_at_ist=lifecycle["signal_initiated_at_ist"],
            market_timestamp_at_initiation=lifecycle["market_timestamp_at_initiation"],
            last_evaluated_at=lifecycle["last_evaluated_at"],
            last_updated_at=lifecycle["last_updated_at"],
            timestamp_status=lifecycle["timestamp_status"],
            created_at=lifecycle.get("created_at"),
            confirming_started_at=lifecycle.get("confirming_started_at"),
            activated_at=lifecycle.get("activated_at"),
            closed_at=lifecycle.get("closed_at"),
            signal_category=lifecycle.get("signal_category", "LIVE_SIGNAL"),
            is_live=lifecycle.get("is_live", False)
        )


signal_engine = SignalEngine()

