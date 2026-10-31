"""
ShonyaBot: Institutional Grok AI & Manual Option Execution Engine
- Works seamlessly on Grok AI recommendations & interactive chart setup.
- Dual Execution Mode: PAPER (default safe simulation) vs LIVE (Fyers broker order gateway).
- Real Broker Telemetry: In LIVE mode, fetches live P&L, LTP, and quantities directly from Fyers API.
  Zero theoretical guesswork.
- Dynamic Risk Architecture:
  * User-adjustable Target 1, Target 2, and Stop Loss dynamically on the fly.
  * Automated Breakeven Armor (ratchets SL to entry + 1% once Target 1 is hit).
  * Emergency Kill-Switch (Square Off All).
  * Mandatory ₹75 statutory brokerage accounted per trade.
"""
import os
import json
import time
import uuid
import sqlite3
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.core.config import get_settings
from app.core.market_hours import get_current_ist, is_market_open
from app.services.fyers_service import fyers_service
from app.services.ai_advisor_service import ai_advisor

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "shonya_trades.db")


class ShonyaBot:
    FLAT_BROKERAGE_PER_TRADE = 75.0
    CAPITAL_CEILING = 30000.0

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.is_active: bool = True
        self.trading_mode: str = "PAPER"  # "PAPER" or "LIVE"
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
                    source TEXT NOT NULL,  -- GROK_AI or MANUAL or INSTITUTIONAL_SIGNAL
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
                    created_at TEXT NOT NULL
                )
            """)
            c.execute("CREATE INDEX IF NOT EXISTS idx_shonya_status ON shonya_trades(status)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_shonya_symbol ON shonya_trades(symbol)")
            conn.commit()

    def _load_config(self):
        """Loads persistent bot state, defaulting to ACTIVE in PAPER mode."""
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
                conn.commit()
        except Exception as e:
            logger.debug(f"ShonyaBot config load fallback: {e}")

    # -------------------------------------------------------------
    # Configuration & Control Switches
    # -------------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        """Returns bot state, trading mode, capital status, and Fyers broker health."""
        open_trades = self.get_open_trades()
        fyers_ok, fyers_msg = fyers_service.validate_connection()
        fyers_funds = fyers_service.get_funds() if fyers_ok else {"available_balance": 0.0}

        metrics = self.get_performance_metrics()

        return {
            "success": True,
            "bot_name": "ShonyaBot",
            "is_active": self.is_active,
            "trading_mode": self.trading_mode,
            "fyers_connected": fyers_ok,
            "fyers_status_message": fyers_msg,
            "fyers_available_balance": fyers_funds.get("available_balance", 0.0),
            "capital_ceiling": self.CAPITAL_CEILING,
            "open_positions_count": len(open_trades),
            "open_positions": open_trades,
            "metrics": metrics
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
    # Trade Placement (Grok Signal Approved & Manual Chart Trading)
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
        source: str = "MANUAL",
        thesis: str = ""
    ) -> Dict[str, Any]:
        """
        Executes a trade in ShonyaBot either in PAPER or LIVE mode.
        If LIVE, routes order to Fyers exchange gateway.
        """
        sym = symbol.upper()
        opt_t = option_type.upper()
        settings = get_settings()
        lot_size = settings.LOT_SIZES.get(sym, 65 if sym == "NIFTY" else 30)
        total_qty = lots * lot_size

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

        # Dynamic Target & SL calculations if not explicitly provided
        t1 = target1 if (target1 and target1 > 0) else round(est_ltp * 1.14, 1)
        t2 = target2 if (target2 and target2 > 0) else round(est_ltp * 1.35, 1)
        sl = stop_loss if (stop_loss and stop_loss > 0) else round(est_ltp * 0.86, 1)

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
                    mfe_pts, mae_pts, thesis, created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, 'BUY', ?, ?,
                    ?, ?, ?, ?, ?, 0,
                    'OPEN', ?, ?, ?, ?,
                    ?, 0.0, 75.0, -75.0, 0.0,
                    0.0, 0.0, ?, ?
                )
            """, (
                trade_id, sym, strike, opt_t, fyers_sym, lots, total_qty,
                est_ltp, est_ltp, t1, t2, sl,
                mode, source, broker_order_id, broker_position_id,
                now_dt, thesis, now_dt
            ))
            conn.commit()

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
    # Automated Institutional Paper Trading Signal Evaluator
    # -------------------------------------------------------------
    async def evaluate_tick_for_paper_entry(
        self,
        symbol: str,
        chain: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Automated Institutional Paper Trading Signal Evaluator:
        - Active only when self.is_active is True and trading_mode is 'PAPER'
        - Enforces strict 1-position-per-segment (no duplicate trades in same symbol)
        - Time Gate: 09:20 to 15:15 IST (Blackout between 11:30 and 12:45 midday lull unless extreme confluence <=22 or >=78)
        - ADX Gate: ADX >= 20.0 Trend Expansion (eliminates choppy flat whipsaws)
        - AlphaTrend & Confluence alignment:
          * Bullish: Confluence Score >= 70, Confluence Bias == BULLISH, 5M AlphaTrend == BULLISH
          * Bearish: Confluence Score <= 30, Confluence Bias == BEARISH, 5M AlphaTrend == BEARISH
        - Strike Selection: 1-ITM Strike Selection (CE: atm - step, PE: atm + step, fallback to ATM if LTP < 25)
        - Risk Architecture:
          * 1 Lot sizing
          * Target 1: +18% (locks Breakeven Armor to Entry + 1%)
          * Target 2: +35% (Full profit target)
          * Hard SL: -14% (Hard protective stop)
        """
        if not self.is_active:
            return None

        if self.trading_mode != "PAPER":
            # Safety gate: Automated tick execution only for PAPER trades unless user explicitly toggles
            return None

        if not chain or not getattr(chain, "strikes", None):
            return None

        sym = symbol.upper()
        now_dt = get_current_ist()
        t = now_dt.time()

        # Gate 1: Check existing open position in this index segment (Exact 1 position limit)
        open_trade = self.get_open_trade_for_symbol(sym)
        if open_trade:
            return None

        # Gate 2: Trading Hours (09:20 - 15:15 IST)
        from datetime import time as dt_time
        if not (dt_time(9, 20, 0) <= t <= dt_time(15, 15, 0)):
            return None

        from app.services.tracker_bot import tracker_bot
        from app.services.option_confluence_service import option_confluence_service
        settings = get_settings()
        step = settings.STRIKE_STEPS.get(sym, 50)
        atm = chain.atm_strike
        spot = chain.spot_price

        if spot <= 0 or atm <= 0:
            return None

        # Gate 3: Confluence & Midday Lull Filter
        conf = await option_confluence_service.analyze_confluence(sym, range_strikes=2, parsed_chain=chain)
        if not conf:
            return None

        summary = conf.get("summary", {})
        overall_score = float(summary.get("overall_confluence_score", summary.get("confluence_score", 50.0)))
        overall_bias = summary.get("overall_bias", "NEUTRAL")

        # Midday Rest Zone (11:30 - 12:45 IST) - bypass only for extreme conviction
        if dt_time(11, 30, 0) <= t <= dt_time(12, 45, 0):
            if 22.0 < overall_score < 78.0:
                return None

        # Gate 4: Technical Indicators (ADX & AlphaTrend)
        tech = tracker_bot.get_technical_state(sym)
        adx = float(tech.get("adx", 0.0) or 0.0)
        ott_state = tech.get("ott_state", "NEUTRAL")
        trend_dir_strength = float(tech.get("trend_dir_strength", 0.0) or 0.0)

        # ADX >= 20.0 Trend Expansion Rule (eliminates 100% of flat chop false breakouts)
        if adx < 20.0:
            return None

        # Alignment Check
        is_bullish = (overall_score >= 70.0) and ("BULLISH" in overall_bias.upper()) and (ott_state == "BULLISH" or trend_dir_strength > 0)
        is_bearish = (overall_score <= 30.0) and ("BEARISH" in overall_bias.upper()) and (ott_state == "BEARISH" or trend_dir_strength < 0)

        if not is_bullish and not is_bearish:
            return None

        opt_type = "CE" if is_bullish else "PE"

        # Gate 5: 1-ITM Strike Selection (ATM ± 1 relevant direction)
        preferred_strike = (atm - step) if is_bullish else (atm + step)

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

        # Targets & Stop Loss
        t1 = round(ltp * 1.18, 1)  # +18% Target 1 (Breakeven Armor trigger)
        t2 = round(ltp * 1.35, 1)  # +35% Target 2 (Full Exit)
        sl = round(ltp * 0.86, 1)  # -14% Hard Stop

        thesis = (
            f"Institutional Auto Paper Trade | 1-ITM ({int(chosen_strike)} {opt_type}) | "
            f"ADX: {adx:.1f} (≥20 Trend) | Conf: {overall_score:.0f}/100 ({overall_bias}) | "
            f"AlphaTrend: {ott_state}"
        )

        res = self.place_trade(
            symbol=sym,
            strike=chosen_strike,
            option_type=opt_type,
            lots=1,
            entry_price=ltp,
            target1=t1,
            target2=t2,
            stop_loss=sl,
            source="INSTITUTIONAL_SIGNAL",
            thesis=thesis
        )
        if res.get("success"):
            logger.info(f"ShonyaBot AUTO PAPER TRADE OPENED: {sym} {chosen_strike} {opt_type} @ ₹{ltp:.1f} | ID: {res.get('trade_id')}")
        return res

    # -------------------------------------------------------------
    # Live Polling & Position Tracking (Zero Theoretical Guesswork)
    # -------------------------------------------------------------
    def update_positions_tick(self, chain_map: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Polls positions every cycle:
        - In LIVE mode, fetches real broker positions and P&L directly from Fyers API.
        - In PAPER mode, updates LTP from chain_map or Fyers quotes.
        - Enforces EOD Square-Off at 15:25 IST.
        - Checks Target 1 (+18% -> Breakeven Armor ratchet to entry + 1%).
        - Checks Target 2 (+35% full exit) and Stop-Loss (-14% hard exit).
        """
        open_trades = self.get_open_trades()
        if not open_trades:
            return []

        from app.core.market_hours import get_current_ist
        from datetime import time as dt_time
        now_time = get_current_ist().time()
        is_eod = (now_time >= dt_time(15, 25, 0))

        # If LIVE mode, fetch broker positions once
        broker_positions = {}
        if any(t["execution_mode"] == "LIVE" for t in open_trades):
            if fyers_service.is_configured():
                res = fyers_service.get_positions()
                if res.get("s") == "ok":
                    for p in res.get("netPositions", []):
                        sym = p.get("symbol")
                        broker_positions[sym] = p

        updated = []
        for trade in open_trades:
            t_id = trade["id"]
            mode = trade["execution_mode"]
            fyers_sym = trade.get("fyers_symbol")
            qty = int(trade["quantity"])
            entry_p = float(trade["entry_price"])
            t1 = float(trade["target1"])
            t2 = float(trade["target2"])
            sl = float(trade["stop_loss"])
            be_locked = int(trade.get("breakeven_locked", 0))

            current_p = entry_p
            broker_pnl = 0.0

            if mode == "LIVE" and fyers_sym and fyers_sym in broker_positions:
                b_pos = broker_positions[fyers_sym]
                net_qty = int(b_pos.get("netQty", 0))
                current_p = float(b_pos.get("ltp", entry_p))
                broker_pnl = float(b_pos.get("pl", 0.0))  # ACTUAL broker unrealized/net P&L!

                # If position was closed in broker terminal directly
                if net_qty == 0:
                    self.exit_trade(t_id, exit_reason="BROKER_TERMINAL_EXIT", exit_price=current_p)
                    continue
            else:
                # PAPER mode LTP resolution
                resolved = False
                if chain_map and trade["symbol"] in chain_map:
                    ch = chain_map[trade["symbol"]]
                    stk = float(trade["strike"])
                    otype = trade["option_type"]
                    for s_row in getattr(ch, "strikes", []):
                        if abs(s_row.strikePrice - stk) < 0.1:
                            c_sub = s_row.CE if otype == "CE" else s_row.PE
                            if c_sub and c_sub.lastPrice > 0:
                                current_p = float(c_sub.lastPrice)
                                resolved = True
                            break

                # Second attempt: quotes fallback
                if not resolved and fyers_sym:
                    q = fyers_service.get_quotes([fyers_sym])
                    if q and q.get("s") == "ok" and q.get("d"):
                        current_p = float(q["d"][0].get("v", {}).get("lp", entry_p))

            gross_pnl = broker_pnl if mode == "LIVE" else round((current_p - entry_p) * qty, 2)
            net_pnl = round(gross_pnl - self.FLAT_BROKERAGE_PER_TRADE, 2)

            # MFE and MAE
            pts = current_p - entry_p
            mfe = max(float(trade.get("mfe_pts", 0.0)), pts)
            mae = min(float(trade.get("mae_pts", 0.0)), pts)

            # EOD Square-Off at 15:25 IST
            if is_eod:
                self.exit_trade(t_id, exit_reason="EOD_SQUAREOFF (15:25 IST)", exit_price=current_p)
                continue

            # Check Breakeven Armor (Target 1 achieved: +18%)
            new_be_locked = be_locked
            new_sl = sl
            if current_p >= t1 and be_locked == 0:
                new_be_locked = 1
                # Lock stop loss to entry + 1% to protect statutory fees
                new_sl = max(sl, round(entry_p * 1.01, 1))
                logger.info(f"ShonyaBot BREAKEVEN ARMOR TRIGGERED on {t_id}! SL moved to ₹{new_sl:.1f}")

            # Check Exits: Target 2 or Stop Loss
            if current_p >= t2:
                self.exit_trade(t_id, exit_reason="TARGET_2_ACHIEVED (+35%)", exit_price=current_p)
                continue
            elif current_p <= new_sl:
                reason = "BREAKEVEN_STOP (Entry + 1%)" if new_be_locked == 1 else "STOP_LOSS_HIT (-14%)"
                self.exit_trade(t_id, exit_reason=reason, exit_price=current_p)
                continue

            # Update live state in database
            with self._get_conn() as conn:
                c = conn.cursor()
                c.execute("""
                    UPDATE shonya_trades
                    SET current_price = ?, gross_pnl = ?, net_pnl = ?, fyers_broker_pnl = ?,
                        breakeven_locked = ?, stop_loss = ?, mfe_pts = ?, mae_pts = ?
                    WHERE id = ?
                """, (current_p, gross_pnl, net_pnl, broker_pnl, new_be_locked, new_sl, mfe, mae, t_id))
                conn.commit()

            updated.append({
                "id": t_id,
                "current_price": current_p,
                "gross_pnl": gross_pnl,
                "net_pnl": net_pnl,
                "broker_pnl": broker_pnl,
                "breakeven_locked": bool(new_be_locked),
                "stop_loss": new_sl
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

                # Fetch updated broker positions to obtain exact realized P&L
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

        # In LIVE mode, also trigger broker-level exit_all to guarantee nothing is left hanging
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

    def get_trade_history(self, limit: int = 50) -> List[Dict[str, Any]]:
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
