"""
Comprehensive Multi-Day Simulation & Comparison Report Generator
Runs across 4 Full Recorded Live Days:
- 2026-09-21 (Monday)
- 2026-09-22 (Tuesday)
- 2026-09-23 (Wednesday)
- 2026-09-24 (Thursday - Expiry Day)

Generates full comparison between:
1. Baseline Bot (Naive, unfiltered, far OTM trades)
2. Smart Quality Bot V1 (TQS >= 70, ATM/1-ITM, 09:16 open)
3. Improved Bot V2 (09:30 Opening Settlement Filter, Fast +20% Breakeven Ladder, +35% Profit Lock, Gamma Safety)
"""
import os
import json
import sqlite3
from typing import Dict, Any, List

DB_PATH = "/home/ubuntu/nse-dashboard/backend/app/db/terminal_snapshots.db"
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "terminal_snapshots.db")

LOT_SIZES = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120}
STRIKE_STEPS = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25}
MIN_PREMIUMS = {"NIFTY": 45.0, "BANKNIFTY": 75.0, "FINNIFTY": 40.0, "MIDCPNIFTY": 25.0}


class BacktestTrade:
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
        self.mfe_pts = 0.0
        self.mfe_inr = 0.0
        self.mae_pts = 0.0
        self.mae_inr = 0.0

    def update_mtm(self, ltp, mode="IMPROVED_V2"):
        if self.status != "OPEN":
            return
        self.curr_p = ltp
        pts = (ltp - self.entry_p) if self.role == "BUYER" else (self.entry_p - ltp)
        gross = pts * self.lot
        self.mfe_pts = max(self.mfe_pts, pts)
        self.mfe_inr = max(self.mfe_inr, gross)
        self.mae_pts = min(self.mae_pts, pts)
        self.mae_inr = min(self.mae_inr, gross)

        if self.role == "BUYER":
            gain_pct = (ltp - self.entry_p) / self.entry_p if self.entry_p > 0 else 0
            if mode == "IMPROVED_V2":
                # Upgraded 3-stage dynamic trailing ladder
                if gain_pct >= 0.60:
                    self.trailing_sl = max(self.trailing_sl, round(self.entry_p * 1.35, 2))
                elif gain_pct >= 0.35:
                    self.trailing_sl = max(self.trailing_sl, round(self.entry_p * 1.15, 2))
                elif gain_pct >= 0.20:
                    self.trailing_sl = max(self.trailing_sl, self.entry_p)  # Fast Breakeven Lock!
            elif mode == "SMART_V1":
                if gain_pct >= 0.70:
                    self.trailing_sl = max(self.trailing_sl, round(self.entry_p * 1.45, 2))
                elif gain_pct >= 0.45:
                    self.trailing_sl = max(self.trailing_sl, round(self.entry_p * 1.22, 2))
                elif gain_pct >= 0.25:
                    self.trailing_sl = max(self.trailing_sl, self.entry_p)
        else:
            decay_pct = (self.entry_p - ltp) / self.entry_p if self.entry_p > 0 else 0
            if mode == "IMPROVED_V2":
                if decay_pct >= 0.60:
                    self.trailing_sl = min(self.trailing_sl, round(self.entry_p * 0.40, 2))
                elif decay_pct >= 0.35:
                    self.trailing_sl = min(self.trailing_sl, self.entry_p)
            elif mode == "SMART_V1":
                if decay_pct >= 0.65:
                    self.trailing_sl = min(self.trailing_sl, round(self.entry_p * 0.45, 2))
                elif decay_pct >= 0.40:
                    self.trailing_sl = min(self.trailing_sl, self.entry_p)

    def close(self, exit_p, exit_t, reason):
        self.status = "CLOSED"
        self.exit_p = exit_p
        self.exit_t = exit_t
        self.exit_reason = reason
        pts = (exit_p - self.entry_p) if self.role == "BUYER" else (self.entry_p - exit_p)
        self.gross_pnl = round(pts * self.lot, 2)
        self.net_pnl = round(self.gross_pnl - self.brokerage, 2)


def run_bot_sim(target_date: str, mode: str) -> Dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("SELECT * FROM intraday_snapshots WHERE trade_date = ? ORDER BY timestamp ASC, id ASC", (target_date,))
    snapshots = c.fetchall()

    c.execute("SELECT * FROM intraday_strike_snapshots WHERE trade_date = ?", (target_date,))
    strike_rows = c.fetchall()
    conn.close()

    strike_map = {}
    for sr in strike_rows:
        key = (sr["symbol"], sr["time_str"], float(sr["strike"]), sr["option_type"])
        strike_map[key] = dict(sr)

    active_positions: Dict[str, BacktestTrade] = {}
    closed_trades: List[BacktestTrade] = []
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

        # Check exits for open position
        if sym in active_positions:
            tr = active_positions[sym]
            s_key = (sym, t_str, tr.strike, tr.otype)
            curr_row = strike_map.get(s_key)
            if curr_row:
                ltp = curr_row["ltp"]
                tr.update_mtm(ltp, mode=mode)

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
                            cd = 45 if consecutive_losses[sym] >= 2 else (20 if mode == "IMPROVED_V2" else 0)
                            if cd > 0:
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
                        reason = "GAMMA_SAFETY_EXIT" if (is_expiry_day and mode == "IMPROVED_V2") else ("TRAILING_SL_HIT" if tr.trailing_sl < tr.sl_p else "STOP_LOSS_HIT")
                        tr.close(ltp, t_str, reason)
                        daily_realized_loss += tr.net_pnl
                        if tr.net_pnl < 0:
                            consecutive_losses[sym] += 1
                            cd = 45 if consecutive_losses[sym] >= 2 else (20 if mode == "IMPROVED_V2" else 0)
                            if cd > 0:
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

        # Risk Control: Daily circuit breaker
        if mode in ["SMART_V1", "IMPROVED_V2"] and daily_realized_loss <= -3500.0:
            continue

        # Cooldown check
        if sym in symbol_cooldowns:
            if t_str < symbol_cooldowns[sym]:
                continue
            else:
                del symbol_cooldowns[sym]

        # Entry Window:
        # Improved V2 waits for 09:30 opening settlement!
        start_t = "09:30" if mode == "IMPROVED_V2" else "09:16"
        if t_str < start_t or t_str > "15:25":
            continue

        # Directional Signals
        is_bullish = confluence >= 68.0 or pcr >= 1.20
        is_bearish = confluence <= 32.0 or pcr <= 0.80

        # Choppy market filter
        if mode in ["SMART_V1", "IMPROVED_V2"]:
            if 0.94 <= pcr <= 1.06 and 48.0 <= confluence <= 52.0:
                continue

        role = "BUYER" if (is_bullish or is_bearish) else "SELLER"

        # User Constraint: Omit 1-lot option selling on Expiry Day (unfavorable risk-reward & high gamma)
        if mode == "IMPROVED_V2" and is_expiry_day and role == "SELLER":
            continue

        # Signal Persistence
        if mode in ["SMART_V1", "IMPROVED_V2"]:
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

            if mode == "IMPROVED_V2":
                # Strike selection: ATM, or 1-ITM on expiry day afternoon
                target_strike = (atm - step) if (is_expiry_day and t_str >= "12:30" and otype == "CE") else (
                    (atm + step) if (is_expiry_day and t_str >= "12:30" and otype == "PE") else atm
                )
            elif mode == "SMART_V1":
                target_strike = atm
            else:
                # Baseline takes OTM strikes (+1 OTM)
                target_strike = (atm + step) if otype == "CE" else (atm - step)

            s_key = (sym, t_str, float(target_strike), otype)
            contract = strike_map.get(s_key)
            if not contract:
                continue

            ltp = contract["ltp"]
            if ltp <= 0:
                continue

            # Minimum premium filter
            min_prem = MIN_PREMIUMS.get(sym, 35.0)
            if mode in ["SMART_V1", "IMPROVED_V2"] and ltp < min_prem:
                continue

            # TQS Gate
            if mode in ["SMART_V1", "IMPROVED_V2"]:
                p1 = 25.0 if abs(confluence - 50) >= 20 else 15.0
                p2 = 20.0 if target_strike == atm else 17.0
                oi = contract["oi"] or 0
                vol = contract["volume"] or 0
                p3 = 18.0 if oi > 50000 and vol > 20000 else 10.0
                p4 = 18.0 if (otype == "CE" and spot > atm) or (otype == "PE" and spot < atm) else 10.0
                p5 = 14.0
                tqs = round(p1 + p2 + p3 + p4 + p5, 1)

                min_tqs = 74.0 if (mode == "IMPROVED_V2" and "11:30" <= t_str <= "13:30") else 70.0
                if tqs < min_tqs:
                    continue
            else:
                tqs = 50.0

            target_p = round(ltp * 1.50, 2)
            sl_p = round(ltp * 0.70, 2)

            tr = BacktestTrade(
                tid=f"{mode}_{sym}_{t_str.replace(':', '')}",
                sym=sym, role="BUYER", strat="MOMENTUM_BUY", strike=target_strike,
                otype=otype, entry_t=t_str, entry_p=ltp, target_p=target_p, sl_p=sl_p,
                lot=lot, tqs=tqs
            )
            active_positions[sym] = tr

        else:
            # SELLER
            otype = "PE" if confluence >= 50 else "CE"
            sell_strike = (atm - step) if otype == "PE" else (atm + step)

            s_key = (sym, t_str, float(sell_strike), otype)
            contract = strike_map.get(s_key)
            if not contract:
                continue

            credit = contract["ltp"]
            if credit < 8.0:
                continue

            tqs = 68.0 if mode in ["SMART_V1", "IMPROVED_V2"] else 50.0
            target_p = round(credit * 0.30, 2)
            sl_p = round(credit * 1.80, 2)

            tr = BacktestTrade(
                tid=f"{mode}_{sym}_{t_str.replace(':', '')}",
                sym=sym, role="SELLER", strat="CREDIT_SPREAD", strike=sell_strike,
                otype=otype, entry_t=t_str, entry_p=credit, target_p=target_p, sl_p=sl_p,
                lot=lot, tqs=tqs
            )
            active_positions[sym] = tr

    # Squareoff remaining
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
    b_wins = len([t for t in buyers if t.net_pnl > 0])
    s_wins = len([t for t in sellers if t.net_pnl > 0])

    return {
        "date": target_date,
        "mode": mode,
        "total_trades": tot,
        "win_rate_pct": win_rate,
        "gross_pnl_inr": gross_pnl,
        "brokerage_inr": brokerage,
        "net_pnl_inr": net_pnl,
        "buyer_trades": len(buyers),
        "buyer_wins": b_wins,
        "buyer_net_pnl": b_net,
        "seller_trades": len(sellers),
        "seller_wins": s_wins,
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
    comparison = {}

    for d in dates:
        comparison[d] = {
            "baseline": run_bot_sim(d, "BASELINE"),
            "smart_v1": run_bot_sim(d, "SMART_V1"),
            "improved_v2": run_bot_sim(d, "IMPROVED_V2")
        }

    # Summary
    print("\n" + "=" * 105)
    print("MULTI-DAY PERFORMANCE BENCHMARK (4 DAYS: SEP 21 - SEP 24)")
    print("=" * 105)
    print(f"{'Date':12s} | {'Bot Version':20s} | {'Trades':6s} | {'Win %':6s} | {'Gross P&L':12s} | {'Brok (Rs)':10s} | {'Net P&L':12s} | {'Buyer Net':11s} | {'Seller Net':11s}")
    print("-" * 105)

    for d in dates:
        for m, label in [("baseline", "Baseline Naive"), ("smart_v1", "Smart Quality V1"), ("improved_v2", "Improved Bot V2")]:
            res = comparison[d][m]
            print(f"{d:12s} | {label:20s} | {res['total_trades']:6d} | {res['win_rate_pct']:5.1f}% | Rs.{res['gross_pnl_inr']:>9,.2f} | Rs.{res['brokerage_inr']:>8,.2f} | Rs.{res['net_pnl_inr']:>9,.2f} | Rs.{res['buyer_net_pnl']:>8,.2f} | Rs.{res['seller_net_pnl']:>8,.2f}")
        print("-" * 105)

    print("\n" + "=" * 105)
    print("CUMULATIVE 4-DAY TOTALS")
    print("=" * 105)
    for m, label in [("baseline", "Baseline Naive Bot"), ("smart_v1", "Smart Quality Bot V1"), ("improved_v2", "Improved Bot V2 (09:30 + Fast BE)")]:
        tot_t = sum(comparison[d][m]["total_trades"] for d in dates)
        tot_w = sum(comparison[d][m]["buyer_wins"] + comparison[d][m]["seller_wins"] for d in dates)
        tot_g = sum(comparison[d][m]["gross_pnl_inr"] for d in dates)
        tot_b = sum(comparison[d][m]["brokerage_inr"] for d in dates)
        tot_n = sum(comparison[d][m]["net_pnl_inr"] for d in dates)
        tot_buyer_n = sum(comparison[d][m]["buyer_net_pnl"] for d in dates)
        tot_seller_n = sum(comparison[d][m]["seller_net_pnl"] for d in dates)
        wr = round(tot_w / tot_t * 100, 1) if tot_t > 0 else 0.0

        print(f"\n>>> {label} <<<")
        print(f"  Total Trades:     {tot_t} trades (Win Rate: {wr}%)")
        print(f"  Gross Realized:   Rs. {tot_g:>12,.2f}")
        print(f"  Brokerage Paid:   Rs. -{tot_b:>11,.2f}  (Flat Rs. 100/lot: Rs. 50 Buy + Rs. 50 Sell)")
        print(f"  NET REALIZED P&L: Rs. {tot_n:>12,.2f}")
        print(f"    - Buyer Net:    Rs. {tot_buyer_n:>12,.2f}")
        print(f"    - Seller Net:   Rs. {tot_seller_n:>12,.2f}")

    # Output JSON file
    out_path = "/home/ubuntu/nse-dashboard/backend/app/db/full_multiday_benchmark.json"
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(comparison, f, indent=2)
        print(f"\nAudit saved to {out_path}")
    except Exception as e:
        print("Save error:", e)


if __name__ == "__main__":
    main()
