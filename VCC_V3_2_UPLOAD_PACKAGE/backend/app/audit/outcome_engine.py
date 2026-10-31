"""
Forward Outcome Engine for VCC V3.2 Audit Architecture.
Calculates T+5m, T+15m, T+30m returns, MFE, MAE, and directional correctness.
Strictly excludes non-directional signals (WATCH, NO SIGNAL, SIGNAL CONFLICT) from win/loss statistics.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from app.domain.contracts import SignalOutcome


class ForwardOutcomeEngine:
    """
    Dedicated Forward Outcome Evaluator.
    Calculates outcomes strictly from snapshots occurring AFTER signal timestamp T.
    """

    @staticmethod
    def evaluate_outcome(
        snapshot_id: str,
        signal_timestamp: str,
        symbol: str,
        direction: str,
        entry_spot: float,
        future_snapshots: List[Dict[str, Any]]
    ) -> Optional[SignalOutcome]:
        if not future_snapshots or entry_spot <= 0:
            return None

        # Filter strictly for snapshots after signal timestamp T (Anti-Lookahead)
        t_signal = datetime.fromisoformat(signal_timestamp) if isinstance(signal_timestamp, str) else signal_timestamp
        valid_futures = []

        for sn in future_snapshots:
            ts = sn.get("timestamp")
            if ts:
                ts_dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
                if ts_dt > t_signal:
                    valid_futures.append((ts_dt, sn.get("spot_price", entry_spot)))

        if not valid_futures:
            return None

        # Helper to get spot at horizon
        def get_spot_at_horizon(target_mins: int) -> Optional[float]:
            target_dt = t_signal + timedelta(minutes=target_mins)
            best_spot = None
            min_diff = float("inf")
            for ts_dt, spot_val in valid_futures:
                diff = abs((ts_dt - target_dt).total_seconds())
                if diff < min_diff:
                    min_diff = diff
                    best_spot = spot_val
            # Return spot if within 3 minutes of horizon
            if min_diff <= 180:
                return best_spot
            return None

        spot_t5 = get_spot_at_horizon(5)
        spot_t15 = get_spot_at_horizon(15)
        spot_t30 = get_spot_at_horizon(30)

        return_t5 = round(((spot_t5 - entry_spot) / entry_spot) * 100.0, 4) if spot_t5 else None
        return_t15 = round(((spot_t15 - entry_spot) / entry_spot) * 100.0, 4) if spot_t15 else None
        return_t30 = round(((spot_t30 - entry_spot) / entry_spot) * 100.0, 4) if spot_t30 else None

        # MFE / MAE over 30m window
        mfe = 0.0
        mae = 0.0
        for ts_dt, spot_val in valid_futures:
            if (ts_dt - t_signal).total_seconds() <= 1800:
                ret = ((spot_val - entry_spot) / entry_spot) * 100.0
                if direction == "BULLISH":
                    if ret > mfe: mfe = ret
                    if ret < mae: mae = ret
                elif direction == "BEARISH":
                    if -ret > mfe: mfe = -ret
                    if -ret < mae: mae = -ret

        # Exclude Non-Directional Signals from Win/Loss Statistics
        if direction not in ["BULLISH", "BEARISH"]:
            correctness = "EXCLUDED_NON_DIRECTIONAL"
        elif return_t30 is not None:
            if direction == "BULLISH":
                correctness = "CORRECT" if return_t30 > 0 else "INCORRECT"
            else:
                correctness = "CORRECT" if return_t30 < 0 else "INCORRECT"
        else:
            correctness = "PENDING"

        return SignalOutcome(
            snapshot_id=snapshot_id,
            timestamp=signal_timestamp if isinstance(signal_timestamp, str) else signal_timestamp.isoformat(),
            symbol=symbol.upper(),
            direction=direction,
            spot_price=entry_spot,
            spot_t5=spot_t5,
            spot_t15=spot_t15,
            spot_t30=spot_t30,
            return_t5_pct=return_t5,
            return_t15_pct=return_t15,
            return_t30_pct=return_t30,
            mfe_t30_pct=round(mfe, 4),
            mae_t30_pct=round(mae, 4),
            directional_correctness_30m=correctness,
            outcome_evaluated=True
        )

    def evaluate_retrospective_outcome(
        self,
        signal_timestamp: str,
        signal_spot: float,
        signal_direction: str,
        historical_snapshots: List[Any]
    ) -> Dict[str, Any]:
        """
        Retrospective evaluation helper across historical MarketSnapshots or dictionaries.
        """
        future_dicts = []
        for s in historical_snapshots:
            ts = s.timestamp if hasattr(s, "timestamp") else s.get("timestamp")
            spot_val = s.spot.spot_price if hasattr(s, "spot") and hasattr(s.spot, "spot_price") else s.get("spot_price", signal_spot)
            future_dicts.append({"timestamp": ts, "spot_price": spot_val})

        res = self.evaluate_outcome(
            snapshot_id="RETRO_EVAL",
            signal_timestamp=signal_timestamp,
            symbol="NIFTY",
            direction=signal_direction,
            entry_spot=signal_spot,
            future_snapshots=future_dicts
        )

        if not res:
            return {
                "spot_t5": None,
                "spot_t15": None,
                "spot_t30": None,
                "mfe_t30_pct": 0.0,
                "mae_t30_pct": 0.0,
                "directional_correctness_30m": False
            }

        return {
            "spot_t5": res.spot_t5,
            "spot_t15": res.spot_t15,
            "spot_t30": res.spot_t30,
            "mfe_t30_pct": res.mfe_t30_pct,
            "mae_t30_pct": res.mae_t30_pct,
            "directional_correctness_30m": (res.directional_correctness_30m == "CORRECT")
        }


outcome_engine = ForwardOutcomeEngine()
forward_outcome_engine = outcome_engine
