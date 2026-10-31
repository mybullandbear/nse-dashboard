"""
Signal Lifecycle Engine for VCC V3.2 Audit Architecture.
Tracks signal lifecycle transitions (CREATED, CONFIRMED, EXPIRED, SUPERSEDED, CLOSED).
Does NOT perform market calculations.
"""
from typing import Dict, Any, Optional
from datetime import datetime


class SignalLifecycleEngine:
    """
    Dedicated Signal Lifecycle Manager.
    """

    def __init__(self):
        self._signal_states: Dict[str, Dict[str, Any]] = {}

    def track_signal(
        self,
        symbol: str,
        current_label: str,
        current_state: str,
        now_dt: datetime
    ) -> Dict[str, Any]:
        symbol = symbol.upper()
        sig_state = self._signal_states.get(symbol, {})

        # Reset state on new trade date
        if sig_state and (not sig_state.get("started_dt") or sig_state["started_dt"].date() != now_dt.date()):
            sig_state = {}

        if sig_state.get("label") != current_label:
            if sig_state.get("label"):
                lifecycle_stage = "SUPERSEDED"
            else:
                lifecycle_stage = "CREATED"

            sig_state = {
                "label": current_label,
                "stage": lifecycle_stage,
                "started_dt": now_dt,
                "last_confirmed_dt": now_dt,
                "confirm_count": 1,
                "total_evals": 1
            }
        else:
            sig_state["last_confirmed_dt"] = now_dt
            sig_state["confirm_count"] += 1
            sig_state["total_evals"] += 1
            cnt = sig_state["confirm_count"]

            if current_state in ["MARKET CLOSED", "SIGNAL CONFLICT / INVALIDATED"]:
                lifecycle_stage = "EXPIRED"
            elif cnt >= 3:
                lifecycle_stage = "CONFIRMED"
            else:
                lifecycle_stage = "ACTIVE"

            sig_state["stage"] = lifecycle_stage

        self._signal_states[symbol] = sig_state

        lifetime_sec = max(0.0, (now_dt - sig_state["started_dt"]).total_seconds())

        return {
            "symbol": symbol,
            "current_stage": sig_state["stage"],
            "lifetime_sec": round(lifetime_sec, 1),
            "confirm_count": sig_state["confirm_count"],
            "total_evals": sig_state["total_evals"]
        }


lifecycle_engine = SignalLifecycleEngine()
