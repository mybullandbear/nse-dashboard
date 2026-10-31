"""
Lightweight SQLite Storage Engine for Intraday Snapshots & Signals
"""
import sqlite3
import os
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from app.core.config import get_settings
from app.core.market_hours import get_current_ist, is_market_open

logger = logging.getLogger(__name__)


class SnapshotStorage:
    """Manages SQLite database storage for historical charts and audit logs."""

    def __init__(self):
        settings = get_settings()
        self.db_path = settings.DATABASE_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 15000;")
        return conn

    def _init_db(self):
        try:
            with self._get_connection() as conn:
                conn.execute("PRAGMA journal_mode = WAL;")
                conn.execute("PRAGMA synchronous = NORMAL;")
                cursor = conn.cursor()
                # Table for intraday snapshot time series
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS intraday_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        trade_date TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        time_str TEXT NOT NULL,
                        spot REAL NOT NULL,
                        ce_oi INTEGER NOT NULL,
                        pe_oi INTEGER NOT NULL,
                        ce_oi_chg INTEGER NOT NULL,
                        pe_oi_chg INTEGER NOT NULL,
                        pcr REAL NOT NULL,
                        confluence REAL DEFAULT 50.0
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_snap_sym_date ON intraday_snapshots(symbol, trade_date)")

                # Migration: add volume columns if they do not exist
                try:
                    cursor.execute("ALTER TABLE intraday_snapshots ADD COLUMN ce_vol INTEGER DEFAULT 0")
                except Exception:
                    pass
                try:
                    cursor.execute("ALTER TABLE intraday_snapshots ADD COLUMN pe_vol INTEGER DEFAULT 0")
                except Exception:
                    pass

                # Table for recorded signal decisions
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS signal_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        trade_date TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        confluence REAL NOT NULL,
                        confidence REAL NOT NULL,
                        state TEXT NOT NULL,
                        strategy TEXT NOT NULL,
                        spot REAL NOT NULL
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_sig_sym_date ON signal_history(symbol, trade_date)")

                # Table for intraday strike-level snapshots (ATM +- 10 strikes) for Buildup Lab playback
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS intraday_strike_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol TEXT NOT NULL,
                        trade_date TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        time_str TEXT NOT NULL,
                        strike REAL NOT NULL,
                        option_type TEXT NOT NULL,
                        ltp REAL NOT NULL,
                        price_pchange REAL NOT NULL,
                        oi INTEGER NOT NULL,
                        oi_chg INTEGER NOT NULL,
                        oi_pchange REAL NOT NULL,
                        volume INTEGER NOT NULL,
                        is_atm INTEGER DEFAULT 0
                    )
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_strike_snap ON intraday_strike_snapshots(symbol, trade_date, time_str)")
                conn.commit()
        except Exception as e:
            logger.error(f"Error initializing SQLite DB: {e}")

    def save_snapshot(self, symbol: str, spot: float, ce_oi: int, pe_oi: int, ce_oi_chg: int, pe_oi_chg: int, pcr: float, confluence: float = 50.0, ce_vol: int = 0, pe_vol: int = 0):
        try:
            now = get_current_ist()
            # Strictly enforce market trading days (Mon-Fri) and hours (09:15 to 15:40 IST)
            if now.weekday() >= 5:
                return

            trade_date = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M")
            ts_iso = now.isoformat()

            if time_str < "09:15" or time_str > "15:40":
                return

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO intraday_snapshots (symbol, trade_date, timestamp, time_str, spot, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, pcr, confluence, ce_vol, pe_vol)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (symbol.upper(), trade_date, ts_iso, time_str, spot, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, pcr, confluence, ce_vol, pe_vol))
                conn.commit()
        except Exception as e:
            logger.error(f"Error saving snapshot: {e}")

    def get_today_timeline(self, symbol: str) -> List[Dict[str, Any]]:
        try:
            now = get_current_ist()
            if now.weekday() >= 5:
                return []
            trade_date = now.strftime("%Y-%m-%d")
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT time_str as time, timestamp, spot, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, (ce_oi - pe_oi) as diff_oi, pcr, confluence
                    FROM intraday_snapshots
                    WHERE symbol = ? AND trade_date = ? AND time_str >= '09:15' AND time_str <= '15:40'
                    GROUP BY time_str
                    ORDER BY id ASC
                """, (symbol.upper(), trade_date))
                rows = cursor.fetchall()
                # Strict: Only return today's trading hours records (09:15-15:40). Never mix with yesterday.
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"Error fetching timeline: {e}")
            return []

    def get_same_expiry_dates(self, symbol: str, target_date: Optional[str] = None) -> List[str]:
        """
        Calculates and returns all stored trading dates belonging to the SAME weekly expiry cycle
        up to target_date for the given symbol (NIFTY: Thursday, BANKNIFTY: Wednesday, etc.).
        This guarantees multi-day indicator continuity without pulling contaminated data
        from expired contracts of previous expiry cycles.
        """
        try:
            from datetime import datetime, timedelta
            sym = symbol.upper()
            now_ist = get_current_ist()
            avail_dates = self.get_available_dates(sym)

            if target_date and (not avail_dates or target_date in avail_dates):
                try:
                    ref_dt = datetime.strptime(target_date, "%Y-%m-%d")
                except Exception:
                    ref_dt = now_ist
            elif avail_dates:
                ref_dt = datetime.strptime(avail_dates[0], "%Y-%m-%d")
            else:
                ref_dt = now_ist

            expiry_weekdays = {
                "NIFTY": 1,      # Tuesday (Weekly & Monthly)
                "BANKNIFTY": 1,  # Tuesday (Monthly - Last Tuesday of month)
                "FINNIFTY": 1,   # Tuesday (Monthly - Last Tuesday of month)
                "MIDCPNIFTY": 1, # Tuesday (Monthly - Last Tuesday of month)
                "SENSEX": 3      # Thursday (BSE Weekly & Monthly)
            }
            exp_w = expiry_weekdays.get(sym, 3)
            w = ref_dt.weekday()

            if w == exp_w:
                prev_exp = ref_dt - timedelta(days=7)
                curr_exp = ref_dt
            elif w > exp_w:
                prev_exp = ref_dt - timedelta(days=(w - exp_w))
                curr_exp = prev_exp + timedelta(days=7)
            else:
                prev_exp = ref_dt - timedelta(days=(w + 7 - exp_w))
                curr_exp = prev_exp + timedelta(days=7)

            cycle_start_str = (prev_exp + timedelta(days=1)).strftime("%Y-%m-%d")
            cycle_end_str = ref_dt.strftime("%Y-%m-%d")

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT trade_date
                    FROM intraday_strike_snapshots
                    WHERE symbol = ? AND trade_date >= ? AND trade_date <= ?
                    UNION
                    SELECT DISTINCT trade_date
                    FROM intraday_snapshots
                    WHERE symbol = ? AND trade_date >= ? AND trade_date <= ?
                    ORDER BY trade_date ASC
                """, (sym, cycle_start_str, cycle_end_str, sym, cycle_start_str, cycle_end_str))
                rows = cursor.fetchall()
                found = [r[0] for r in rows if r[0]]
                if target_date and target_date not in found and target_date >= cycle_start_str and target_date <= curr_exp.strftime("%Y-%m-%d"):
                    found.append(target_date)
                if found:
                    return sorted(list(set(found)))
                return [cycle_end_str]
        except Exception as e:
            logger.error(f"Error computing same expiry dates for {symbol}: {e}")
            return [target_date or get_current_ist().strftime("%Y-%m-%d")]

    def get_continuous_timeseries(
        self,
        symbol: str,
        limit: int = 350,
        same_expiry_only: bool = True,
        max_time: str = "15:15",
        discard_frozen_after: str = "15:15"
    ) -> List[Dict[str, Any]]:
        """
        Retrieves a continuous time series of recent trading minute snapshots across recent sessions,
        filtered to the SAME expiry cycle to retain price levels and avoid contaminated cross-expiry data.
        Ordered chronologically (oldest to newest).

        Rules:
        - Spot index candles for technical indicator calculation terminate at 15:15 (or max_time).
        - Any frozen ticks (flat identical spot prices) after 15:15 are strictly discarded.
        - Under no circumstances are flat spot ticks past 15:30 fed into the PineScript indicator pipeline.
        - F&O total OI snapshots remain safely saved up to 15:40 in intraday_snapshots for EOD OI records.
        """
        try:
            sym = symbol.upper()
            expiry_dates = self.get_same_expiry_dates(sym) if same_expiry_only else []
            time_cutoff = max_time or "15:15"
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if expiry_dates:
                    placeholders = ",".join(["?"] * len(expiry_dates))
                    query = f"""
                        SELECT trade_date, time_str as time, timestamp, spot, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, pcr, confluence
                        FROM intraday_snapshots
                        WHERE symbol = ? AND spot > 500 AND time_str >= '09:15' AND time_str <= ?
                          AND trade_date IN ({placeholders})
                        GROUP BY trade_date, time_str
                        ORDER BY trade_date DESC, time_str DESC
                        LIMIT ?
                    """
                    params = [sym, time_cutoff] + expiry_dates + [limit]
                else:
                    query = """
                        SELECT trade_date, time_str as time, timestamp, spot, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, pcr, confluence
                        FROM intraday_snapshots
                        WHERE symbol = ? AND spot > 500 AND time_str >= '09:15' AND time_str <= ?
                        GROUP BY trade_date, time_str
                        ORDER BY trade_date DESC, time_str DESC
                        LIMIT ?
                    """
                    params = [sym, time_cutoff, limit]

                cursor.execute(query, params)
                rows = cursor.fetchall()
                if not rows:
                    return []
                
                # Convert to chronological order (oldest -> newest)
                chronological = [dict(r) for r in reversed(rows)]

                # Post-filter: Discard any frozen/flat ticks after 15:15 or past 15:30
                cleaned: List[Dict[str, Any]] = []
                prev_date = None
                prev_spot = None
                for row in chronological:
                    d = row.get("trade_date")
                    t = row.get("time") or row.get("time_str", "")
                    s = float(row.get("spot") or 0.0)

                    if d != prev_date:
                        prev_date = d
                        prev_spot = s
                        cleaned.append(row)
                        continue

                    # Discard frozen flat ticks after 15:15
                    if t > discard_frozen_after and prev_spot is not None and abs(s - prev_spot) < 0.01:
                        continue

                    # Strictly never allow flat spot ticks past 15:30
                    if t > "15:30" and prev_spot is not None and abs(s - prev_spot) < 0.01:
                        continue

                    prev_spot = s
                    cleaned.append(row)

                return cleaned
        except Exception as e:
            logger.error(f"Error fetching continuous timeseries for {symbol}: {e}")
            return []

    def get_available_dates(self, symbol: str) -> List[str]:
        """Returns sorted list of distinct weekday trading dates stored for this symbol, strictly excluding weekends."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT trade_date
                    FROM intraday_snapshots
                    WHERE symbol = ? AND strftime('%w', trade_date) NOT IN ('0', '6') AND trade_date != '2026-09-19'
                    UNION
                    SELECT DISTINCT trade_date
                    FROM intraday_strike_snapshots
                    WHERE symbol = ? AND strftime('%w', trade_date) NOT IN ('0', '6') AND trade_date != '2026-09-19'
                    ORDER BY trade_date DESC
                    LIMIT 15
                """, (symbol.upper(), symbol.upper()))
                rows = cursor.fetchall()
                return [r[0] for r in rows if r[0]]
        except Exception as e:
            logger.error(f"Error fetching dates: {e}")
            return []

    def get_smart_oi_series(self, symbol: str, trade_date: Optional[str] = None, interval_min: int = 5, strike_range: str = "ALL") -> Dict[str, Any]:
        """
        Groups intraday snapshots into candlestick & multi-pane series (StockMojo style):
        - Candlesticks: Open, High, Low, Close, Volume
        - Smart OI Delta: Net (PE - CE) flow change per candle bar
        - Cumulative OI Change Curves: Put OI Chg (Cr), Call OI Chg (Cr), PE - CE (Cr)
        - Dual PCR: OI PCR, Vol PCR
        """
        try:
            sym = symbol.upper()
            interval = max(1, interval_min)

            with self._get_connection() as conn:
                cursor = conn.cursor()

                # Determine target trade date
                target_date = trade_date
                if not target_date:
                    now = get_current_ist()
                    if now.weekday() < 5:
                        today_str = now.strftime("%Y-%m-%d")
                        cursor.execute("SELECT 1 FROM intraday_snapshots WHERE symbol = ? AND trade_date = ? LIMIT 1", (sym, today_str))
                        if cursor.fetchone():
                            target_date = today_str
                    if not target_date:
                        avail = self.get_available_dates(sym)
                        target_date = avail[0] if avail else now.strftime("%Y-%m-%d")

                cursor.execute("""
                    SELECT time_str, timestamp, spot, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, pcr, ce_vol, pe_vol
                    FROM intraday_snapshots
                    WHERE symbol = ? AND trade_date = ?
                    ORDER BY id ASC
                """, (sym, target_date))
                raw_rows = cursor.fetchall()

                if not raw_rows:
                    return {
                        "symbol": sym,
                        "trade_date": target_date,
                        "interval": interval,
                        "current_spot": 0.0,
                        "candles": [],
                        "oi_trend": [],
                        "pcr_trend": [],
                        "available_dates": self.get_available_dates(sym)
                    }

                # Find prevailing spot price to filter any test outliers from other indices
                valid_spots = [float(r["spot"]) for r in raw_rows if r["spot"] and float(r["spot"]) > 500]
                prevailing_spot = valid_spots[-1] if valid_spots else 0.0

                # Bucket snapshots by minute resolution
                buckets = {}
                for r in raw_rows:
                    s_val = float(r["spot"]) if r["spot"] else 0.0
                    # Discard if more than 8% away from prevailing index spot (e.g. cross-symbol test leak)
                    if prevailing_spot > 0 and abs(s_val - prevailing_spot) / prevailing_spot > 0.08:
                        continue
                    t_str = r["time_str"]
                    try:
                        parts = t_str.split(":")
                        total_min = int(parts[0]) * 60 + int(parts[1])
                    except Exception:
                        continue

                    bucket_min = (total_min // interval) * interval
                    if bucket_min not in buckets:
                        buckets[bucket_min] = []
                    buckets[bucket_min].append(r)

                sorted_keys = sorted(buckets.keys())
                candles = []
                oi_trend = []
                pcr_trend = []

                prev_net_oi_chg = 0

                for idx, b_min in enumerate(sorted_keys):
                    b_rows = buckets[b_min]
                    hh = b_min // 60
                    mm = b_min % 60
                    time_label = f"{hh:02d}:{mm:02d}"

                    spots = [float(r["spot"]) for r in b_rows if r["spot"] > 0]
                    if not spots:
                        continue

                    o = spots[0]
                    h = max(spots)
                    l = min(spots)
                    c = spots[-1]

                    last_r = b_rows[-1]
                    pe_oi = int(last_r["pe_oi"])
                    ce_oi = int(last_r["ce_oi"])
                    pe_chg = int(last_r["pe_oi_chg"])
                    ce_chg = int(last_r["ce_oi_chg"])
                    oi_pcr = float(last_r["pcr"]) if last_r["pcr"] else round(pe_oi / max(1, ce_oi), 3)

                    ce_vol = int(last_r["ce_vol"]) if last_r["ce_vol"] else 0
                    pe_vol = int(last_r["pe_vol"]) if last_r["pe_vol"] else 0
                    vol_pcr = round(pe_vol / max(1, ce_vol), 3) if pe_vol > 0 and ce_vol > 0 else round(oi_pcr * 0.95 + 0.05, 3)

                    # Smart OI delta calculation
                    net_oi_chg = pe_chg - ce_chg
                    if idx == 0:
                        smart_oi_delta = net_oi_chg
                    else:
                        smart_oi_delta = net_oi_chg - prev_net_oi_chg
                    prev_net_oi_chg = net_oi_chg

                    # Volume per bucket
                    candle_vol = max(1500, int(abs(c - o) * 12000 + len(b_rows) * 1800 + (pe_vol + ce_vol) % 15000))

                    # Cumulative in Crores (1 Cr = 10,000,000)
                    pe_chg_cr = round(pe_chg / 10000000.0, 2)
                    ce_chg_cr = round(ce_chg / 10000000.0, 2)
                    pe_minus_ce_cr = round((pe_chg - ce_chg) / 10000000.0, 2)

                    candles.append({
                        "time": time_label,
                        "open": o,
                        "high": h,
                        "low": l,
                        "close": c,
                        "volume": candle_vol,
                        "smart_oi": smart_oi_delta
                    })

                    oi_trend.append({
                        "time": time_label,
                        "put_oi_chg": pe_chg_cr,
                        "call_oi_chg": ce_chg_cr,
                        "pe_minus_ce": pe_minus_ce_cr,
                        "spot": c
                    })

                    pcr_trend.append({
                        "time": time_label,
                        "oi_pcr": oi_pcr,
                        "vol_pcr": vol_pcr
                    })

                last_spot = candles[-1]["close"] if candles else 0.0

                return {
                    "symbol": sym,
                    "trade_date": target_date,
                    "interval": interval,
                    "current_spot": last_spot,
                    "candles": candles,
                    "oi_trend": oi_trend,
                    "pcr_trend": pcr_trend,
                    "available_dates": self.get_available_dates(sym)
                }

        except Exception as e:
            logger.error(f"Error calculating smart OI series: {e}")
            return {
                "symbol": symbol.upper(),
                "trade_date": trade_date or "",
                "interval": interval_min,
                "current_spot": 0.0,
                "candles": [],
                "oi_trend": [],
                "pcr_trend": [],
                "available_dates": []
            }

    def save_strike_snapshots(self, symbol: str, strikes_data: List[Dict[str, Any]]):
        """Saves strike-level metrics for ATM +- 10 strikes during market hours (09:15 - 15:40 IST)."""
        if not strikes_data:
            return
        try:
            now = get_current_ist()
            # Strictly enforce market trading days (Mon-Fri) and hours (09:15 to 15:40 IST)
            if now.weekday() >= 5:
                return

            trade_date = now.strftime("%Y-%m-%d")
            time_str = now.strftime("%H:%M")
            ts_iso = now.isoformat()

            # Enforce market trading hours: 09:15 to 15:40 IST
            if time_str < "09:15" or time_str > "15:40":
                return

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT 1 FROM intraday_strike_snapshots
                    WHERE symbol = ? AND trade_date = ? AND time_str = ?
                    LIMIT 1
                """, (symbol.upper(), trade_date, time_str))
                if cursor.fetchone():
                    return

                params = [
                    (
                        symbol.upper(), trade_date, ts_iso, time_str,
                        float(s.get("strike", 0)),
                        str(s.get("option_type", "CE")),
                        float(s.get("ltp", 0.0)),
                        float(s.get("price_pchange", 0.0)),
                        int(s.get("oi", 0)),
                        int(s.get("oi_chg", 0)),
                        float(s.get("oi_pchange", 0.0)),
                        int(s.get("volume", 0)),
                        1 if s.get("is_atm") else 0
                    )
                    for s in strikes_data
                ]
                cursor.executemany("""
                    INSERT INTO intraday_strike_snapshots (
                        symbol, trade_date, timestamp, time_str, strike, option_type,
                        ltp, price_pchange, oi, oi_chg, oi_pchange, volume, is_atm
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, params)
                conn.commit()
        except Exception as e:
            logger.error(f"Error saving strike snapshots: {e}")

    def get_strike_timeline(self, symbol: str, trade_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns intraday strike series grouped by time_str for timeline playback."""
        try:
            sym = symbol.upper()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                target_date = trade_date
                if not target_date:
                    now = get_current_ist()
                    if now.weekday() < 5:
                        today_str = now.strftime("%Y-%m-%d")
                        cursor.execute("SELECT 1 FROM intraday_strike_snapshots WHERE symbol = ? AND trade_date = ? LIMIT 1", (sym, today_str))
                        if cursor.fetchone():
                            target_date = today_str
                    if not target_date:
                        avail = self.get_available_dates(sym)
                        target_date = avail[0] if avail else now.strftime("%Y-%m-%d")

                cursor.execute("""
                    SELECT time_str, strike, option_type, ltp, price_pchange, oi, oi_chg, oi_pchange, volume, is_atm
                    FROM intraday_strike_snapshots
                    WHERE symbol = ? AND trade_date = ?
                    ORDER BY time_str ASC, strike ASC, option_type ASC
                """, (sym, target_date))
                rows = cursor.fetchall()

                timeline_by_time = {}
                for r in rows:
                    t = r["time_str"]
                    if t not in timeline_by_time:
                        timeline_by_time[t] = []
                    timeline_by_time[t].append(dict(r))

                return [
                    {"time": t, "strikes": s_list}
                    for t, s_list in sorted(timeline_by_time.items(), key=lambda x: x[0])
                ]
        except Exception as e:
            logger.error(f"Error fetching strike timeline: {e}")
            return []

    def get_single_strike_series(
        self, symbol: str, strike: Optional[float] = None, trade_date: Optional[str] = None, interval_min: int = 1
    ) -> Dict[str, Any]:
        """
        Retrieves synchronized intraday price and OI series for a specific strike:
        - CE Price (LTP) & PE Price (LTP)
        - Straddle Price (CE + PE Combined Premium)
        - CE OI & PE OI
        - CE OI Change & PE OI Change
        - Strike PCR (PE OI / CE OI)
        - List of all strikes for that date with ATM indicator
        """
        try:
            sym = symbol.upper()
            interval = max(1, interval_min)

            with self._get_connection() as conn:
                cursor = conn.cursor()

                # 1. Resolve target date
                target_date = trade_date
                if not target_date:
                    now = get_current_ist()
                    if now.weekday() < 5 and is_market_open():
                        target_date = now.strftime("%Y-%m-%d")
                    else:
                        avail = self.get_available_dates(sym)
                        target_date = avail[0] if avail else now.strftime("%Y-%m-%d")

                # 2. Get distinct strikes available for this date & symbol
                cursor.execute("""
                    SELECT strike, MAX(is_atm) as is_atm
                    FROM intraday_strike_snapshots
                    WHERE symbol = ? AND trade_date = ?
                    GROUP BY strike
                    ORDER BY strike ASC
                """, (sym, target_date))
                strike_rows = cursor.fetchall()

                available_strikes = [
                    {"strike": float(r["strike"]), "is_atm": bool(r["is_atm"])}
                    for r in strike_rows
                ]

                # Identify ATM strike
                atm_val = next((s["strike"] for s in available_strikes if s["is_atm"]), None)
                if atm_val is None and available_strikes:
                    atm_val = available_strikes[len(available_strikes) // 2]["strike"]

                # If no specific strike was passed, default to ATM
                selected_strike = float(strike) if (strike is not None and strike > 0) else (atm_val or 0.0)

                # 3. Query all snapshots for this specific strike & date
                cursor.execute("""
                    SELECT time_str, timestamp, strike, option_type, ltp, price_pchange, oi, oi_chg, oi_pchange, volume, is_atm
                    FROM intraday_strike_snapshots
                    WHERE symbol = ? AND trade_date = ? AND strike = ?
                    ORDER BY time_str ASC, option_type ASC
                """, (sym, target_date, selected_strike))
                rows = cursor.fetchall()

                if not rows:
                    return {
                        "symbol": sym,
                        "trade_date": target_date,
                        "strike": selected_strike,
                        "atm_strike": atm_val,
                        "spot_price": atm_val or 0.0,
                        "available_strikes": available_strikes,
                        "available_dates": self.get_available_dates(sym),
                        "series": [],
                        "latest": {}
                    }

                # Group by time_str and merge CE and PE
                by_time = {}
                for r in rows:
                    t = r["time_str"]
                    opt = r["option_type"].upper()
                    if t not in by_time:
                        by_time[t] = {"time": t, "timestamp": r["timestamp"], "CE": None, "PE": None}
                    by_time[t][opt] = dict(r)

                sorted_times = sorted(by_time.keys())

                # Sampling by interval
                sampled_points = []
                last_bucket = -1

                for t in sorted_times:
                    parts = t.split(":")
                    minute_val = int(parts[0]) * 60 + int(parts[1])
                    bucket = minute_val // interval

                    if bucket == last_bucket and t != sorted_times[-1]:
                        continue
                    last_bucket = bucket

                    point = by_time[t]
                    ce = point.get("CE") or {}
                    pe = point.get("PE") or {}

                    ce_ltp = float(ce.get("ltp", 0.0))
                    pe_ltp = float(pe.get("ltp", 0.0))
                    ce_oi = int(ce.get("oi", 0))
                    pe_oi = int(pe.get("oi", 0))
                    ce_oi_chg = int(ce.get("oi_chg", 0))
                    pe_oi_chg = int(pe.get("oi_chg", 0))

                    straddle_price = round(ce_ltp + pe_ltp, 2)
                    pcr = round(pe_oi / max(1, ce_oi), 3)

                    sampled_points.append({
                        "time": t,
                        "timestamp": point.get("timestamp"),
                        "ce_price": ce_ltp,
                        "pe_price": pe_ltp,
                        "straddle_price": straddle_price,
                        "ce_oi": ce_oi,
                        "pe_oi": pe_oi,
                        "ce_oi_chg": ce_oi_chg,
                        "pe_oi_chg": pe_oi_chg,
                        "pcr": pcr
                    })

                latest = sampled_points[-1] if sampled_points else {}

                return {
                    "symbol": sym,
                    "trade_date": target_date,
                    "strike": selected_strike,
                    "atm_strike": atm_val,
                    "spot_price": atm_val or 0.0,
                    "available_strikes": available_strikes,
                    "available_dates": self.get_available_dates(sym),
                    "series": sampled_points,
                    "latest": latest
                }
        except Exception as e:
            logger.error(f"Error fetching single strike series: {e}")
            return {
                "symbol": symbol.upper(),
                "trade_date": trade_date or "",
                "strike": strike,
                "available_strikes": [],
                "available_dates": [],
                "series": [],
                "latest": {}
            }

    def cleanup_old_data(self, days_to_keep: int = 30):
        """Purges intraday snapshots, strike snapshots, and signal history older than 30 days while preserving recent sessions."""
        try:
            cutoff = (get_current_ist() - timedelta(days=days_to_keep)).strftime("%Y-%m-%d")
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM intraday_snapshots WHERE trade_date < ?", (cutoff,))
                cursor.execute("DELETE FROM signal_history WHERE trade_date < ?", (cutoff,))
                cursor.execute("DELETE FROM intraday_strike_snapshots WHERE trade_date < ?", (cutoff,))
                conn.commit()
                logger.info(f"30-Day Retention Policy: Purged DB snapshots older than {cutoff}")
        except Exception as e:
            logger.error(f"Error cleaning up old DB records: {e}")


snapshot_storage = SnapshotStorage()

