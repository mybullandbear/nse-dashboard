"""
Layer 3 Intelligence: ShonyaBot Execution & Risk Engine
=======================================================
Handles 5-Gate evaluation, position state machine, risk management, and trailing SL.
Infused with Asset-Specific Multi-Indicator Weighted Confluence & Trend-Trailing Rules.
"""
import time
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, time as dt_time

from app.core.market_hours import get_current_ist

logger = logging.getLogger(__name__)

# Asset-Specific Optimal Configurations
INDEX_CONFIGS: Dict[str, Dict[str, Any]] = {
    "NIFTY": {
        "weights": {"at": 2.0, "td": 2.0, "hull": 1.5, "sh": 0.5, "px": 0.5, "bt": 2.0},
        "bull_threshold": 68.0,
        "bear_threshold": 32.0,
        "cut_bull_cis": 44.0,
        "cut_bear_cis": 56.0,
        "lot_size": 75,
        "step": 50.0
    },
    "BANKNIFTY": {
        "weights": {"at": 2.0, "td": 2.0, "hull": 1.5, "sh": 0.5, "px": 0.5, "bt": 2.0},
        "bull_threshold": 68.0,
        "bear_threshold": 32.0,
        "cut_bull_cis": 44.0,
        "cut_bear_cis": 56.0,
        "lot_size": 30,
        "step": 100.0
    },
    "FINNIFTY": {
        "weights": {"at": 1.0, "td": 1.0, "hull": 1.0, "sh": 1.0, "px": 0.0, "bt": 1.0},
        "bull_threshold": 68.0,
        "bear_threshold": 32.0,
        "cut_bull_cis": 44.0,
        "cut_bear_cis": 56.0,
        "lot_size": 65,
        "step": 50.0
    },
    "MIDCPNIFTY": {
        "weights": {"at": 2.0, "td": 1.5, "hull": 0.0, "sh": 0.0, "px": 0.0, "bt": 2.5},
        "bull_threshold": 68.0,
        "bear_threshold": 32.0,
        "cut_bull_cis": 44.0,
        "cut_bear_cis": 56.0,
        "lot_size": 120,
        "step": 25.0
    }
}


class ShonyaEngine:
    def __init__(self):
        self.mode = "PAPER" # "PAPER" | "LIVE"
        self.is_active = True
        self.positions: List[Dict[str, Any]] = []
        self.daily_pnl = 0.0
        self.max_daily_loss = 5000.0
        self.target_profit = 15000.0

    @staticmethod
    def calculate_composite_score(signals: Dict[str, float], weights: Dict[str, float]) -> float:
        total_w = sum(weights.values())
        if total_w <= 0:
            return 50.0
        weighted_sum = sum(signals.get(k, 0.0) * weights.get(k, 0.0) for k in weights)
        normalized_net = weighted_sum / total_w
        return round(50.0 + (50.0 * normalized_net), 1)

    def evaluate_gates(
        self,
        confluence_data: Dict[str, Any],
        symbol: str = "NIFTY",
        signals: Optional[Dict[str, float]] = None,
        pcr: float = 1.0
    ) -> Dict[str, Any]:
        """
        Evaluates the 5 institutional gates with asset-tailored indicator weighting.
        """
        sym = symbol.upper()
        cfg = INDEX_CONFIGS.get(sym, INDEX_CONFIGS["NIFTY"])
        weights = cfg["weights"]
        bull_thresh = cfg["bull_threshold"]
        bear_thresh = cfg["bear_threshold"]

        # Calculate or extract Weighted Composite Indicator Score (CIS)
        if signals:
            score = self.calculate_composite_score(signals, weights)
        else:
            score = float(confluence_data.get("confluence_score", confluence_data.get("score", 50.0)))

        now_dt = get_current_ist()
        t = now_dt.time()

        # Gate 1: Weighted Confluence Threshold
        gate1 = "PASS" if (score >= bull_thresh or score <= bear_thresh) else "WAIT"

        # Gate 2: Directional Bias Agreement
        bias = "BULLISH" if score >= bull_thresh else ("BEARISH" if score <= bear_thresh else "NEUTRAL")
        gate2 = "PASS" if bias in ["BULLISH", "BEARISH"] else "WAIT"

        # Gate 3: Institutional Option Flow Filter (PCR Support / Resistance)
        if bias == "BULLISH":
            gate3 = "PASS" if pcr >= 0.70 else "CHOP"
        elif bias == "BEARISH":
            gate3 = "PASS" if pcr <= 1.30 else "CHOP"
        else:
            gate3 = "CHOP"

        # Gate 4: Time of Day Gate (09:25 - 14:15 IST)
        gate4 = "PASS" if (dt_time(9, 25, 0) <= t <= dt_time(14, 15, 0)) else "REST_PERIOD"

        # Gate 5: Position Lock (Exact 1 open position per segment)
        has_open = any(p.get("symbol") == sym for p in self.positions)
        gate5 = "LOCKED" if has_open else "AVAILABLE"

        decision = "WAIT"
        reason = "Awaiting institutional confluence alignment"

        if gate1 == "PASS" and gate2 == "PASS" and gate3 == "PASS" and gate4 == "PASS" and not has_open:
            if score >= bull_thresh:
                decision = "BUY_CALL"
                reason = f"High conviction Bullish Confluence (CIS {score:.1f} >= {bull_thresh}) + PCR {pcr:.2f}"
            elif score <= bear_thresh:
                decision = "BUY_PUT"
                reason = f"High conviction Bearish Confluence (CIS {score:.1f} <= {bear_thresh}) + PCR {pcr:.2f}"
        elif has_open:
            decision = "HOLD_POSITION"
            reason = "Active trade in progress; trailing SL armed"
        elif gate4 == "REST_PERIOD":
            decision = "AVOID_TRADING"
            reason = "Outside allowable entry hours (09:25 - 14:15 IST)"
        elif gate3 == "CHOP":
            decision = "AVOID_CHOP"
            reason = "PCR diverging against price momentum; preserving capital"

        return {
            "symbol": sym,
            "decision": decision,
            "reason": reason,
            "cis_score": score,
            "pcr": pcr,
            "weights_used": weights,
            "gates": {
                "confluence": gate1,
                "direction": gate2,
                "flow_pcr": gate3,
                "time_window": gate4,
                "concurrency": gate5
            },
            "timestamp": time.time()
        }

    def update_positions_ltp(
        self,
        current_ltp: float,
        current_spot: float = 0.0,
        bt_state: str = "FLAT",
        bt_fail: Optional[float] = None,
        prox_per: float = 50.0,
        major_wall: float = 0.0,
        current_pcr: float = 1.0,
        is_eod: bool = False
    ):
        """Updates P&L and enforces dynamic structural indicator exits to takeover smooth days."""
        for pos in self.positions:
            entry = pos.get("entry_price", 100.0)
            current = current_ltp
            pos["current_price"] = current
            pts = current - entry
            pnl_pct = (pts / max(0.1, entry)) * 100.0
            pos["pnl_pct"] = round(pnl_pct, 2)
            pos["net_pnl"] = round(pts * pos.get("quantity", 50), 2)

            peak_p = max(pos.get("peak_price", entry), current)
            pos["peak_price"] = peak_p
            peak_pcr = max(pos.get("peak_pcr", current_pcr), current_pcr)
            pos["peak_pcr"] = peak_pcr
            trough_pcr = min(pos.get("trough_pcr", current_pcr), current_pcr)
            pos["trough_pcr"] = trough_pcr

            # 1. Takeover the smooth days: EOD Harvest at 15:20 IST
            if is_eod:
                pos["exit_trigger"] = "EOD_SMOOTH_TREND_HARVEST_15:20"
                continue

            # 2. Dynamic Breakeven Armor (locked once gain >= +20%)
            if pnl_pct >= 20.0 and not pos.get("breakeven_armored"):
                pos["breakeven_armored"] = True
                pos["stop_loss"] = round(entry * 1.02, 1)

            # 3. Emergency Protective Stop Floor
            if current <= pos.get("stop_loss", entry * 0.85):
                pos["exit_trigger"] = "BREAKEVEN_STOP" if pos.get("breakeven_armored") else "PROTECTIVE_STOP_-15%"
                continue

            # 4. Dynamic Structural Invalidation Exits
            opt_type = pos.get("option_type", "CE")
            if opt_type == "CE":
                if bt_fail is not None and current_spot < bt_fail and pnl_pct < 10.0:
                    pos["exit_trigger"] = "BREAKOUT_PIVOT_FAILURE"
                elif bt_state == "SHORT":
                    pos["exit_trigger"] = "BREAKOUT_TRACKER_FLIPPED_SHORT"
                elif prox_per < 40.0 and pnl_pct > 10.0:
                    pos["exit_trigger"] = "PROXIMITY_MA_STACK_LOST"
                elif major_wall > 0 and current_spot >= (major_wall - 15.0) and pnl_pct > 15.0:
                    pos["exit_trigger"] = "MAJOR_CE_WALL_REJECTION"
            elif opt_type == "PE":
                if bt_fail is not None and current_spot > bt_fail and pnl_pct < 10.0:
                    pos["exit_trigger"] = "BREAKOUT_PIVOT_FAILURE"
                elif bt_state == "LONG":
                    pos["exit_trigger"] = "BREAKOUT_TRACKER_FLIPPED_LONG"
                elif prox_per > 60.0 and pnl_pct > 10.0:
                    pos["exit_trigger"] = "PROXIMITY_MA_STACK_RECLAIMED"
                elif major_wall > 0 and current_spot <= (major_wall + 15.0) and pnl_pct > 15.0:
                    pos["exit_trigger"] = "MAJOR_PE_WALL_REJECTION"

    def get_terminal_summary(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "active": self.is_active,
            "daily_pnl": self.daily_pnl,
            "positions_count": len(self.positions),
            "positions": self.positions,
            "max_daily_loss": self.max_daily_loss,
            "target_profit": self.target_profit,
            "index_configs": INDEX_CONFIGS
        }


shonya_engine = ShonyaEngine()
