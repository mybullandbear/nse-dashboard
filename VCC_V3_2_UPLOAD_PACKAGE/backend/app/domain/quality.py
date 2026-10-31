"""
Centralized Data Quality Evaluator & Data Gate for VCC V3.2.
Categorizes MarketSnapshot instances into DataStatus (REAL_LIVE, REAL_RECENT, REAL_STALE,
INVALID, MISSING, SYNTHETIC, UNKNOWN) and evaluates signal eligibility.
"""
from datetime import datetime
from typing import Tuple, List, Optional
from app.domain.contracts import MarketSnapshot, DataQuality, DataStatus
from app.core.constants import system_config
from app.services.market_hours import IST


class DataQualityEvaluator:
    """
    Authoritative Data Quality Evaluator & Hard Real-Data Gate.
    Ensures that ONLY validated REAL market data can enter signal decision pipelines.
    """

    @staticmethod
    def evaluate(snapshot: MarketSnapshot, now_dt: Optional[datetime] = None) -> Tuple[DataQuality, List[str]]:
        reasons: List[str] = []
        now = now_dt or datetime.now(IST)
        if now.tzinfo is None:
            now = now.replace(tzinfo=IST)

        # 1. Populate/Normalize Metadata attributes
        if snapshot.metadata.source_name and snapshot.metadata.source_name != "SIMULATED" and (not snapshot.metadata.provider or snapshot.metadata.provider == "SIMULATED"):
            snapshot.metadata.provider = snapshot.metadata.source_name
        provider = snapshot.metadata.provider or snapshot.metadata.source_name or "FYERS"
        snapshot.metadata.symbol = snapshot.symbol
        snapshot.metadata.exchange = snapshot.metadata.exchange or "NSE"
        snapshot.metadata.provider = provider
        snapshot.metadata.received_timestamp = snapshot.metadata.received_timestamp or now.isoformat()
        snapshot.metadata.market_timestamp = (
            snapshot.metadata.market_timestamp
            or snapshot.spot.timestamp
            or snapshot.timestamp
        )
        snapshot.metadata.provider_timestamp = (
            snapshot.metadata.provider_timestamp
            or snapshot.metadata.spot_timestamp
            or snapshot.metadata.market_timestamp
        )

        # Real data flag check: Provider must be a real feed (FYERS, FYERS_LIVE, NSE, NSE_LIVE, PERSISTED_DB, V3_BACKGROUND)
        is_real_provider = (provider in ["FYERS", "FYERS_LIVE", "NSE", "NSE_LIVE", "PERSISTED_DB", "V3_BACKGROUND"] or getattr(snapshot.metadata, "is_real_data", False)) and snapshot.metadata.source_name != "SIMULATED"
        snapshot.metadata.is_real_data = is_real_provider

        # 2. Rule 1: Synthetic or Simulated Data -> PROHIBITED FOR SIGNALS
        if not is_real_provider or provider == "SIMULATED" or snapshot.metadata.source_name == "SIMULATED":
            snapshot.metadata.data_status = DataStatus.SYNTHETIC
            snapshot.metadata.completeness_status = "SYNTHETIC"
            snapshot.metadata.validation_status = "SYNTHETIC_DATA_PROHIBITED"
            snapshot.metadata.is_stale = True
            snapshot.quality = DataQuality.INVALID
            snapshot.metadata.quality = DataQuality.INVALID
            reasons.append("Synthetic/Simulated data source is prohibited for signal generation")
            return DataQuality.INVALID, reasons

        # 3. Rule 2 & 4: Missing Spot Price or Non-Positive Spot
        if not snapshot.spot or snapshot.spot.spot_price <= 0:
            snapshot.metadata.data_status = DataStatus.MISSING
            snapshot.metadata.completeness_status = "MISSING_SPOT"
            snapshot.metadata.validation_status = "INVALID_SPOT_PRICE"
            snapshot.metadata.is_stale = True
            snapshot.quality = DataQuality.INVALID
            snapshot.metadata.quality = DataQuality.INVALID
            reasons.append("Missing or invalid spot price")
            return DataQuality.INVALID, reasons

        # 4. Rule 4: Missing Option Chain or Empty Strikes
        if not snapshot.option_chain or not snapshot.option_chain.strikes:
            snapshot.metadata.data_status = DataStatus.MISSING
            snapshot.metadata.completeness_status = "EMPTY_STRIKES"
            snapshot.metadata.validation_status = "INVALID_OPTION_CHAIN"
            snapshot.metadata.is_stale = True
            snapshot.quality = DataQuality.INVALID
            snapshot.metadata.quality = DataQuality.INVALID
            reasons.append("Missing option chain or empty strikes matrix")
            return DataQuality.INVALID, reasons

        # 5. Provider Reported Explicit Error
        if snapshot.metadata.last_error:
            reasons.append(f"Provider reported error: {snapshot.metadata.last_error}")

        # 6. Calculate Timestamp Age & Discrepancies
        snapshot.compute_data_age(now_dt=now)
        spot_age = snapshot.metadata.spot_data_age_sec
        opt_age = snapshot.metadata.option_data_age_sec
        max_age = max(spot_age, opt_age)
        snapshot.metadata.data_age_seconds = max_age

        if abs(spot_age - opt_age) > 10.0:
            reasons.append(f"Timestamp discrepancy between spot ({spot_age:.1f}s) and option chain ({opt_age:.1f}s)")

        # 7. Age Categorization & Status Assignment
        stale_invalid_limit = system_config.thresholds.data_stale_invalid_sec  # 30.0s
        stale_warning_limit = system_config.thresholds.data_stale_warning_sec  # 5.0s

        snapshot.metadata.completeness_status = "COMPLETE"

        if max_age > stale_invalid_limit:
            snapshot.metadata.data_status = DataStatus.REAL_STALE
            snapshot.metadata.is_stale = True
            snapshot.metadata.validation_status = "REAL_DATA_STALE"
            snapshot.quality = DataQuality.INVALID
            snapshot.metadata.quality = DataQuality.INVALID
            reasons.append(f"Data age ({max_age:.1f}s) exceeds stale invalid threshold ({stale_invalid_limit}s)")
            return DataQuality.INVALID, reasons

        if max_age > stale_warning_limit or reasons:
            snapshot.metadata.data_status = DataStatus.REAL_RECENT
            snapshot.metadata.is_stale = False
            snapshot.metadata.validation_status = "REAL_DATA_RECENT"
            snapshot.quality = DataQuality.DEGRADED
            snapshot.metadata.quality = DataQuality.DEGRADED
            if not reasons:
                reasons.append(f"Data age ({max_age:.1f}s) exceeds warning threshold ({stale_warning_limit}s)")
            return DataQuality.DEGRADED, reasons

        snapshot.metadata.data_status = DataStatus.REAL_LIVE
        snapshot.metadata.is_stale = False
        snapshot.metadata.validation_status = "REAL_DATA_LIVE"
        snapshot.quality = DataQuality.GOOD
        snapshot.metadata.quality = DataQuality.GOOD
        return DataQuality.GOOD, ["Data quality verified real and live"]

    @staticmethod
    def is_signal_eligible(snapshot: MarketSnapshot, now_dt: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Hard Real-Data Gate Check.
        Returns (is_eligible: bool, reason_code: str).
        """
        DataQualityEvaluator.evaluate(snapshot, now_dt=now_dt)
        status = snapshot.metadata.data_status

        if status == DataStatus.SYNTHETIC:
            return False, "SYNTHETIC_DATA_PROHIBITED"
        elif status == DataStatus.UNKNOWN:
            return False, "UNKNOWN_DATA_STATUS"
        elif status == DataStatus.INVALID:
            return False, "INVALID_DATA_STRUCTURE"
        elif status == DataStatus.MISSING:
            return False, "MISSING_REQUIRED_DATA"
        elif status == DataStatus.REAL_STALE:
            return False, "STALE_DATA_PROHIBITED_FOR_LIVE_SIGNAL"
        elif status in [DataStatus.REAL_LIVE, DataStatus.REAL_RECENT]:
            if not snapshot.metadata.is_real_data:
                return False, "NON_REAL_DATA_PROHIBITED"
            if snapshot.metadata.completeness_status != "COMPLETE":
                return False, f"INCOMPLETE_DATA_{snapshot.metadata.completeness_status}"
            return True, "ELIGIBLE_FOR_SIGNAL"
        else:
            return False, "DATA_GATE_REJECTED"


data_quality_evaluator = DataQualityEvaluator()

