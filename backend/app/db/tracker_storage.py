"""
SQLite Storage Repository for Smart Signal Tracker Bot
Adheres to Backend Design Agent Tenets: Zero Data Loss, ACID transactions, Thread Safety.
Manages:
- bot_trades: Active positions & completed trade journal with Gross/Net P&L, MFE/MAE, TQS.
- bot_metrics: Category-wise P&L aggregation, expectancy, and adaptive learning parameters.
"""
import os
import json
import sqlite3
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from app.core.market_hours import get_current_ist

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "trade_tracker.db")


class TrackerStorage:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes tables with explicit indices and runs safe schema migrations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    strategy_type TEXT NOT NULL,
                    role TEXT NOT NULL,
                    regime TEXT,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,
                    status TEXT NOT NULL,
                    legs_json TEXT NOT NULL,
                    lot_size INTEGER NOT NULL,
                    entry_net_price REAL NOT NULL,
                    current_net_price REAL NOT NULL,
                    exit_net_price REAL,
                    target_price REAL NOT NULL,
                    stop_loss_price REAL NOT NULL,
                    trailing_stop_price REAL NOT NULL,
                    unrealized_pnl_inr REAL DEFAULT 0.0,
                    realized_pnl_inr REAL DEFAULT 0.0,
                    exit_reason TEXT,
                    confluence_at_entry REAL,
                    created_at TEXT NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bot_trades_status ON bot_trades(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bot_trades_symbol ON bot_trades(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bot_trades_role ON bot_trades(role)")

            # Run safe migrations for advanced tracking columns
            migration_cols = [
                ("gross_realized_pnl_inr", "REAL DEFAULT 0.0"),
                ("gross_unrealized_pnl_inr", "REAL DEFAULT 0.0"),
                ("brokerage_inr", "REAL DEFAULT 0.0"),
                ("mfe_pts", "REAL DEFAULT 0.0"),
                ("mfe_inr", "REAL DEFAULT 0.0"),
                ("mae_pts", "REAL DEFAULT 0.0"),
                ("mae_inr", "REAL DEFAULT 0.0"),
                ("tqs_score", "REAL DEFAULT 0.0"),
                ("tqs_breakdown_json", "TEXT"),
                ("session_bucket", "TEXT"),
                ("trade_date", "TEXT"),
                ("lots", "INTEGER DEFAULT 1"),
                ("signal_details", "TEXT")
            ]
            for col_name, col_type in migration_cols:
                try:
                    cursor.execute(f"ALTER TABLE bot_trades ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_metrics (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Shadow Variant D Isolated Tables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_shadow_trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    strategy_type TEXT NOT NULL,
                    role TEXT NOT NULL,
                    regime TEXT,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,
                    status TEXT NOT NULL,
                    legs_json TEXT NOT NULL,
                    lot_size INTEGER NOT NULL,
                    entry_net_price REAL NOT NULL,
                    current_net_price REAL NOT NULL,
                    exit_net_price REAL,
                    target_price REAL NOT NULL,
                    stop_loss_price REAL NOT NULL,
                    trailing_stop_price REAL NOT NULL,
                    unrealized_pnl_inr REAL DEFAULT 0.0,
                    realized_pnl_inr REAL DEFAULT 0.0,
                    gross_realized_pnl_inr REAL DEFAULT 0.0,
                    gross_unrealized_pnl_inr REAL DEFAULT 0.0,
                    brokerage_inr REAL DEFAULT 75.0,
                    mfe_pts REAL DEFAULT 0.0,
                    mfe_inr REAL DEFAULT 0.0,
                    mae_pts REAL DEFAULT 0.0,
                    mae_inr REAL DEFAULT 0.0,
                    exit_reason TEXT,
                    confluence_at_entry REAL,
                    tqs_score REAL DEFAULT 0.0,
                    tqs_breakdown_json TEXT,
                    session_bucket TEXT,
                    trade_date TEXT,
                    lots INTEGER DEFAULT 1,
                    signal_details TEXT,
                    created_at TEXT NOT NULL,
                    is_alternative INTEGER DEFAULT 0,
                    moneyness_tag TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bot_shadow_trades_status ON bot_shadow_trades(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bot_shadow_trades_symbol ON bot_shadow_trades(symbol)")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bot_shadow_evaluations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    time_str TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    strike REAL NOT NULL,
                    tag TEXT NOT NULL,
                    ltp REAL NOT NULL,
                    bid REAL DEFAULT 0.0,
                    ask REAL DEFAULT 0.0,
                    spread REAL DEFAULT 0.0,
                    volume INTEGER DEFAULT 0,
                    oi INTEGER DEFAULT 0,
                    quote_age_seconds REAL DEFAULT 0.0,
                    confluence REAL NOT NULL,
                    tqs_score REAL NOT NULL,
                    p1_signal REAL NOT NULL,
                    p2_strike REAL NOT NULL,
                    p3_liquidity REAL NOT NULL,
                    p4_momentum REAL NOT NULL,
                    p5_risk_reward REAL NOT NULL,
                    required_outlay REAL NOT NULL,
                    available_capital REAL NOT NULL,
                    decision TEXT NOT NULL,
                    rejection_reason TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bot_shadow_eval_date ON bot_shadow_evaluations(trade_date, symbol)")
            conn.commit()

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Returns all currently open positions."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bot_trades WHERE status = 'OPEN' ORDER BY entry_time DESC")
            rows = cursor.fetchall()
            return [self._row_to_trade(r) for r in rows]

    def get_open_trade_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Returns active open trade for a specific index symbol, enforcing 1-trade limit."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bot_trades WHERE status = 'OPEN' AND symbol = ? LIMIT 1", (symbol.upper(),))
            row = cursor.fetchone()
            return self._row_to_trade(row) if row else None

    def insert_trade(self, trade: Dict[str, Any]) -> str:
        """Inserts a new open trade transactionally with brokerage and initial MFE/MAE."""
        trade_id = trade.get("id") or f"tr_{trade['symbol']}_{int(datetime.now().timestamp())}"
        now_dt = get_current_ist()
        now_iso = now_dt.isoformat()
        trade_date = trade.get("trade_date") or now_dt.strftime("%Y-%m-%d")

        # Variant C 1-lot scout baseline with flat Rs. 75 strategy accounting charge
        lots = trade.get("lots", 1)
        lot_size = trade.get("lot_size", 75)
        brokerage = float(trade.get("brokerage_inr", 75.0))
        signal_details = trade.get("signal_details", "")

        tqs_breakdown = trade.get("tqs_breakdown", {})
        tqs_json = json.dumps(tqs_breakdown) if isinstance(tqs_breakdown, dict) else str(tqs_breakdown)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO bot_trades (
                    id, symbol, strategy_type, role, regime, entry_time, status,
                    legs_json, lot_size, entry_net_price, current_net_price,
                    target_price, stop_loss_price, trailing_stop_price,
                    unrealized_pnl_inr, realized_pnl_inr,
                    gross_unrealized_pnl_inr, gross_realized_pnl_inr, brokerage_inr,
                    mfe_pts, mfe_inr, mae_pts, mae_inr,
                    tqs_score, tqs_breakdown_json, session_bucket, trade_date,
                    confluence_at_entry, created_at, lots, signal_details
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, 'OPEN',
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    0.0, 0.0,
                    0.0, 0.0, ?,
                    0.0, 0.0, 0.0, 0.0,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?
                )
            """, (
                trade_id,
                trade["symbol"].upper(),
                trade["strategy_type"],
                trade["role"].upper(),
                trade.get("regime", ""),
                trade.get("entry_time") or now_iso,
                json.dumps(trade.get("legs", [])),
                lot_size,
                trade["entry_net_price"],
                trade.get("current_net_price", trade["entry_net_price"]),
                trade["target_price"],
                trade["stop_loss_price"],
                trade.get("trailing_stop_price", trade["stop_loss_price"]),
                brokerage,
                trade.get("tqs_score", 0.0),
                tqs_json,
                trade.get("session_bucket", "MORNING"),
                trade_date,
                trade.get("confluence_at_entry", 50.0),
                now_iso,
                lots,
                signal_details
            ))
            conn.commit()
            return trade_id

    def update_trade_mtm(
        self,
        trade_id: str,
        current_net_price: float,
        gross_unrealized_pnl: float,
        net_unrealized_pnl: float,
        trailing_stop: float,
        mfe_pts: float,
        mfe_inr: float,
        mae_pts: float,
        mae_inr: float,
        legs_json: str = None
    ):
        """Updates live marked-to-market prices, trailing stop, and MFE/MAE excursions."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if legs_json:
                cursor.execute("""
                    UPDATE bot_trades
                    SET current_net_price = ?,
                        gross_unrealized_pnl_inr = ?,
                        unrealized_pnl_inr = ?,
                        trailing_stop_price = ?,
                        mfe_pts = MAX(COALESCE(mfe_pts, 0.0), ?),
                        mfe_inr = MAX(COALESCE(mfe_inr, 0.0), ?),
                        mae_pts = MIN(COALESCE(mae_pts, 0.0), ?),
                        mae_inr = MIN(COALESCE(mae_inr, 0.0), ?),
                        legs_json = ?
                    WHERE id = ?
                """, (current_net_price, gross_unrealized_pnl, net_unrealized_pnl, trailing_stop,
                      mfe_pts, mfe_inr, mae_pts, mae_inr, legs_json, trade_id))
            else:
                cursor.execute("""
                    UPDATE bot_trades
                    SET current_net_price = ?,
                        gross_unrealized_pnl_inr = ?,
                        unrealized_pnl_inr = ?,
                        trailing_stop_price = ?,
                        mfe_pts = MAX(COALESCE(mfe_pts, 0.0), ?),
                        mfe_inr = MAX(COALESCE(mfe_inr, 0.0), ?),
                        mae_pts = MIN(COALESCE(mae_pts, 0.0), ?),
                        mae_inr = MIN(COALESCE(mae_inr, 0.0), ?),
                    WHERE id = ?
                """, (current_net_price, gross_unrealized_pnl, net_unrealized_pnl, trailing_stop,
                      mfe_pts, mfe_inr, mae_pts, mae_inr, trade_id))
            conn.commit()

    def close_trade(
        self,
        trade_id: str,
        exit_net_price: float,
        gross_realized_pnl: float,
        net_realized_pnl: float,
        exit_reason: str,
        mfe_pts: float = None,
        mfe_inr: float = None,
        mae_pts: float = None,
        mae_inr: float = None
    ):
        """Closes an active trade transactionally with Gross P&L, Net P&L (after Rs 100 brokerage)."""
        now_iso = get_current_ist().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if mfe_inr is not None and mae_inr is not None:
                cursor.execute("""
                    UPDATE bot_trades
                    SET status = 'CLOSED',
                        exit_net_price = ?,
                        gross_realized_pnl_inr = ?,
                        realized_pnl_inr = ?,
                        gross_unrealized_pnl_inr = 0.0,
                        unrealized_pnl_inr = 0.0,
                        mfe_pts = MAX(COALESCE(mfe_pts, 0.0), ?),
                        mfe_inr = MAX(COALESCE(mfe_inr, 0.0), ?),
                        mae_pts = MIN(COALESCE(mae_pts, 0.0), ?),
                        mae_inr = MIN(COALESCE(mae_inr, 0.0), ?),
                        exit_reason = ?,
                        exit_time = ?
                    WHERE id = ?
                """, (exit_net_price, gross_realized_pnl, net_realized_pnl,
                      mfe_pts, mfe_inr, mae_pts, mae_inr, exit_reason, now_iso, trade_id))
            else:
                cursor.execute("""
                    UPDATE bot_trades
                    SET status = 'CLOSED',
                        exit_net_price = ?,
                        gross_realized_pnl_inr = ?,
                        realized_pnl_inr = ?,
                        gross_unrealized_pnl_inr = 0.0,
                        unrealized_pnl_inr = 0.0,
                        exit_reason = ?,
                        exit_time = ?
                    WHERE id = ?
                """, (exit_net_price, gross_realized_pnl, net_realized_pnl, exit_reason, now_iso, trade_id))
            conn.commit()

    def get_closed_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns completed trades for journal display."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bot_trades WHERE status = 'CLOSED' ORDER BY exit_time DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [self._row_to_trade(r) for r in rows]

    def get_today_trades(self, trade_date: str = None) -> List[Dict[str, Any]]:
        """Returns all trades executed today."""
        if not trade_date:
            trade_date = get_current_ist().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bot_trades WHERE trade_date = ? ORDER BY entry_time ASC", (trade_date,))
            rows = cursor.fetchall()
            return [self._row_to_trade(r) for r in rows]

    def get_today_realized_pnl(self, trade_date: str = None) -> float:
        """Returns sum of net realized PnL today."""
        if not trade_date:
            trade_date = get_current_ist().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COALESCE(SUM(realized_pnl_inr), 0.0) FROM bot_trades WHERE status = 'CLOSED' AND trade_date = ?", (trade_date,))
            res = cursor.fetchone()
            return float(res[0]) if res else 0.0

    def get_consecutive_losses_for_symbol(self, symbol: str, trade_date: str = None) -> int:
        """Counts current streak of consecutive losses today for this symbol."""
        if not trade_date:
            trade_date = get_current_ist().strftime("%Y-%m-%d")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT realized_pnl_inr FROM bot_trades
                WHERE status = 'CLOSED' AND symbol = ? AND trade_date = ?
                ORDER BY exit_time DESC LIMIT 5
            """, (symbol.upper(), trade_date))
            rows = cursor.fetchall()
            streak = 0
            for r in rows:
                if r[0] < 0:
                    streak += 1
                else:
                    break
            return streak

    def get_category_pnl_summary(self) -> Dict[str, Any]:
        """
        Computes category-wise P&L breakdown:
        - By Strategy Role (SELLER vs BUYER) with Gross PnL, Brokerage, Net PnL, Win Rate, Profit Factor
        - By Symbol (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY)
        - By Time-of-Day Session (MORNING, MIDDAY, AFTERNOON)
        - Rolling Expectancy, Average R-Multiple, and Max Drawdown
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Global closed totals
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_trades,
                    COALESCE(SUM(gross_realized_pnl_inr), 0.0) as total_gross_realized_pnl,
                    COALESCE(SUM(realized_pnl_inr), 0.0) as total_net_realized_pnl,
                    COALESCE(SUM(brokerage_inr), 0.0) as total_brokerage,
                    COALESCE(SUM(CASE WHEN realized_pnl_inr > 0 THEN 1 ELSE 0 END), 0) as winning_trades,
                    COALESCE(SUM(CASE WHEN realized_pnl_inr < 0 THEN 1 ELSE 0 END), 0) as losing_trades,
                    COALESCE(SUM(CASE WHEN realized_pnl_inr > 0 THEN realized_pnl_inr ELSE 0 END), 0.0) as gross_profit,
                    COALESCE(SUM(CASE WHEN realized_pnl_inr < 0 THEN ABS(realized_pnl_inr) ELSE 0 END), 0.0) as gross_loss,
                    COALESCE(AVG(CASE WHEN realized_pnl_inr > 0 THEN realized_pnl_inr END), 0.0) as avg_win,
                    COALESCE(AVG(CASE WHEN realized_pnl_inr < 0 THEN ABS(realized_pnl_inr) END), 0.0) as avg_loss
                FROM bot_trades WHERE status = 'CLOSED'
            """)
            g_row = cursor.fetchone()
            tot = g_row["total_trades"]
            wins = g_row["winning_trades"]
            losses = g_row["losing_trades"]
            win_rate = round((wins / tot * 100.0), 1) if tot > 0 else 0.0
            gross_p = g_row["gross_profit"]
            gross_l = g_row["gross_loss"]
            profit_factor = round(gross_p / gross_l, 2) if gross_l > 0 else (round(gross_p, 2) if gross_p > 0 else 1.0)
            avg_win = round(g_row["avg_win"], 2)
            avg_loss = round(g_row["avg_loss"], 2)

            # Rolling Expectancy: E = (Win% * AvgWin) - (Loss% * AvgLoss)
            win_pct = wins / tot if tot > 0 else 0.0
            loss_pct = losses / tot if tot > 0 else 0.0
            expectancy = round((win_pct * avg_win) - (loss_pct * avg_loss), 2)

            # Global unrealized open P&L
            cursor.execute("""
                SELECT 
                    COALESCE(SUM(gross_unrealized_pnl_inr), 0.0) as total_gross_unrealized,
                    COALESCE(SUM(unrealized_pnl_inr), 0.0) as total_net_unrealized,
                    COUNT(*) as open_count 
                FROM bot_trades WHERE status = 'OPEN'
            """)
            u_row = cursor.fetchone()

            # Breakdown by Strategy Role (SELLER vs BUYER)
            cursor.execute("""
                SELECT 
                    role,
                    COUNT(*) as count,
                    COALESCE(SUM(gross_realized_pnl_inr), 0.0) as gross_pnl,
                    COALESCE(SUM(brokerage_inr), 0.0) as brokerage,
                    COALESCE(SUM(realized_pnl_inr), 0.0) as net_pnl,
                    COALESCE(SUM(CASE WHEN realized_pnl_inr > 0 THEN 1 ELSE 0 END), 0) as wins,
                    COALESCE(SUM(CASE WHEN realized_pnl_inr > 0 THEN realized_pnl_inr ELSE 0 END), 0.0) as gp,
                    COALESCE(SUM(CASE WHEN realized_pnl_inr < 0 THEN ABS(realized_pnl_inr) ELSE 0 END), 0.0) as gl,
                    COALESCE(AVG(CASE WHEN realized_pnl_inr > 0 THEN realized_pnl_inr END), 0.0) as r_avg_win,
                    COALESCE(AVG(CASE WHEN realized_pnl_inr < 0 THEN ABS(realized_pnl_inr) END), 0.0) as r_avg_loss
                FROM bot_trades WHERE status = 'CLOSED'
                GROUP BY role
            """)
            role_rows = cursor.fetchall()
            role_breakdown = {
                "SELLER": {"gross_pnl": 0.0, "brokerage": 0.0, "net_pnl": 0.0, "trades": 0, "win_rate": 0.0, "profit_factor": 1.0, "expectancy": 0.0},
                "BUYER": {"gross_pnl": 0.0, "brokerage": 0.0, "net_pnl": 0.0, "trades": 0, "win_rate": 0.0, "profit_factor": 1.0, "expectancy": 0.0}
            }
            for rr in role_rows:
                r_key = rr["role"]
                r_cnt = rr["count"]
                r_wins = rr["wins"]
                r_gp = rr["gp"]
                r_gl = rr["gl"]
                r_pf = round(r_gp / r_gl, 2) if r_gl > 0 else (round(r_gp, 2) if r_gp > 0 else 1.0)
                r_w_pct = r_wins / r_cnt if r_cnt > 0 else 0.0
                r_l_pct = (r_cnt - r_wins) / r_cnt if r_cnt > 0 else 0.0
                r_exp = round((r_w_pct * rr["r_avg_win"]) - (r_l_pct * rr["r_avg_loss"]), 2)
                role_breakdown[r_key] = {
                    "gross_pnl": round(rr["gross_pnl"], 2),
                    "brokerage": round(rr["brokerage"], 2),
                    "net_pnl": round(rr["net_pnl"], 2),
                    "trades": r_cnt,
                    "win_rate": round((r_wins / r_cnt * 100.0), 1) if r_cnt > 0 else 0.0,
                    "profit_factor": r_pf,
                    "expectancy": r_exp
                }

            # Breakdown by Symbol
            cursor.execute("""
                SELECT 
                    symbol,
                    COUNT(*) as count,
                    COALESCE(SUM(gross_realized_pnl_inr), 0.0) as gross_pnl,
                    COALESCE(SUM(brokerage_inr), 0.0) as brokerage,
                    COALESCE(SUM(realized_pnl_inr), 0.0) as net_pnl,
                    COALESCE(SUM(CASE WHEN realized_pnl_inr > 0 THEN 1 ELSE 0 END), 0) as wins
                FROM bot_trades WHERE status = 'CLOSED'
                GROUP BY symbol
            """)
            sym_rows = cursor.fetchall()
            symbol_breakdown = {
                "NIFTY": {"gross_pnl": 0.0, "net_pnl": 0.0, "brokerage": 0.0, "trades": 0, "win_rate": 0.0},
                "BANKNIFTY": {"gross_pnl": 0.0, "net_pnl": 0.0, "brokerage": 0.0, "trades": 0, "win_rate": 0.0},
                "FINNIFTY": {"gross_pnl": 0.0, "net_pnl": 0.0, "brokerage": 0.0, "trades": 0, "win_rate": 0.0},
                "MIDCPNIFTY": {"gross_pnl": 0.0, "net_pnl": 0.0, "brokerage": 0.0, "trades": 0, "win_rate": 0.0}
            }
            for sr in sym_rows:
                s_key = sr["symbol"]
                s_cnt = sr["count"]
                s_wins = sr["wins"]
                symbol_breakdown[s_key] = {
                    "gross_pnl": round(sr["gross_pnl"], 2),
                    "net_pnl": round(sr["net_pnl"], 2),
                    "brokerage": round(sr["brokerage"], 2),
                    "trades": s_cnt,
                    "win_rate": round((s_wins / s_cnt * 100.0), 1) if s_cnt > 0 else 0.0
                }

            # Breakdown by Time-of-Day Session
            cursor.execute("""
                SELECT 
                    COALESCE(session_bucket, 'MORNING') as session,
                    COUNT(*) as count,
                    COALESCE(SUM(realized_pnl_inr), 0.0) as net_pnl,
                    COALESCE(SUM(CASE WHEN realized_pnl_inr > 0 THEN 1 ELSE 0 END), 0) as wins
                FROM bot_trades WHERE status = 'CLOSED'
                GROUP BY session_bucket
            """)
            session_rows = cursor.fetchall()
            session_breakdown = {
                "MORNING": {"net_pnl": 0.0, "trades": 0, "win_rate": 0.0},
                "MIDDAY": {"net_pnl": 0.0, "trades": 0, "win_rate": 0.0},
                "AFTERNOON": {"net_pnl": 0.0, "trades": 0, "win_rate": 0.0}
            }
            for sess in session_rows:
                s_name = sess["session"]
                s_cnt = sess["count"]
                s_wins = sess["wins"]
                if s_name in session_breakdown:
                    session_breakdown[s_name] = {
                        "net_pnl": round(sess["net_pnl"], 2),
                        "trades": s_cnt,
                        "win_rate": round((s_wins / s_cnt * 100.0), 1) if s_cnt > 0 else 0.0
                    }

            # Compute Max Drawdown from closed trade equity curve
            cursor.execute("SELECT realized_pnl_inr FROM bot_trades WHERE status = 'CLOSED' ORDER BY exit_time ASC")
            equity_curve = cursor.fetchall()
            cum_pnl = 0.0
            peak_equity = 0.0
            max_drawdown = 0.0
            for eq in equity_curve:
                cum_pnl += eq[0]
                if cum_pnl > peak_equity:
                    peak_equity = cum_pnl
                dd = peak_equity - cum_pnl
                if dd > max_drawdown:
                    max_drawdown = dd

            total_gross_realized = round(g_row["total_gross_realized_pnl"], 2)
            total_net_realized = round(g_row["total_net_realized_pnl"], 2)
            total_brokerage = round(g_row["total_brokerage"], 2)
            total_gross_unrealized = round(u_row["total_gross_unrealized"], 2)
            total_net_unrealized = round(u_row["total_net_unrealized"], 2)

            return {
                "total_trades": tot,
                "open_trades_count": u_row["open_count"],
                "total_gross_realized_pnl_inr": total_gross_realized,
                "total_net_realized_pnl_inr": total_net_realized,
                "total_realized_pnl_inr": total_net_realized,  # Backward compatible alias
                "total_brokerage_inr": total_brokerage,
                "total_gross_unrealized_pnl_inr": total_gross_unrealized,
                "total_net_unrealized_pnl_inr": total_net_unrealized,
                "total_unrealized_pnl_inr": total_net_unrealized,  # Backward compatible alias
                "gross_combined_pnl_inr": round(total_gross_realized + total_gross_unrealized, 2),
                "net_combined_pnl_inr": round(total_net_realized + total_net_unrealized, 2),
                "overall_win_rate_pct": win_rate,
                "profit_factor": profit_factor,
                "rolling_expectancy_inr": expectancy,
                "max_drawdown_inr": round(max_drawdown, 2),
                "avg_win_inr": avg_win,
                "avg_loss_inr": avg_loss,
                "by_role": role_breakdown,
                "by_symbol": symbol_breakdown,
                "by_session": session_breakdown
            }

    def get_learning_params(self) -> Dict[str, Any]:
        """Returns adaptive learning thresholds and quality gates."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value_json FROM bot_metrics WHERE key = 'learning_params'")
            row = cursor.fetchone()
            if row:
                try:
                    return json.loads(row["value_json"])
                except Exception:
                    pass
            # Default institutional thresholds
            return {
                "buyer_min_tqs": 70.0,
                "seller_min_tqs": 66.0,
                "seller_min_confluence": 53.0,
                "buyer_min_confluence": 68.0,
                "daily_loss_limit_inr": 3500.0,
                "symbol_daily_loss_limit_inr": 1500.0,
                "max_consecutive_losses": 2,
                "cooldown_minutes": 45,
                "min_premium_nifty": 45.0,
                "min_premium_banknifty": 75.0,
                "min_premium_finnifty": 40.0,
                "min_premium_midcpnifty": 25.0,
                "learning_iterations": 0,
                "last_adaptive_update": get_current_ist().isoformat()
            }

    def save_learning_params(self, params: Dict[str, Any]):
        """Persists updated adaptive learning thresholds."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO bot_metrics (key, value_json, updated_at)
                VALUES ('learning_params', ?, ?)
            """, (json.dumps(params), get_current_ist().isoformat()))
            conn.commit()

    def get_trade_by_id(self, trade_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single trade by its unique ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bot_trades WHERE id = ?", (trade_id,))
            row = cursor.fetchone()
            return self._row_to_trade(row) if row else None

    # =========================================================
    # VARIANT D SHADOW LEDGER METHODS (Completely Isolated)
    # =========================================================
    def get_shadow_open_trades(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bot_shadow_trades WHERE status = 'OPEN' ORDER BY entry_time DESC")
            rows = cursor.fetchall()
            return [self._row_to_trade(r) for r in rows]

    def get_shadow_open_trade_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bot_shadow_trades WHERE status = 'OPEN' AND symbol = ? LIMIT 1", (symbol.upper(),))
            row = cursor.fetchone()
            return self._row_to_trade(row) if row else None

    def insert_shadow_trade(self, trade: Dict[str, Any]) -> str:
        trade_id = trade.get("id") or f"shadow_{trade['symbol']}_{int(datetime.now().timestamp())}"
        now_dt = get_current_ist()
        now_iso = now_dt.isoformat()
        trade_date = trade.get("trade_date") or now_dt.strftime("%Y-%m-%d")
        lots = trade.get("lots", 1)
        lot_size = trade.get("lot_size", 75)
        brokerage = float(trade.get("brokerage_inr", 75.0))
        signal_details = trade.get("signal_details", "")
        tqs_breakdown = trade.get("tqs_breakdown", {})
        tqs_json = json.dumps(tqs_breakdown) if isinstance(tqs_breakdown, dict) else str(tqs_breakdown)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO bot_shadow_trades (
                    id, symbol, strategy_type, role, regime, entry_time, status,
                    legs_json, lot_size, entry_net_price, current_net_price,
                    target_price, stop_loss_price, trailing_stop_price,
                    brokerage_inr, tqs_score, tqs_breakdown_json, session_bucket,
                    trade_date, confluence_at_entry, created_at, lots, signal_details,
                    is_alternative, moneyness_tag
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, 'OPEN',
                    ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?
                )
            """, (
                trade_id, trade["symbol"].upper(), trade["strategy_type"], trade["role"].upper(),
                trade.get("regime", ""), trade.get("entry_time") or now_iso,
                json.dumps(trade.get("legs", [])), lot_size, trade["entry_net_price"],
                trade.get("current_net_price", trade["entry_net_price"]), trade["target_price"],
                trade["stop_loss_price"], trade.get("trailing_stop_price", trade["stop_loss_price"]),
                brokerage, trade.get("tqs_score", 0.0), tqs_json,
                trade.get("session_bucket", "MORNING"), trade_date, trade.get("confluence_at_entry", 50.0),
                now_iso, lots, signal_details, int(trade.get("is_alternative", 0)), trade.get("moneyness_tag", "ATM")
            ))
            conn.commit()
            return trade_id

    def update_shadow_trade_mtm(
        self,
        trade_id: str,
        current_net_price: float,
        gross_unrealized_pnl: float,
        net_unrealized_pnl: float,
        trailing_stop: float,
        mfe_pts: float,
        mfe_inr: float,
        mae_pts: float,
        mae_inr: float,
        legs_json: str = None
    ):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if legs_json:
                cursor.execute("""
                    UPDATE bot_shadow_trades
                    SET current_net_price = ?, gross_unrealized_pnl_inr = ?, unrealized_pnl_inr = ?,
                        trailing_stop_price = ?, mfe_pts = MAX(COALESCE(mfe_pts, 0.0), ?),
                        mfe_inr = MAX(COALESCE(mfe_inr, 0.0), ?), mae_pts = MIN(COALESCE(mae_pts, 0.0), ?),
                        mae_inr = MIN(COALESCE(mae_inr, 0.0), ?), legs_json = ?
                    WHERE id = ?
                """, (current_net_price, gross_unrealized_pnl, net_unrealized_pnl, trailing_stop,
                      mfe_pts, mfe_inr, mae_pts, mae_inr, legs_json, trade_id))
            else:
                cursor.execute("""
                    UPDATE bot_shadow_trades
                    SET current_net_price = ?, gross_unrealized_pnl_inr = ?, unrealized_pnl_inr = ?,
                        trailing_stop_price = ?, mfe_pts = MAX(COALESCE(mfe_pts, 0.0), ?),
                        mfe_inr = MAX(COALESCE(mfe_inr, 0.0), ?), mae_pts = MIN(COALESCE(mae_pts, 0.0), ?),
                        mae_inr = MIN(COALESCE(mae_inr, 0.0), ?)
                    WHERE id = ?
                """, (current_net_price, gross_unrealized_pnl, net_unrealized_pnl, trailing_stop,
                      mfe_pts, mfe_inr, mae_pts, mae_inr, trade_id))
            conn.commit()

    def close_shadow_trade(
        self,
        trade_id: str,
        exit_net_price: float,
        gross_realized_pnl: float,
        net_realized_pnl: float,
        exit_reason: str,
        mfe_pts: float = None,
        mfe_inr: float = None,
        mae_pts: float = None,
        mae_inr: float = None
    ):
        now_iso = get_current_ist().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE bot_shadow_trades
                SET status = 'CLOSED', exit_net_price = ?, gross_realized_pnl_inr = ?, realized_pnl_inr = ?,
                    gross_unrealized_pnl_inr = 0.0, unrealized_pnl_inr = 0.0, mfe_pts = MAX(COALESCE(mfe_pts, 0.0), ?),
                    mfe_inr = MAX(COALESCE(mfe_inr, 0.0), ?), mae_pts = MIN(COALESCE(mae_pts, 0.0), ?),
                    mae_inr = MIN(COALESCE(mae_inr, 0.0), ?), exit_reason = ?, exit_time = ?
                WHERE id = ?
            """, (exit_net_price, gross_realized_pnl, net_realized_pnl,
                  mfe_pts or 0.0, mfe_inr or 0.0, mae_pts or 0.0, mae_inr or 0.0, exit_reason, now_iso, trade_id))
            conn.commit()

    def get_shadow_closed_trades(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bot_shadow_trades WHERE status = 'CLOSED' ORDER BY exit_time DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [self._row_to_trade(r) for r in rows]

    def get_shadow_trade_by_id(self, trade_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bot_shadow_trades WHERE id = ?", (trade_id,))
            row = cursor.fetchone()
            return self._row_to_trade(row) if row else None

    def insert_shadow_evaluation(self, record: Dict[str, Any]):
        now_iso = get_current_ist().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO bot_shadow_evaluations (
                    timestamp, trade_date, time_str, symbol, direction, strike, tag,
                    ltp, bid, ask, spread, volume, oi, quote_age_seconds,
                    confluence, tqs_score, p1_signal, p2_strike, p3_liquidity,
                    p4_momentum, p5_risk_reward, required_outlay, available_capital,
                    decision, rejection_reason
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?
                )
            """, (
                record.get("timestamp") or now_iso, record.get("trade_date", ""),
                record.get("time_str", ""), record.get("symbol", ""),
                record.get("direction", ""), float(record.get("strike", 0.0)),
                record.get("tag", "ATM"), float(record.get("ltp", 0.0)),
                float(record.get("bid", 0.0)), float(record.get("ask", 0.0)),
                float(record.get("spread", 0.0)), int(record.get("volume", 0)),
                int(record.get("oi", 0)), float(record.get("quote_age_seconds", 0.0)),
                float(record.get("confluence", 50.0)), float(record.get("tqs_score", 0.0)),
                float(record.get("p1_signal", 0.0)), float(record.get("p2_strike", 0.0)),
                float(record.get("p3_liquidity", 0.0)), float(record.get("p4_momentum", 0.0)),
                float(record.get("p5_risk_reward", 0.0)), float(record.get("required_outlay", 0.0)),
                float(record.get("available_capital", 30000.0)), record.get("decision", "REJECTED"),
                record.get("rejection_reason")
            ))
            conn.commit()

    def get_shadow_evaluations(self, limit: int = 500) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM bot_shadow_evaluations ORDER BY id DESC LIMIT ?", (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def _row_to_trade(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        if "legs_json" in d:
            try:
                d["legs"] = json.loads(d["legs_json"])
            except Exception:
                d["legs"] = []
        if "tqs_breakdown_json" in d and d["tqs_breakdown_json"]:
            try:
                d["tqs_breakdown"] = json.loads(d["tqs_breakdown_json"])
            except Exception:
                d["tqs_breakdown"] = {}
        return d


tracker_storage = TrackerStorage()

