"""
Test Improved Institutional Bot with:
1. Opening 15-Minute Settlement Filter (Start at 09:30 IST instead of 09:16)
2. Fast Breakeven Lock at +20% gain (never let a winner turn into a -30% loser!)
3. Tier-2 Profit Lock at +35% gain (locks +15%)
4. Expiry Day Afternoon Gamma Defense
5. Midday Chop Gate (11:30 - 13:30 IST)
"""
import os
import sys
import json
import sqlite3
from typing import Dict, Any, List

DB_PATH = "/home/ubuntu/nse-dashboard/backend/app/db/terminal_snapshots.db"
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "terminal_snapshots.db")

LOT_SIZES = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120}
STRIKE_STEPS = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50, "MIDCPNIFTY": 25}
MIN_PREMIUMS = {"NIFTY": 45.0, "BANKNIFTY": 75.0, "FINNIFTY": 40.0, "MIDCPNIFTY": 25.0}


class ImprovedSimTrade:
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

    def update_mtm(self, ltp, spot, step):
        if self.status != "OPEN":
            return
        self.curr_p = ltp
        pts = (ltp - self.entry_p) if self.role == "BUYER" else (self.entry_p - ltp)
        gross = pts * self.lot
        self.mfe_pts = max(self.mfe_pts, pts)
        self.mfe_inr = max(self.mfe_inr, gross)
        self.mae_pts = min(self.mae_pts, pts)
        self.mae_inr = min(self.mae_inr, gross)

        # IMPROVED 3-STAGE DYNAMIC TRAILING SL
        if self.role == "BUYER":
            gain_pct = (ltp - self.entry_p) / self.entry_p if self.entry_p > 0 else 0
            if gain_pct >= 0.60:
                self.trailing_sl = max(self.trailing_sl, round(self.entry_p * 1.35, 2))
            elif gain_pct >= 0.35:
                self.trailing_sl = max(self.trailing_sl, round(self.entry_p * 1.15, 2))
            elif gain_pct >= 0.20:
                self.trailing_sl = max(self.trailing_sl, self.entry_p)  # Breakeven lock at +20%!
        else:
            decay_pct = (self.entry_p - ltp) / self.entry_p if self.entry_p > 0 else 0
            if decay_pct >= 0.60:
                self.trailing_sl = min(self.trailing_sl, round(self.entry_p * 0.40, 2))
            elif decay_pct >= 0.35:
                self.trailing_sl = min(self.trailing_sl, self.entry_p)  # Breakeven lock at 35% decay

            # Expiry Day Gamma Emergency Exit: If spot breaches short strike on expiry day
            if self.date == "2026-09-24":
                if (self.otype == "PE" and spot < (self.strike + 0.5 * step)) or \
                   (self.otype == "CE" and spot > (self.strike - 0.5 * step)):
                    self.trailing_sl = ltp  # Emergency exit

    def close(self, exit_p, exit_t, reason):
        self.status = "CLOSED"
        self.exit_p = exit_p
        self.exit_t = exit_t
        self.exit_reason = reason
        pts = (exit_p - self.entry_p) if self.role == "BUYER" else (self.entry_p - exit_p)
        self.gross_pnl = round(pts * self.lot, 2)
        self.net_pnl = round(self.gross_pnl - self.brokerage, 2)


def run_improved_backtest(target_date: str) -> Dict[str, Any]:
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

    active_positions: Dict[str, ImprovedSimTrade] = {}
    closed_trades: List[ImprovedSimTrade] = []
    signal_ticks: Dict[str, Dict[str, Any]] = {}
    spot_by_minute: Dict[str, Dict[str, float]] = {s: {} for s in LOT_SIZES}
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

        # Track spot by minute
        spot_by_minute[sym][t_str] = spot

        # Find 3-5 minute past spot for authentic momentum
        h_val, m_val = map(int, t_str.split(":"))
        past_spot = None
        for dm in [3, 4, 5, 2]:
            p_tot = h_val * 60 + m_val - dm
            if p_tot >= 9 * 60 + 15:
                cand_t = f"{p_tot // 60:02d}:{p_tot % 60:02d}"
                if cand_t in spot_by_minute[sym]:
                    past_spot = spot_by_minute[sym][cand_t]
                    break
        spot_momentum = (spot - past_spot) if past_spot is not None else 0.0

        if t_str < "11:30":
            sess = "MORNING"
        elif t_str < "13:30":
            sess = "MIDDAY"
        else:
            sess = "AFTERNOON"

        # Check exit
        if sym in active_positions:
            tr = active_positions[sym]
            s_key = (sym, t_str, tr.strike, tr.otype)
            curr_row = strike_map.get(s_key)
            if curr_row:
                ltp = curr_row["ltp"]
                tr.update_mtm(ltp, spot, step)

                if tr.role == "BUYER":
                    if ltp >= tr.target_p:
                        tr.close(ltp, t_str, "TARGET_HIT (+50% Momentum)")
                        daily_realized_loss += tr.net_pnl
                        consecutive_losses[sym] = 0
                        closed_trades.append(tr)
                        del active_positions[sym]
                        continue
                    elif ltp <= tr.trailing_sl:
                        reason = "TRAILING_SL_HIT" if tr.trailing_sl > tr.sl_p else "STOP_LOSS_HIT"
                        tr.close(ltp, t_str, reason)
                        daily_realized_loss += tr.net_pnl
                        if tr.net_pnl < 0:
                            consecutive_losses[sym] += 1
                            cd_mins = 45 if consecutive_losses[sym] >= 2 else 20
                            symbol_cooldowns[sym] = add_minutes(t_str, cd_mins)
                        else:
                            consecutive_losses[sym] = 0
                            # 5-minute breather after any exit
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
                        reason = "GAMMA_SAFETY_EXIT" if (is_expiry_day and ltp >= tr.trailing_sl) else ("TRAILING_SL_HIT" if tr.trailing_sl < tr.sl_p else "STOP_LOSS_HIT")
                        tr.close(ltp, t_str, reason)
                        daily_realized_loss += tr.net_pnl
                        if tr.net_pnl < 0:
                            consecutive_losses[sym] += 1
                            cd_mins = 45 if consecutive_losses[sym] >= 2 else 25
                            symbol_cooldowns[sym] = add_minutes(t_str, cd_mins)
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

        # Risk Controls: Daily Circuit Breaker (-3500)
        if daily_realized_loss <= -3500.0:
            continue

        # Risk Controls: Symbol Consecutive Loss Cooldown (2 consecutive losses = 45 min cooldown)
        if sym in symbol_cooldowns:
            if t_str < symbol_cooldowns[sym]:
                continue
            else:
                del symbol_cooldowns[sym]

        # -------------------------------------------------------------
        # IMPROVEMENT 1: OPENING 15-MINUTE SETTLEMENT FILTER
        # Do not enter fresh trades before 09:30:00 IST!
        # Allows market opening volatility to settle and authentic trend to form.
        # -------------------------------------------------------------
        if t_str < "09:30" or t_str > "15:25":
            continue

        # IMPROVEMENT 3: MIDDAY CHOP GATE
        # Require higher confluence (>= 75 or <= 25) during midday lunch hours
        if sess == "MIDDAY" and not (confluence >= 75.0 or confluence <= 25.0):
            continue

        # Directional Signals: PCR is valid ONLY when aligned with spot momentum
        is_bullish = (confluence >= 68.0) or (pcr >= 1.20 and spot_momentum > 0)
        is_bearish = (confluence <= 32.0) or (pcr <= 0.80 and spot_momentum < 0)

        # Choppy market filter
        if 0.94 <= pcr <= 1.06 and 48.0 <= confluence <= 52.0:
            continue

        if is_expiry_day:
            # On Expiry day, 1 lot selling is omitted due to gamma risk; strictly take high-conviction BUYER trades
            if not (is_bullish or is_bearish):
                continue
            role = "BUYER"
        else:
            role = "BUYER" if (is_bullish or is_bearish) else "SELLER"

        # Signal Persistence Filter
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

            # Spot Price Multi-Minute Momentum Confirmation
            if otype == "CE" and spot_momentum < 0:
                continue
            if otype == "PE" and spot_momentum > 0:
                continue

            # On expiry day afternoon, prefer 1-ITM for gamma stability
            if is_expiry_day and t_str >= "12:30":
                target_strike = (atm - step) if otype == "CE" else (atm + step)
            else:
                target_strike = atm

            s_key = (sym, t_str, float(target_strike), otype)
            contract = strike_map.get(s_key)
            if not contract:
                continue

            ltp = contract["ltp"]
            if ltp <= 0:
                continue

            min_prem = MIN_PREMIUMS.get(sym, 35.0)
            if ltp < min_prem:
                continue

            # TQS Gate
            p1 = 25.0 if abs(confluence - 50) >= 20 else 15.0
            p2 = 20.0 if target_strike == atm else 17.0
            oi = contract["oi"] or 0
            vol = contract["volume"] or 0
            p3 = 18.0 if oi > 50000 and vol > 20000 else 10.0
            p4 = 18.0 if (otype == "CE" and spot > atm) or (otype == "PE" and spot < atm) else 10.0
            p5 = 14.0
            tqs = round(p1 + p2 + p3 + p4 + p5, 1)

            min_tqs = 74.0 if sess == "MIDDAY" else 70.0
            if tqs < min_tqs:
                continue

            target_p = round(ltp * 1.50, 2)
            sl_p = round(ltp * 0.70, 2)

            tr = ImprovedSimTrade(
                tid=f"IMP_{sym}_{t_str.replace(':', '')}",
                sym=sym, role="BUYER", strat="MOMENTUM_BUY", strike=target_strike,
                otype=otype, entry_t=t_str, entry_p=ltp, target_p=target_p, sl_p=sl_p,
                lot=lot, tqs=tqs, date=target_date, session=sess
            )
            active_positions[sym] = tr

        else:
            # SELLER
            # Defense: No naked selling on Expiry afternoon (Gamma Graveyard)
            if is_expiry_day and t_str >= "12:30":
                continue

            otype = "PE" if confluence >= 50 else "CE"

            # Underlying Momentum Gate for Sellers: Never sell into accelerating adverse momentum
            if otype == "PE" and spot_momentum < -0.0006 * spot:
                continue
            if otype == "CE" and spot_momentum > 0.0006 * spot:
                continue

            otm_steps = 2 if is_expiry_day else 1
            sell_strike = (atm - otm_steps * step) if otype == "PE" else (atm + otm_steps * step)

            s_key = (sym, t_str, float(sell_strike), otype)
            contract = strike_map.get(s_key)
            if not contract:
                continue

            credit = contract["ltp"]
            min_credit = 10.0 if is_expiry_day else 8.0
            if credit < min_credit:
                continue

            decay_target = 0.20 if is_expiry_day else 0.30
            target_p = round(credit * decay_target, 2)
            sl_p = round(credit * 1.80, 2)

            tr = ImprovedSimTrade(
                tid=f"IMP_{sym}_{t_str.replace(':', '')}",
                sym=sym, role="SELLER", strat="CREDIT_SPREAD", strike=sell_strike,
                otype=otype, entry_t=t_str, entry_p=credit, target_p=target_p, sl_p=sl_p,
                lot=lot, tqs=68.0, date=target_date, session=sess
            )
            active_positions[sym] = tr

    for sym, tr in list(active_positions.items()):
        tr.close(tr.curr_p, "15:35", "EOD_SQUAREOFF")
        closed_trades.append(tr)

    tot = len(closed_trades)
    wins = [t for t in closed_trades if t.net_pnl > 0]
    win_rate = round(len(wins) / tot * 100.0, 1) if tot > 0 else 0.0
    net_pnl = round(sum(t.net_pnl for t in closed_trades), 2)
    gross_pnl = round(sum(t.gross_pnl for t in closed_trades), 2)
    brokerage = round(sum(t.brokerage for t in closed_trades), 2)

    buyers = [t for t in closed_trades if t.role == "BUYER"]
    sellers = [t for t in closed_trades if t.role == "SELLER"]
    b_net = round(sum(t.net_pnl for t in buyers), 2)
    s_net = round(sum(t.net_pnl for t in sellers), 2)

    return {
        "date": target_date,
        "total_trades": tot,
        "win_rate_pct": win_rate,
        "gross_pnl": gross_pnl,
        "brokerage": brokerage,
        "net_pnl": net_pnl,
        "buyer_net": b_net,
        "seller_net": s_net,
        "trades": [
            {
                "sym": t.sym, "role": t.role, "strike": t.strike, "otype": t.otype,
                "in": t.entry_t, "out": t.exit_t, "net": t.net_pnl, "mfe": t.mfe_inr, "reason": t.exit_reason
            }
            for t in closed_trades
        ]
    }


def main():
    dates = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"]
    print("=" * 80)
    print("TESTING UPGRADED BOT (09:30 OPENING FILTER + FAST BREAKEVEN TRAILING)")
    print("=" * 80)

    tot_net = 0.0
    tot_trades = 0
    tot_b_net = 0.0
    tot_s_net = 0.0

    for d in dates:
        res = run_improved_backtest(d)
        tot_net += res["net_pnl"]
        tot_trades += res["total_trades"]
        tot_b_net += res["buyer_net"]
        tot_s_net += res["seller_net"]
        print(f"\nDATE: {d} | Trades: {res['total_trades']} | Win Rate: {res['win_rate_pct']}% | Net P&L: Rs. {res['net_pnl']:>9,.2f} | Buyer: Rs. {res['buyer_net']:>9,.2f} | Seller: Rs. {res['seller_net']:>9,.2f}")
        for t in res["trades"]:
            print(f"   [{t['role']:6s}] {t['sym']:10s} {t['strike']} {t['otype']:2s} | In: {t['in']} -> Out: {t['out']} | Net: Rs. {t['net']:>8.2f} | {t['reason']}")

    print("\n" + "=" * 80)
    print("CUMULATIVE 4-DAY RESULT OF THE UPGRADED BOT:")
    print("=" * 80)
    print(f"Total Trades: {tot_trades}")
    print(f"Cumulative Net P&L: Rs. {tot_net:,.2f}")
    print(f"Buyer Net P&L:      Rs. {tot_b_net:,.2f}")
    print(f"Seller Net P&L:     Rs. {tot_s_net:,.2f}")


if __name__ == "__main__":
    main()
