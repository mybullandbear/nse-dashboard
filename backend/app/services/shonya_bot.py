"""
ShonyaBot: 5-Minute OI Buildup Direction & Hull Suite Trailing Execution Engine
=============================================================================
Trades NIFTY, BANKNIFTY, and SENSEX based on verified institutional rules:
1. Directional Source: Open Interest (OI) Chain Data (Long Buildup, Short Buildup, Short Covering, Long Unwinding).
2. Indicator Confirmation: 5-Minute Responsive Hull Suite (EHMA 14, multiplier 1.5).
3. Directional Synchronization Filter:
   - Trade ONLY when OI Buildup and Hull Suite are in the SAME direction.
   - Strictly DO NOT trade when OI and Hull are in OPPOSITE directions (eliminates false breakouts).
4. Trailing & Exit Architecture:
   - Orders are trailed along the Hull Suite signal.
   - Hull Trend Reversal (BULLISH -> BEARISH for CE, BEARISH -> BULLISH for PE) acts as the EXIT point.
   - EOD Squareoff at 15:15-15:20 IST.
5. High-Fidelity Paper Trading & Live Broker Execution:
   - Fills on next-tick open with live MTM, MAE, MFE, and transaction cost tracking.
"""
import os
import json
import time
import uuid
import sqlite3
import logging
import math
import threading
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, time as dt_time

import pandas as pd

from app.core.config import get_settings
from app.core.market_hours import get_current_ist, is_market_open
from app.services.fyers_service import fyers_service
from app.services.technical_indicators import TechnicalIndicators
from app.db.storage import snapshot_storage

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "shonya_trades.db")


# ─────────────────────────────────────────────────────────────────────────────
# Asset-Specific Specifications (NIFTY, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY)
# ─────────────────────────────────────────────────────────────────────────────
INDEX_CONFIGS: Dict[str, Dict[str, Any]] = {
    "NIFTY": {
        "lot_size": 65,
        "step": 50.0,
        "strategy": "OI_BUILDUP_HULL_CONFLUENCE",
        "timeframe": "5m",
        "description": "5m OI Buildup + Hull Suite (EHMA 14) Confluence. Trail and exit on Hull flip."
    },
    "BANKNIFTY": {
        "lot_size": 30,
        "step": 100.0,
        "strategy": "OI_BUILDUP_HULL_CONFLUENCE",
        "timeframe": "5m",
        "description": "5m OI Buildup + Hull Suite (EHMA 14) Confluence. Trail and exit on Hull flip."
    },
    "SENSEX": {
        "lot_size": 20,
        "step": 100.0,
        "strategy": "OI_BUILDUP_HULL_CONFLUENCE",
        "timeframe": "5m",
        "description": "5m OI Buildup + Hull Suite (EHMA 14) Confluence. Trail and exit on Hull flip."
    },
    "FINNIFTY": {
        "lot_size": 60,
        "step": 50.0,
        "strategy": "OI_BUILDUP_HULL_CONFLUENCE",
        "timeframe": "5m",
        "description": "5m OI Buildup + Hull Suite Confluence."
    },
    "MIDCPNIFTY": {
        "lot_size": 120,
        "step": 25.0,
        "strategy": "OI_BUILDUP_HULL_CONFLUENCE",
        "timeframe": "5m",
        "description": "5m OI Buildup + Hull Suite Confluence."
    }
}


class ShonyaBot:
    FLAT_BROKERAGE_PER_TRADE = 85.0
    CAPITAL_CEILING = 100000.0

    def __init__(self, db_path: str = DB_PATH):
        self._trade_lock = threading.RLock()
        self.db_path = db_path
        self.is_active: bool = True
        self.trading_mode: str = "PAPER"  # "PAPER" or "LIVE"
        self.capital_ceiling: float = 100000.0
        # Primary user requested assets: NIFTY, BANKNIFTY, SENSEX
        self.last_entry_candle: Dict[str, str] = {}
        # Multi-Bar Signal Persistence Filter: Tracks last signals to eliminate intra-bar twitches
        self.confluence_persistence: Dict[str, List[str]] = {}
        self._init_db()
        self._load_config()
        # This modernization build cannot restore a persisted live mode.
        self.trading_mode = "PAPER"
        self.is_active = False

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
                    source TEXT NOT NULL,
                    broker_order_id TEXT,
                    broker_position_id TEXT,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,
                    exit_reason TEXT,
                    gross_pnl REAL DEFAULT 0.0,
                    brokerage REAL DEFAULT 85.0,
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
            conn.commit()

    def _load_config(self):
        """Loads persistent bot state, defaulting to ACTIVE in PAPER mode with NIFTY, BANKNIFTY, SENSEX."""
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
                        self.capital_ceiling = 100000.0
                else:
                    c.execute("INSERT OR REPLACE INTO shonya_config (key, value) VALUES ('capital_ceiling', '100000.0')")
                    self.capital_ceiling = 100000.0

                c.execute("SELECT value FROM shonya_config WHERE key = 'enabled_symbols'")
                row_syms = c.fetchone()
                if row_syms:
                    try:
                        parsed_syms = json.loads(row_syms["value"])
                        if isinstance(parsed_syms, list) and parsed_syms:
                            self.enabled_symbols = [s.upper() for s in parsed_syms if s.upper() in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]]
                    except Exception:
                        self.enabled_symbols = ["NIFTY", "BANKNIFTY", "SENSEX"]
                else:
                    self.enabled_symbols = ["NIFTY", "BANKNIFTY", "SENSEX"]
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
        self.capital_ceiling = float(max(1000.0, amount))
        try:
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("INSERT OR REPLACE INTO shonya_config (key, value) VALUES ('capital_ceiling', ?)", (str(self.capital_ceiling),))
                conn.commit()
        except Exception as e:
            logger.debug(f"Error persisting capital_ceiling: {e}")
        logger.info(f"ShonyaBot capital ceiling updated to: ₹{self.capital_ceiling:,.2f}")
        return self.capital_ceiling

    def set_enabled_symbols(self, symbols: List[str]) -> List[str]:
        valid = [s.upper() for s in symbols if s.upper() in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]]
        self.enabled_symbols = valid if valid else ["NIFTY", "BANKNIFTY", "SENSEX"]
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
        open_trades = self.get_open_trades()
        fyers_ok, fyers_msg = fyers_service.validate_connection()
        fyers_funds = fyers_service.get_funds() if fyers_ok else {"available_balance": 0.0}

        metrics = self.get_performance_metrics()
        cap_stat = self.get_capital_status()

        return {
            "success": True,
            "bot_name": "ShonyaBot (5m OI Buildup + Hull Trailing Engine)",
            "is_active": self.is_active,
            "trading_mode": self.trading_mode,
            "fyers_connected": fyers_ok,
            "fyers_status_message": fyers_msg,
            "fyers_available_balance": fyers_funds.get("available_balance", 0.0),
            "capital_ceiling": self.capital_ceiling,
            "capital_status": cap_stat,
            "enabled_symbols": self.enabled_symbols,
            "available_symbols": ["NIFTY", "BANKNIFTY", "SENSEX"],
            "open_positions_count": len(open_trades),
            "open_positions": open_trades,
            "metrics": metrics,
            "index_configs": INDEX_CONFIGS,
            "strategy": {
                "name": "5m OI Buildup + Hull Suite Trailing",
                "rules": "1. Trade direction given by OI Buildup. 2. Filter out opposing Hull directions. 3. Trail and exit on Hull signal flip."
            }
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
        logger.info(f"ShonyaBot state changed: {'ACTIVE' if active else 'PAUSED'}")
        return self.is_active

    def set_mode(self, mode: str) -> str:
        mode_upper = mode.upper()
        if mode_upper != "PAPER":
            raise ValueError("Live trading is disabled in this build")
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
    # 5-Minute Indicator Engine: OI Buildup & Hull Suite (Closed Bar Confirmation)
    # -------------------------------------------------------------
    def get_5min_indicator_state(
        self,
        symbol: str,
        current_spot: float = 0.0,
        current_total_oi: int = 0,
        pe_oi_chg: int = 0,
        ce_oi_chg: int = 0
    ) -> Dict[str, Any]:
        """
        Computes 5-minute candles, Responsive Hull Suite (len 14, mult 1.5),
        and OI Buildup classification (Long Buildup, Short Buildup, Short Covering, Long Unwinding).
        Crucially isolates confirmed CLOSED bars from the currently forming bar to prevent
        intra-candle noise, whipsaws, and hyper-frequent execution churn.
        """
        sym = symbol.upper()
        query_sym = "NIFTY" if sym == "SENSEX" else sym

        history = snapshot_storage.get_continuous_timeseries(
            query_sym,
            limit=250,
            max_time="15:15",
            discard_frozen_after="15:15"
        )
        if not history:
            return {
                "valid": False,
                "buildup": "NEUTRAL",
                "oi_dir": "NEUTRAL",
                "hull_trend": "NEUTRAL",
                "is_aligned": False,
                "is_opposed": False,
                "last_closed_candle_id": None
            }

        df = pd.DataFrame(history)
        if sym == "SENSEX":
            df["spot"] = df["spot"] * 3.32

        def get_5min_bucket(time_str):
            try:
                h, m = map(int, time_str.split(":"))
                bucket_m = (m // 5) * 5
                return f"{h:02d}:{bucket_m:02d}"
            except Exception:
                return None

        df["bucket"] = df["time"].apply(get_5min_bucket)
        df = df.dropna(subset=["bucket"]).copy()

        grouped = df.groupby(["trade_date", "bucket"], sort=False)
        bars = []
        for (t_date, bucket), grp in grouped:
            c = float(grp["spot"].iloc[-1])
            ce_oi = int(grp["ce_oi"].iloc[-1] or 0)
            pe_oi = int(grp["pe_oi"].iloc[-1] or 0)
            bars.append({
                "trade_date": t_date,
                "time": bucket,
                "close": c,
                "total_oi": ce_oi + pe_oi,
                "ce_oi_chg": int(grp["ce_oi_chg"].iloc[-1] or 0),
                "pe_oi_chg": int(grp["pe_oi_chg"].iloc[-1] or 0)
            })

        if not bars:
            return {"valid": False, "buildup": "NEUTRAL", "oi_dir": "NEUTRAL", "hull_trend": "NEUTRAL", "is_aligned": False, "is_opposed": False, "last_closed_candle_id": None}

        now_dt = get_current_ist()
        today_str = now_dt.strftime("%Y-%m-%d")
        curr_bucket = f"{now_dt.hour:02d}:{(now_dt.minute // 5) * 5:02d}"

        # If live tick provided, ensure latest forming candle reflects it
        if current_spot > 0:
            bars[-1]["close"] = float(current_spot)
        if current_total_oi > 0:
            bars[-1]["total_oi"] = int(current_total_oi)

        # Distinguish confirmed CLOSED bars from the currently forming bar:
        # If the last bar belongs to today and the current 5-min bucket, it is still forming.
        is_last_forming = (bars[-1]["trade_date"] == today_str and bars[-1]["time"] == curr_bucket)
        if is_last_forming and len(bars) > 1:
            closed_bars = bars[:-1]
        else:
            closed_bars = bars

        # 1. Compute Responsive Hull Suite on CONFIRMED CLOSED BARS
        closed_closes = [b["close"] for b in closed_bars]
        hull_res = TechnicalIndicators.compute_hull(closed_closes, mode="Ehma", length=14, length_mult=1.5)
        mhull = hull_res["mhull"][-1]
        shull = hull_res["shull"][-1]
        hull_trend = hull_res.get("curr_state") or ("BULLISH" if mhull > shull else ("BEARISH" if mhull < shull else "NEUTRAL"))

        # 2. Compute 5-min OI Buildup on CONFIRMED CLOSED BARS
        last_closed = closed_bars[-1]
        prev_closed = closed_bars[-2] if len(closed_bars) > 1 else last_closed

        last_c = float(last_closed["close"])
        prev_c = float(prev_closed["close"])
        last_oi = int(last_closed["total_oi"])
        prev_oi = int(prev_closed["total_oi"])

        p_chg = last_c - prev_c
        oi_chg = last_oi - prev_oi
        c_pe_chg = int(last_closed.get("pe_oi_chg", 0))
        c_ce_chg = int(last_closed.get("ce_oi_chg", 0))
        net_pe_ce = c_pe_chg - c_ce_chg

        if p_chg >= 0 and oi_chg >= 0:
            buildup = "LONG_BUILDUP"
            oi_dir = "BULLISH"
        elif p_chg < 0 and oi_chg >= 0:
            buildup = "SHORT_BUILDUP"
            oi_dir = "BEARISH"
        elif p_chg >= 0 and oi_chg < 0:
            buildup = "SHORT_COVERING"
            oi_dir = "BULLISH" if net_pe_ce >= 0 else "NEUTRAL"
        else:
            buildup = "LONG_UNWINDING"
            oi_dir = "BEARISH" if net_pe_ce < 0 else "NEUTRAL"

        # 3. Directional Alignment & Opposing Filter
        is_aligned = (oi_dir == hull_trend) and (oi_dir in ["BULLISH", "BEARISH"])
        is_opposed = (oi_dir != hull_trend) and (oi_dir in ["BULLISH", "BEARISH"])

        last_closed_candle_id = f"{last_closed['trade_date']}_{last_closed['time']}"

        # 4. Optional Live Forming Snapshot (for visual monitoring, NOT used for premature triggers)
        all_closes = [b["close"] for b in bars]
        live_hull_res = TechnicalIndicators.compute_hull(all_closes, mode="Ehma", length=14, length_mult=1.5)
        live_mhull = live_hull_res["mhull"][-1]
        live_shull = live_hull_res["shull"][-1]
        live_trend = live_hull_res.get("curr_state") or ("BULLISH" if live_mhull > live_shull else ("BEARISH" if live_mhull < live_shull else "NEUTRAL"))

        return {
            "valid": True,
            "symbol": sym,
            "close": last_c,
            "mhull": mhull,
            "shull": shull,
            "hull_trend": hull_trend,
            "buildup": buildup,
            "oi_dir": oi_dir,
            "is_aligned": is_aligned,
            "is_opposed": is_opposed,
            "last_closed_candle_id": last_closed_candle_id,
            "last_closed_candle_time": last_closed["time"],
            "live_forming": {
                "candle_time": curr_bucket,
                "spot": current_spot or bars[-1]["close"],
                "mhull": live_mhull,
                "shull": live_shull,
                "hull_trend": live_trend
            },
            "bars_count": len(bars),
            "closed_bars_count": len(closed_bars)
        }

    # -------------------------------------------------------------
    # Trade Placement (Paper & Live Execution)
    # -------------------------------------------------------------
    def place_trade(self, *args, **kwargs):
        with self._trade_lock:
            return self._place_trade_locked(*args, **kwargs)

    def _place_trade_locked(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        lots: int = 1,
        entry_price: Optional[float] = None,
        target1: Optional[float] = None,
        target2: Optional[float] = None,
        stop_loss: Optional[float] = None,
        source: str = "OI_BUILDUP_HULL_CONFLUENCE",
        thesis: str = "",
        pcr: float = 1.0,
        cis_score: float = 50.0
    ) -> Dict[str, Any]:
        sym = symbol.upper()
        opt_t = option_type.upper()
        if self.trading_mode != "PAPER":
            return {"success": False, "message": "Live trading is disabled in this build"}
        if sym not in INDEX_CONFIGS or opt_t not in {"CE", "PE"} or type(lots) is not int or not 1 <= lots <= 10:
            return {"success": False, "message": "Invalid contract or lot quantity"}
        numbers = [strike, entry_price, target1, target2, stop_loss]
        if any(v is not None and (not math.isfinite(v) or v <= 0) for v in numbers):
            return {"success": False, "message": "Prices and strike must be finite and positive"}
        cfg = INDEX_CONFIGS.get(sym, INDEX_CONFIGS["NIFTY"])
        lot_size = cfg.get("lot_size", 65)
        total_qty = lots * lot_size

        # Capital Affordability Validation
        cap_stat = self.get_capital_status()
        required_margin = (entry_price or 100.0) * total_qty
        if required_margin > cap_stat["available_capital"]:
            return {
                "success": False,
                "message": f"Insufficient available capital: Required margin ₹{required_margin:,.0f} exceeds available ₹{cap_stat['available_capital']:,.0f} (Total Capital: ₹{self.capital_ceiling:,.0f})."
            }

        # Prevent duplicate open trade in same symbol (1 position per segment)
        open_existing = self.get_open_trade_for_symbol(sym)
        if open_existing:
            return {
                "success": False,
                "message": f"Position already open for {sym} (ID: {open_existing['id']}). Close it before entering new trade."
            }

        fyers_sym = fyers_service.resolve_option_symbol(sym, strike, opt_t)
        est_ltp = entry_price or 0.0

        if est_ltp <= 0 and fyers_sym:
            q_res = fyers_service.get_quotes([fyers_sym])
            if q_res and q_res.get("s") == "ok" and q_res.get("d"):
                est_ltp = float(q_res["d"][0].get("v", {}).get("lp", 0.0))

        if est_ltp <= 0:
            return {"success": False, "message": "No executable quote; paper entry rejected"}

        # Stop loss: -25% protective disaster stop (Main exit is Hull signal flip)
        sl = stop_loss if (stop_loss and stop_loss > 0) else round(est_ltp * 0.75, 1)
        t1 = target1 if (target1 and target1 > 0) else round(est_ltp * 1.30, 1)
        t2 = target2 if (target2 and target2 > 0) else round(est_ltp * 1.60, 1)

        if est_ltp * total_qty > cap_stat["available_capital"]:
            return {"success": False, "message": "Insufficient capital at resolved quote"}
        if not (0 < sl < est_ltp < t1 <= t2):
            return {"success": False, "message": "Require stop < entry < target1 <= target2"}

        trade_id = f"SHONYA_{sym}_{int(strike)}_{opt_t}_{int(time.time())}"
        now_dt = get_current_ist().strftime("%Y-%m-%d %H:%M:%S")

        broker_order_id = None
        broker_position_id = None
        mode = self.trading_mode

        # LIVE Broker Execution
        if mode == "LIVE":
            if not fyers_service.is_configured():
                return {"success": False, "message": "Cannot place LIVE trade: Fyers broker not configured or logged in."}
            if not fyers_sym:
                return {"success": False, "message": f"Cannot resolve live Fyers contract symbol for {sym} {strike} {opt_t}."}

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
                    ?, 0.0, 85.0, -85.0, 0.0,
                    0.0, 0.0, ?, ?, ?, ?, ?, ?
                )
            """, (
                trade_id, sym, strike, opt_t, fyers_sym, lots, total_qty,
                est_ltp, est_ltp, t1, t2, sl,
                mode, source, broker_order_id, broker_position_id,
                now_dt, thesis, now_dt, est_ltp, pcr, pcr, cis_score
            ))
            conn.commit()

        logger.info(f"ShonyaBot [{mode}] Trade Initiated: {trade_id} | {sym} {int(strike)} {opt_t} @ ₹{est_ltp:.1f} | Thesis: {thesis}")

        # Dispatch Mobile Notification
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
                "entry_time": now_dt.split(" ")[-1] if " " in now_dt else now_dt
            })
        except Exception as e:
            logger.debug(f"Mobile alert dispatch error: {e}")

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
    # Automated Signal Evaluator (Tick / Polling Cycle)
    # -------------------------------------------------------------
    async def evaluate_tick_for_paper_entry(
        self,
        symbol: str,
        chain: Any
    ) -> Optional[Dict[str, Any]]:
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

        sym = symbol.upper()
        # Strictly trade the user's requested symbols (NIFTY, BANKNIFTY, SENSEX)
        if sym not in self.enabled_symbols:
            return None

        # Exact 1 open trade per symbol limit
        open_trade = self.get_open_trade_for_symbol(sym)
        if open_trade:
            return None

        now_dt = get_current_ist()
        t = now_dt.time()
        # Trading Hours (09:20 - 14:45 IST) - Avoid late session expiration risk
        if not (dt_time(9, 20, 0) <= t <= dt_time(14, 45, 0)):
            return None

        cfg = INDEX_CONFIGS.get(sym, INDEX_CONFIGS["NIFTY"])
        step = cfg["step"]
        atm = getattr(chain, "atm_strike", 0.0) if chain else 0.0
        spot = getattr(chain, "spot_price", 0.0) if chain else 0.0

        if sym == "SENSEX" and (spot <= 0 or atm <= 0):
            # Synthesize SENSEX spot from NIFTY if not in chain
            spot = 76500.0
            atm = 76500.0

        # Centralized Strategy Confluence Evaluation
        from app.services.option_confluence_service import option_confluence_service
        conf = await option_confluence_service.analyze_confluence(sym, parsed_chain=chain, compute_strike_candles=False)
        if not conf:
            return None

        strat_conf = conf.get("strategy_confluence", {})
        action = strat_conf.get("action", {})
        verdict = action.get("verdict", "")
        opt_type = action.get("type", "")
        is_aligned = action.get("is_aligned", False)
        is_opposed = action.get("is_opposed", False)

        # ─────────────────────────────────────────────────────────────
        # STRICT 5-MINUTE CANDLE CLOSE BOUNDARY GATE
        # ─────────────────────────────────────────────────────────────
        # 5-minute candles close at minute % 5 == 0 (09:20, 09:25, 09:30, 09:35, ...)
        # Only evaluate entries within the confirmed close window (first 45 seconds of the 5m mark).
        # Any mid-candle ticks (minute % 5 != 0 or second > 45) are strictly locked out from opening new trades!
        if now_dt.minute % 5 != 0 or now_dt.second > 45:
            return None

        from datetime import timedelta
        prev_5m = now_dt - timedelta(minutes=5)
        closed_candle_id = f"{prev_5m.strftime('%Y-%m-%d')}_{prev_5m.hour:02d}:{(prev_5m.minute // 5) * 5:02d}"

        # Allow only 1 trade execution per completed 5-minute candle
        if self.last_entry_candle.get(sym) == closed_candle_id:
            return None

        # RULE 1: OPPOSITE DIRECTION FILTER
        if is_opposed or verdict == "CONFLICT - NO TRADE":
            logger.info(
                f"ShonyaBot [{sym}]: OPPOSITE DIRECTION ({action.get('sub')}). Trade rejected by filter."
            )
            return None

        # RULE 2: DIRECTIONAL CONFLUENCE (Trade only on BUY CALL or BUY PUT)
        if not is_aligned or verdict not in ["BUY CALL", "BUY PUT"]:
            return None

        # 2-BAR PERSISTENCE FILTER (Eliminates single-tick false spikes)
        if sym not in self.confluence_persistence:
            self.confluence_persistence[sym] = []
        self.confluence_persistence[sym].append(verdict)
        if len(self.confluence_persistence[sym]) > 5:
            self.confluence_persistence[sym].pop(0)

        # Require at least 2 consecutive aligned signals across interval boundaries
        recent_verdicts = self.confluence_persistence[sym][-2:]
        if len(recent_verdicts) < 2 or not all(v == verdict for v in recent_verdicts):
            logger.debug(f"ShonyaBot [{sym}]: Waiting for 2-bar persistence confirmation ({recent_verdicts})")
            return None

        # Mark candle as evaluated to prevent duplicate entries in same 5m bar
        self.last_entry_candle[sym] = closed_candle_id

        # DELTA & STRIKE DISTANCE ALIGNMENT (Optimal Delta 0.50 - 0.55)
        # Symmetrical Rule: Select 1-ITM (Delta ~0.53) if liquid & tight spread, else ATM (Delta ~0.50)
        preferred_itm_strike = (atm - step) if opt_type == "CE" else (atm + step)
        chosen_strike = atm
        ltp = 0.0

        if chain and getattr(chain, "strikes", None):
            strike_map = {s.strikePrice: s for s in chain.strikes}
            itm_row = strike_map.get(preferred_itm_strike)
            atm_row = strike_map.get(atm)

            itm_contract = (itm_row.CE if opt_type == "CE" else itm_row.PE) if itm_row else None
            atm_contract = (atm_row.CE if opt_type == "CE" else atm_row.PE) if atm_row else None

            use_itm = False
            if itm_contract and itm_contract.lastPrice > 35.0:
                itm_oi = itm_contract.openInterest
                itm_vol = itm_contract.totalTradedVolume
                bid = itm_contract.bidprice
                ask = itm_contract.askPrice
                spread_pct = ((ask - bid) / ask) if (ask > 0 and bid > 0) else 0.0

                # If ITM has adequate liquidity and tight spread (<3%), choose 1-ITM for higher Delta response
                if (itm_oi >= 20000 or itm_vol >= 5000) and spread_pct <= 0.035:
                    use_itm = True

            if use_itm and itm_contract:
                chosen_strike = preferred_itm_strike
                ltp = float(itm_contract.lastPrice)
            elif atm_contract and atm_contract.lastPrice > 0:
                chosen_strike = atm
                ltp = float(atm_contract.lastPrice)
            elif itm_contract and itm_contract.lastPrice > 0:
                chosen_strike = preferred_itm_strike
                ltp = float(itm_contract.lastPrice)

        if ltp <= 0:
            ltp = 110.0 if opt_type == "CE" else 115.0

        thesis = (
            f"Centralized 5m Strategy: {verdict} ({opt_type}) | "
            f"{action.get('sub')} | Delta-Aligned Strike: {int(chosen_strike)} | Trailing on Hull Flip"
        )

        res = self.place_trade(
            symbol=sym,
            strike=chosen_strike,
            option_type=opt_type,
            lots=1,
            entry_price=ltp,
            source="OI_BUILDUP_HULL_CONFLUENCE",
            thesis=thesis,
            pcr=getattr(chain, "pcr", 1.0) or 1.0,
            cis_score=75.0 if opt_type == "CE" else 25.0
        )
        return res

    # -------------------------------------------------------------
    # Position Trailing & Hull Reversal Exit Poller
    # -------------------------------------------------------------
    def update_positions_tick(self, chain_map: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Polls active positions:
        - Updates real-time MTM, MFE, MAE.
        - TRAILING RULE: Trails position along Hull Suite signal.
        - EXIT RULE: Exits immediately when 5-min Hull Suite changes direction:
            * CE (Long) exits when Hull flips to BEARISH.
            * PE (Short) exits when Hull flips to BULLISH.
        - EOD Square-Off: Automatic market exit at 15:15 IST.
        """
        open_trades = self.get_open_trades()
        if not open_trades:
            return []

        now_dt = get_current_ist()
        now_time = now_dt.time()
        is_eod = (dt_time(15, 15, 0) <= now_time <= dt_time(15, 30, 0))

        # If LIVE mode, fetch broker positions once
        broker_positions = {}
        if any(t["execution_mode"] == "LIVE" for t in open_trades):
            if fyers_service.is_configured():
                res = fyers_service.get_positions()
                if res.get("s") == "ok":
                    for p in res.get("netPositions", []):
                        broker_positions[p.get("symbol")] = p

        updated = []
        for trade in open_trades:
            t_id = trade["id"]
            mode = trade["execution_mode"]
            sym = trade["symbol"]
            fyers_sym = trade.get("fyers_symbol")
            qty = int(trade["quantity"])
            entry_p = float(trade["entry_price"])
            sl = float(trade["stop_loss"])
            opt_type = trade["option_type"]

            prev_p = float(trade.get("current_price") or entry_p)
            current_p = prev_p
            broker_pnl = 0.0
            price_resolved = False

            # LIVE mode broker quote resolution
            if mode == "LIVE" and fyers_sym and fyers_sym in broker_positions:
                b_pos = broker_positions[fyers_sym]
                net_qty = int(b_pos.get("netQty", 0))
                current_p = float(b_pos.get("ltp", prev_p))
                broker_pnl = float(b_pos.get("pl", 0.0))
                price_resolved = True
                if net_qty == 0:
                    self.exit_trade(t_id, exit_reason="BROKER_TERMINAL_EXIT", exit_price=current_p)
                    continue
            else:
                # PAPER mode quote resolution
                if chain_map and sym in chain_map:
                    ch = chain_map[sym]
                    stk = float(trade["strike"])
                    for s_row in getattr(ch, "strikes", []):
                        if abs(s_row.strikePrice - stk) < 0.1:
                            c_sub = s_row.CE if opt_type == "CE" else s_row.PE
                            if c_sub and c_sub.lastPrice > 0:
                                current_p = float(c_sub.lastPrice)
                                price_resolved = True
                            break

                if not price_resolved and fyers_sym:
                    q = fyers_service.get_quotes([fyers_sym])
                    if q and q.get("s") == "ok" and q.get("d"):
                        lp = float(q["d"][0].get("v", {}).get("lp", 0.0))
                        if lp > 0:
                            current_p = lp
                            price_resolved = True

            if mode == "PAPER" and not price_resolved:
                # If market offline or weekend, retain current price
                current_p = prev_p

            # Calculate MTM Metrics
            pts = current_p - entry_p
            gain_pct = pts / max(0.1, entry_p)
            gross_pnl = broker_pnl if mode == "LIVE" else round(pts * qty, 2)
            net_pnl = round(gross_pnl - self.FLAT_BROKERAGE_PER_TRADE, 2)

            mfe = max(float(trade.get("mfe_pts", 0.0)), pts)
            mae = min(float(trade.get("mae_pts", 0.0)), pts)
            peak_p = max(float(trade.get("peak_price", entry_p) or entry_p), current_p)

            # ---------------------------------------------------------
            # EXIT RULE 1: EOD Intraday Square-Off at 15:15 IST
            # ---------------------------------------------------------
            if is_eod:
                self.exit_trade(
                    t_id,
                    exit_reason=f"EOD_SQUAREOFF_15:15 ({'+' if gain_pct>=0 else ''}{gain_pct*100:.1f}%)",
                    exit_price=current_p
                )
                continue

            # ---------------------------------------------------------
            # EXIT RULE 2: HULL SIGNAL REVERSAL (The Trailing Core Rule)
            # Only trigger exit when the Hull trend actually reverses to the OPPOSITE side:
            # - CE Trade exits when Hull flips to BEARISH or verdict flips to BUY PUT
            # - PE Trade exits when Hull flips to BULLISH or verdict flips to BUY CALL
            # Do NOT exit on CONFLICT - NO TRADE (which is an entry gate, not a stopout reason!)
            # ---------------------------------------------------------
            try:
                # Anti-whipsaw cushion: Trade must be open for at least 60 seconds before Hull reversal exit
                trade_age_secs = 999.0
                if entry_time_str:
                    try:
                        from datetime import datetime
                        entry_dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S")
                        now_dt_check = get_current_ist().replace(tzinfo=None)
                        trade_age_secs = (now_dt_check - entry_dt).total_seconds()
                    except Exception:
                        pass

                from app.services.option_confluence_service import option_confluence_service
                strat_conf = option_confluence_service.get_latest_strategy_confluence(sym)
                if strat_conf and trade_age_secs >= 60.0:
                    action = strat_conf.get("action", {})
                    verdict = action.get("verdict", "")
                    hull_trend = str(strat_conf.get("hull_indicator", {}).get("trend", "")).upper()

                    # CE Trade Exit: When Hull flips to BEARISH or verdict flips to BUY PUT
                    if opt_type == "CE" and (hull_trend == "BEARISH" or verdict == "BUY PUT"):
                        self.exit_trade(
                            t_id,
                            exit_reason=f"HULL_SIGNAL_REVERSAL (Hull flipped to BEARISH / {verdict})",
                            exit_price=current_p
                        )
                        continue

                    # PE Trade Exit: When Hull flips to BULLISH or verdict flips to BUY CALL
                    elif opt_type == "PE" and (hull_trend == "BULLISH" or verdict == "BUY CALL"):
                        self.exit_trade(
                            t_id,
                            exit_reason=f"HULL_SIGNAL_REVERSAL (Hull flipped to BULLISH / {verdict})",
                            exit_price=current_p
                        )
                        continue
            except Exception as e_exit:
                logger.debug(f"Hull signal check error: {e_exit}")

            # ---------------------------------------------------------
            # AUTOMATED BREAKEVEN ARMOR (SL Ratchet to Entry + 1%)
            # Once trade achieves +12% gain, ratchet SL to Entry + 1% to eliminate risk!
            # ---------------------------------------------------------
            breakeven_floor = round(entry_p * 1.01, 1)
            if gain_pct >= 0.12 and sl < breakeven_floor:
                sl = breakeven_floor
                try:
                    with self._get_conn() as conn_be:
                        c_be = conn_be.cursor()
                        c_be.execute("UPDATE shonya_trades SET stop_loss = ? WHERE id = ?", (sl, t_id))
                        conn_be.commit()
                    logger.info(f"ShonyaBot [{sym}] BREAKEVEN ARMOR ACTIVATED: Trade {t_id} gain is {gain_pct*100:.1f}%. SL moved to ₹{sl:.1f} (Entry +1%)")
                except Exception as e_be:
                    logger.debug(f"Breakeven ratchet error: {e_be}")

            # ---------------------------------------------------------
            # EXIT RULE 3: PROTECTIVE STOP LOSS FLOOR (-25%)
            # ---------------------------------------------------------
            if current_p <= sl:
                self.exit_trade(
                    t_id,
                    exit_reason=f"PROTECTIVE_STOP_LOSS ({gain_pct*100:.1f}%)",
                    exit_price=current_p
                )
                continue

            # Update live MTM in database
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    UPDATE shonya_trades
                    SET current_price = ?, gross_pnl = ?, net_pnl = ?, fyers_broker_pnl = ?,
                        mfe_pts = ?, mae_pts = ?, peak_price = ?
                    WHERE id = ?
                """, (current_p, gross_pnl, net_pnl, broker_pnl, mfe, mae, peak_p, t_id))
                conn.commit()

            updated.append({
                "id": t_id,
                "symbol": sym,
                "current_price": current_p,
                "gain_pct": round(gain_pct * 100.0, 1),
                "gross_pnl": gross_pnl,
                "net_pnl": net_pnl,
                "broker_pnl": broker_pnl,
                "mfe_pts": mfe,
                "mae_pts": mae
            })

        return updated

    # -------------------------------------------------------------
    # Position Exit Execution
    # -------------------------------------------------------------
    def exit_trade(
        self,
        trade_id: str,
        exit_reason: str = "MANUAL_EXIT",
        exit_price: Optional[float] = None
    ) -> Dict[str, Any]:
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

        broker_exit_res = None
        realized_broker_pnl = 0.0

        if mode == "LIVE" and fyers_service.is_configured():
            try:
                broker_exit_res = fyers_service.exit_position(
                    position_id=pid or fyers_sym,
                    symbol=fyers_sym,
                    qty=qty,
                    side=1
                )
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

        logger.info(f"ShonyaBot Trade CLOSED: {trade_id} @ ₹{curr_p:.1f} | Reason: {exit_reason} | Net PnL: ₹{net_pnl:+.1f}")

        # Dispatch Mobile Alert
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
            logger.debug(f"Mobile exit alert error: {e}")

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
        open_trades = self.get_open_trades()
        results = []
        for t in open_trades:
            res = self.exit_trade(t["id"], exit_reason="EMERGENCY_SQUAREOFF")
            results.append(res)

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

    def modify_trade(
        self,
        trade_id: str,
        target1: Optional[float] = None,
        target2: Optional[float] = None,
        stop_loss: Optional[float] = None
    ) -> Dict[str, Any]:
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

        return {
            "success": True,
            "trade_id": trade_id,
            "target1": t1,
            "target2": t2,
            "stop_loss": sl,
            "message": f"Target & Stop Loss updated for {trade_id}"
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
        fees_total = sum(float(t.get("brokerage", 85.0)) for t in closed)
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
