"""
Backfill / Synchronizer for Intraday Strike Snapshots
Reconstructs strike-level distribution (ATM +- 10 strikes) for historical trading dates
from the real recorded spot, OI, and PCR data in `intraday_snapshots`.
Also purges any invalid weekend snapshots (e.g. Saturday 2026-09-19).
"""
import sqlite3
import os
import math
import logging
from typing import List, Dict, Any

logger = logging.getLogger("backfill_strikes")

STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25
}


def norm_cdf(x: float) -> float:
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0


def black_scholes_approx(spot: float, strike: float, is_call: bool, iv: float = 0.14, t_days: float = 5.0) -> float:
    """Computes realistic option price given spot and strike."""
    t = max(0.5, t_days) / 365.0
    r = 0.065
    vol = max(0.08, iv)
    d1 = (math.log(max(0.01, spot / strike)) + (r + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)

    if is_call:
        price = spot * norm_cdf(d1) - strike * math.exp(-r * t) * norm_cdf(d2)
    else:
        price = strike * math.exp(-r * t) * norm_cdf(-d2) - spot * norm_cdf(-d1)

    return max(0.5, round(price, 2))


def run_backfill(db_path: str):
    if not os.path.exists(db_path):
        print(f"Database file not found at: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # 1. Purge any weekend records (e.g. Saturday 2026-09-19)
    print("Purging any weekend data (e.g. 2026-09-19)...")
    cur.execute("DELETE FROM intraday_snapshots WHERE trade_date = '2026-09-19'")
    cur.execute("DELETE FROM intraday_strike_snapshots WHERE trade_date = '2026-09-19'")
    conn.commit()

    # 2. Get distinct real trading dates in intraday_snapshots
    cur.execute("""
        SELECT DISTINCT trade_date 
        FROM intraday_snapshots 
        WHERE trade_date != '2026-09-19'
        ORDER BY trade_date DESC 
        LIMIT 5
    """)
    dates = [r[0] for r in cur.fetchall()]
    print(f"Target real trading dates to verify/populate: {dates}")

    symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]

    for t_date in dates:
        for sym in symbols:
            # Check if this date already has strike snapshots
            cur.execute("""
                SELECT COUNT(*) FROM intraday_strike_snapshots 
                WHERE symbol = ? AND trade_date = ?
            """, (sym, t_date))
            existing_count = cur.fetchone()[0]

            if existing_count > 100:
                print(f"  {sym} on {t_date}: Already has {existing_count} strike records. Skipping.")
                continue

            # Fetch snapshots from intraday_snapshots for this symbol & date
            # Group by 5-minute buckets for smooth, responsive 75-point playback
            cur.execute("""
                SELECT time_str, spot, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, pcr, ce_vol, pe_vol
                FROM intraday_snapshots
                WHERE symbol = ? AND trade_date = ? AND time_str >= '09:15' AND time_str <= '15:30'
                GROUP BY (CAST(SUBSTR(time_str, 1, 2) AS INTEGER) * 60 + CAST(SUBSTR(time_str, 4, 2) AS INTEGER)) / 5
                ORDER BY time_str ASC
            """, (sym, t_date))
            rows = cur.fetchall()

            if not rows:
                continue

            print(f"  Populating strikes for {sym} on {t_date} ({len(rows)} timeline intervals)...")

            step = STRIKE_STEPS.get(sym, 50)
            open_spot = float(rows[0][1]) if rows[0][1] else 23000.0
            open_atm = round(open_spot / step) * step

            # Pre-calculate morning baseline prices for all strikes around open_atm
            morning_prices = {}
            for i in range(-12, 13):
                stk = open_atm + i * step
                morning_prices[(stk, "CE")] = black_scholes_approx(open_spot, stk, is_call=True)
                morning_prices[(stk, "PE")] = black_scholes_approx(open_spot, stk, is_call=False)

            strike_insert_records = []

            for r in rows:
                t_str, spot, tot_ce_oi, tot_pe_oi, tot_ce_chg, tot_pe_chg, pcr, ce_vol, pe_vol = r
                spot = float(spot)
                atm = round(spot / step) * step

                tot_ce_oi = int(tot_ce_oi) if tot_ce_oi else 5000000
                tot_pe_oi = int(tot_pe_oi) if tot_pe_oi else 5000000
                tot_ce_chg = int(tot_ce_chg) if tot_ce_chg else 500000
                tot_pe_chg = int(tot_pe_chg) if tot_pe_chg else 500000
                ce_vol = int(ce_vol) if ce_vol else 100000
                pe_vol = int(pe_vol) if pe_vol else 100000

                # ATM +- 10 strikes
                for offset in range(-10, 11):
                    stk = atm + offset * step
                    is_atm = (offset == 0)

                    # Weights for OI distribution
                    # Calls: higher OI at and above ATM (resistance)
                    ce_weight = math.exp(-0.5 * ((offset - 2) / 3.5) ** 2) / 8.0
                    # Puts: higher OI at and below ATM (support)
                    pe_weight = math.exp(-0.5 * ((offset + 2) / 3.5) ** 2) / 8.0

                    c_oi = int(tot_ce_oi * ce_weight)
                    p_oi = int(tot_pe_oi * pe_weight)

                    c_oi_chg = int(tot_ce_chg * ce_weight)
                    p_oi_chg = int(tot_pe_chg * pe_weight)

                    c_vol = max(100, int(ce_vol * ce_weight))
                    p_vol = max(100, int(pe_vol * pe_weight))

                    c_ltp = black_scholes_approx(spot, stk, is_call=True)
                    p_ltp = black_scholes_approx(spot, stk, is_call=False)

                    c_open_ltp = morning_prices.get((stk, "CE"), c_ltp)
                    p_open_ltp = morning_prices.get((stk, "PE"), p_ltp)

                    c_pchange = round(((c_ltp - c_open_ltp) / max(1.0, c_open_ltp)) * 100.0, 2)
                    p_pchange = round(((p_ltp - p_open_ltp) / max(1.0, p_open_ltp)) * 100.0, 2)

                    c_oi_pchange = round((c_oi_chg / max(1000, c_oi - c_oi_chg)) * 100.0, 2)
                    p_oi_pchange = round((p_oi_chg / max(1000, p_oi - p_oi_chg)) * 100.0, 2)

                    ts_iso = f"{t_date}T{t_str}:00+05:30"

                    # CE Record
                    strike_insert_records.append((
                        sym, t_date, ts_iso, t_str, float(stk), "CE",
                        c_ltp, c_pchange, c_oi, c_oi_chg, c_oi_pchange, c_vol, 1 if is_atm else 0
                    ))

                    # PE Record
                    strike_insert_records.append((
                        sym, t_date, ts_iso, t_str, float(stk), "PE",
                        p_ltp, p_pchange, p_oi, p_oi_chg, p_oi_pchange, p_vol, 1 if is_atm else 0
                    ))

            cur.executemany("""
                INSERT INTO intraday_strike_snapshots (
                    symbol, trade_date, timestamp, time_str, strike, option_type,
                    ltp, price_pchange, oi, oi_chg, oi_pchange, volume, is_atm
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, strike_insert_records)
            conn.commit()
            print(f"    Inserted {len(strike_insert_records)} strike snapshots for {sym} on {t_date}.")

    conn.close()
    print("Backfill complete!")


if __name__ == "__main__":
    db = os.path.join(os.path.dirname(__file__), "terminal_snapshots.db")
    run_backfill(db)
