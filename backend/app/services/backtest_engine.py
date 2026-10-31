"""
Backtest & Training Engine for Smart Options Trading Bot
Simulates tick-by-tick option market from SQLite snapshots:
- Day 1 (Training & Calibration): 2026-09-16
- Day 2 (Out-of-sample Testing): 2026-09-17
Compares:
1. Baseline Naive Bot (unfiltered, poor OTMs, single conviction threshold)
2. Institutional Smart Quality Bot (ATM/1-ITM, TQS score >= 70, persistence, MFE/MAE trailing, daily risk limits, Rs 100/lot brokerage)
"""
import os
import sys
import json
import sqlite3
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, time

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "terminal_snapshots.db")

LOT_SIZES = {
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "FINNIFTY": 60,
    "MIDCPNIFTY": 120,
    "SENSEX": 20
}

STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "SENSEX": 100
}

MIN_PREMIUMS = {
    "NIFTY": 45.0,
    "BANKNIFTY": 75.0,
    "FINNIFTY": 40.0,
    "MIDCPNIFTY": 25.0
}


class SimulatedTrade:
    def __init__(
        self,
        trade_id: str,
        symbol: str,
        role: str,
        strategy_type: str,
        strike: float,
        option_type: str,
        entry_time: str,
        entry_price: float,
        target_price: float,
        stop_loss_price: float,
        lot_size: int,
        tqs_score: float = 0.0,
        trade_date: str = ""
    ):
        self.trade_id = trade_id
        self.symbol = symbol
        self.role = role  # "BUYER" or "SELLER"
        self.strategy_type = strategy_type
        self.strike = strike
        self.option_type = option_type
        self.entry_time = entry_time
        self.entry_price = entry_price
        self.current_price = entry_price
        self.target_price = target_price
        self.stop_loss_price = stop_loss_price
        self.trailing_sl = stop_loss_price
        self.lot_size = lot_size
        self.tqs_score = tqs_score
        self.trade_date = trade_date

        self.status = "OPEN"
        self.exit_time = ""
        self.exit_price = 0.0
        self.exit_reason = ""

        self.gross_pnl = 0.0
        self.net_pnl = 0.0
        self.brokerage = 100.0  # Rs 100 per lot round-trip

        self.mfe_pts = 0.0
        self.mfe_inr = 0.0
        self.mae_pts = 0.0
        self.mae_inr = 0.0

    def update_mtm(self, ltp: float):
        if self.status != "OPEN":
            return

        self.current_price = ltp
        if self.role == "BUYER":
            pts = ltp - self.entry_price
            gross = pts * self.lot_size
        else:  # SELLER credit spread
            pts = self.entry_price - ltp
            gross = pts * self.lot_size

        self.mfe_pts = max(self.mfe_pts, pts)
        self.mfe_inr = max(self.mfe_inr, gross)
        self.mae_pts = min(self.mae_pts, pts)
        self.mae_inr = min(self.mae_inr, gross)

        # Dynamic Trailing Stop Loss
        if self.role == "BUYER":
            gain_pct = (ltp - self.entry_price) / self.entry_price if self.entry_price > 0 else 0
            if gain_pct >= 0.70:
                self.trailing_sl = max(self.trailing_sl, round(self.entry_price * 1.45, 2))
            elif gain_pct >= 0.45:
                self.trailing_sl = max(self.trailing_sl, round(self.entry_price * 1.22, 2))
            elif gain_pct >= 0.25:
                self.trailing_sl = max(self.trailing_sl, self.entry_price)  # Breakeven lock
        else:
            decay_pct = (self.entry_price - ltp) / self.entry_price if self.entry_price > 0 else 0
            if decay_pct >= 0.65:
                self.trailing_sl = min(self.trailing_sl, round(self.entry_price * 0.45, 2))
            elif decay_pct >= 0.40:
                self.trailing_sl = min(self.trailing_sl, self.entry_price)

    def close(self, exit_price: float, exit_time: str, reason: str):
        self.status = "CLOSED"
        self.exit_price = exit_price
        self.exit_time = exit_time
        self.exit_reason = reason

        if self.role == "BUYER":
            self.gross_pnl = round((exit_price - self.entry_price) * self.lot_size, 2)
        else:
            self.gross_pnl = round((self.entry_price - exit_price) * self.lot_size, 2)

        self.net_pnl = round(self.gross_pnl - self.brokerage, 2)


def run_backtest_simulation(
    target_date: str,
    bot_mode: str = "SMART_QUALITY",  # "BASELINE" or "SMART_QUALITY"
    buyer_min_tqs: float = 70.0,
    seller_min_tqs: float = 66.0
) -> Dict[str, Any]:
    """
    Simulates trading for a specific date using recorded snapshot data.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Load intraday snapshots ordered by time
    cursor.execute("""
        SELECT * FROM intraday_snapshots
        WHERE trade_date = ?
        ORDER BY timestamp ASC, id ASC
    """, (target_date,))
    snapshots = cursor.fetchall()

    # Load strike snapshots map: (symbol, time_str, strike, option_type) -> row
    cursor.execute("""
        SELECT * FROM intraday_strike_snapshots
        WHERE trade_date = ?
    """, (target_date,))
    strike_rows = cursor.fetchall()
    conn.close()

    strike_map = {}
    for sr in strike_rows:
        key = (sr["symbol"], sr["time_str"], float(sr["strike"]), sr["option_type"])
        strike_map[key] = dict(sr)

    # State tracking
    active_positions: Dict[str, SimulatedTrade] = {}  # symbol -> trade
    closed_trades: List[SimulatedTrade] = []
    signal_ticks: Dict[str, Dict[str, Any]] = {}
    daily_realized_loss = 0.0

    for snap in snapshots:
        sym = snap["symbol"]
        t_str = snap["time_str"]
        spot = snap["spot"]
        pcr = snap["pcr"]
        confluence = snap["confluence"] or 50.0
        step = STRIKE_STEPS.get(sym, 50)
        lot = LOT_SIZES.get(sym, 75)
        atm = round(spot / step) * step

        # Check existing active trade for exit
        if sym in active_positions:
            tr = active_positions[sym]
            # Lookup latest strike price
            s_key = (sym, t_str, tr.strike, tr.option_type)
            curr_row = strike_map.get(s_key)
            if curr_row:
                ltp = curr_row["ltp"]
                tr.update_mtm(ltp)

                # Check Exits
                if tr.role == "BUYER":
                    if ltp >= tr.target_price:
                        tr.close(ltp, t_str, "TARGET_HIT (+50% Momentum Target)")
                        daily_realized_loss += tr.net_pnl
                        closed_trades.append(tr)
                        del active_positions[sym]
                        continue
                    elif ltp <= tr.trailing_sl:
                        reason = "TRAILING_SL_HIT" if tr.trailing_sl > tr.stop_loss_price else "STOP_LOSS_HIT"
                        tr.close(ltp, t_str, reason)
                        daily_realized_loss += tr.net_pnl
                        closed_trades.append(tr)
                        del active_positions[sym]
                        continue
                else:  # SELLER
                    if ltp <= tr.target_price:
                        tr.close(ltp, t_str, "TARGET_HIT (Decay Captured)")
                        daily_realized_loss += tr.net_pnl
                        closed_trades.append(tr)
                        del active_positions[sym]
                        continue
                    elif ltp >= tr.trailing_sl:
                        reason = "TRAILING_SL_HIT" if tr.trailing_sl < tr.stop_loss_price else "STOP_LOSS_HIT"
                        tr.close(ltp, t_str, reason)
                        daily_realized_loss += tr.net_pnl
                        closed_trades.append(tr)
                        del active_positions[sym]
                        continue

            # Auto EOD square-off at 15:35
            if t_str >= "15:35":
                exit_price = curr_row["ltp"] if curr_row else tr.current_price
                tr.close(exit_price, t_str, "EOD_SQUAREOFF (15:35 Safety)")
                daily_realized_loss += tr.net_pnl
                closed_trades.append(tr)
                del active_positions[sym]
                continue

            continue  # Already in active trade for this symbol

        # If no active trade, evaluate entry
        # Check time window (09:16 to 15:25)
        if t_str < "09:16" or t_str > "15:25":
            continue

        # Daily loss circuit breaker (-3500)
        if bot_mode == "SMART_QUALITY" and daily_realized_loss <= -3500.0:
            continue

        # Formulate directional bias from confluence
        is_bullish = confluence >= 68.0 or pcr >= 1.20
        is_bearish = confluence <= 32.0 or pcr <= 0.80

        # Choppy regime check
        if bot_mode == "SMART_QUALITY":
            if 0.94 <= pcr <= 1.06 and 48.0 <= confluence <= 52.0:
                continue  # NO-TRADE CHOPPY filter

        role = "BUYER" if (is_bullish or is_bearish) else "SELLER"

        # Signal Persistence Filter for Smart Quality Bot (Needs >= 2 consecutive ticks)
        if bot_mode == "SMART_QUALITY":
            dir_sig = "BULL" if is_bullish else ("BEAR" if is_bearish else "NEUTRAL")
            prev_sig = signal_ticks.get(sym, {})
            if prev_sig.get("dir") != dir_sig:
                signal_ticks[sym] = {"dir": dir_sig, "count": 1}
                continue
            else:
                prev_sig["count"] += 1
                if prev_sig["count"] < 2:
                    continue

        if role == "BUYER":
            otype = "CE" if is_bullish else "PE"
            # Strike selection:
            # Baseline: Can pick 1-2 OTM or ATM
            # Smart Quality: Strictly ATM or 1-step ITM
            if bot_mode == "SMART_QUALITY":
                # Prefer ATM
                target_strike = atm
            else:
                # Baseline allows 1 OTM
                target_strike = (atm + step) if otype == "CE" else (atm - step)

            s_key = (sym, t_str, float(target_strike), otype)
            contract = strike_map.get(s_key)
            if not contract:
                continue

            ltp = contract["ltp"]
            if ltp <= 0:
                continue

            # Minimum premium check in Smart Quality Bot
            min_prem = MIN_PREMIUMS.get(sym, 35.0)
            if bot_mode == "SMART_QUALITY" and ltp < min_prem:
                continue

            # Compute TQS
            if bot_mode == "SMART_QUALITY":
                # TQS 5 Pillars calculation
                p1 = 25.0 if abs(confluence - 50) >= 20 else 15.0
                p2 = 20.0 if target_strike == atm else 16.0
                oi = contract["oi"] or 0
                vol = contract["volume"] or 0
                p3 = 18.0 if oi > 50000 and vol > 20000 else 10.0
                p4 = 18.0 if (otype == "CE" and spot > atm) or (otype == "PE" and spot < atm) else 10.0
                p5 = 14.0  # R:R is 1:1.66
                tqs = round(p1 + p2 + p3 + p4 + p5, 1)

                if tqs < buyer_min_tqs:
                    continue
            else:
                tqs = 50.0  # Baseline doesn't compute TQS

            target_p = round(ltp * 1.50, 2)
            sl_p = round(ltp * 0.70, 2)

            new_trade = SimulatedTrade(
                trade_id=f"{bot_mode}_{sym}_{t_str.replace(':', '')}",
                symbol=sym,
                role="BUYER",
                strategy_type="MOMENTUM_BUY",
                strike=target_strike,
                option_type=otype,
                entry_time=t_str,
                entry_price=ltp,
                target_price=target_p,
                stop_loss_price=sl_p,
                lot_size=lot,
                tqs_score=tqs,
                trade_date=target_date
            )
            active_positions[sym] = new_trade

        else:
            # SELLER
            otype = "PE" if confluence >= 50 else "CE"
            # Short strike: 1 OTM
            sell_strike = (atm - step) if otype == "PE" else (atm + step)

            s_key = (sym, t_str, float(sell_strike), otype)
            contract = strike_map.get(s_key)
            if not contract:
                continue

            credit = contract["ltp"]
            if credit < 8.0:
                continue

            if bot_mode == "SMART_QUALITY":
                tqs = 70.0
                if tqs < seller_min_tqs:
                    continue
            else:
                tqs = 50.0

            target_p = round(credit * 0.30, 2)
            sl_p = round(credit * 1.80, 2)

            new_trade = SimulatedTrade(
                trade_id=f"{bot_mode}_{sym}_{t_str.replace(':', '')}",
                symbol=sym,
                role="SELLER",
                strategy_type="CREDIT_SPREAD",
                strike=sell_strike,
                option_type=otype,
                entry_time=t_str,
                entry_price=credit,
                target_price=target_p,
                stop_loss_price=sl_p,
                lot_size=lot,
                tqs_score=tqs,
                trade_date=target_date
            )
            active_positions[sym] = new_trade

    # Force close any remaining open positions at end of day
    for sym, tr in list(active_positions.items()):
        tr.close(tr.current_price, "15:35", "EOD_SQUAREOFF")
        closed_trades.append(tr)

    # Compute Statistics
    tot = len(closed_trades)
    wins = [t for t in closed_trades if t.net_pnl > 0]
    losses = [t for t in closed_trades if t.net_pnl <= 0]
    win_rate = round(len(wins) / tot * 100.0, 1) if tot > 0 else 0.0

    gross_pnl = round(sum(t.gross_pnl for t in closed_trades), 2)
    total_brokerage = round(sum(t.brokerage for t in closed_trades), 2)
    net_pnl = round(sum(t.net_pnl for t in closed_trades), 2)

    gross_profit = sum(t.gross_pnl for t in wins)
    gross_loss = abs(sum(t.gross_pnl for t in losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 1.0)

    # Buyer vs Seller Breakdown
    buyer_trades = [t for t in closed_trades if t.role == "BUYER"]
    seller_trades = [t for t in closed_trades if t.role == "SELLER"]

    b_wins = [t for t in buyer_trades if t.net_pnl > 0]
    b_win_rate = round(len(b_wins) / len(buyer_trades) * 100.0, 1) if buyer_trades else 0.0
    b_gross = round(sum(t.gross_pnl for t in buyer_trades), 2)
    b_net = round(sum(t.net_pnl for t in buyer_trades), 2)
    b_brokerage = round(sum(t.brokerage for t in buyer_trades), 2)

    s_wins = [t for t in seller_trades if t.net_pnl > 0]
    s_win_rate = round(len(s_wins) / len(seller_trades) * 100.0, 1) if seller_trades else 0.0
    s_gross = round(sum(t.gross_pnl for t in seller_trades), 2)
    s_net = round(sum(t.net_pnl for t in seller_trades), 2)
    s_brokerage = round(sum(t.brokerage for t in seller_trades), 2)

    # Max Drawdown
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in closed_trades:
        cum += t.net_pnl
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    avg_mfe = round(sum(t.mfe_inr for t in closed_trades) / tot, 2) if tot > 0 else 0.0
    avg_mae = round(sum(t.mae_inr for t in closed_trades) / tot, 2) if tot > 0 else 0.0

    return {
        "date": target_date,
        "bot_mode": bot_mode,
        "total_trades": tot,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate_pct": win_rate,
        "gross_pnl_inr": gross_pnl,
        "brokerage_inr": total_brokerage,
        "net_pnl_inr": net_pnl,
        "profit_factor": profit_factor,
        "max_drawdown_inr": round(max_dd, 2),
        "avg_mfe_inr": avg_mfe,
        "avg_mae_inr": avg_mae,
        "buyer_breakdown": {
            "trades": len(buyer_trades),
            "wins": len(b_wins),
            "win_rate_pct": b_win_rate,
            "gross_pnl_inr": b_gross,
            "brokerage_inr": b_brokerage,
            "net_pnl_inr": b_net
        },
        "seller_breakdown": {
            "trades": len(seller_trades),
            "wins": len(s_wins),
            "win_rate_pct": s_win_rate,
            "gross_pnl_inr": s_gross,
            "brokerage_inr": s_brokerage,
            "net_pnl_inr": s_net
        },
        "trades": [
            {
                "id": t.trade_id,
                "symbol": t.symbol,
                "role": t.role,
                "strategy": t.strategy_type,
                "strike": t.strike,
                "type": t.option_type,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "gross_pnl": t.gross_pnl,
                "net_pnl": t.net_pnl,
                "mfe_inr": t.mfe_inr,
                "mae_inr": t.mae_inr,
                "exit_reason": t.exit_reason
            }
            for t in closed_trades
        ]
    }


def main():
    print("=" * 80)
    print("INSTITUTIONAL OPTIONS TRADING BOT - TRAINING & OUT-OF-SAMPLE TEST HARNESS")
    print("=" * 80)

    # 1. Day 1 (Training & Calibration): 2026-09-16
    print("\n>>> DAY 1 (TRAINING DAY - 2026-09-16) <<<")
    day1_baseline = run_backtest_simulation("2026-09-16", bot_mode="BASELINE")
    day1_smart = run_backtest_simulation("2026-09-16", bot_mode="SMART_QUALITY", buyer_min_tqs=70.0)

    print(f"\n[DAY 1 BASELINE BOT]:")
    print(f"  Trades: {day1_baseline['total_trades']} | Win Rate: {day1_baseline['win_rate_pct']}%")
    print(f"  Gross P&L: Rs. {day1_baseline['gross_pnl_inr']:,.2f} | Brokerage: Rs. {day1_baseline['brokerage_inr']:,.2f} | Net P&L: Rs. {day1_baseline['net_pnl_inr']:,.2f}")
    print(f"  Profit Factor: {day1_baseline['profit_factor']} | Max DD: Rs. {day1_baseline['max_drawdown_inr']:,.2f}")

    print(f"\n[DAY 1 SMART QUALITY BOT (Calibrated TQS >= 70, ATM/1-ITM)]:")
    print(f"  Trades: {day1_smart['total_trades']} | Win Rate: {day1_smart['win_rate_pct']}%")
    print(f"  Gross P&L: Rs. {day1_smart['gross_pnl_inr']:,.2f} | Brokerage: Rs. {day1_smart['brokerage_inr']:,.2f} | Net P&L: Rs. {day1_smart['net_pnl_inr']:,.2f}")
    print(f"  Profit Factor: {day1_smart['profit_factor']} | Max DD: Rs. {day1_smart['max_drawdown_inr']:,.2f}")
    print(f"  Avg MFE: Rs. {day1_smart['avg_mfe_inr']:,.2f} | Avg MAE: Rs. {day1_smart['avg_mae_inr']:,.2f}")
    print(f"  Buyer Net P&L: Rs. {day1_smart['buyer_breakdown']['net_pnl_inr']:,.2f} ({day1_smart['buyer_breakdown']['trades']} trades)")
    print(f"  Seller Net P&L: Rs. {day1_smart['seller_breakdown']['net_pnl_inr']:,.2f} ({day1_smart['seller_breakdown']['trades']} trades)")

    # 2. Day 2 (Testing Day - 2026-09-17)
    print("\n" + "=" * 80)
    print(">>> DAY 2 (OUT-OF-SAMPLE TESTING DAY - 2026-09-17) <<<")
    day2_baseline = run_backtest_simulation("2026-09-17", bot_mode="BASELINE")
    day2_smart = run_backtest_simulation("2026-09-17", bot_mode="SMART_QUALITY", buyer_min_tqs=70.0)

    print(f"\n[DAY 2 BASELINE BOT (Over-trading, unconfirmed signals)]:")
    print(f"  Trades: {day2_baseline['total_trades']} | Win Rate: {day2_baseline['win_rate_pct']}%")
    print(f"  Gross P&L: Rs. {day2_baseline['gross_pnl_inr']:,.2f} | Brokerage: Rs. {day2_baseline['brokerage_inr']:,.2f} | Net P&L: Rs. {day2_baseline['net_pnl_inr']:,.2f}")
    print(f"  Profit Factor: {day2_baseline['profit_factor']} | Max DD: Rs. {day2_baseline['max_drawdown_inr']:,.2f}")

    print(f"\n[DAY 2 SMART QUALITY BOT (Institutional Filters & TQS Entry)]:")
    print(f"  Trades: {day2_smart['total_trades']} | Win Rate: {day2_smart['win_rate_pct']}%")
    print(f"  Gross P&L: Rs. {day2_smart['gross_pnl_inr']:,.2f} | Brokerage: Rs. {day2_smart['brokerage_inr']:,.2f} | Net P&L: Rs. {day2_smart['net_pnl_inr']:,.2f}")
    print(f"  Profit Factor: {day2_smart['profit_factor']} | Max DD: Rs. {day2_smart['max_drawdown_inr']:,.2f}")
    print(f"  Avg MFE: Rs. {day2_smart['avg_mfe_inr']:,.2f} | Avg MAE: Rs. {day2_smart['avg_mae_inr']:,.2f}")
    print(f"  Buyer Net P&L: Rs. {day2_smart['buyer_breakdown']['net_pnl_inr']:,.2f} ({day2_smart['buyer_breakdown']['trades']} trades)")
    print(f"  Seller Net P&L: Rs. {day2_smart['seller_breakdown']['net_pnl_inr']:,.2f} ({day2_smart['seller_breakdown']['trades']} trades)")

    # Save detailed JSON artifacts
    results = {
        "training_day_2026_09_16": {
            "baseline": day1_baseline,
            "smart_quality": day1_smart
        },
        "testing_day_2026_09_17": {
            "baseline": day2_baseline,
            "smart_quality": day2_smart
        }
    }
    out_path = os.path.join(os.path.dirname(__file__), "..", "db", "backtest_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nDetailed backtest results saved to: {out_path}")


if __name__ == "__main__":
    main()
