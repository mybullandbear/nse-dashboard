"""
Smart Money Intraday Timeline Manager for VCC V3.2.
Provides timestamp normalization, session partitioning (09:15-15:45 IST), and 1-minute deduplication.
Pure analytical module independent of database or network.
"""
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

IST = timezone(timedelta(hours=5, minutes=30))


class SmartMoneyTimelineManager:

    @staticmethod
    def is_within_market_session(time_str: str) -> bool:
        """Strictly filter for Indian Market Session (09:15 - 15:45 IST)."""
        if not time_str:
            return False
        parts = time_str.split(':')
        if len(parts) < 2:
            return False
        try:
            h, m = int(parts[0]), int(parts[1])
            time_mins = h * 60 + m
            return 555 <= time_mins < 940  # 09:15 (555) to 15:40 (940 IST)
        except ValueError:
            return False

    def build_timeline(
        self,
        snapshot_records: List[Any],
        spot_fallback: float = 24500.0
    ) -> List[Dict[str, Any]]:
        """
        Deduplicates raw snapshot records to max 1 point per minute during 09:15-15:45 IST.
        Returns formatted intraday timeline list.
        """
        if not snapshot_records:
            return []

        seen_minutes: Dict[str, Dict[str, Any]] = {}

        for sn in snapshot_records:
            # Extract timestamp attribute or dict key
            ts = getattr(sn, 'timestamp', None) if not isinstance(sn, dict) else sn.get('timestamp')
            if not ts:
                continue

            time_str = ""
            try:
                if isinstance(ts, str):
                    dt = datetime.fromisoformat(ts)
                elif isinstance(ts, datetime):
                    dt = ts
                else:
                    dt = None

                if dt:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=IST)
                    else:
                        dt = dt.astimezone(IST)
                    time_str = dt.strftime("%H:%M")
            except Exception:
                time_str = str(ts).split('T')[1][:5] if 'T' in str(ts) else str(ts)[:5]

            if not self.is_within_market_session(time_str):
                continue

            spot_val = float(getattr(sn, 'spot_price', None) if not isinstance(sn, dict) else sn.get('spot_price', spot_fallback)) or spot_fallback
            ce_oi = int(getattr(sn, 'total_ce_oi', None) if not isinstance(sn, dict) else sn.get('total_ce_oi', 0)) or 0
            pe_oi = int(getattr(sn, 'total_pe_oi', None) if not isinstance(sn, dict) else sn.get('total_pe_oi', 0)) or 0
            ce_oi_chg = int(getattr(sn, 'total_ce_chg', None) if not isinstance(sn, dict) else sn.get('total_ce_chg', 0)) or 0
            pe_oi_chg = int(getattr(sn, 'total_pe_chg', None) if not isinstance(sn, dict) else sn.get('total_pe_chg', 0)) or 0
            sm_score = float(getattr(sn, 'smart_money_score', None) if not isinstance(sn, dict) else sn.get('smart_money_score', 50.0)) or 50.0

            seen_minutes[time_str] = {
                "time": time_str,
                "ce_oi": ce_oi,
                "pe_oi": pe_oi,
                "ce_oi_chg": ce_oi_chg,
                "pe_oi_chg": pe_oi_chg,
                "spot": spot_val,
                "score": sm_score,
                "conviction": sm_score
            }

        if not seen_minutes:
            return []

        return [seen_minutes[k] for k in sorted(seen_minutes.keys())]

    @staticmethod
    def generate_fallback_timeline(spot_base: float = 24500.0) -> List[Dict[str, Any]]:
        times_list = ["09:15", "09:30", "09:45", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30"]
        num_pts = len(times_list)
        fallback = []
        for idx, t in enumerate(times_list):
            factor = (idx + 1) / num_pts
            fallback.append({
                "time": t,
                "ce_oi": int(12500000 * (0.82 + 0.18 * factor)),
                "pe_oi": int(15200000 * (0.78 + 0.22 * factor)),
                "ce_oi_chg": int(340000 * (0.1 + 0.9 * factor)),
                "pe_oi_chg": int(820000 * (0.1 + 0.9 * factor)),
                "spot": round(spot_base * (1 + (factor - 0.5) * 0.003), 2)
            })
        return fallback


smart_money_timeline_manager = SmartMoneyTimelineManager()
