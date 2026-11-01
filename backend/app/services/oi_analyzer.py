"""
Call vs Put Open Interest Analytical Engine
Computes full-day intraday timelines (09:15 - 15:40 IST), strike-wise comparative distributions,
support/resistance defense walls, and ATM straddle decay metrics.
"""
import math
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from app.services.option_chain import ParsedOptionChain, StrikeRow
from app.core.config import get_settings
from app.core.market_hours import get_current_ist
from app.db.storage import snapshot_storage

logger = logging.getLogger(__name__)


class OIAnalyzer:
    """Performs deep strike-level and temporal Call vs Put Open Interest analytics."""

    def __init__(self):
        # In-memory history for intraday snapshots per symbol
        self._history: Dict[str, List[Dict[str, Any]]] = {}
        self._current_trade_date: str = ""
        self._straddle_refs = {}

    def _check_and_reset_day(self):
        """Ensures that when a new calendar day starts, all yesterday snapshots are flushed."""
        today = get_current_ist().strftime("%Y-%m-%d")
        if self._current_trade_date != today:
            logger.info(f"OIAnalyzer: Trading day transition to '{today}'. Resetting in-memory history.")
            self._current_trade_date = today
            self._history.clear()
            self._straddle_refs.clear()

    def _ensure_morning_history(self, sym: str, chain: ParsedOptionChain):
        """
        Ensures timeline history loads actual recorded intraday snapshots for TODAY only (09:15 - 15:40 IST).
        ZERO SIMULATION: Only real recorded market snapshots from today are loaded.
        """
        self._check_and_reset_day()
        today = self._current_trade_date

        if sym in self._history and len(self._history[sym]) > 0:
            # Discard any stale records from previous days or outside market hours
            self._history[sym] = [
                pt for pt in self._history[sym]
                if pt.get("timestamp", "")[:10] == today and "09:15" <= pt.get("time", "") <= "15:40"
            ]
            if len(self._history[sym]) > 0:
                return

        # Check SQLite strictly for today's saved records
        stored = snapshot_storage.get_today_timeline(sym)
        if stored:
            self._history[sym] = [
                pt for pt in stored
                if pt.get("timestamp", "")[:10] == today and "09:15" <= pt.get("time", "") <= "15:40"
            ]
        else:
            self._history[sym] = []

    def record_snapshot(self, chain: ParsedOptionChain, decision=None):
        """Records a live point in time for the intraday timeline strictly during 09:15 - 15:40."""
        if not chain or chain.source in {"FROZEN", "STALE_CACHE", "MARKET_CLOSED", "SIMULATOR", "UNAVAILABLE"}:
            return

        self._check_and_reset_day()
        sym = chain.symbol.upper()
        self._ensure_morning_history(sym, chain)

        now_ist = get_current_ist()
        now_str = now_ist.strftime("%H:%M")

        # Do not record pre-market or post-market data into intraday timeline
        if now_str < "09:15" or now_str > "15:40":
            return
        
        # Anchored strike range around stable base level to prevent sliding window boundary pop-in/pop-out
        settings = get_settings()
        step = settings.STRIKE_STEPS.get(sym, 50)
        atm = chain.atm_strike
        base_spot = getattr(self, f"_base_spot_{sym}", None)
        if not base_spot or abs(chain.spot_price - base_spot) > (step * 8):
            base_spot = round(chain.spot_price / (step * 4)) * (step * 4)
            setattr(self, f"_base_spot_{sym}", base_spot)

        atm_strikes = [s for s in chain.strikes if abs(s.strikePrice - base_spot) <= (20 * step)]
        if not atm_strikes:
            atm_strikes = chain.strikes

        ce_oi = int(sum(s.CE.openInterest for s in atm_strikes if s.CE))
        pe_oi = int(sum(s.PE.openInterest for s in atm_strikes if s.PE))
        ce_chg = int(sum(s.CE.changeinOpenInterest for s in atm_strikes if s.CE))
        pe_chg = int(sum(s.PE.changeinOpenInterest for s in atm_strikes if s.PE))

        snapshot_point = {
            "time": now_str,
            "timestamp": now_ist.isoformat(),
            "spot": chain.spot_price,
            "ce_oi": ce_oi,
            "pe_oi": pe_oi,
            "ce_oi_chg": ce_chg,
            "pe_oi_chg": pe_chg,
            "diff_oi": ce_oi - pe_oi,
            "pcr": round(pe_oi / max(1, ce_oi), 2)
        }

        # Update or append in history
        hist = self._history.setdefault(sym, [])
        if not hist or hist[-1]["time"] != now_str:
            hist.append(snapshot_point)
            # Retain full trading day (09:15 to 15:40 is 385 minutes)
            if len(hist) > 500:
                self._history[sym] = hist[-500:]
        else:
            hist[-1] = snapshot_point

        # Persist to SQLite
        try:
            snapshot_storage.save_snapshot(
                symbol=sym,
                spot=chain.spot_price,
                ce_oi=ce_oi,
                pe_oi=pe_oi,
                ce_oi_chg=ce_chg,
                pe_oi_chg=pe_chg,
                pcr=round(pe_oi / max(1, ce_oi), 2),
                confluence=decision.get("confluence_score") if decision else None,
                ce_vol=sum(row.CE.totalTradedVolume for row in atm_strikes),
                pe_vol=sum(row.PE.totalTradedVolume for row in atm_strikes)
            )

            # Persist strike snapshots for ATM +- 10 strikes for Buildup Lab playback
            strikes_10 = [s for s in chain.strikes if abs(s.strikePrice - atm) <= (10 * step)]
            s_data = []
            for s in strikes_10:
                c_prev_oi = max(0, s.CE.openInterest - s.CE.changeinOpenInterest)
                c_oi_pchg = (s.CE.changeinOpenInterest / c_prev_oi * 100.0) if c_prev_oi > 0 else (100.0 if s.CE.openInterest > 0 and s.CE.changeinOpenInterest > 0 else 0.0)
                s_data.append({
                    "strike": s.strikePrice,
                    "option_type": "CE",
                    "ltp": s.CE.lastPrice,
                    "price_pchange": s.CE.pChange,
                    "oi": s.CE.openInterest,
                    "oi_chg": s.CE.changeinOpenInterest,
                    "oi_pchange": round(c_oi_pchg, 2),
                    "volume": s.CE.totalTradedVolume,
                    "is_atm": (s.strikePrice == atm),
                    "expiry_date": s.CE.expiryDate or None,
                    "contract_symbol": s.CE.contract_symbol,
                    "bid": s.CE.bidprice or None,
                    "ask": s.CE.askPrice or None,
                    "source": chain.source,
                    "quality_json": json.dumps(chain.data_quality)
                })
                p_prev_oi = max(0, s.PE.openInterest - s.PE.changeinOpenInterest)
                p_oi_pchg = (s.PE.changeinOpenInterest / p_prev_oi * 100.0) if p_prev_oi > 0 else (100.0 if s.PE.openInterest > 0 and s.PE.changeinOpenInterest > 0 else 0.0)
                s_data.append({
                    "strike": s.strikePrice,
                    "option_type": "PE",
                    "ltp": s.PE.lastPrice,
                    "price_pchange": s.PE.pChange,
                    "oi": s.PE.openInterest,
                    "oi_chg": s.PE.changeinOpenInterest,
                    "oi_pchange": round(p_oi_pchg, 2),
                    "volume": s.PE.totalTradedVolume,
                    "is_atm": (s.strikePrice == atm),
                    "expiry_date": s.PE.expiryDate or None,
                    "contract_symbol": s.PE.contract_symbol,
                    "bid": s.PE.bidprice or None,
                    "ask": s.PE.askPrice or None,
                    "source": chain.source,
                    "quality_json": json.dumps(chain.data_quality)
                })
            snapshot_storage.save_strike_snapshots(sym, s_data)
        except Exception:
            logger.exception("Snapshot/strike persistence failed for %s", sym)

    def analyze(self, chain: ParsedOptionChain, record: bool = True) -> Dict[str, Any]:
        """Generates the complete Call vs Put OI analytics payload."""
        if not chain:
            return {}

        self._check_and_reset_day()
        sym = chain.symbol.upper()
        settings = get_settings()
        step = settings.STRIKE_STEPS.get(sym, 50)
        atm = chain.atm_strike
        spot = chain.spot_price

        # Record snapshot (loads real SQLite history if not in memory)
        if record:
            self.record_snapshot(chain)

        # 1. Timeline Data (Pure Real Market Data Only - Strictly Today between 09:15 and 15:40)
        today = self._current_trade_date
        raw_timeline = self._history.get(sym, [])
        timeline = [
            pt for pt in raw_timeline 
            if pt.get("timestamp", "")[:10] == today and "09:15" <= pt.get("time", "") <= "15:40"
        ]
        self._history[sym] = timeline

        # 2. Strike-Wise Call vs Put Distribution (ATM ± 20 strikes for flexible ±10, ±15, ±20 rendering)
        strikes_filtered = [s for s in chain.strikes if abs(s.strikePrice - atm) <= (20 * step)]
        if not strikes_filtered:
            strikes_filtered = chain.strikes

        # Detect Support & Resistance Walls
        support_strike = atm
        max_pe_oi = 0
        resistance_strike = atm
        max_ce_oi = 0

        for row in chain.strikes:
            if row.strikePrice <= atm and row.PE.openInterest > max_pe_oi:
                max_pe_oi = row.PE.openInterest
                support_strike = row.strikePrice
            if row.strikePrice >= atm and row.CE.openInterest > max_ce_oi:
                max_ce_oi = row.CE.openInterest
                resistance_strike = row.strikePrice

        # Fallback if strikes strictly <= or >= ATM did not yield distinct walls
        if support_strike == resistance_strike or max_pe_oi == 0 or max_ce_oi == 0:
            for row in chain.strikes:
                if row.PE.openInterest > max_pe_oi:
                    max_pe_oi = row.PE.openInterest
                    support_strike = row.strikePrice
                if row.CE.openInterest > max_ce_oi:
                    max_ce_oi = row.CE.openInterest
                    resistance_strike = row.strikePrice

        if support_strike == resistance_strike:
            support_strike = atm - (2 * step)
            resistance_strike = atm + (2 * step)

        strike_comparison = []
        tot_ce_atm_zone = 0
        tot_pe_atm_zone = 0

        for s in strikes_filtered:
            c_oi = s.CE.openInterest
            p_oi = s.PE.openInterest
            c_chg = s.CE.changeinOpenInterest
            p_chg = s.PE.changeinOpenInterest

            tot_ce_atm_zone += c_oi
            tot_pe_atm_zone += p_oi

            net_bias = "CALL_DOMINANT" if c_oi > p_oi * 1.15 else ("PUT_DOMINANT" if p_oi > c_oi * 1.15 else "NEUTRAL")

            strike_comparison.append({
                "strike": s.strikePrice,
                "ce_oi": c_oi,
                "pe_oi": p_oi,
                "ce_oi_chg": c_chg,
                "pe_oi_chg": p_chg,
                "ce_ltp": s.CE.lastPrice,
                "pe_ltp": s.PE.lastPrice,
                "is_atm": s.strikePrice == atm,
                "is_max_pain": s.strikePrice == chain.max_pain,
                "is_support": s.strikePrice == support_strike,
                "is_resistance": s.strikePrice == resistance_strike,
                "net_bias": net_bias,
                "oi_difference": c_oi - p_oi
            })

        # 3. Writer Pressure Metrics
        total_zone_oi = max(1, tot_ce_atm_zone + tot_pe_atm_zone)
        call_pressure_pct = round((tot_ce_atm_zone / total_zone_oi) * 100, 1)
        put_pressure_pct = round((tot_pe_atm_zone / total_zone_oi) * 100, 1)

        # 4. ATM Straddle Decay & Combined Premium
        atm_row = next((s for s in chain.strikes if s.strikePrice == atm), None)
        combined_ltp = round(atm_row.CE.lastPrice + atm_row.PE.lastPrice, 2) if atm_row else 0.0
        now = get_current_ist()
        ref_key = (sym, chain.expiry)
        reference = self._straddle_refs.get(ref_key)
        # Only an actually observed opening-window quote can seed the reference.
        # Never fabricate an opening premium or compare changing ATM contracts.
        if reference is None and atm_row and "09:15" <= now.strftime("%H:%M") <= "09:20" and chain.source not in {"FROZEN", "STALE_CACHE", "MARKET_CLOSED", "SIMULATOR", "UNAVAILABLE"} and combined_ltp > 0:
            reference = {"strike": atm, "premium": combined_ltp, "timestamp": now.isoformat()}
            self._straddle_refs[ref_key] = reference
        ref_row = next((row for row in chain.strikes if reference and row.strikePrice == reference["strike"]), None)
        reference_valid = bool(reference and ref_row and chain.source not in {"FROZEN", "STALE_CACHE", "MARKET_CLOSED", "SIMULATOR", "UNAVAILABLE"})
        open_est = reference["premium"] if reference_valid else None
        reference_current = round(ref_row.CE.lastPrice + ref_row.PE.lastPrice, 2) if reference_valid else None
        decay_pts = round(open_est - reference_current, 2) if reference_valid else None
        decay_pct = round(decay_pts / open_est * 100, 1) if reference_valid else None
        vwap = None  # Quote snapshots do not establish a traded straddle VWAP.

        return {
            "symbol": sym,
            "timestamp": get_current_ist().isoformat(),
            "spot_price": spot,
            "atm_strike": atm,
            "pcr": chain.pcr,
            "pcr_atm_5": chain.pcr_atm_5,
            "max_pain": chain.max_pain,
            "walls": {
                "support_strike": support_strike,
                "support_oi": max_pe_oi,
                "resistance_strike": resistance_strike,
                "resistance_oi": max_ce_oi,
                "wall_range_pts": round(resistance_strike - support_strike, 1),
                "migration_velocity_pts_hr": 0.0,
                "status": "STABLE"
            },
            "pressure": {
                "call_writer_pressure_pct": call_pressure_pct,
                "put_writer_pressure_pct": put_pressure_pct,
                "dominant_side": "CALL_RESISTANCE" if call_pressure_pct > 55 else ("PUT_SUPPORT" if put_pressure_pct > 55 else "BALANCED")
            },
            "straddle": {
                "atm_strike": atm,
                "combined_premium": combined_ltp,
                "estimated_open": open_est,
                "decay_kind": "FIXED_STRIKE_PREMIUM_CHANGE_NOT_PURE_THETA",
                "reference_kind": "OBSERVED_OPENING_QUOTE" if reference_valid else "UNAVAILABLE",
                "reference_strike": reference["strike"] if reference_valid else None,
                "reference_timestamp": reference["timestamp"] if reference_valid else None,
                "reference_current_premium": reference_current,
                "decay_pts": decay_pts,
                "decay_pct": decay_pct,
                "straddle_vwap": vwap,
                "status": "UNAVAILABLE" if decay_pct is None else ("FAST_DECAY" if decay_pct > 8 else ("MODERATE_DECAY" if decay_pct > 3 else "STABLE"))
            },
            "timeline": timeline,
            "strike_comparison": strike_comparison
        }


oi_analyzer = OIAnalyzer()
