"""
Canonical Call Wall and Put Wall Velocity Engine for VCC V3.2.
Measures structural OI wall movement over time (points per hour).
Enforces:
1. CallWallVelocity = (curr_call_wall - prev_call_wall) / elapsed_hours
2. PutWallVelocity  = (curr_put_wall - prev_put_wall) / elapsed_hours
3. Independent velocity availability (Call and Put velocity are evaluated independently).
4. Strict non-zero missing data semantics (Velocity = 0.0 only when strikes are identical; None when unavailable).
5. Data quality & same option universe validation (symbol, exchange, expiry matching).
6. Anti-lookahead & session/timestamp ordering (prev < curr <= calc).
"""
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from dateutil import parser as dt_parser
from app.domain.contracts import MarketSnapshot, DataQuality
from app.analytics.wall_engine import wall_engine
from app.core.constants import system_config

logger = logging.getLogger(__name__)


class WallVelocityEngine:
    """
    Canonical Wall Velocity Engine for VCC V3.2.
    Single authoritative module for structural Call/Put Wall movement velocity (pts/hr).
    """

    @staticmethod
    def _parse_ts(ts_val: Any) -> Optional[datetime]:
        if not ts_val:
            return None
        if isinstance(ts_val, datetime):
            return ts_val
        try:
            return dt_parser.parse(str(ts_val))
        except Exception:
            return None

    @classmethod
    def select_previous_snapshot(
        cls,
        current_snapshot: MarketSnapshot,
        historical_snapshots: List[MarketSnapshot]
    ) -> Optional[MarketSnapshot]:
        """
        Deterministic selection policy: Selects snapshot closest to 1 hour (60 minutes) ago
        belonging to the same option universe (symbol, exchange, expiry) within [15m, 120m] window.
        """
        if not current_snapshot or not historical_snapshots:
            return None

        curr_ts = cls._parse_ts(current_snapshot.metadata.market_timestamp or current_snapshot.timestamp)
        if not curr_ts:
            return None

        sym = current_snapshot.symbol
        exch = current_snapshot.metadata.exchange
        exp = current_snapshot.expiry

        valid_candidates = []
        for snap in historical_snapshots:
            if not snap or not snap.metadata:
                continue
            if not snap.metadata.is_real_data or snap.metadata.source_name == "SIMULATED":
                continue
            if snap.quality == DataQuality.INVALID or snap.metadata.is_stale:
                continue
            if snap.symbol != sym or snap.metadata.exchange != exch or snap.expiry != exp:
                continue

            prev_ts = cls._parse_ts(snap.metadata.market_timestamp or snap.timestamp)
            if not prev_ts or prev_ts >= curr_ts:
                continue

            elapsed_sec = (curr_ts - prev_ts).total_seconds()
            # Allowed window: 15 minutes (900s) to 120 minutes (7200s)
            if 900.0 <= elapsed_sec <= 7200.0:
                diff_from_1h = abs(elapsed_sec - 3600.0)
                valid_candidates.append((diff_from_1h, snap))

        if not valid_candidates:
            return None

        # Sort by proximity to 3600s (1 hour)
        valid_candidates.sort(key=lambda x: x[0])
        return valid_candidates[0][1]

    @classmethod
    def compute_wall_velocity(
        cls,
        current_snapshot: MarketSnapshot,
        historical_snapshots: Optional[List[MarketSnapshot]] = None,
        previous_snapshot: Optional[MarketSnapshot] = None
    ) -> Dict[str, Any]:
        """
        Computes canonical Call Wall Velocity and Put Wall Velocity (points per hour).
        Returns strongly-typed dict with independent availability statuses.
        """
        threshold = getattr(system_config.thresholds, 'wall_migration_threshold_pts_per_hr', 25.0)  # 25.0 pts/hr

        curr_walls = wall_engine.compute_walls(current_snapshot)

        # Base failure output generator
        def _build_unavailable(reason: str):
            return {
                "call_wall_velocity": None,
                "call_wall_velocity_status": "UNAVAILABLE",
                "call_wall_migration_direction": "UNAVAILABLE",
                "put_wall_velocity": None,
                "put_wall_velocity_status": "UNAVAILABLE",
                "put_wall_migration_direction": "UNAVAILABLE",
                "elapsed_hours": None,
                "reason": reason,
                "current_walls": curr_walls
            }

        # Quality Check on Current Snapshot
        if (
            not current_snapshot
            or not current_snapshot.metadata.is_real_data
            or current_snapshot.metadata.source_name == "SIMULATED"
            or current_snapshot.quality == DataQuality.INVALID
            or current_snapshot.metadata.is_stale
        ):
            return _build_unavailable("CURRENT_SNAPSHOT_INVALID_OR_STALE")

        # Select previous snapshot if not directly supplied
        if not previous_snapshot and historical_snapshots:
            previous_snapshot = cls.select_previous_snapshot(current_snapshot, historical_snapshots)

        if not previous_snapshot:
            return _build_unavailable("INSUFFICIENT_HISTORY")

        # Quality Check on Previous Snapshot
        if (
            not previous_snapshot.metadata.is_real_data
            or previous_snapshot.metadata.source_name == "SIMULATED"
            or previous_snapshot.quality == DataQuality.INVALID
            or previous_snapshot.metadata.is_stale
        ):
            return _build_unavailable("PREVIOUS_SNAPSHOT_INVALID_OR_STALE")

        # Option Universe Matching
        if (
            previous_snapshot.symbol != current_snapshot.symbol
            or previous_snapshot.metadata.exchange != current_snapshot.metadata.exchange
            or previous_snapshot.expiry != current_snapshot.expiry
        ):
            return _build_unavailable("UNIVERSE_MISMATCH")

        # Timestamps & Time Gap Validation
        curr_ts = cls._parse_ts(current_snapshot.metadata.market_timestamp or current_snapshot.timestamp)
        prev_ts = cls._parse_ts(previous_snapshot.metadata.market_timestamp or previous_snapshot.timestamp)

        if not curr_ts or not prev_ts:
            return _build_unavailable("TIMESTAMP_INVALID")

        if prev_ts >= curr_ts:
            return _build_unavailable("TIMESTAMP_ORDER_INVALID")

        elapsed_seconds = (curr_ts - prev_ts).total_seconds()
        if elapsed_seconds <= 0.0:
            return _build_unavailable("ZERO_ELAPSED_TIME")

        # Max acceptable time gap: 8 hours (28800s) to prevent cross-session overnight distortion
        if elapsed_seconds > 28800.0:
            return _build_unavailable("CROSS_SESSION_TIME_GAP_EXCEEDED")

        elapsed_hours = elapsed_seconds / 3600.0

        prev_walls = wall_engine.compute_walls(previous_snapshot)

        # ----------------------------------------------------
        # 1. CALL WALL VELOCITY
        # ----------------------------------------------------
        curr_call = curr_walls["call_wall_strike"]
        prev_call = prev_walls["call_wall_strike"]

        if (
            curr_walls["call_wall_status"] == "AVAILABLE"
            and prev_walls["call_wall_status"] == "AVAILABLE"
            and curr_call is not None
            and prev_call is not None
        ):
            call_vel = round((curr_call - prev_call) / elapsed_hours, 2)
            call_status = "AVAILABLE"
            if call_vel >= threshold:
                call_dir = "UPWARD"
            elif call_vel <= -threshold:
                call_dir = "DOWNWARD"
            else:
                call_dir = "STABLE"
        else:
            call_vel = None
            call_status = "UNAVAILABLE"
            call_dir = "UNAVAILABLE"

        # ----------------------------------------------------
        # 2. PUT WALL VELOCITY
        # ----------------------------------------------------
        curr_put = curr_walls["put_wall_strike"]
        prev_put = prev_walls["put_wall_strike"]

        if (
            curr_walls["put_wall_status"] == "AVAILABLE"
            and prev_walls["put_wall_status"] == "AVAILABLE"
            and curr_put is not None
            and prev_put is not None
        ):
            put_vel = round((curr_put - prev_put) / elapsed_hours, 2)
            put_status = "AVAILABLE"
            if put_vel >= threshold:
                put_dir = "UPWARD"
            elif put_vel <= -threshold:
                put_dir = "DOWNWARD"
            else:
                put_dir = "STABLE"
        else:
            put_vel = None
            put_status = "UNAVAILABLE"
            put_dir = "UNAVAILABLE"

        return {
            "call_wall_velocity": call_vel,
            "call_wall_velocity_status": call_status,
            "call_wall_migration_direction": call_dir,
            "put_wall_velocity": put_vel,
            "put_wall_velocity_status": put_status,
            "put_wall_migration_direction": put_dir,
            "elapsed_hours": round(elapsed_hours, 4),
            "current_walls": curr_walls,
            "previous_walls": prev_walls,
            "reason": "OK"
        }


wall_velocity_engine = WallVelocityEngine()
