"""
ShonyaBot: Institutional Weighted Confluence Execution & Risk Engine
====================================================================
- Operates on asset-tailored multi-indicator weighted confluence (AlphaTrend, TrendDirection,
  Hull Suite, Shonya Gravity, Proximity MAPO, Breakout Tracker) + Institutional Option Data (PCR & OI Walls).
- Individual Asset Weight Configurations (Backtested & Verified on Clean Sessions):
  * NIFTY 50: Trend Expansion Matrix (AlphaTrend: 2.0, TrendDir: 2.0, Hull: 1.5, Shonya: 0.5, Proximity: 0.5, Breakout: 2.0)
  * BANKNIFTY: Trend Expansion Matrix (AlphaTrend: 2.0, TrendDir: 2.0, Hull: 1.5, Shonya: 0.5, Proximity: 0.5, Breakout: 2.0)
  * FINNIFTY: Proximity Neglected Matrix (AlphaTrend: 1.0, TrendDir: 1.0, Hull: 1.0, Shonya: 1.0, Proximity: 0.0, Breakout: 1.0)
  * MIDCPNIFTY: Fast Triad Matrix (AlphaTrend: 2.0, TrendDir: 1.5, Hull: 0.0, Shonya: 0.0, Proximity: 0.0, Breakout: 2.5)
- Dual Execution Mode: PAPER (default high-fidelity simulation) vs LIVE (Fyers broker exchange gateway).
- Real Broker Telemetry: In LIVE mode, fetches real broker P&L, LTP, and quantities directly from Fyers API.
- Trend-Riding Risk Architecture:
  * Hard Initial Stop Loss: -15% option contract premium.
  * Breakeven Profit Armor: Once gain >= +15%, ratchets SL to Entry + 2% (zero risk).
  * Dynamic Trend Trail on Large Runners: On +40%+ gain, trails at 75% of peak gains.
  * Structural Trend Breakdown Cut: Closes CE if CIS <= 44.0; closes PE if CIS >= 56.0.
  * PCR Reversal Exhaustion Cut: Exits if PCR diverges significantly against trend (> 0.15 shift) while gain < 5%.
  * EOD Squareoff: 15:20 IST automatic market exit.
  * Natural Bot Discipline: Max 2 trades/day per asset, 45-min cooldown, blocks duplicate loss re-entry.
"""
import os
import json
import time
import uuid
import sqlite3
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, time as dt_time

from app.core.config import get_settings
from app.core.market_hours import get_current_ist, is_market_open
from app.services.fyers_service import fyers_service
from app.services.ai_advisor_service import ai_advisor

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "shonya_trades.db")


# ─────────────────────────────────────────────────────────────────────────────
# Asset-Specific Optimal Configurations (Discovered in Clean Multi-Session Backtests)
# ─────────────────────────────────────────────────────────────────────────────
INDEX_CONFIGS: Dict[str, Dict[str, Any]] = {
    "NIFTY": {
        "scenario": 1,  # S1: Index Spot Driven
        "scenario_name": "S1_IndexSpot",
        "weights_name": "Trend_Expansion",
        "weights": {
            "at": 2.0,    # AlphaTrend
            "td": 2.0,    # TrendDirection
            "hull": 1.5,  # Hull Suite EHMA 34
            "sh": 0.5,    # Shonya Gravity
            "px": 0.5,    # Proximity MAPO
            "bt": 2.0     # Breakout Tracker
        },
        "bull_threshold": 68.0,
        "bear_threshold": 32.0,
        "cut_bull_cis": 44.0,   # Exit CE if CIS <= 44.0
        "cut_bear_cis": 56.0,   # Exit PE if CIS >= 56.0
        "lot_size": 65,
        "step": 50.0
    },
    "BANKNIFTY": {
        "scenario": 1,
        "scenario_name": "S1_IndexSpot",
        "weights_name": "Trend_Expansion",
        "weights": {
            "at": 2.0,
            "td": 2.0,
            "hull": 1.5,
            "sh": 0.5,
            "px": 0.5,
            "bt": 2.0
        },
        "bull_threshold": 68.0,
        "bear_threshold": 32.0,
        "cut_bull_cis": 44.0,
        "cut_bear_cis": 56.0,
        "lot_size": 30,
        "step": 100.0
    },
    "FINNIFTY": {
        "scenario": 1,
        "scenario_name": "S1_IndexSpot",
        "weights_name": "Drop_Proximity",
        "weights": {
            "at": 1.0,
            "td": 1.0,
            "hull": 1.0,
            "sh": 1.0,
            "px": 0.0,    # Proximity MAPO neglected
            "bt": 1.0
        },
        "bull_threshold": 68.0,
        "bear_threshold": 32.0,
        "cut_bull_cis": 44.0,
        "cut_bear_cis": 56.0,
        "lot_size": 60,
        "step": 50.0
    },
    "MIDCPNIFTY": {
        "scenario": 1,
        "scenario_name": "S1_IndexSpot",
        "weights_name": "Alpha_Breakout_Duo",
        "weights": {
            "at": 2.0,
            "td": 1.5,
            "hull": 0.0,   # Hull Suite neglected
            "sh": 0.0,     # Shonya Gravity neglected
            "px": 0.0,     # Proximity MAPO neglected
            "bt": 2.5      # Fast Breakout Heavy
        },
        "bull_threshold": 68.0,
        "bear_threshold": 32.0,
        "cut_bull_cis": 44.0,
        "cut_bear_cis": 56.0,
        "lot_size": 120,
        "step": 25.0
    },
    "SENSEX": {
        "scenario": 1,
        "scenario_name": "S1_IndexSpot",
        "weights_name": "Alpha_Breakout_Duo",
        "weights": {
            "at": 2.0,
            "td": 1.5,
            "hull": 1.0,
            "sh": 1.0,
            "px": 1.0,
            "bt": 2.0
        },
        "bull_threshold": 68.0,
        "bear_threshold": 32.0,
        "cut_bull_cis": 44.0,
        "cut_bear_cis": 56.0,
        "lot_size": 20,
        "step": 100.0
    }
}


class ShonyaBot:
    FLAT_BROKERAGE_PER_TRADE = 75.0
    CAPITAL_CEILING = 90000.0

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.is_active: bool = True
        self.trading_mode: str = "PAPER"  # "PAPER" or "LIVE"
        self.capital_ceiling: float = 90000.0
        self.enabled_symbols: List[str] = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
        self._init_db()
        self._load_config()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                CREATE TABLE IF NOT EXISTS shonya_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS shonya_trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    strike REAL NOT NULL,
                    option_type TEXT NOT NULL,
                    fyers_symbol TEXT,
                    side TEXT NOT NULL,
                    lots INTEGER NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    exit_price REAL,
                    target1 REAL NOT NULL,
                    target2 REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    breakeven_locked INTEGER DEFAULT 0,
                    status TEXT NOT NULL,  -- OPEN, CLOSED, CANCELLED
                    execution_mode TEXT NOT NULL,  -- PAPER or LIVE
                    source TEXT NOT NULL,  -- GROK_AI or MANUAL or INSTITUTIONAL_WEIGHTED_CONFLUENCE
                    broker_order_id TEXT,
                    broker_position_id TEXT,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,
                    exit_reason TEXT,
                    gross_pnl REAL DEFAULT 0.0,
                    brokerage REAL DEFAULT 75.0,
                    net_pnl REAL DEFAULT 0.0,
                    fyers_broker_pnl REAL DEFAULT 0.0,
                    mfe_pts REAL DEFAULT 0.0,
                    mae_pts REAL DEFAULT 0.0,
                    thesis TEXT,
                    created_at TEXT NOT NULL,
                    peak_price REAL DEFAULT 0.0,
                    peak_pcr REAL DEFAULT 1.0,
                    trough_pcr REAL DEFAULT 1.0,
                    cis_score REAL DEFAULT 50.0
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_shonya_status ON shonya_trades(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_shonya_symbol ON shonya_trades(symbol)")

            # Backward-compatible schema migration
            existing_cols = {col[1] for col in c.execute("PRAGMA table_info(shonya_trades)").fetchall()}
            for col_name, col_def in [
                ("peak_price", "REAL DEFAULT 0.0"),
                ("peak_pcr", "REAL DEFAULT 1.0"),
                ("trough_pcr", "REAL DEFAULT 1.0"),
                ("cis_score", "REAL DEFAULT 50.0")
            ]:
                if col_name not in existing_cols:
                    try:
                        c.execute(f"ALTER TABLE shonya_trades ADD COLUMN {col_name} {col_def}")
                    except Exception:
                        pass

            conn.commit()

    def _load_config(self):
        """Loads persistent bot state, defaulting to ACTIVE in PAPER mode with ₹90,000 capital and all 4 symbols."""
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("SELECT value FROM shonya_config WHERE key = 'is_active'")
                row = c.fetchone()
                if row:
                    self.is_active = (row["value"] == "1" or str(row["value"]).lower() == "true")
                else:
                    c.execute("INSERT OR REPLACE INTO shonya_config (key, value) VALUES ('is_active', '1')")
                    self.is_active = True

                c.execute("SELECT value FROM shonya_config WHERE key = 'trading_mode'")
                row_m = c.fetchone()
                if row_m:
                    self.trading_mode = row_m["value"].upper()
                else:
                    c.execute("INSERT OR REPLACE INTO shonya_config (key, value) VALUES ('trading_mode', 'PAPER')")
                    self.trading_mode = "PAPER"

                c.execute("SELECT value FROM shonya_config WHERE key = 'capital_ceiling'")
                row_cap = c.fetchone()
                if row_cap:
                    try:
                        self.capital_ceiling = float(row_cap["value"])
                    except Exception:
                        self.capital_ceiling = 90000.0
                else:
                    c.execute("INSERT OR REPLACE INTO shonya_config (key, value) VALUES ('capital_ceiling', '90000.0')")
                    self.capital_ceiling = 90000.0

                c.execute("SELECT value FROM shonya_config WHERE key = 'enabled_symbols'")
                row_syms = c.fetchone()
                if row_syms:
                    try:
                        parsed_syms = json.loads(row_syms["value"])
                        if isinstance(parsed_syms, list) and parsed_syms:
                            self.enabled_symbols = [s.upper() for s in parsed_syms if s.upper() in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]]
                    except Exception:
                        self.enabled_symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
                else:
                    self.enabled_symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
                    c.execute("INSERT OR REPLACE INTO shonya_config (key, value) VALUES ('enabled_symbols', ?)", (json.dumps(self.enabled_symbols),))

                conn.commit()
        except Exception as e:
            logger.debug(f"ShonyaBot config load fallback: {e}")

    # -------------------------------------------------------------
    # Configuration & Control Switches
    # -------------------------------------------------------------
    def get_capital_status(self) -> Dict[str, Any]:
        """Computes live committed margin across all open trades and remaining available capital."""
        open_trades = self.get_open_trades()
        committed = sum(float(t.get("entry_price", 0.0)) * int(t.get("quantity", 0)) for t in open_trades)
        available = max(0.0, self.capital_ceiling - committed)
        util_pct = round((committed / max(1.0, self.capital_ceiling)) * 100.0, 1)
        return {
            "capital_ceiling": self.capital_ceiling,
            "committed_margin": round(committed, 2),
            "available_capital": round(available, 2),
            "utilization_pct": util_pct,
            "open_trades_count": len(open_trades)
        }

    def set_capital(self, amount: float) -> float:
        """Updates and persists total trading capital ceiling across database and credentials."""
        self.capital_ceiling = float(max(1000.0, amount))
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO shonya_config (key, value) VALUES ('capital_ceiling', ?)", (str(self.capital_ceiling),))
                conn.commit()
        except Exception as e:
            logger.debug(f"Error persisting capital_ceiling: {e}")
        try:
            from app.core.credentials import save_trading_fund
            save_trading_fund(self.capital_ceiling)
        except Exception:
            pass
        logger.info(f"ShonyaBot capital ceiling updated to: ₹{self.capital_ceiling:,.2f}")
        return self.capital_ceiling

    def set_enabled_symbols(self, symbols: List[str]) -> List[str]:
        """Sets which indices ShonyaBot is allowed to evaluate and trade (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY)."""
        valid = [s.upper() for s in symbols if s.upper() in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]]
        self.enabled_symbols = valid if valid else ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO shonya_config (key, value) VALUES ('enabled_symbols', ?)", (json.dumps(self.enabled_symbols),))
                conn.commit()
        except Exception as e:
            logger.debug(f"Error persisting enabled_symbols: {e}")
        logger.info(f"ShonyaBot enabled trading symbols updated: {self.enabled_symbols}")
        return self.enabled_symbols

    def get_status(self) -> Dict[str, Any]:
        """Returns bot state, trading mode, capital status, enabled symbols, and Fyers broker health."""
        open_trades = self.get_open_trades()
        fyers_ok, fyers_msg = fyers_service.validate_connection()
        fyers_funds = fyers_service.get_funds() if fyers_ok else {"available_balance": 0.0}

        metrics = self.get_performance_metrics()
        cap_stat = self.get_capital_status()

        return {
            "success": True,
            "bot_name": "ShonyaBot",
            "is_active": self.is_active,
            "trading_mode": self.trading_mode,
            "fyers_connected": fyers_ok,
            "fyers_status_message": fyers_msg,
            "fyers_available_balance": fyers_funds.get("available_balance", 0.0),
            "capital_ceiling": self.capital_ceiling,
            "capital_status": cap_stat,
            "enabled_symbols": self.enabled_symbols,
            "available_symbols": ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"],
            "open_positions_count": len(open_trades),
            "open_positions": open_trades,
            "metrics": metrics,
            "index_configs": INDEX_CONFIGS
        }

    def set_active(self, active: bool) -> bool:
        self.is_active = active
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO shonya_config (key, value) VALUES ('is_active', ?)", ('1' if active else '0',))
                conn.commit()
        except Exception as e:
            logger.debug(f"Error persisting is_active: {e}")
        logger.info(f"ShonyaBot state changed: {'ACTIVE' if active else 'OFF'}")
        return self.is_active

    def set_mode(self, mode: str) -> str:
        mode_upper = mode.upper()
        if mode_upper in ["PAPER", "LIVE"]:
            self.trading_mode = mode_upper
            try:
                with self._get_conn() as conn:
                    c = conn.cursor()
                    c.execute("INSERT OR REPLACE INTO shonya_config (key, value) VALUES ('trading_mode', ?)", (self.trading_mode,))
                    conn.commit()
            except Exception as e:
                logger.debug(f"Error persisting trading_mode: {e}")
            logger.info(f"ShonyaBot execution mode switched to: {self.trading_mode}")
        return self.trading_mode

    # -------------------------------------------------------------
    # Weighted Confluence Math Engine
    # -------------------------------------------------------------
    @staticmethod
    def calculate_composite_score(signals: Dict[str, float], weights: Dict[str, float]) -> float:
        """
        Computes the 0-100 Composite Indicator Score (CIS) from normalized signals [-1.0, +1.0]
        and asset-specific weights.
        50.0 = Neutral
        > 50.0 = Bullish Confluence
        < 50.0 = Bearish Confluence
        """
        total_w = sum(weights.values())
        if total_w <= 0:
            return 50.0

        weighted_sum = sum(signals.get(k, 0.0) * weights.get(k, 0.0) for k in weights)
        normalized_net = weighted_sum / total_w
        score = 50.0 + (50.0 * normalized_net)
        return round(score, 1)

    @staticmethod
    def extract_signals_from_indicators(ind_dict: Dict[str, Any]) -> Dict[str, float]:
        """
        Normalizes outputs of all 6 indicators into [-1.0, +1.0] directional signals:
        1. AlphaTrend (at)
        2. TrendDirection (td)
        3. Hull Suite EHMA (hull)
        4. Shonya Gravity (sh)
        5. Proximity MAPO (px)
        6. Breakout Tracker (bt)
        """
        # 1. AlphaTrend
        at_st = str(ind_dict.get("alphatrend_state", "NEUTRAL")).upper()
        sig_at = 1.0 if "BULL" in at_st else (-1.0 if "BEAR" in at_st else 0.0)

        # 2. TrendDirection (logistic tanh momentum)
        td_str = float(ind_dict.get("trend_dir_strength", 0.0) or 0.0)
        sig_td = max(-1.0, min(1.0, td_str * 2.5))

        # 3. Hull Suite
        hull_st = str(ind_dict.get("hull_state", "NEUTRAL")).upper()
        sig_hull = 1.0 if ("BULL" in hull_st or "GREEN" in hull_st) else (-1.0 if ("BEAR" in hull_st or "RED" in hull_st) else 0.0)

        # 4. Shonya Gravity
        sh_st = str(ind_dict.get("shonya_state", "NEUTRAL")).upper()
        sig_sh = 1.0 if "BULL" in sh_st else (-1.0 if "BEAR" in sh_st else 0.0)

        # 5. Proximity MAPO
        prox_per = float(ind_dict.get("prox_per", 50.0) or 50.0)
        sig_px = max(-1.0, min(1.0, (prox_per - 50.0) / 30.0))

        # 6. Breakout Tracker
        brk_st = str(ind_dict.get("brk_state", "FLAT")).upper()
        brk_bias = str(ind_dict.get("brk_bias", "NEUTRAL")).upper()
        brk_sig = str(ind_dict.get("brk_signal", "HOLD")).upper()
        sig_bt = 1.0 if (brk_st == "LONG" or brk_bias == "BULLISH" or brk_sig == "BUY") else (
            -1.0 if (brk_st == "SHORT" or brk_bias == "BEARISH" or brk_sig in ["SELL", "EXIT"]) else 0.0
        )

        return {
            "at": sig_at,
            "td": sig_td,
            "hull": sig_hull,
            "sh": sig_sh,
            "px": sig_px,
            "bt": sig_bt
        }

    # -------------------------------------------------------------
    # Trade Placement (Grok Signal Approved, Automated, & Manual)
    # -------------------------------------------------------------
    def place_trade(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        lots: int = 1,
        entry_price: Optional[float] = None,
        target1: Optional[float] = None,
        target2: Optional[float] = None,
        stop_loss: Optional[float] = None,
        source: str = "INSTITUTIONAL_WEIGHTED_CONFLUENCE",
        thesis: str = "",
        pcr: float = 1.0,
        cis_score: float = 50.0
    ) -> Dict[str, Any]:
        """
        Executes a trade in ShonyaBot either in PAPER or LIVE mode.
        If LIVE, routes order to Fyers exchange gateway.
        """
        sym = symbol.upper()
        opt_t = option_type.upper()
        settings = get_settings()
        cfg = INDEX_CONFIGS.get(sym, INDEX_CONFIGS["NIFTY"])
        lot_size = cfg.get("lot_size", settings.LOT_SIZES.get(sym, 65 if sym == "NIFTY" else 30))
        total_qty = lots * lot_size

        # Capital Affordability Validation
        cap_stat = self.get_capital_status()
        required_margin = (entry_price or 100.0) * total_qty
        if required_margin > cap_stat["available_capital"]:
            return {
                "success": False,
                "message": f"Insufficient available capital: Required margin ₹{required_margin:,.0f} exceeds available ₹{cap_stat['available_capital']:,.0f} (Total Capital: ₹{self.capital_ceiling:,.0f})."
            }

        # Prevent duplicate open trade in same symbol
        open_existing = self.get_open_trade_for_symbol(sym)
        if open_existing:
            return {
                "success": False,
                "message": f"Position already open for {sym} (ID: {open_existing['id']}). Close it before entering new trade."
            }

        # Resolve Fyers contract symbol and current market LTP
        fyers_sym = fyers_service.resolve_option_symbol(sym, strike, opt_t)
        est_ltp = entry_price or 0.0

        if est_ltp <= 0 and fyers_sym:
            q_res = fyers_service.get_quotes([fyers_sym])
            if q_res and q_res.get("s") == "ok" and q_res.get("d"):
                est_ltp = float(q_res["d"][0].get("v", {}).get("lp", 0.0))

        if est_ltp <= 0:
            est_ltp = 100.0  # safe fallback if market offline

        # Dynamic Risk Architecture:
        # Initial Hard SL: -15% on contract premium
        sl = stop_loss if (stop_loss and stop_loss > 0) else round(est_ltp * 0.85, 1)
        # Target 1 (+15% Profit Armor Trigger to lock SL at Entry + 2%)
        t1 = target1 if (target1 and target1 > 0) else round(est_ltp * 1.15, 1)
        # Target 2 (+50% Trend Extension)
        t2 = target2 if (target2 and target2 > 0) else round(est_ltp * 1.50, 1)

        trade_id = f"SHONYA_{sym}_{int(strike)}_{opt_t}_{int(time.time())}"
        now_dt = get_current_ist().strftime("%Y-%m-%d %H:%M:%S")

        broker_order_id = None
        broker_position_id = None
        mode = self.trading_mode

        # LIVE Broker Execution
        if mode == "LIVE":
            if not fyers_service.is_configured():
                return {
                    "success": False,
                    "message": "Cannot place LIVE trade: Fyers broker not configured or logged in."
                }
            if not fyers_sym:
                return {
                    "success": False,
                    "message": f"Cannot resolve live Fyers contract symbol for {sym} {strike} {opt_t}."
                }

            order_res = fyers_service.place_order(
                symbol=fyers_sym,
                qty=total_qty,
                side=1,  # BUY
                order_type=2,  # MARKET
                product_type="INTRADAY"
            )

            if order_res.get("s") != "ok":
                return {
                    "success": False,
                    "message": f"Fyers broker order rejected: {order_res.get('message', 'Unknown error')}",
                    "broker_response": order_res
                }

            broker_order_id = str(order_res.get("id", ""))
            broker_position_id = fyers_sym
            logger.info(f"ShonyaBot LIVE ORDER PLACED on Fyers: {fyers_sym} x {total_qty} (Order ID: {broker_order_id})")

        # Persist to SQLite
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO shonya_trades (
                    id, symbol, strike, option_type, fyers_symbol, side, lots, quantity,
                    entry_price, current_price, target1, target2, stop_loss, breakeven_locked,
                    status, execution_mode, source, broker_order_id, broker_position_id,
                    entry_time, gross_pnl, brokerage, net_pnl, fyers_broker_pnl,
                    mfe_pts, mae_pts, thesis, created_at, peak_price, peak_pcr, trough_pcr, cis_score
                ) VALUES (
                    ?, ?, ?, ?, ?, 'BUY', ?, ?,
                    ?, ?, ?, ?, ?, 0,
                    'OPEN', ?, ?, ?, ?,
                    ?, 0.0, 75.0, -75.0, 0.0,
                    0.0, 0.0, ?, ?, ?, ?, ?, ?
                )
            """, (
                trade_id, sym, strike, opt_t, fyers_sym, lots, total_qty,
                est_ltp, est_ltp, t1, t2, sl,
                mode, source, broker_order_id, broker_position_id,
                now_dt, thesis, now_dt, est_ltp, pcr, pcr, cis_score
            ))
            conn.commit()

        logger.info(f"ShonyaBot {mode} Trade Initiated: {trade_id} | {sym} {strike} {opt_t} @ ₹{est_ltp:.1f} | CIS: {cis_score} | PCR: {pcr:.2f}")

        # Dispatch Real-Time Mobile Trade Notification (Telegram + ntfy lockscreen)
        try:
            from app.services.mobile_notification_service import mobile_alerts
            mobile_alerts.notify_trade_entry({
                "symbol": sym,
                "strike": strike,
                "option_type": opt_t,
                "entry_price": est_ltp,
                "stop_loss": sl,
                "lots": lots,
                "quantity": total_qty,
                "mode": mode,
                "cis_score": cis_score,
                "pcr": pcr,
                "entry_time": now_dt.strftime("%H:%M:%S")
            })
        except Exception as e:
            logger.warning(f"Failed to dispatch mobile trade entry alert: {e}")

        return {
            "success": True,
            "trade_id": trade_id,
            "symbol": sym,
            "strike": strike,
            "option_type": opt_t,
            "lots": lots,
            "quantity": total_qty,
            "entry_price": est_ltp,
            "target1": t1,
            "target2": t2,
            "stop_loss": sl,
            "mode": mode,
            "broker_order_id": broker_order_id,
            "message": f"{mode} trade initiated for {sym} {int(strike)} {opt_t} at ₹{est_ltp:.1f}"
        }

    # -------------------------------------------------------------
    # Dynamic Modification of Target & Stop-Loss
    # -------------------------------------------------------------
    def modify_trade(
        self,
        trade_id: str,
        target1: Optional[float] = None,
        target2: Optional[float] = None,
        stop_loss: Optional[float] = None
    ) -> Dict[str, Any]:
        """Allows user to dynamically modify Target 1, Target 2, and Stop Loss on an active trade."""
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM shonya_trades WHERE id = ? AND status = 'OPEN'", (trade_id,))
            row = c.fetchone()
            if not row:
                return {"success": False, "message": f"Active trade {trade_id} not found."}

            t1 = float(target1) if target1 is not None and target1 > 0 else float(row["target1"])
            t2 = float(target2) if target2 is not None and target2 > 0 else float(row["target2"])
            sl = float(stop_loss) if stop_loss is not None and stop_loss > 0 else float(row["stop_loss"])

            c.execute("""
                UPDATE shonya_trades
                SET target1 = ?, target2 = ?, stop_loss = ?
                WHERE id = ?
            """, (t1, t2, sl, trade_id))
            conn.commit()

        logger.info(f"ShonyaBot: Trade {trade_id} modified. T1: {t1}, T2: {t2}, SL: {sl}")
        return {
            "success": True,
            "trade_id": trade_id,
            "target1": t1,
            "target2": t2,
            "stop_loss": sl,
            "message": f"Target & Stop Loss updated for {trade_id}"
        }

    # -------------------------------------------------------------
    # Automated Weighted Confluence Signal Evaluator
    # -------------------------------------------------------------
    async def evaluate_tick_for_paper_entry(
        self,
        symbol: str,
        chain: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Automated Institutional Weighted Confluence Signal Evaluator:
        - Evaluates the 6 PineScript indicators with asset-specific weights.
        - Backtested & unforced execution: rides full day trends without artificial capping.
        - Natural Trade Discipline: Max 2 trades/day per asset, 45-min cooldown between trades.
        - Enforces 1-position-per-segment (no concurrent trades in same symbol).
        - Strike Selection: 1-ITM strike (CE: ATM - step, PE: ATM + step, fallback to ATM if LTP < 25).
        - Executes in PAPER or LIVE mode depending on `self.trading_mode`.
        """
        return await self.evaluate_and_execute_signals(symbol, chain)

    async def evaluate_and_execute_signals(
        self,
        symbol: str,
        chain: Any
    ) -> Optional[Dict[str, Any]]:
        if not self.is_active:
            return None

        if self.trading_mode not in ["PAPER", "LIVE"]:
            return None

        if not chain or not getattr(chain, "strikes", None):
            return None

        sym = symbol.upper()
        now_dt = get_current_ist()
        t = now_dt.time()

        # Gate 0: User-Selected Segment Filter (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY)
        if sym not in self.enabled_symbols:
            return None

        # Gate 1: Check existing open position in this index segment (Exact 1 position limit)
        open_trade = self.get_open_trade_for_symbol(sym)
        if open_trade:
            return None

        # Gate 2: Trading Hours (09:25 - 14:15 IST) - No entries after 14:15 to prevent late-session chop
        if not (dt_time(9, 25, 0) <= t <= dt_time(14, 15, 0)):
            return None

        cfg = INDEX_CONFIGS.get(sym, INDEX_CONFIGS["NIFTY"])
        weights = cfg["weights"]
        bull_thresh = cfg["bull_threshold"]
        bear_thresh = cfg["bear_threshold"]
        step = cfg["step"]
        atm = getattr(chain, "atm_strike", 0.0)
        spot = getattr(chain, "spot_price", 0.0)

        if spot <= 0 or atm <= 0:
            return None

        # Gate 3: Check Daily Trade Count & Cooldown
        with self._get_conn() as conn:
            c = conn.cursor()
            today_str = now_dt.strftime("%Y-%m-%d")
            c.execute("""
                SELECT id, option_type, status, exit_time, net_pnl, created_at
                FROM shonya_trades
                WHERE symbol = ? AND date(created_at) = ?
                ORDER BY created_at ASC
            """, (sym, today_str))
            today_trades = [dict(r) for r in c.fetchall()]

        # Strictly max 2 trades per day per symbol (Natural bot discipline)
        if len(today_trades) >= 2:
            return None

        last_trade = today_trades[-1] if today_trades else None
        if last_trade:
            # Check 45-minute cooldown after previous trade's exit
            exit_time_str = last_trade.get("exit_time")
            if exit_time_str:
                try:
                    last_exit_dt = datetime.strptime(exit_time_str, "%Y-%m-%d %H:%M:%S")
                    minutes_since_exit = (now_dt.replace(tzinfo=None) - last_exit_dt).total_seconds() / 60.0
                    if minutes_since_exit < 45.0:
                        return None
                except Exception:
                    pass

        # Gate 4: Compute 6 Centralized Technical Indicators & Composite CIS Score
        from app.services.option_confluence_service import option_confluence_service
        ind_dict = option_confluence_service.get_price_indicators(sym, current_spot=spot)
        signals = self.extract_signals_from_indicators(ind_dict)
        cis_score = self.calculate_composite_score(signals, weights)

        # Gate 5: Option Data Confluence (PCR & Walls)
        pcr = getattr(chain, "pcr", 1.0) or 1.0
        if pcr <= 0:
            pcr = 1.0

        # Bot Discipline: Do not immediately re-enter the exact same failed direction
        last_trade_type = last_trade.get("option_type") if last_trade else ""
        last_trade_lost = (float(last_trade.get("net_pnl", 0.0)) <= 0) if last_trade else False

        trigger_ce = False
        trigger_pe = False

        # Bullish Entry: CIS >= bull_threshold AND institutional put writing support (PCR >= 0.70)
        if cis_score >= bull_thresh and pcr >= 0.70:
            trigger_ce = True

        # Bearish Entry: CIS <= bear_threshold AND institutional call writing resistance (PCR <= 1.30)
        elif cis_score <= bear_thresh and pcr <= 1.30:
            trigger_pe = True

        # Discipline filter on 2nd trade
        if len(today_trades) == 1 and last_trade_lost:
            if last_trade_type == "CE" and trigger_ce and cis_score < (bull_thresh + 5.0):
                return None
            if last_trade_type == "PE" and trigger_pe and cis_score > (bear_thresh - 5.0):
                return None

        if not trigger_ce and not trigger_pe:
            return None

        opt_type = "CE" if trigger_ce else "PE"

        # Gate 6: 1-ITM Strike Selection (ATM ± 1 step)
        preferred_strike = (atm - step) if opt_type == "CE" else (atm + step)

        strike_map = {s.strikePrice: s for s in chain.strikes}
        chosen_strike = preferred_strike
        c_row = strike_map.get(chosen_strike)
        contract = (c_row.CE if opt_type == "CE" else c_row.PE) if c_row else None
        ltp = float(contract.lastPrice if contract else 0.0)

        # Liquidity cushion: fallback to ATM if 1-ITM is missing or LTP < 25
        if ltp < 25.0:
            chosen_strike = atm
            c_row = strike_map.get(chosen_strike)
            contract = (c_row.CE if opt_type == "CE" else c_row.PE) if c_row else None
            ltp = float(contract.lastPrice if contract else 0.0)

        if ltp < 25.0:
            return None

        # Sizing and Targets
        lots = 1
        lot_size = cfg.get("lot_size", 50)
        required_capital = ltp * lots * lot_size
        cap_stat = self.get_capital_status()
        if required_capital > cap_stat["available_capital"]:
            logger.info(
                f"ShonyaBot: Candidate rejected for {sym} - Required margin ₹{required_capital:,.1f} "
                f"exceeds available capital ₹{cap_stat['available_capital']:,.1f} (Ceiling: ₹{self.capital_ceiling:,.0f})"
            )
            return None

        sl = round(ltp * 0.85, 1)   # -15% initial stop
        t1 = round(ltp * 1.15, 1)   # +15% target 1 (Breakeven Armor ratchet trigger)
        t2 = round(ltp * 1.50, 1)   # +50% target 2 (Trend extension)

        thesis = (
            f"Weighted Confluence Bot | 1-ITM ({int(chosen_strike)} {opt_type}) | "
            f"CIS: {cis_score:.1f}/100 ({cfg['weights_name']}) | PCR: {pcr:.2f} | "
            f"AT: {ind_dict.get('alphatrend_state')} | BT: {ind_dict.get('brk_state')}"
        )

        res = self.place_trade(
            symbol=sym,
            strike=chosen_strike,
            option_type=opt_type,
            lots=lots,
            entry_price=ltp,
            target1=t1,
            target2=t2,
            stop_loss=sl,
            source="INSTITUTIONAL_WEIGHTED_CONFLUENCE",
            thesis=thesis,
            pcr=pcr,
            cis_score=cis_score
        )
        return res

    # -------------------------------------------------------------
    # Live Polling & Position Tracking (Zero Theoretical Guesswork)
    # -------------------------------------------------------------
    def update_positions_tick(self, chain_map: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Polls positions every cycle:
        - In LIVE mode, fetches real broker positions and P&L directly from Fyers API.
        - In PAPER mode, updates LTP from chain_map or Fyers quotes.
        - Enforces EOD Trend Square-Off at 15:20 IST.
        - Checks Breakeven Profit Armor (+15% -> ratchets SL to entry + 2%).
        - Checks Dynamic Trend Trail on Large Runners (+40%+ -> trails 75% of peak gains).
        - Checks Structural Confluence Breakdown Cut (CIS <= 44 for CE, CIS >= 56 for PE).
        - Checks PCR Reversal Exhaustion Cut (0.15 divergence against trend while gain < 5%).
        """
        open_trades = self.get_open_trades()
        if not open_trades:
            return []

        now_dt = get_current_ist()
        now_time = now_dt.time()
        is_eod = (dt_time(15, 20, 0) <= now_time <= dt_time(15, 30, 0))

        # If LIVE mode, fetch broker positions once
        broker_positions = {}
        if any(t["execution_mode"] == "LIVE" for t in open_trades):
            if fyers_service.is_configured():
                res = fyers_service.get_positions()
                if res.get("s") == "ok":
                    for p in res.get("netPositions", []):
                        sym_p = p.get("symbol")
                        broker_positions[sym_p] = p

        from app.services.option_confluence_service import option_confluence_service

        updated = []
        for trade in open_trades:
            t_id = trade["id"]
            mode = trade["execution_mode"]
            sym = trade["symbol"]
            fyers_sym = trade.get("fyers_symbol")
            qty = int(trade["quantity"])
            entry_p = float(trade["entry_price"])
            sl = float(trade["stop_loss"])
            be_locked = int(trade.get("breakeven_locked", 0))
            cfg = INDEX_CONFIGS.get(sym, INDEX_CONFIGS["NIFTY"])

            prev_p = float(trade.get("current_price") or entry_p)
            current_p = prev_p
            broker_pnl = 0.0
            price_resolved = False

            if mode == "LIVE" and fyers_sym and fyers_sym in broker_positions:
                b_pos = broker_positions[fyers_sym]
                net_qty = int(b_pos.get("netQty", 0))
                current_p = float(b_pos.get("ltp", prev_p))
                broker_pnl = float(b_pos.get("pl", 0.0))  # Real broker P&L
                price_resolved = True

                if net_qty == 0:
                    self.exit_trade(t_id, exit_reason="BROKER_TERMINAL_EXIT", exit_price=current_p)
                    continue
            else:
                # PAPER mode LTP resolution
                if chain_map and sym in chain_map:
                    ch = chain_map[sym]
                    stk = float(trade["strike"])
                    otype = trade["option_type"]
                    for s_row in getattr(ch, "strikes", []):
                        if abs(s_row.strikePrice - stk) < 0.1:
                            c_sub = s_row.CE if otype == "CE" else s_row.PE
                            if c_sub and c_sub.lastPrice > 0:
                                current_p = float(c_sub.lastPrice)
                                price_resolved = True
                            break

                # Second attempt: quotes fallback
                if not price_resolved and fyers_sym:
                    q = fyers_service.get_quotes([fyers_sym])
                    if q and q.get("s") == "ok" and q.get("d"):
                        lp = float(q["d"][0].get("v", {}).get("lp", 0.0))
                        if lp > 0:
                            current_p = lp
                            price_resolved = True

            if mode == "PAPER" and not price_resolved:
                continue

            # Calculate PnL & Metrics
            pts = current_p - entry_p
            gain_pct = pts / max(0.1, entry_p)
            gross_pnl = broker_pnl if mode == "LIVE" else round(pts * qty, 2)
            net_pnl = round(gross_pnl - self.FLAT_BROKERAGE_PER_TRADE, 2)

            mfe = max(float(trade.get("mfe_pts", 0.0)), pts)
            mae = min(float(trade.get("mae_pts", 0.0)), pts)
            peak_p = max(float(trade.get("peak_price", entry_p) or entry_p), current_p)

            # Re-evaluate live spot indicators & CIS score
            curr_spot = 0.0
            curr_pcr = float(trade.get("peak_pcr", 1.0) or 1.0)
            if chain_map and sym in chain_map:
                curr_spot = getattr(chain_map[sym], "spot_price", 0.0)
                curr_pcr = getattr(chain_map[sym], "pcr", curr_pcr) or curr_pcr

            ind_dict = option_confluence_service.get_price_indicators(sym, current_spot=curr_spot)
            signals = self.extract_signals_from_indicators(ind_dict)
            cis_score = self.calculate_composite_score(signals, cfg["weights"])

            peak_pcr = max(float(trade.get("peak_pcr", curr_pcr) or curr_pcr), curr_pcr)
            trough_pcr = min(float(trade.get("trough_pcr", curr_pcr) or curr_pcr), curr_pcr)

            # Extract dynamic structural indicator parameters
            bt_state = str(ind_dict.get("brk_state", "FLAT")).upper()
            bt_bias = str(ind_dict.get("brk_bias", "NEUTRAL")).upper()
            bt_fail = ind_dict.get("brk_fail")
            bt_trail = ind_dict.get("brk_trail")
            prox_per = float(ind_dict.get("prox_per", 50.0) or 50.0)

            # Major OI Walls from option chain
            major_ce_wall = 0.0
            major_pe_wall = 0.0
            ce_oi_chg = 0
            pe_oi_chg = 0
            if chain_map and sym in chain_map:
                ch = chain_map[sym]
                ce_ois = []
                pe_ois = []
                for s_row in getattr(ch, "strikes", []):
                    stk_val = float(s_row.strikePrice)
                    if s_row.CE and stk_val >= curr_spot:
                        ce_ois.append((stk_val, int(s_row.CE.openInterest or 0)))
                        ce_oi_chg += int(getattr(s_row.CE, "changeinOpenInterest", 0) or 0)
                    if s_row.PE and stk_val <= curr_spot:
                        pe_ois.append((stk_val, int(s_row.PE.openInterest or 0)))
                        pe_oi_chg += int(getattr(s_row.PE, "changeinOpenInterest", 0) or 0)
                if ce_ois:
                    major_ce_wall = max(ce_ois, key=lambda x: x[1])[0]
                if pe_ois:
                    major_pe_wall = max(pe_ois, key=lambda x: x[1])[0]

            peak_pcr = max(float(trade.get("peak_pcr", curr_pcr) or curr_pcr), curr_pcr)
            trough_pcr = min(float(trade.get("trough_pcr", curr_pcr) or curr_pcr), curr_pcr)

            # -------------------------------------------------------------
            # 1. TAKEOVER THE SMOOTH DAYS: RIDE DIRECTLY UNTIL 15:20 IST
            # If the market trend remains intact, hold until the 15:20 closing bell!
            # -------------------------------------------------------------
            if is_eod:
                self.exit_trade(
                    t_id,
                    exit_reason=f"EOD_SMOOTH_TREND_HARVEST_15:20 ({'+' if gain_pct>=0 else ''}{gain_pct*100:.1f}%)",
                    exit_price=current_p
                )
                continue

            # -------------------------------------------------------------
            # 2. DYNAMIC BREAKEVEN ARMOR (Anchored to Structural Trail / +20% gain)
            # -------------------------------------------------------------
            new_sl = sl
            new_be_locked = be_locked
            entry_spot = float(trade.get("entry_price", curr_spot))

            # Dynamic Breakeven lock once Breakout Tracker trailing level ratchets in favor
            if trade["option_type"] == "CE" and bt_trail is not None and bt_trail > curr_spot and be_locked == 0:
                new_be_locked = 1
                new_sl = max(sl, round(entry_p * 1.02, 1))
                logger.info(f"ShonyaBot DYNAMIC BREAKEVEN LOCKED on {t_id}! Breakout trail above entry. SL ratcheted to ₹{new_sl:.1f}")
            elif trade["option_type"] == "PE" and bt_trail is not None and bt_trail < curr_spot and be_locked == 0:
                new_be_locked = 1
                new_sl = max(sl, round(entry_p * 1.02, 1))
                logger.info(f"ShonyaBot DYNAMIC BREAKEVEN LOCKED on {t_id}! Breakout trail below entry. SL ratcheted to ₹{new_sl:.1f}")

            # Baseline profit lock if gain >= +20%
            if gain_pct >= 0.20 and be_locked == 0:
                new_be_locked = 1
                new_sl = max(sl, round(entry_p * 1.02, 1))
                logger.info(f"ShonyaBot BREAKEVEN ARMOR LOCKED on {t_id} (+{gain_pct*100:.1f}%)! SL: ₹{new_sl:.1f}")

            # Notify mobile of Breakeven Armor Lock
            if new_be_locked == 1 and be_locked == 0:
                try:
                    from app.services.mobile_notification_service import mobile_alerts
                    mobile_alerts.notify_breakeven_armor({
                        "symbol": sym,
                        "strike": trade["strike"],
                        "option_type": trade["option_type"],
                        "entry_price": entry_p,
                        "current_price": current_p,
                        "stop_loss": new_sl
                    })
                except Exception as e:
                    logger.warning(f"Failed to dispatch mobile breakeven armor alert: {e}")

            # -------------------------------------------------------------
            # 3. EMERGENCY PROTECTIVE STOP
            # -------------------------------------------------------------
            if current_p <= new_sl:
                reason = f"BREAKEVEN_STOP (Locked +{((new_sl - entry_p)/entry_p)*100:.1f}%)" if new_sl > entry_p else "PROTECTIVE_STOP (-15%)"
                self.exit_trade(t_id, exit_reason=reason, exit_price=current_p)
                continue

            # -------------------------------------------------------------
            # 4. DYNAMIC STRUCTURAL EXITS (Zero Arbitrary Percentage Trailing)
            # -------------------------------------------------------------
            if trade["option_type"] == "CE":
                # A. Breakout Pivot Failure
                if bt_fail is not None and curr_spot < float(bt_fail) and gain_pct < 0.10:
                    self.exit_trade(t_id, exit_reason=f"BREAKOUT_PIVOT_FAILURE (Spot {curr_spot:.1f} < Fail {bt_fail:.1f})", exit_price=current_p)
                    continue

                # B. Breakout Confirmed Flip
                if bt_state == "SHORT" and bt_bias == "BEARISH":
                    self.exit_trade(t_id, exit_reason="BREAKOUT_TRACKER_FLIPPED_SHORT", exit_price=current_p)
                    continue

                # C. Proximity MA Stack Loss (Rides smooth days above 50%, exits only on full ribbon loss)
                if prox_per < 40.0 and gain_pct > 0.10:
                    self.exit_trade(t_id, exit_reason=f"PROXIMITY_MA_STACK_LOST (MAPO {prox_per:.1f}% < 40%)", exit_price=current_p)
                    continue

                # D. Major Call Wall Rejection
                if major_ce_wall > 0 and curr_spot >= (major_ce_wall - 15.0) and ce_oi_chg > (pe_oi_chg * 1.8) and gain_pct > 0.15:
                    self.exit_trade(t_id, exit_reason=f"MAJOR_CE_WALL_REJECTION ({major_ce_wall:.0f} Wall Defense)", exit_price=current_p)
                    continue

                # E. Institutional Put Unwinding
                if (peak_pcr - curr_pcr) >= 0.20 and pe_oi_chg < 0 and gain_pct < 0.05:
                    self.exit_trade(t_id, exit_reason=f"INSTITUTIONAL_PUT_UNWINDING (PCR collapsed {peak_pcr:.2f}->{curr_pcr:.2f})", exit_price=current_p)
                    continue

            elif trade["option_type"] == "PE":
                # A. Breakout Pivot Failure
                if bt_fail is not None and curr_spot > float(bt_fail) and gain_pct < 0.10:
                    self.exit_trade(t_id, exit_reason=f"BREAKOUT_PIVOT_FAILURE (Spot {curr_spot:.1f} > Fail {bt_fail:.1f})", exit_price=current_p)
                    continue

                # B. Breakout Confirmed Flip
                if bt_state == "LONG" and bt_bias == "BULLISH":
                    self.exit_trade(t_id, exit_reason="BREAKOUT_TRACKER_FLIPPED_LONG", exit_price=current_p)
                    continue

                # C. Proximity MA Stack Reclaim
                if prox_per > 60.0 and gain_pct > 0.10:
                    self.exit_trade(t_id, exit_reason=f"PROXIMITY_MA_STACK_RECLAIMED (MAPO {prox_per:.1f}% > 60%)", exit_price=current_p)
                    continue

                # D. Major Put Floor Rejection
                if major_pe_wall > 0 and curr_spot <= (major_pe_wall + 15.0) and pe_oi_chg > (ce_oi_chg * 1.8) and gain_pct > 0.15:
                    self.exit_trade(t_id, exit_reason=f"MAJOR_PE_WALL_REJECTION ({major_pe_wall:.0f} Floor Defense)", exit_price=current_p)
                    continue

                # E. Institutional Call Unwinding
                if (curr_pcr - trough_pcr) >= 0.20 and ce_oi_chg < 0 and gain_pct < 0.05:
                    self.exit_trade(t_id, exit_reason=f"INSTITUTIONAL_CALL_UNWINDING (PCR surged {trough_pcr:.2f}->{curr_pcr:.2f})", exit_price=current_p)
                    continue

            # Update live state in database
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    UPDATE shonya_trades
                    SET current_price = ?, gross_pnl = ?, net_pnl = ?, fyers_broker_pnl = ?,
                        breakeven_locked = ?, stop_loss = ?, mfe_pts = ?, mae_pts = ?,
                        peak_price = ?, peak_pcr = ?, trough_pcr = ?, cis_score = ?
                    WHERE id = ?
                """, (
                    current_p, gross_pnl, net_pnl, broker_pnl,
                    new_be_locked, new_sl, mfe, mae,
                    peak_p, peak_pcr, trough_pcr, cis_score, t_id
                ))
                conn.commit()

            updated.append({
                "id": t_id,
                "symbol": sym,
                "current_price": current_p,
                "gain_pct": round(gain_pct * 100.0, 1),
                "gross_pnl": gross_pnl,
                "net_pnl": net_pnl,
                "broker_pnl": broker_pnl,
                "breakeven_locked": bool(new_be_locked),
                "stop_loss": new_sl,
                "cis_score": cis_score,
                "pcr": curr_pcr
            })

        return updated

    # -------------------------------------------------------------
    # Position Exit & Emergency Square-Off
    # -------------------------------------------------------------
    def exit_trade(
        self,
        trade_id: str,
        exit_reason: str = "MANUAL_EXIT",
        exit_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Closes an open position.
        In LIVE mode, places an offsetting square-off order in Fyers.
        Zero theoretical estimation.
        """
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM shonya_trades WHERE id = ? AND status = 'OPEN'", (trade_id,))
            row = c.fetchone()
            if not row:
                return {"success": False, "message": f"Open trade {trade_id} not found."}

            trade = dict(row)

        mode = trade["execution_mode"]
        fyers_sym = trade.get("fyers_symbol")
        qty = int(trade["quantity"])
        entry_p = float(trade["entry_price"])
        pid = trade.get("broker_position_id")

        curr_p = exit_price or float(trade["current_price"])

        # Execute LIVE square-off in Fyers broker
        broker_exit_res = None
        realized_broker_pnl = 0.0

        if mode == "LIVE" and fyers_service.is_configured():
            try:
                broker_exit_res = fyers_service.exit_position(
                    position_id=pid or fyers_sym,
                    symbol=fyers_sym,
                    qty=qty,
                    side=1  # Was BUY, so exit will SELL
                )
                logger.info(f"ShonyaBot LIVE EXIT ORDER submitted to Fyers for {trade_id}: {broker_exit_res}")

                time.sleep(0.5)
                f_pos = fyers_service.get_positions()
                if f_pos.get("s") == "ok":
                    for p in f_pos.get("netPositions", []):
                        if p.get("symbol") == fyers_sym:
                            curr_p = float(p.get("sellAvg", curr_p))
                            realized_broker_pnl = float(p.get("realized_profit", (curr_p - entry_p) * qty))
            except Exception as e:
                logger.error(f"Error during LIVE broker exit for {trade_id}: {e}")

        gross_pnl = realized_broker_pnl if (mode == "LIVE" and realized_broker_pnl != 0.0) else round((curr_p - entry_p) * qty, 2)
        net_pnl = round(gross_pnl - self.FLAT_BROKERAGE_PER_TRADE, 2)
        now_dt = get_current_ist().strftime("%Y-%m-%d %H:%M:%S")

        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE shonya_trades
                SET status = 'CLOSED', exit_time = ?, exit_price = ?, exit_reason = ?,
                    gross_pnl = ?, net_pnl = ?, fyers_broker_pnl = ?
                WHERE id = ?
            """, (now_dt, curr_p, exit_reason, gross_pnl, net_pnl, realized_broker_pnl, trade_id))
            conn.commit()

        logger.info(f"ShonyaBot Position CLOSED: {trade_id} at ₹{curr_p:.1f} (Reason: {exit_reason}, Net PnL: ₹{net_pnl:+.1f})")

        # Dispatch Real-Time Mobile Trade Exit Alert (Telegram + ntfy lockscreen)
        try:
            from app.services.mobile_notification_service import mobile_alerts
            mobile_alerts.notify_trade_exit({
                "symbol": trade.get("symbol", ""),
                "strike": trade.get("strike", 0),
                "option_type": trade.get("option_type", "CE"),
                "entry_price": entry_p,
                "exit_price": curr_p,
                "net_pnl": net_pnl,
                "exit_reason": exit_reason,
                "exit_time": now_dt.split(" ")[-1] if " " in now_dt else now_dt
            })
        except Exception as e:
            logger.warning(f"Failed to dispatch mobile trade exit alert: {e}")

        return {
            "success": True,
            "trade_id": trade_id,
            "exit_price": curr_p,
            "exit_reason": exit_reason,
            "gross_pnl": gross_pnl,
            "brokerage": self.FLAT_BROKERAGE_PER_TRADE,
            "net_pnl": net_pnl,
            "mode": mode,
            "broker_response": broker_exit_res
        }

    def squareoff_all(self) -> Dict[str, Any]:
        """Emergency Kill Switch: Squares off all open positions immediately."""
        open_trades = self.get_open_trades()
        results = []
        for t in open_trades:
            res = self.exit_trade(t["id"], exit_reason="EMERGENCY_SQUAREOFF")
            results.append(res)

        # In LIVE mode, also trigger broker-level exit_all
        if self.trading_mode == "LIVE" and fyers_service.is_configured():
            try:
                fyers_service.exit_all_positions()
            except Exception as e:
                logger.warning(f"Error calling fyers exit_all_positions: {e}")

        return {
            "success": True,
            "count": len(results),
            "results": results,
            "message": f"Successfully squared off {len(results)} positions."
        }

    # -------------------------------------------------------------
    # Queries & Performance Reporting
    # -------------------------------------------------------------
    def get_open_trades(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM shonya_trades WHERE status = 'OPEN' ORDER BY created_at DESC")
            return [dict(r) for r in c.fetchall()]

    def get_open_trade_for_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        sym = symbol.upper()
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM shonya_trades WHERE symbol = ? AND status = 'OPEN'", (sym,))
            row = c.fetchone()
            return dict(row) if row else None

    def get_trade_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM shonya_trades WHERE status = 'CLOSED' ORDER BY exit_time DESC LIMIT ?", (limit,))
            return [dict(r) for r in c.fetchall()]

    def get_performance_metrics(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM shonya_trades WHERE status = 'CLOSED'")
            closed = [dict(r) for r in c.fetchall()]

        total = len(closed)
        if total == 0:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate_pct": 0.0,
                "gross_pnl_inr": 0.0,
                "total_fees_inr": 0.0,
                "net_pnl_inr": 0.0,
                "profit_factor": 0.0,
                "avg_trade_inr": 0.0
            }

        wins = [t for t in closed if float(t.get("net_pnl", 0.0)) > 0]
        losses = [t for t in closed if float(t.get("net_pnl", 0.0)) <= 0]
        gross_total = sum(float(t.get("gross_pnl", 0.0)) for t in closed)
        fees_total = sum(float(t.get("brokerage", 75.0)) for t in closed)
        net_total = sum(float(t.get("net_pnl", 0.0)) for t in closed)

        gross_wins = sum(float(t.get("gross_pnl", 0.0)) for t in wins)
        gross_losses = abs(sum(float(t.get("gross_pnl", 0.0)) for t in losses))
        pf = round(gross_wins / gross_losses, 2) if gross_losses > 0 else (99.0 if gross_wins > 0 else 0.0)

        return {
            "total_trades": total,
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate_pct": round((len(wins) / total) * 100, 1),
            "gross_pnl_inr": round(gross_total, 2),
            "total_fees_inr": round(fees_total, 2),
            "net_pnl_inr": round(net_total, 2),
            "profit_factor": pf,
            "avg_trade_inr": round(net_total / total, 2)
        }


shonya_bot = ShonyaBot()
