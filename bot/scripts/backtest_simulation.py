"""
Empirical Backtest Simulation Harness
Evaluates SmartTrackerBot across historical option chain tick records.
Tests:
1. Concurrency enforcement (Max 1 trade per symbol)
2. PineScript OTT Trend Alignment & ADX Velocity Gating
3. Dynamic Breakeven ladder
4. Gross vs Net P&L (₹100/lot brokerage deduction)
"""
import os
import sys
import sqlite3
from typing import Dict, Any, List

# Add parent directories to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from bot.engine.technical_indicators import TechnicalIndicators

# Search for terminal_snapshots.db in common locations
POSSIBLE_DB_PATHS = [
    os.path.join(os.path.dirname(__file__), "..", "..", "backend", "app", "db", "terminal_snapshots.db"),
    os.path.join(os.path.dirname(__file__), "terminal_snapshots.db"),
    os.path.join(os.getcwd(), "terminal_snapshots.db")
]

DB_PATH = next((p for p in POSSIBLE_DB_PATHS if os.path.exists(p)), POSSIBLE_DB_PATHS[0])

LOT_SIZES = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120}
STRIKE_STEPS = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25}
MIN_PREMIUMS = {"NIFTY": 45.0, "BANKNIFTY": 75.0, "FINNIFTY": 40.0, "MIDCPNIFTY": 25.0}


class SimTrade:
    def __init__(self, tid, sym, role, strat, strike, otype, entry_t, entry_p, target_p, sl_p, lot, tqs=0.0):
        self.tid = tid
        self.sym = sym
        self.role = role
        self.strat = strat
        self.strike = strike
        self.otype = otype
        self.entry_t = entry_t
        self.entry_p = entry_p
        self.curr_p = entry_p
        self.target_p = target_p
        self.sl_p = sl_p
        self.trailing_sl = sl_p
        self.lot = lot
        self.tqs = tqs
        self.status = "OPEN"
        self.exit_t = ""
        self.exit_p = 0.0
        self.exit_reason = ""
        self.gross_pnl = 0.0
        self.net_pnl = 0.0
        self.brokerage = 100.0
        self.mfe_inr = 0.0
        self.mae_inr = 0.0

    def update_mtm(self, ltp):
        if self.status != "OPEN":
            return
        self.curr_p = ltp
        pts = (ltp - self.entry_p) if self.role == "BUYER" else (self.entry_p - ltp)
        gross = pts * self.lot
        self.mfe_inr = max(self.mfe_inr, gross)
        self.mae_inr = min(self.mae_inr, gross)

        if self.role == "BUYER":
            gain_pct = (ltp - self.entry_p) / self.entry_p if self.entry_p > 0 else 0
            if gain_pct >= 0.60:
                self.trailing_sl = max(self.trailing_sl, round(self.entry_p * 1.35, 2))
            elif gain_pct >= 0.35:
                self.trailing_sl = max(self.trailing_sl, round(self.entry_p * 1.15, 2))
            elif gain_pct >= 0.20:
                self.trailing_sl = max(self.trailing_sl, self.entry_p)
        else:
            decay_pct = (self.entry_p - ltp) / self.entry_p if self.entry_p > 0 else 0
            if decay_pct >= 0.60:
                self.trailing_sl = min(self.trailing_sl, round(self.entry_p * 0.40, 2))
            elif decay_pct >= 0.35:
                self.trailing_sl = min(self.trailing_sl, self.entry_p)

    def close(self, exit_p, exit_t, reason):
        self.status = "CLOSED"
        self.exit_p = exit_p
        self.exit_t = exit_t
        self.exit_reason = reason
        pts = (exit_p - self.entry_p) if self.role == "BUYER" else (self.entry_p - exit_p)
        self.gross_pnl = round(pts * self.lot, 2)
        self.net_pnl = round(self.gross_pnl - self.brokerage, 2)


def build_minute_candles(snapshots: List[sqlite3.Row]) -> Dict[str, Dict[str, Dict[str, float]]]:
    bars: Dict[str, Dict[str, Dict[str, float]]] = {}
    for snap in snapshots:
        sym = snap["symbol"]
        t_str = snap["time_str"]
        spot = snap["spot"]
        if sym not in bars:
            bars[sym] = {}
        if t_str not in bars[sym]:
            bars[sym][t_str] = {"open": spot, "high": spot, "low": spot, "close": spot}
        else:
            b = bars[sym][t_str]
            b["high"] = max(b["high"], spot)
            b["low"] = min(b["low"], spot)
            b["close"] = spot
    return bars


def compute_symbol_indicators(candles: Dict[str, Dict[str, float]], ott_percent: float = 0.30, adx_len: int = 9) -> Dict[str, Dict[str, Any]]:
    sorted_times = sorted(candles.keys())
    highs = [candles[t]["high"] for t in sorted_times]
    lows = [candles[t]["low"] for t in sorted_times]
    closes = [candles[t]["close"] for t in sorted_times]

    plus_di, minus_di, adx = TechnicalIndicators.compute_adx(highs, lows, closes, length=adx_len)
    mavg, ott, trend_state = TechnicalIndicators.compute_ott(closes, length=2, percent=ott_percent)

    result = {}
    for i, t in enumerate(sorted_times):
        result[t] = {
            "close": closes[i],
            "plus_di": plus_di[i],
            "minus_di": minus_di[i],
            "adx": adx[i],
            "mavg": mavg[i],
            "ott": ott[i],
            "ott_state": trend_state[i]
        }
    return result


def run_simulation(target_date: str, db_path: str = DB_PATH) -> Dict[str, Any]:
    if not os.path.exists(db_path):
        return {"error": f"Database file not found at {db_path}"}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT * FROM intraday_snapshots WHERE trade_date = ? ORDER BY timestamp ASC, id ASC", (target_date,))
    snapshots = c.fetchall()

    c.execute("SELECT * FROM intraday_strike_snapshots WHERE trade_date = ?", (target_date,))
    strike_rows = c.fetchall()
    conn.close()

    if not snapshots:
        return {"error": f"No snapshot records found for date {target_date}"}

    strike_map = {}
    for sr in strike_rows:
        key = (sr["symbol"], sr["time_str"], float(sr["strike"]), sr["option_type"])
        strike_map[key] = dict(sr)

    candle_dict = build_minute_candles(snapshots)
    indicators = {}
    for sym in candle_dict:
        indicators[sym] = compute_symbol_indicators(candle_dict[sym], ott_percent=0.30, adx_len=9)

    active_positions: Dict[str, SimTrade] = {}
    closed_trades: List[SimTrade] = []
    signal_ticks: Dict[str, Dict[str, Any]] = {}
    daily_realized_loss = 0.0
    symbol_cooldowns: Dict[str, str] = {}
    consecutive_losses: Dict[str, int] = {s: 0 for s in LOT_SIZES}

    def add_minutes(t_s: str, mins: int) -> str:
        h, m = map(int, t_s.split(":"))
        total = h * 60 + m + mins
        return f"{total // 60:02d}:{total % 60:02d}"

    is_expiry_day = (target_date == "2026-09-24")

    for snap in snapshots:
        sym = snap["symbol"]
        t_str = snap["time_str"]
        spot = snap["spot"]
        pcr = snap["pcr"]
        confluence = snap["confluence"] or 50.0
        step = STRIKE_STEPS.get(sym, 50)
        lot = LOT_SIZES.get(sym, 75)
        atm = round(spot / step) * step

        if sym in active_positions:
            tr = active_positions[sym]
            s_key = (sym, t_str, tr.strike, tr.otype)
            curr_row = strike_map.get(s_key)
            if curr_row:
                ltp = curr_row["ltp"]
                tr.update_mtm(ltp)

                if tr.role == "BUYER":
                    if ltp >= tr.target_p:
                        tr.close(ltp, t_str, "TARGET_HIT (+50% Momentum)")
                        daily_realized_loss += tr.net_pnl
                        consecutive_losses[sym] = 0
                        symbol_cooldowns[sym] = add_minutes(t_str, 5)
                        closed_trades.append(tr)
                        del active_positions[sym]
                        continue
                    elif ltp <= tr.trailing_sl:
                        reason = "TRAILING_SL_HIT" if tr.trailing_sl > tr.sl_p else "STOP_LOSS_HIT"
                        tr.close(ltp, t_str, reason)
                        daily_realized_loss += tr.net_pnl
                        if tr.net_pnl < 0:
                            consecutive_losses[sym] += 1
                            cd = 45 if consecutive_losses[sym] >= 2 else 20
                            symbol_cooldowns[sym] = add_minutes(t_str, cd)
                        else:
                            consecutive_losses[sym] = 0
                            symbol_cooldowns[sym] = add_minutes(t_str, 5)
                        closed_trades.append(tr)
                        del active_positions[sym]
                        continue
                else:  # SELLER
                    if ltp <= tr.target_p:
                        tr.close(ltp, t_str, "TARGET_HIT (Decay Captured)")
                        daily_realized_loss += tr.net_pnl
                        consecutive_losses[sym] = 0
                        symbol_cooldowns[sym] = add_minutes(t_str, 5)
                        closed_trades.append(tr)
                        del active_positions[sym]
                        continue
                    elif ltp >= tr.trailing_sl:
                        reason = "TRAILING_SL_HIT" if tr.trailing_sl < tr.sl_p else "STOP_LOSS_HIT"
                        tr.close(ltp, t_str, reason)
                        daily_realized_loss += tr.net_pnl
                        if tr.net_pnl < 0:
                            consecutive_losses[sym] += 1
                            cd = 45 if consecutive_losses[sym] >= 2 else 20
                            symbol_cooldowns[sym] = add_minutes(t_str, cd)
                        else:
                            consecutive_losses[sym] = 0
                            symbol_cooldowns[sym] = add_minutes(t_str, 5)
                        closed_trades.append(tr)
                        del active_positions[sym]
                        continue

            if t_str >= "15:35":
                exit_price = curr_row["ltp"] if curr_row else tr.curr_p
                tr.close(exit_price, t_str, "EOD_SQUAREOFF (15:35 Safety)")
                daily_realized_loss += tr.net_pnl
                closed_trades.append(tr)
                del active_positions[sym]
                continue

            continue  # Concurrency lock

        if daily_realized_loss <= -3500.0:
            continue

        if sym in symbol_cooldowns:
            if t_str < symbol_cooldowns[sym]:
                continue
            else:
                del symbol_cooldowns[sym]

        if t_str < "09:30" or t_str > "15:25":
            continue

        ind = indicators.get(sym, {}).get(t_str, {})
        adx = ind.get("adx", 0.0)
        ott_state = ind.get("ott_state", "NEUTRAL")

        is_bullish = confluence >= 68.0 or pcr >= 1.20
        is_bearish = confluence <= 32.0 or pcr <= 0.80

        if 0.94 <= pcr <= 1.06 and 48.0 <= confluence <= 52.0:
            continue

        role = "BUYER" if (is_bullish or is_bearish) else "SELLER"

        if is_expiry_day and role == "SELLER":
            continue

        dir_sig = "BULL" if is_bullish else ("BEAR" if is_bearish else "NEUTRAL")
        prev = signal_ticks.get(sym, {})
        if prev.get("dir") != dir_sig:
            signal_ticks[sym] = {"dir": dir_sig, "count": 1}
            continue
        else:
            prev["count"] += 1
            if prev["count"] < 2:
                continue

        if role == "BUYER":
            otype = "CE" if is_bullish else "PE"

            # PineScript Filters:
            if otype == "CE" and ott_state != "BULLISH":
                continue
            if otype == "PE" and ott_state != "BEARISH":
                continue
            if adx < 18.0:
                continue

            target_strike = (atm - step) if (is_expiry_day and t_str >= "12:30" and otype == "CE") else (
                (atm + step) if (is_expiry_day and t_str >= "12:30" and otype == "PE") else atm
            )

            s_key = (sym, t_str, float(target_strike), otype)
            contract = strike_map.get(s_key)
            if not contract:
                continue

            ltp = contract["ltp"]
            if ltp <= 0 or ltp < MIN_PREMIUMS.get(sym, 35.0):
                continue

            p1 = 25.0 if abs(confluence - 50) >= 20 else 15.0
            p2 = 20.0 if target_strike == atm else 17.0
            oi = contract["oi"] or 0
            vol = contract["volume"] or 0
            p3 = 18.0 if oi > 50000 and vol > 20000 else 10.0
            p4 = 18.0 if (otype == "CE" and spot > atm) or (otype == "PE" and spot < atm) else 10.0
            p5 = 14.0
            tqs = round(p1 + p2 + p3 + p4 + p5, 1)

            min_tqs = 74.0 if ("11:30" <= t_str <= "13:30") else 70.0
            if tqs < min_tqs:
                continue

            target_p = round(ltp * 1.50, 2)
            sl_p = round(ltp * 0.70, 2)

            tr = SimTrade(
                tid=f"PINE_{sym}_{t_str.replace(':', '')}",
                sym=sym, role="BUYER", strat="MOMENTUM_BUY", strike=target_strike,
                otype=otype, entry_t=t_str, entry_p=ltp, target_p=target_p, sl_p=sl_p,
                lot=lot, tqs=tqs
            )
            active_positions[sym] = tr

        else:
            otype = "PE" if confluence >= 50 else "CE"
            sell_strike = (atm - step) if otype == "PE" else (atm + step)

            s_key = (sym, t_str, float(sell_strike), otype)
            contract = strike_map.get(s_key)
            if not contract:
                continue

            credit = contract["ltp"]
            if credit < 8.0:
                continue

            target_p = round(credit * 0.30, 2)
            sl_p = round(credit * 1.80, 2)

            tr = SimTrade(
                tid=f"PINE_{sym}_{t_str.replace(':', '')}",
                sym=sym, role="SELLER", strat="CREDIT_SPREAD", strike=sell_strike,
                otype=otype, entry_t=t_str, entry_p=credit, target_p=target_p, sl_p=sl_p,
                lot=lot, tqs=68.0
            )
            active_positions[sym] = tr

    for sym, tr in list(active_positions.items()):
        tr.close(tr.curr_p, "15:35", "EOD_SQUAREOFF")
        closed_trades.append(tr)

    tot = len(closed_trades)
    wins = [t for t in closed_trades if t.net_pnl > 0]
    win_rate = round(len(wins) / tot * 100.0, 1) if tot > 0 else 0.0
    gross_pnl = round(sum(t.gross_pnl for t in closed_trades), 2)
    brokerage = round(sum(t.brokerage for t in closed_trades), 2)
    net_pnl = round(sum(t.net_pnl for t in closed_trades), 2)

    buyers = [t for t in closed_trades if t.role == "BUYER"]
    sellers = [t for t in closed_trades if t.role == "SELLER"]
    b_net = round(sum(t.net_pnl for t in buyers), 2)
    s_net = round(sum(t.net_pnl for t in sellers), 2)

    return {
        "date": target_date,
        "total_trades": tot,
        "win_rate_pct": win_rate,
        "gross_pnl_inr": gross_pnl,
        "brokerage_inr": brokerage,
        "net_pnl_inr": net_pnl,
        "buyer_trades": len(buyers),
        "buyer_wins": len([t for t in buyers if t.net_pnl > 0]),
        "buyer_net_pnl": b_net,
        "seller_trades": len(sellers),
        "seller_wins": len([t for t in sellers if t.net_pnl > 0]),
        "seller_net_pnl": s_net,
        "trades": [
            {
                "sym": t.sym, "role": t.role, "strike": t.strike, "otype": t.otype,
                "in": t.entry_t, "out": t.exit_t, "entry": t.entry_p, "exit": t.exit_p,
                "net": t.net_pnl, "mfe": t.mfe_inr, "mae": t.mae_inr, "reason": t.exit_reason
            }
            for t in closed_trades
        ]
    }


def main():
    dates = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"]
    print("=" * 105)
    print("RUNNING MULTI-DAY EMPIRICAL BOT BACKTEST SIMULATION")
    print(f"Database Path: {DB_PATH}")
    print("=" * 105)

    tot_net = 0.0
    tot_trades = 0
    tot_b_net = 0.0
    tot_s_net = 0.0

    for d in dates:
        res = run_simulation(d)
        if "error" in res:
            print(f"Date {d}: {res['error']}")
            continue

        tot_net += res["net_pnl_inr"]
        tot_trades += res["total_trades"]
        tot_b_net += res["buyer_net_pnl"]
        tot_s_net += res["seller_net_pnl"]

        print(f"\nDATE: {d} | Trades: {res['total_trades']} | Win Rate: {res['win_rate_pct']}% | Net: Rs. {res['net_pnl_inr']:>9,.2f} | Buyer: Rs. {res['buyer_net_pnl']:>9,.2f} | Seller: Rs. {res['seller_net_pnl']:>9,.2f}")
        for t in res["trades"]:
            print(f"   [{t['role']:6s}] {t['sym']:10s} {t['strike']} {t['otype']:2s} | In: {t['in']} -> Out: {t['out']} | Net: Rs. {t['net']:>8.2f} | MFE: Rs. {t['mfe']:>7.1f} | {t['reason']}")

    print("\n" + "=" * 105)
    print(f"CUMULATIVE PERFORMANCE: {tot_trades} Trades | Net Realized P&L: Rs. {tot_net:>10,.2f}")
    print(f"Buyer Net: Rs. {tot_b_net:>10,.2f} | Seller Net: Rs. {tot_s_net:>10,.2f}")
    print("=" * 105)


if __name__ == "__main__":
    main()
