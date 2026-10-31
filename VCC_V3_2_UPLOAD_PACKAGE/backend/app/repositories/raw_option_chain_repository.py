"""
Raw Option Chain Historical Repository (Phase 9B-0).
Persists immutable real-data-only option chain observations tick-by-tick.
STRICT REAL-DATA RULES:
- Zero synthetic or simulator fallback data stored.
- Missing values stay NULL (None).
- Genuine 0 remains 0.
- Preserves provider provenance (FYERS_LIVE) and IST session state.
"""
import uuid
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from app.db.database import SessionLocal
from app.db.models import RawOptionChainObservationModel
from app.domain.contracts import MarketSnapshot
from app.services.market_hours import get_ist_now, get_market_session_info, IST

logger = logging.getLogger(__name__)


def _extract_numeric_or_none(obj: Any, field_name: str) -> Optional[float]:
    """
    Extracts a numeric field value cleanly from an object or dictionary.
    Returns None if the field is missing or None.
    Returns float(val) if numeric, preserving genuine 0.0 values.
    CRITICAL: Never coerce missing None values or genuine zero values.
    """
    if obj is None:
        return None

    if isinstance(obj, dict):
        val = obj.get(field_name)
    else:
        val = getattr(obj, field_name, None)

    if val is None:
        return None

    try:
        return float(val)
    except (ValueError, TypeError):
        return None


class RawOptionChainRepository:
    """
    Production-grade, real-data-only repository for persisting raw option-chain observations.
    """

    def __init__(self):
        self.total_rows_persisted: int = 0
        self.last_capture_time: Optional[str] = None
        self.last_capture_counts: Dict[str, int] = {}
        self.last_error: Optional[str] = None

    def save_snapshot_raw_chain(self, snapshot: MarketSnapshot) -> int:
        """
        Extracts and persists full option chain contract ticks from a MarketSnapshot.
        Enforces strict real-data provenance gating and 0 vs NULL semantics.
        Returns total number of rows successfully inserted.
        """
        if not snapshot or not hasattr(snapshot, "option_chain") or not snapshot.option_chain:
            logger.debug("Raw option chain persistence skipped: empty snapshot or option_chain")
            return 0

        metadata = getattr(snapshot, "metadata", None)
        if not metadata:
            logger.debug("Raw option chain persistence skipped: missing metadata")
            return 0

        # Provenance Check: MUST BE REAL DATA
        is_real = getattr(metadata, "is_real_data", False)
        provider = str(getattr(metadata, "provider", getattr(metadata, "source_name", "UNKNOWN"))).upper()
        data_status = str(getattr(metadata, "data_status", "UNKNOWN"))

        if not is_real or provider == "SIMULATED" or "SYNTHETIC" in data_status:
            logger.debug(f"Raw option chain persistence rejected: non-real provenance (is_real={is_real}, provider={provider}, data_status={data_status})")
            return 0

        strikes = getattr(snapshot.option_chain, "strikes", [])
        if not strikes:
            logger.debug("Raw option chain persistence skipped: no strike contracts in option chain")
            return 0

        symbol = str(getattr(snapshot, "symbol", "")).upper()
        if not symbol:
            return 0

        now_ist = get_ist_now()
        observed_at = getattr(metadata, "provider_timestamp", None) or getattr(snapshot, "timestamp", None) or now_ist.isoformat()
        trade_date = now_ist.strftime("%Y-%m-%d")
        
        session_info = get_market_session_info(now_dt=now_ist)
        session_state = session_info.get("session_state", "LIVE_MARKET")

        spot_price = _extract_numeric_or_none(getattr(snapshot, "spot", None), "spot_price")
        if spot_price is None or spot_price <= 0:
            spot_price = _extract_numeric_or_none(snapshot.option_chain, "spot_price")

        if spot_price is None or spot_price <= 0:
            logger.warning(f"Raw option chain persistence rejected for {symbol}: invalid spot price ({spot_price})")
            return 0

        capture_run_id = f"RUN_{symbol}_{now_ist.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        quality_str = str(getattr(snapshot, "quality", "GOOD"))

        records_to_insert: List[Dict[str, Any]] = []

        for strike_obj in strikes:
            strike_price = _extract_numeric_or_none(strike_obj, "strike_price")
            if strike_price is None or strike_price <= 0:
                continue

            contract_expiry = getattr(strike_obj, "expiry", None) or getattr(snapshot.option_chain, "expiry", None) or getattr(snapshot, "expiry", None)
            if not contract_expiry:
                continue

            # 1. CALL OPTION (CE)
            ce_tick = getattr(strike_obj, "ce_tick", None)
            ce_ltp = _extract_numeric_or_none(ce_tick, "ltp") if ce_tick else _extract_numeric_or_none(strike_obj, "ce_ltp")
            ce_oi = _extract_numeric_or_none(ce_tick, "oi") if ce_tick else _extract_numeric_or_none(strike_obj, "ce_oi")
            ce_doi = _extract_numeric_or_none(ce_tick, "oi_change") if ce_tick else _extract_numeric_or_none(strike_obj, "ce_oi_change")
            ce_bid = _extract_numeric_or_none(ce_tick, "bid") if ce_tick else _extract_numeric_or_none(strike_obj, "ce_bid")
            ce_ask = _extract_numeric_or_none(ce_tick, "ask") if ce_tick else _extract_numeric_or_none(strike_obj, "ce_ask")
            ce_vol = _extract_numeric_or_none(ce_tick, "volume") if ce_tick else _extract_numeric_or_none(strike_obj, "ce_volume")
            ce_iv = _extract_numeric_or_none(ce_tick, "iv") if ce_tick else _extract_numeric_or_none(strike_obj, "ce_iv")

            records_to_insert.append({
                "observed_at": str(observed_at),
                "trade_date": trade_date,
                "symbol": symbol,
                "expiry": str(contract_expiry),
                "strike": float(strike_price),
                "option_type": "CE",
                "spot": float(spot_price),
                "ltp": ce_ltp,
                "oi": ce_oi,
                "oi_change": ce_doi,
                "bid": ce_bid,
                "ask": ce_ask,
                "volume": ce_vol,
                "iv": ce_iv,
                "underlying_timestamp": str(observed_at),
                "provider_timestamp": str(observed_at),
                "provider": provider,
                "data_status": data_status,
                "data_quality": quality_str,
                "session_state": session_state,
                "capture_run_id": capture_run_id,
                "created_at": datetime.utcnow()
            })

            # 2. PUT OPTION (PE)
            pe_tick = getattr(strike_obj, "pe_tick", None)
            pe_ltp = _extract_numeric_or_none(pe_tick, "ltp") if pe_tick else _extract_numeric_or_none(strike_obj, "pe_ltp")
            pe_oi = _extract_numeric_or_none(pe_tick, "oi") if pe_tick else _extract_numeric_or_none(strike_obj, "pe_oi")
            pe_doi = _extract_numeric_or_none(pe_tick, "oi_change") if pe_tick else _extract_numeric_or_none(strike_obj, "pe_oi_change")
            pe_bid = _extract_numeric_or_none(pe_tick, "bid") if pe_tick else _extract_numeric_or_none(strike_obj, "pe_bid")
            pe_ask = _extract_numeric_or_none(pe_tick, "ask") if pe_tick else _extract_numeric_or_none(strike_obj, "pe_ask")
            pe_vol = _extract_numeric_or_none(pe_tick, "volume") if pe_tick else _extract_numeric_or_none(strike_obj, "pe_volume")
            pe_iv = _extract_numeric_or_none(pe_tick, "iv") if pe_tick else _extract_numeric_or_none(strike_obj, "pe_iv")

            records_to_insert.append({
                "observed_at": str(observed_at),
                "trade_date": trade_date,
                "symbol": symbol,
                "expiry": str(contract_expiry),
                "strike": float(strike_price),
                "option_type": "PE",
                "spot": float(spot_price),
                "ltp": pe_ltp,
                "oi": pe_oi,
                "oi_change": pe_doi,
                "bid": pe_bid,
                "ask": pe_ask,
                "volume": pe_vol,
                "iv": pe_iv,
                "underlying_timestamp": str(observed_at),
                "provider_timestamp": str(observed_at),
                "provider": provider,
                "data_status": data_status,
                "data_quality": quality_str,
                "session_state": session_state,
                "capture_run_id": capture_run_id,
                "created_at": datetime.utcnow()
            })

        if not records_to_insert:
            return 0

        # Bulk Append-Only Persistence into DB
        db = SessionLocal()
        try:
            db.bulk_insert_mappings(RawOptionChainObservationModel, records_to_insert)
            db.commit()
            inserted_count = len(records_to_insert)
            
            # Update telemetry
            self.total_rows_persisted += inserted_count
            self.last_capture_time = observed_at
            self.last_capture_counts[symbol] = inserted_count
            logger.info(f"[RawChainCapture] Persisted {inserted_count} real contract ticks for {symbol} (run_id={capture_run_id})")
            return inserted_count
        except Exception as e:
            db.rollback()
            self.last_error = str(e)
            logger.error(f"[RawChainCapture] Failed to persist raw option chain for {symbol}: {e}")
            return 0
        finally:
            db.close()

    def get_latest_live_snapshot(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves the latest complete option chain observation for today's market date.
        Enforces today's trade date, real provider, and acceptable data status.
        """
        now_ist = get_ist_now()
        today_str = now_ist.strftime("%Y-%m-%d")
        sym_clean = symbol.upper()

        db = SessionLocal()
        try:
            latest = db.query(
                RawOptionChainObservationModel.capture_run_id,
                RawOptionChainObservationModel.observed_at,
                RawOptionChainObservationModel.spot,
                RawOptionChainObservationModel.expiry,
                RawOptionChainObservationModel.provider,
                RawOptionChainObservationModel.data_status
            ).filter(
                RawOptionChainObservationModel.symbol == sym_clean,
                RawOptionChainObservationModel.trade_date == today_str,
                RawOptionChainObservationModel.provider == "FYERS_LIVE"
            ).order_by(RawOptionChainObservationModel.id.desc()).first()

            if not latest:
                return None

            run_id, obs_at, spot_val, exp_val, provider_val, status_val = latest

            ticks = db.query(RawOptionChainObservationModel).filter(
                RawOptionChainObservationModel.capture_run_id == run_id
            ).all()

            return {
                "capture_run_id": run_id,
                "symbol": sym_clean,
                "observed_at": obs_at,
                "spot": spot_val,
                "expiry": exp_val,
                "provider": provider_val,
                "data_status": status_val,
                "contract_count": len(ticks),
                "ticks": [
                    {
                        "strike": t.strike,
                        "option_type": t.option_type,
                        "ltp": t.ltp,
                        "oi": t.oi,
                        "oi_change": t.oi_change,
                        "bid": t.bid,
                        "ask": t.ask,
                        "volume": t.volume,
                        "iv": t.iv
                    } for t in ticks
                ]
            }
        except Exception as e:
            logger.error(f"Error fetching latest live snapshot for {symbol}: {e}")
            return None
        finally:
            db.close()

    def get_today_chain(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Retrieves all raw contract observations captured today for symbol.
        """
        today_str = get_ist_now().strftime("%Y-%m-%d")
        sym_clean = symbol.upper()

        db = SessionLocal()
        try:
            ticks = db.query(RawOptionChainObservationModel).filter(
                RawOptionChainObservationModel.symbol == sym_clean,
                RawOptionChainObservationModel.trade_date == today_str
            ).order_by(RawOptionChainObservationModel.id.asc()).all()

            return [
                {
                    "id": t.id,
                    "capture_run_id": t.capture_run_id,
                    "observed_at": t.observed_at,
                    "strike": t.strike,
                    "option_type": t.option_type,
                    "spot": t.spot,
                    "ltp": t.ltp,
                    "oi": t.oi,
                    "oi_change": t.oi_change
                } for t in ticks
            ]
        except Exception as e:
            logger.error(f"Error fetching today's chain for {symbol}: {e}")
            return []
        finally:
            db.close()

    def get_recent_history(self, symbol: str, days: int = 3) -> List[Dict[str, Any]]:
        """
        Retrieves recent historical observations for symbol with a HARD MAXIMUM of days <= 3.
        Physical 3-day boundary is strictly enforced.
        """
        from datetime import timedelta
        eff_days = min(max(1, days), 3)  # Hard cap <= 3 days
        now_ist = get_ist_now()
        cutoff_date = (now_ist.date() - timedelta(days=eff_days)).strftime("%Y-%m-%d")
        sym_clean = symbol.upper()

        db = SessionLocal()
        try:
            ticks = db.query(RawOptionChainObservationModel).filter(
                RawOptionChainObservationModel.symbol == sym_clean,
                RawOptionChainObservationModel.trade_date >= cutoff_date
            ).order_by(RawOptionChainObservationModel.id.asc()).all()

            return [
                {
                    "id": t.id,
                    "capture_run_id": t.capture_run_id,
                    "observed_at": t.observed_at,
                    "trade_date": t.trade_date,
                    "strike": t.strike,
                    "option_type": t.option_type,
                    "spot": t.spot,
                    "ltp": t.ltp,
                    "oi": t.oi,
                    "oi_change": t.oi_change
                } for t in ticks
            ]
        except Exception as e:
            logger.error(f"Error fetching recent history for {symbol}: {e}")
            return []
        finally:
            db.close()

    def purge_observations_older_than(self, days: int = 3) -> Dict[str, Any]:
        """
        Purges raw option chain observations older than days (default 3 days).
        Retention boundary is evaluated based on market observation timestamp/trade_date.
        """
        from datetime import timedelta
        now_ist = get_ist_now()
        cutoff_date = (now_ist.date() - timedelta(days=days)).strftime("%Y-%m-%d")
        cutoff_ts = (now_ist - timedelta(days=days)).isoformat()

        db = SessionLocal()
        try:
            # Query candidate count
            candidates = db.query(RawOptionChainObservationModel).filter(
                (RawOptionChainObservationModel.trade_date < cutoff_date) |
                (RawOptionChainObservationModel.observed_at < cutoff_ts)
            )
            cand_count = candidates.count()

            # Execute delete
            del_count = candidates.delete(synchronize_session=False)
            db.commit()

            remaining_count = db.query(RawOptionChainObservationModel).count()
            oldest_obs = db.query(RawOptionChainObservationModel.observed_at).order_by(RawOptionChainObservationModel.id.asc()).first()
            oldest_ts = oldest_obs[0] if oldest_obs else None

            logger.info(
                f"[3-Day Rolling Retention] Deleted {del_count} observations older than {cutoff_date}. "
                f"Remaining rows: {remaining_count}. Oldest remaining observation: {oldest_ts}"
            )
            return {
                "deleted_count": del_count,
                "candidate_count": cand_count,
                "remaining_count": remaining_count,
                "oldest_remaining_ts": oldest_ts,
                "cutoff_date": cutoff_date
            }
        except Exception as e:
            db.rollback()
            logger.error(f"Error purging old raw option chain observations: {e}")
            return {"error": str(e), "deleted_count": 0}
        finally:
            db.close()


# Canonical singleton instance
raw_option_chain_repository = RawOptionChainRepository()

