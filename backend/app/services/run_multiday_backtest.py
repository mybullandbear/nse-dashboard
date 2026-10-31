"""
Multi-Day Backtest & Improvement Laboratory for Smart Options Trading Bot
Runs across ALL available trading days on the database:
- 2026-09-21 (Monday)
- 2026-09-22 (Tuesday)
- 2026-09-23 (Wednesday)
- 2026-09-24 (Thursday - Expiry Day)
Benchmarks:
1. Baseline Naive Bot (unfiltered, poor OTMs, single conviction threshold)
2. Smart Quality Bot (TQS >= 70, ATM/1-ITM, persistence, MFE/MAE trailing, Rs 100 brokerage)
3. Advanced Institutional Bot (Adds Expiry Day Gamma boost, Volatility ATR Scaling, Midday Chop Filter)
"""
import os
import sys
import json
import sqlite3
from typing import Dict, Any, List
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = "/home/ubuntu/nse-dashboard/backend/app/db/terminal_snapshots.db"
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "terminal_snapshots.db")

LOT_SIZES = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120}
STRIKE_STEPS = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25}
MIN_PREMIUMS = {"NIFTY": 45.0, "BANKNIFTY": 75.0, "FINNIFTY": 40.0, "MIDCPNIFTY": 25.0}


class SimTrade:
    def __init__(self, tid, sym, role, strat, strike, otype, entry_t, entry_p, target_p, sl_p, lot, tqs=0.0, date="", session="MORNING"):
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
        self.date = date
        self.session = session
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

    def update_mtm(self, ltp, is_advanced=False):
        if self.status != "OPEN":
            return
        self.curr_p = ltp
        pts = (ltp - self.entry_p) if self.role == "BUYER" else (self.entry_p - ltp)
        gross = pts * self.lot
        self.mfe_pts = max(self.mfe_pts, pts)
        self.mfe_inr = max(self.mfe_inr, gross)
        self.mae_pts = min(self.mae_pts, pts)
        self.mae_inr = min(self.mae_inr, gross)

        # Dynamic Trailing Stop Loss
        if self.role == "BUYER":
            gain_pct = (ltp - self.entry_p) / self.entry_p if self.entry_p > 0 else 0
            if is_advanced:
                # Advanced tight profit locking
                if gain_pct >= 0.60:
                    self.trailing_sl = max(self.trailing_sl, round(self.entry_p * 1.35, 2))
                elif gain_pct >= 0.35:
                    self.trailing_sl = max(self.trailing_sl, round(self.entry_p * 1.15, 2))
                elif gain_pct >= 0.20:
                    self.trailing_sl = max(self.trailing_sl, self.entry_p)
            else:
                if gain_pct >= 0.70:
                    self.trailing_sl = max(self.trailing_sl, round(self.entry_p * 1.45, 2))
                elif gain_pct >= 0.45:
                    self.trailing_sl = max(self.trailing_sl, round(self.entry_p * 1.22, 2))
                elif gain_pct >= 0.25:
                    self.trailing_sl = max(self.trailing_sl, self.entry_p)
        else:
            decay_pct = (self.entry_p - ltp) / self.entry_p if self.entry_p > 0 else 0
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


def run_day_backtest(target_date: str, mode: str = "SMART_QUALITY") -> Dict[str, Any]:
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

    active_positions: Dict[str, SimTrade] = {}
    closed_trades: List[SimTrade] = []
    signal_ticks: Dict[str, Dict[str, Any]] = {}
    daily_realized_loss = 0.0

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

        # Session bucket
        if t_str < "11:30":
            sess = "MORNING"
        elif t_str < "13:30":
            sess = "MIDDAY"
        else:
            sess = "AFTERNOON"

        # Check exit for active position
        if sym in active_positions:
            tr = active_positions[sym]
            s_key = (sym, t_str, tr.strike, tr.otype)
            curr_row = strike_map.get(s_key)
            if curr_row:
                ltp = curr_row["ltp"]
                tr.update_mtm(ltp, is_advanced=(mode == "ADVANCED_V2"))

                if tr.role == "BUYER":
                    if ltp >= tr.target_p:
                        tr.close(ltp, t_str, "TARGET_HIT (+50% Momentum)")
                        daily_realized_loss += tr.net_pnl
                        closed_trades.append(tr)
                        del active_positions[sym]
                        continue
                    elif ltp <= tr.trailing_sl:
                        reason = "TRAILING_SL_HIT" if tr.trailing_sl > tr.sl_p else "STOP_LOSS_HIT"
                        tr.close(ltp, t_str, reason)
                        daily_realized_loss += tr.net_pnl
                        closed_trades.append(tr)
                        del active_positions[sym]
                        continue
                else:  # SELLER
                    if ltp <= tr.target_p:
                        tr.close(ltp, t_str, "TARGET_HIT (Decay Captured)")
                        daily_realized_loss += tr.net_pnl
                        closed_trades.append(tr)
                        del active_positions[sym]
                        continue
                    elif ltp >= tr.trailing_sl:
                        reason = "TRAILING_SL_HIT" if tr.trailing_sl < tr.sl_p else "STOP_LOSS_HIT"
                        tr.close(ltp, t_str, reason)
                        daily_realized_loss += tr.net_pnl
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

        # If no active trade, evaluate entry
        if t_str < "09:16" or t_str > "15:25":
            continue

        # Daily loss circuit breaker
        if mode in ["SMART_QUALITY", "ADVANCED_V2"] and daily_realized_loss <= -3500.0:
            continue

        # Advanced V2: Filter out Midday entries unless TQS is ultra-high
        if mode == "ADVANCED_V2" and sess == "MIDDAY":
            # Midday entries only allowed if extreme conviction
            if not (confluence >= 78.0 or confluence <= 22.0):
                continue

        # Bias determination
        is_bullish = confluence >= 68.0 or pcr >= 1.20
        is_bearish = confluence <= 32.0 or pcr <= 0.80

        # Choppy market filter
        if mode in ["SMART_QUALITY", "ADVANCED_V2"]:
            if 0.94 <= pcr <= 1.06 and 48.0 <= confluence <= 52.0:
                continue

        role = "BUYER" if (is_bullish or is_bearish) else "SELLER"

        # Signal Persistence Filter
        if mode in ["SMART_QUALITY", "ADVANCED_V2"]:
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

            # Strike selection:
            if mode == "ADVANCED_V2":
                # In Advanced mode, on Expiry day afternoon prefer 1-ITM for higher Delta (0.58) to defeat rapid Theta decay!
                if is_expiry_day and t_str >= "12:30":
                    target_strike = (atm - step) if otype == "CE" else (atm + step)
                else:
                    target_strike = atm
            elif mode == "SMART_QUALITY":
                target_strike = atm
            else:
                target_strike = (atm + step) if otype == "CE" else (atm - step)  # Baseline takes OTM

            s_key = (sym, t_str, float(target_strike), otype)
            contract = strike_map.get(s_key)
            if not contract:
                continue

            ltp = contract["ltp"]
            if ltp <= 0:
                continue

            min_prem = MIN_PREMIUMS.get(sym, 35.0)
            if mode in ["SMART_QUALITY", "ADVANCED_V2"] and ltp < min_prem:
                continue

            # TQS Gate
            if mode in ["SMART_QUALITY", "ADVANCED_V2"]:
                p1 = 25.0 if abs(confluence - 50) >= 20 else 15.0
                p2 = 20.0 if target_strike == atm else 17.0
                oi = contract["oi"] or 0
                vol = contract["volume"] or 0
                p3 = 18.0 if oi > 50000 and vol > 20000 else 10.0
                p4 = 18.0 if (otype == "CE" and spot > atm) or (otype == "PE" and spot < atm) else 10.0
                p5 = 14.0
                tqs = round(p1 + p2 + p3 + p4 + p5, 1)

                min_tqs = 74.0 if (mode == "ADVANCED_V2" and sess == "MIDDAY") else 70.0
                if tqs < min_tqs:
                    continue
            else:
                tqs = 50.0

            target_p = round(ltp * 1.50, 2)
            sl_p = round(ltp * 0.70, 2)

            tr = SimTrade(
                tid=f"{mode}_{sym}_{t_str.replace(':', '')}",
                sym=sym, role="BUYER", strat="MOMENTUM_BUY", strike=target_strike,
                otype=otype, entry_t=t_str, entry_p=ltp, target_p=target_p, sl_p=sl_p,
                lot=lot, tqs=tqs, date=target_date, session=sess
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

            if mode in ["SMART_QUALITY", "ADVANCED_V2"]:
                tqs = 68.0
            else:
                tqs = 50.0

            # On Expiry day, sellers take 80% decay target
            decay_target_pct = 0.20 if is_expiry_day else 0.30
            target_p = round(credit * decay_target_pct, 2)
            sl_p = round(credit * 1.80, 2)

            tr = SimTrade(
                tid=f"{mode}_{sym}_{t_str.replace(':', '')}",
                sym=sym, role="SELLER", strat="CREDIT_SPREAD", strike=sell_strike,
                otype=otype, entry_t=t_str, entry_p=credit, target_p=target_p, sl_p=sl_p,
                lot=lot, tqs=tqs, date=target_date, session=sess
            )
            active_positions[sym] = tr

    # Close remaining open
    for sym, tr in list(active_positions.items()):
        tr.close(tr.curr_p, "15:35", "EOD_SQUAREOFF")
        closed_trades.append(tr)

    tot = len(closed_trades)
    wins = [t for t in closed_trades if t.net_pnl > 0]
    losses = [t for t in closed_trades if t.net_pnl <= 0]
    win_rate = round(len(wins) / tot * 100.0, 1) if tot > 0 else 0.0
    gross_pnl = round(sum(t.gross_pnl for t in closed_trades), 2)
    brokerage = round(sum(t.brokerage for t in closed_trades), 2)
    net_pnl = round(sum(t.net_pnl for t in closed_trades), 2)

    gp = sum(t.gross_pnl for t in wins)
    gl = abs(sum(t.gross_pnl for t in losses))
    pf = round(gp / gl, 2) if gl > 0 else (round(gp, 2) if gp > 0 else 1.0)

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
        "profit_factor": pf,
        "buyer_trades": len(buyers),
        "buyer_wins": b_wins,
        "buyer_net_pnl": b_net,
        "seller_trades": len(sellers),
        "seller_wins": s_wins,
        "seller_net_pnl": s_net,
        "trades": [
            {
                "id": t.tid, "sym": t.sym, "role": t.role, "strike": t.strike, "otype": t.otype,
                "in": t.entry_t, "out": t.exit_t, "entry": t.entry_p, "exit": t.exit_p,
                "net": t.net_pnl, "mfe": t.mfe_inr, "mae": t.mae_inr, "reason": t.exit_reason
            }
            for t in closed_trades
        ]
    }


def main():
    dates = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"]
    print("=" * 95)
    print("MULTI-DAY BENCHMARK ACROSS 4 LIVE SESSIONS (2026-09-21 TO 2026-09-24)")
    print("=" * 95)

    all_results = {}

    for d in dates:
        print(f"\n>>> PROCESSING DATE: {d} <<<")
        b_res = run_day_backtest(d, mode="BASELINE")
        s_res = run_day_backtest(d, mode="SMART_QUALITY")
        a_res = run_day_backtest(d, mode="ADVANCED_V2")

        print(f"  [BASELINE]   Trades: {b_res['total_trades']:2d} | Win: {b_res['win_rate_pct']:4.1f}% | Net P&L: Rs. {b_res['net_pnl_inr']:>10,.2f} | Buyer: Rs. {b_res['buyer_net_pnl']:>9,.2f} | Seller: Rs. {b_res['seller_net_pnl']:>8,.2f}")
        print(f"  [SMART_V1]   Trades: {s_res['total_trades']:2d} | Win: {s_res['win_rate_pct']:4.1f}% | Net P&L: Rs. {s_res['net_pnl_inr']:>10,.2f} | Buyer: Rs. {s_res['buyer_net_pnl']:>9,.2f} | Seller: Rs. {s_res['seller_net_pnl']:>8,.2f}")
        print(f"  [ADVANCED_V2]Trades: {a_res['total_trades']:2d} | Win: {a_res['win_rate_pct']:4.1f}% | Net P&L: Rs. {a_res['net_pnl_inr']:>10,.2f} | Buyer: Rs. {a_res['buyer_net_pnl']:>9,.2f} | Seller: Rs. {a_res['seller_net_pnl']:>8,.2f}")

        all_results[d] = {"baseline": b_res, "smart_v1": s_res, "advanced_v2": a_res}

    # Aggregate Multi-Day Totals
    print("\n" + "=" * 95)
    print("CUMULATIVE 4-DAY PERFORMANCE AUDIT (SEPTEMBER 21 - SEPTEMBER 24)")
    print("=" * 95)

    for m, label in [("baseline", "BASELINE BOT"), ("smart_v1", "SMART QUALITY BOT V1"), ("advanced_v2", "ADVANCED INSTITUTIONAL BOT V2")]:
        tot_trades = sum(all_results[d][m]["total_trades"] for d in dates)
        tot_wins = sum(int(round(all_results[d][m]["total_trades"] * all_results[d][m]["win_rate_pct"] / 100)) for d in dates)
        tot_net = sum(all_results[d][m]["net_pnl_inr"] for d in dates)
        tot_gross = sum(all_results[d][m]["gross_pnl_inr"] for d in dates)
        tot_brok = sum(all_results[d][m]["brokerage_inr"] for d in dates)
        tot_buyer_net = sum(all_results[d][m]["buyer_net_pnl"] for d in dates)
        tot_seller_net = sum(all_results[d][m]["seller_net_pnl"] for d in dates)
        win_rate = round(tot_wins / tot_trades * 100, 1) if tot_trades > 0 else 0.0

        print(f"\n{label}:")
        print(f"  Total Trades Taken: {tot_trades} | Cumulative Win Rate: {win_rate}%")
        print(f"  Gross P&L:         Rs. {tot_gross:>11,.2f}")
        print(f"  Total Brokerage:   Rs. -{tot_brok:>10,.2f}  (Flat Rs. 100/lot)")
        print(f"  NET CUMULATIVE P&L: Rs. {tot_net:>11,.2f}")
        print(f"  --> Buyer Net P&L:  Rs. {tot_buyer_net:>11,.2f}")
        print(f"  --> Seller Net P&L: Rs. {tot_seller_net:>11,.2f}")

    # Save to JSON
    out_file = "/home/ubuntu/nse-dashboard/backend/app/db/multiday_backtest_audit.json"
    try:
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2)
        print(f"\nDetailed multiday audit saved to {out_file}")
    except Exception as e:
        print("Save error:", e)


if __name__ == "__main__":
    main()
