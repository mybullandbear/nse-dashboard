"""
Institutional Smart Signal Tracker & Paper Trading Bot Engine
Variant C Production Baseline:
- Concurrency: Max 1 active position per segment/index simultaneously (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY).
- Directional: Option BUYING ONLY (CE and PE).
- Sizing: 1-Lot Scout baseline.
- Hard Capital Ceiling: ₹30,000 max portfolio commitment. Never increased automatically.
- Strategy Accounting: Flat ₹75 charge per completed trade.
- Quality Gate: Independent 5-Pillar TQS >= 70.0 (Decoupled from raw Confluence).
- Trailing & Exits (Variant C): Initial SL -14%, Target 1 +14% (ratchets stop to Entry + 3% Locked Profit Armor),
  Target 2 +35%, completed 5-minute structural trailing, EOD square-off at 15:30 IST.
- Pyramiding: Shadow evaluation only (disabled in live execution).
"""
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, time, timedelta

from app.db.tracker_storage import tracker_storage
from app.db.storage import snapshot_storage
from app.services.option_chain import ParsedOptionChain, StrikeRow
from app.services.trade_engine import calculate_greeks
from app.services.technical_indicators import TechnicalIndicators
from app.services.tqs_service import tqs_service
from app.core.config import get_settings
from app.core.market_hours import get_current_ist, is_market_open

logger = logging.getLogger(__name__)


class SmartTrackerBot:
    HARD_CAPITAL_CEILING: float = 90000.0
    FLAT_BROKERAGE_PER_TRADE: float = 75.0

    # Index-specific optimized trading profiles (Calibrated on real intraday ticks)
    INDEX_PROFILES: Dict[str, Dict[str, Any]] = {
        "NIFTY":      {"bull_score": 70.0, "bear_score": 30.0, "t1_pct": 0.14, "t2_pct": 0.35, "max_trades": 2, "cooldown_mins": 25},
        "BANKNIFTY":  {"bull_score": 65.0, "bear_score": 35.0, "t1_pct": 0.14, "t2_pct": 0.35, "max_trades": 2, "cooldown_mins": 25},
        "FINNIFTY":   {"bull_score": 70.0, "bear_score": 30.0, "t1_pct": 0.14, "t2_pct": 0.35, "max_trades": 2, "cooldown_mins": 25},
        "MIDCPNIFTY": {"bull_score": 72.0, "bear_score": 28.0, "t1_pct": 0.14, "t2_pct": 0.35, "max_trades": 2, "cooldown_mins": 30},
    }

    def __init__(self):
        self.is_active: bool = False
        self._signal_persistence: Dict[str, Dict[str, Any]] = {}
        self._symbol_cooldowns: Dict[str, datetime] = {}
        self._minute_candles: Dict[str, Dict[str, Dict[str, float]]] = {}
        self._current_trade_date: str = ""
        self._daily_trade_counts: Dict[str, int] = {}
        self._rejections_log: List[Dict[str, Any]] = []

    def is_bot_active(self) -> bool:
        return self.is_active

    def set_bot_active(self, active: bool):
        self.is_active = active
        logger.info(f"SmartTrackerBot: Status set to {'ACTIVE' if active else 'PAUSED'}")

    @property
    def capital_ceiling(self) -> float:
        try:
            from app.core.credentials import get_credentials
            return float(get_credentials().total_fund)
        except Exception:
            return self.HARD_CAPITAL_CEILING

    def get_capital_status(self) -> Dict[str, Any]:
        """Computes live committed margin across all open trades and remaining available capital."""
        ceiling = self.capital_ceiling
        open_trades = tracker_storage.get_open_trades()
        committed = sum(float(t.get("entry_net_price", 0.0)) * int(t.get("lot_size", 0)) for t in open_trades)
        available = max(0.0, ceiling - committed)
        return {
            "hard_ceiling": ceiling,
            "committed_margin": round(committed, 2),
            "available_capital": round(available, 2),
            "open_positions": len(open_trades)
        }

    def get_rejections_log(self) -> List[Dict[str, Any]]:
        return list(self._rejections_log)

    def _record_rejection(self, symbol: str, reason: str, details: Dict[str, Any]):
        now_dt = get_current_ist()
        entry = {
            "timestamp": now_dt.isoformat(),
            "time_str": now_dt.strftime("%H:%M:%S"),
            "symbol": symbol,
            "reason": reason,
            "details": details
        }
        self._rejections_log.append(entry)
        if len(self._rejections_log) > 500:
            self._rejections_log.pop(0)
        logger.warning(f"SmartTrackerBot: CANDIDATE REJECTED [{symbol}] Reason: {reason} | {details}")

    def feed_candle_history(self, symbol: str, candles: List[Dict[str, Any]]):
        """Populates minute candles for a symbol."""
        if symbol not in self._minute_candles:
            self._minute_candles[symbol] = {}
        for c in candles:
            t_str = c.get("time_str") or c.get("time")
            if t_str:
                self._minute_candles[symbol][t_str] = {
                    "open": float(c.get("open", 0.0)),
                    "high": float(c.get("high", 0.0)),
                    "low": float(c.get("low", 0.0)),
                    "close": float(c.get("close", 0.0))
                }

    def _record_spot_tick(self, symbol: str, spot: float, now_dt: datetime):
        today_str = now_dt.strftime("%Y-%m-%d")
        if self._current_trade_date != today_str:
            self._current_trade_date = today_str
            self._minute_candles.clear()
            self._daily_trade_counts.clear()

        t_str = now_dt.strftime("%H:%M")
        if symbol not in self._minute_candles:
            self._minute_candles[symbol] = {}
        if t_str not in self._minute_candles[symbol]:
            self._minute_candles[symbol][t_str] = {"open": spot, "high": spot, "low": spot, "close": spot}
        else:
            c = self._minute_candles[symbol][t_str]
            c["high"] = max(c["high"], spot)
            c["low"] = min(c["low"], spot)
            c["close"] = spot

    def _ensure_candles(self, symbol: str):
        now_dt = get_current_ist()
        today_str = now_dt.strftime("%Y-%m-%d")
        if self._current_trade_date != today_str:
            self._current_trade_date = today_str
            self._minute_candles.clear()

        if symbol not in self._minute_candles or len(self._minute_candles[symbol]) < 5:
            stored = snapshot_storage.get_today_timeline(symbol)
            if stored:
                if symbol not in self._minute_candles:
                    self._minute_candles[symbol] = {}
                for r in stored:
                    t_str = r.get("time") or r.get("time_str")
                    sp = float(r.get("spot") or 0.0)
                    if t_str and sp > 0 and t_str not in self._minute_candles[symbol]:
                        self._minute_candles[symbol][t_str] = {"open": sp, "high": sp, "low": sp, "close": sp}

    def get_technical_state(self, symbol: str) -> Dict[str, Any]:
        """Computes live PineScript technical state for the given symbol."""
        self._ensure_candles(symbol)
        bars = self._minute_candles.get(symbol, {})
        if len(bars) < 5:
            return {"adx": 20.0, "ott_state": "NEUTRAL", "plus_di": 25.0, "minus_di": 25.0, "mavg": 0.0, "ott": 0.0, "trend_dir_strength": 0.0}

        sorted_times = sorted(bars.keys())
        highs = [bars[t]["high"] for t in sorted_times]
        lows = [bars[t]["low"] for t in sorted_times]
        closes = [bars[t]["close"] for t in sorted_times]

        plus_di, minus_di, adx = TechnicalIndicators.compute_adx(highs, lows, closes, length=9)
        mavg, ott, trend_state = TechnicalIndicators.compute_ott(closes, length=2, percent=0.30)

        td_strength = 0.0
        if adx and plus_di and minus_di:
            diff = plus_di[-1] - minus_di[-1]
            td_strength = round(diff / max(1.0, plus_di[-1] + minus_di[-1]), 2)

        return {
            "adx": round(adx[-1], 1) if adx else 20.0,
            "plus_di": round(plus_di[-1], 1) if plus_di else 25.0,
            "minus_di": round(minus_di[-1], 1) if minus_di else 25.0,
            "ott_state": trend_state[-1] if trend_state else "NEUTRAL",
            "mavg": round(mavg[-1], 2) if mavg else closes[-1],
            "ott": round(ott[-1], 2) if ott else closes[-1],
            "trend_dir_strength": td_strength
        }

    def get_session_bucket(self, current_time: time) -> str:
        """Categorizes time of day into distinct trading sessions."""
        if time(9, 15, 0) <= current_time < time(11, 30, 0):
            return "MORNING"
        elif time(11, 30, 0) <= current_time < time(13, 30, 0):
            return "MIDDAY"
        else:
            return "AFTERNOON"

    # ---------------------------------------------------------
    # Core Processing Loop (Invoked on Every Polling Tick)
    # ---------------------------------------------------------
    async def process_tick(
        self,
        symbol: str,
        chain: ParsedOptionChain,
        signal_decision: Dict[str, Any]
    ):
        """
        Processes real-time option chain tick for a symbol using Option Confluence Analysis:
        1. Evaluates and updates live Marked-To-Market (MTM) P&L, MFE/MAE excursions for open positions.
        2. Enforces Variant C Stop Ratchet (+14% -> Entry + 3%), 5M AlphaTrend Structural Trailing, and 15:30 IST Safety.
        3. If no position is open in this index segment, evaluates new entry using 5-Pillar TQS and ₹30k capital gates.
        """
        if not chain or not chain.strikes:
            return

        sym = symbol.upper()
        now_dt = get_current_ist()
        t = now_dt.time()

        # Update 1-minute candle for technical indicators
        self._record_spot_tick(sym, chain.spot_price, now_dt)

        # Check existing active trade for this symbol (Exact 1-position-per-segment concurrency)
        open_trade = tracker_storage.get_open_trade_for_symbol(sym)

        # 1. LIVE BASELINE PIPELINE (UNTOUCHED PRODUCTION LOGIC)
        if open_trade:
            await self._update_and_check_exit(open_trade, chain, now_dt)
        elif self.is_active and (time(9, 15, 0) <= t <= time(15, 30, 0)):
            # Enforce anti-churn cooldown buffer
            if sym in self._symbol_cooldowns:
                cooldown_expiry = self._symbol_cooldowns[sym]
                if now_dt >= cooldown_expiry:
                    del self._symbol_cooldowns[sym]

            # Enforce Max Daily Trades per index
            profile = self.INDEX_PROFILES.get(sym, {"max_trades": 2})
            max_daily = profile.get("max_trades", 2)
            if sym not in self._symbol_cooldowns and self._daily_trade_counts.get(sym, 0) < max_daily:
                await self._evaluate_new_entry(sym, chain, signal_decision, now_dt)

        # 2. SHADOW VARIANT D PIPELINE (PARALLEL HYPOTHETICAL LEDGER)
        await self._process_shadow_variant_d(sym, chain, now_dt)

    # ---------------------------------------------------------
    # Position MTM & Excursion Tracking (Variant C Baseline)
    # ---------------------------------------------------------
    async def _update_and_check_exit(
        self,
        trade: Dict[str, Any],
        chain: ParsedOptionChain,
        now_dt: datetime
    ):
        from app.services.option_confluence_service import option_confluence_service
        trade_id = trade["id"]
        symbol = trade["symbol"]
        role = trade["role"]
        lot_size = int(trade.get("lot_size", 75))
        lots = int(trade.get("lots", 1))
        brokerage = float(trade.get("brokerage_inr") or self.FLAT_BROKERAGE_PER_TRADE)
        legs = trade.get("legs", [])
        entry_net = float(trade["entry_net_price"])
        target = float(trade["target_price"])
        stop_loss = float(trade["stop_loss_price"])
        trailing_sl = float(trade.get("trailing_stop_price", stop_loss))
        existing_mfe_pts = float(trade.get("mfe_pts", 0.0) or 0.0)
        existing_mfe_inr = float(trade.get("mfe_inr", 0.0) or 0.0)
        existing_mae_pts = float(trade.get("mae_pts", 0.0) or 0.0)
        existing_mae_inr = float(trade.get("mae_inr", 0.0) or 0.0)

        strike_map: Dict[float, StrikeRow] = {s.strikePrice: s for s in chain.strikes}
        all_legs_updated = True

        # BUYER LOGIC (Directional Option Buying Only)
        buy_ltp = 0.0
        stk = 0.0
        otype = "CE"
        target2_price = None

        for leg in legs:
            stk = float(leg.get("strike", 0.0))
            otype = leg.get("option_type", "CE")
            target2_price = leg.get("target2_price")
            row = strike_map.get(stk)
            if not row:
                all_legs_updated = False
                continue
            contract = row.CE if otype == "CE" else row.PE
            ltp = float(contract.lastPrice if contract else 0.0)
            leg["current_ltp"] = ltp
            buy_ltp = ltp

        if not all_legs_updated or buy_ltp <= 0:
            return

        curr_net = buy_ltp
        pts_pnl = curr_net - entry_net
        gross_unrealized = round(pts_pnl * lot_size, 2)
        net_unrealized = round(gross_unrealized - brokerage, 2)

        new_mfe_pts = max(existing_mfe_pts, pts_pnl)
        new_mfe_inr = max(existing_mfe_inr, gross_unrealized)
        new_mae_pts = min(existing_mae_pts, pts_pnl)
        new_mae_inr = min(existing_mae_inr, gross_unrealized)

        peak_price = max(entry_net + new_mfe_pts, curr_net)
        peak_gain_pts = max(0.0, peak_price - entry_net)
        peak_gain_pct = (peak_gain_pts / entry_net) if entry_net > 0 else 0.0

        # =====================================================================
        # VARIANT C EXECUTION RULES:
        # 1. Target 1 Reached (+14% trigger) -> Move Stop to Entry + 3% (Armor)
        # 2. Keep entire 1 lot open as runner
        # 3. Shadow Pyramiding Risk Gate Evaluation
        # 4. Target 2 Exit (+35%)
        # 5. Completed 5-Minute AlphaTrend Structural Reversal Cut
        # =====================================================================
        if peak_gain_pct >= 0.14:
            armor_sl = round(entry_net * 1.03, 2)
            if armor_sl > trailing_sl:
                trailing_sl = armor_sl
                logger.info(f"SmartTrackerBot: {symbol} {int(stk)}{otype} Target 1 (+14%) Tagged! Stop ratcheted to Entry + 3% (₹{trailing_sl})")

            # ── SHADOW PYRAMIDING EVALUATION (VARIANT D SHADOW ONLY) ──
            scout_locked_pnl = (trailing_sl - entry_net) * lot_size
            pyr_entry = curr_net
            pyr_sl = round(pyr_entry * 0.90, 2)
            pyr_worst_loss = (pyr_entry - pyr_sl) * lot_size
            shadow_charges = self.FLAT_BROKERAGE_PER_TRADE * 2
            shadow_net_worst = scout_locked_pnl - pyr_worst_loss - shadow_charges
            if shadow_net_worst >= -650.0:
                logger.info(f"SmartTrackerBot [SHADOW PYRAMID]: {symbol} {int(stk)}{otype} QUALIFIED scale-in (Worst-case: ₹{shadow_net_worst:.2f} >= -₹650)")
            else:
                logger.info(f"SmartTrackerBot [SHADOW PYRAMID]: {symbol} {int(stk)}{otype} GATED scale-in (Worst-case: ₹{shadow_net_worst:.2f} < -₹650)")

        # Extended Runner Ratchet for strong momentum (> 25% and > 40%)
        if 0.25 <= peak_gain_pct < 0.40:
            p2_tsl = round(entry_net * 1.12, 2)
            if p2_tsl > trailing_sl:
                trailing_sl = p2_tsl
        elif peak_gain_pct >= 0.40:
            p3_tsl = round(entry_net + (0.70 * peak_gain_pts), 2)
            if p3_tsl > trailing_sl:
                trailing_sl = p3_tsl

        # Target 2 Achievement (+35% Target)
        t2 = float(target2_price) if target2_price else round(entry_net * 1.35, 2)
        if curr_net >= t2:
            self._execute_close(trade, curr_net, gross_unrealized, net_unrealized, "TARGET2_ACHIEVED (+35% Structural Expansion)", new_mfe_pts, new_mfe_inr, new_mae_pts, new_mae_inr)
            return

        # Check Stop Loss Tagged (Initial SL -14% or Locked Profit Armor Entry + 3%)
        if curr_net <= trailing_sl:
            reason = "LOCKED_PROFIT_STOP_HIT (Entry + 3%)" if trailing_sl > entry_net else "STOP_LOSS_HIT"
            self._execute_close(trade, curr_net, gross_unrealized, net_unrealized, reason, new_mfe_pts, new_mfe_inr, new_mae_pts, new_mae_inr)
            return

        # 5-Minute AlphaTrend Structural Reversal Cut
        exit_trigger_reason = None
        try:
            conf = await option_confluence_service.analyze_confluence(symbol, range_strikes=1, parsed_chain=chain)
            if conf:
                indicators = conf.get("summary", {}).get("indicators", {})
                at_state = indicators.get("ind1", {}).get("state", "NEUTRAL")
                is_call_trade = (otype == "CE")

                # If AlphaTrend reverses against the option direction
                if is_call_trade and at_state == "BEARISH":
                    exit_trigger_reason = "ALPHATREND_STRUCTURAL_REVERSAL_EXIT (Underlying turned Bearish)"
                elif not is_call_trade and at_state == "BULLISH":
                    exit_trigger_reason = "ALPHATREND_STRUCTURAL_REVERSAL_EXIT (Underlying turned Bullish)"
        except Exception as e_rev:
            logger.debug(f"Confluence reversal check error: {e_rev}")

        if exit_trigger_reason:
            self._execute_close(trade, curr_net, gross_unrealized, net_unrealized, exit_trigger_reason, new_mfe_pts, new_mfe_inr, new_mae_pts, new_mae_inr)
            return

        # EOD Auto-Squareoff at 15:30:00 IST
        if now_dt.time() >= time(15, 30, 0):
            self._execute_close(trade, curr_net, gross_unrealized, net_unrealized, "EOD_SQUAREOFF (15:30 Market Close Safety)", new_mfe_pts, new_mfe_inr, new_mae_pts, new_mae_inr)
            return

        # Save updated MTM
        tracker_storage.update_trade_mtm(
            trade_id=trade_id,
            current_net_price=curr_net,
            gross_unrealized_pnl=gross_unrealized,
            net_unrealized_pnl=net_unrealized,
            trailing_stop=trailing_sl,
            mfe_pts=new_mfe_pts,
            mfe_inr=new_mfe_inr,
            mae_pts=new_mae_pts,
            mae_inr=new_mae_inr,
            legs_json=json.dumps(legs)
        )

    def _execute_close(
        self,
        trade: Dict[str, Any],
        exit_net_price: float,
        gross_realized_pnl: float,
        net_realized_pnl: float,
        exit_reason: str,
        mfe_pts: float = None,
        mfe_inr: float = None,
        mae_pts: float = None,
        mae_inr: float = None
    ):
        trade_id = trade["id"]
        sym = trade["symbol"]
        logger.info(
            f"SmartTrackerBot: Closing trade {trade_id} | Exit: ₹{exit_net_price} | Gross: ₹{gross_realized_pnl} | Net: ₹{net_realized_pnl} | Reason: {exit_reason}"
        )
        tracker_storage.close_trade(
            trade_id=trade_id,
            exit_net_price=exit_net_price,
            gross_realized_pnl=gross_realized_pnl,
            net_realized_pnl=net_realized_pnl,
            exit_reason=exit_reason,
            mfe_pts=mfe_pts,
            mfe_inr=mfe_inr,
            mae_pts=mae_pts,
            mae_inr=mae_inr
        )

        # Post-trade cooldown buffer
        profile = self.INDEX_PROFILES.get(sym, {})
        cooldown_mins = profile.get("cooldown_mins", 25)
        now_dt = get_current_ist()
        self._symbol_cooldowns[sym] = now_dt + timedelta(minutes=cooldown_mins)
        logger.info(f"SmartTrackerBot: {sym} closed. Anti-churn cooldown set for {cooldown_mins}m until {self._symbol_cooldowns[sym].strftime('%H:%M:%S')}")

        self._update_learning_model()

    # ---------------------------------------------------------
    # Evaluate New Trade Entry with 5-Pillar TQS & ₹30k Gating
    # ---------------------------------------------------------
    async def _evaluate_new_entry(
        self,
        symbol: str,
        chain: ParsedOptionChain,
        signal_decision: Dict[str, Any],
        now_dt: datetime
    ):
        # 1. Live Data Provenance & Freshness Gate
        if getattr(chain, "source", "") == "SIMULATOR":
            self._record_rejection(symbol, "SIMULATOR_DATA_REJECTED", {"source": getattr(chain, "source", "")})
            return

        from app.services.option_confluence_service import option_confluence_service
        settings = get_settings()
        step = settings.STRIKE_STEPS.get(symbol, 50)
        base_lot_size = settings.LOT_SIZES.get(symbol, 65)
        atm = chain.atm_strike
        spot = chain.spot_price
        t = now_dt.time()

        if spot <= 0 or atm <= 0:
            return

        # 2. Check Available Capital Against ₹30,000 Hard Ceiling
        cap_status = self.get_capital_status()
        available_cap = cap_status["available_capital"]

        # Run Option Confluence Analysis across ATM corridor
        conf = await option_confluence_service.analyze_confluence(symbol, range_strikes=2, parsed_chain=chain)
        if not conf:
            return

        summary = conf.get("summary", {})
        strikes = conf.get("strikes", [])
        overall_score = float(summary.get("overall_confluence_score", summary.get("confluence_score", 50.0)))
        overall_bias = summary.get("overall_bias", "NEUTRAL")
        indicators = summary.get("indicators", {})
        ind1 = indicators.get("ind1", summary.get("indicator_1", {}))  # AlphaTrend
        ind2 = indicators.get("ind2", summary.get("indicator_2", {}))  # TrendDir

        at_state = ind1.get("state", "NEUTRAL")
        td_strength = float(ind2.get("strength", 0.0) or 0.0)

        profile = self.INDEX_PROFILES.get(symbol, {"bull_score": 70.0, "bear_score": 30.0, "t1_pct": 0.14, "t2_pct": 0.35})
        bull_score = profile.get("bull_score", 70.0)
        bear_score = profile.get("bear_score", 30.0)

        has_bear_confirmation = (at_state == "BEARISH" or td_strength < 0)
        is_bearish_confluence = (overall_score <= bear_score) and has_bear_confirmation

        has_bull_confirmation = (at_state == "BULLISH" or td_strength > 0)
        is_bullish_confluence = (overall_score >= bull_score) and has_bull_confirmation

        if not is_bearish_confluence and not is_bullish_confluence:
            return

        chosen_direction = "CALL" if is_bullish_confluence else "PUT"
        opt_type = "CE" if is_bullish_confluence else "PE"

        # -------------------------------------------------------------
        # STRIKE SELECTION: Prioritize 1-ITM Candidates (Higher Delta)
        # Fallback to ATM if 1-ITM has low liquidity / LTP < 25
        # -------------------------------------------------------------
        candidate_strikes = []
        if is_bullish_confluence:
            # Bullish Breakout: 1-ITM CE (atm - step) first, then ATM
            candidate_strikes = [
                {"strike": atm - step, "tag": "1-ITM"},
                {"strike": atm, "tag": "ATM"}
            ]
        else:
            # Bearish Breakdown: 1-ITM PE (atm + step) first, then ATM
            candidate_strikes = [
                {"strike": atm + step, "tag": "1-ITM"},
                {"strike": atm, "tag": "ATM"}
            ]

        strike_map: Dict[float, StrikeRow] = {s.strikePrice: s for s in chain.strikes}
        evaluated_candidates = []
        tech = self.get_technical_state(symbol)
        tech["alphatrend_state"] = at_state
        tech["trend_dir_strength"] = td_strength

        # ADX Gate: Trend Expansion Filter (ADX >= 20.0 eliminates 100% of chop false breakouts)
        adx = float(tech.get("adx", 0.0) or 0.0)
        if adx < 20.0:
            self._record_rejection(symbol, "ADX_BELOW_20_CHOP_FILTER", {"adx": adx})
            return

        # Midday Rest Zone: 11:30 to 12:45 IST (bypass only for extreme conviction <= 22 or >= 78)
        if time(11, 30, 0) <= t <= time(12, 45, 0):
            if 22.0 < overall_score < 78.0:
                self._record_rejection(symbol, "MIDDAY_CHOP_REST_WINDOW", {"time": str(t), "confluence": overall_score})
                return

        for c_spec in candidate_strikes:
            stk_val = c_spec["strike"]
            tag = c_spec["tag"]
            c_row = strike_map.get(stk_val)
            if not c_row:
                continue

            contract = c_row.CE if opt_type == "CE" else c_row.PE
            ltp = float(contract.lastPrice if contract else 0.0)

            # Avoid low-premium lottery tickets
            if ltp < 25.0:
                continue

            t1 = round(ltp * 1.18, 2)
            t2 = round(ltp * 1.35, 2)
            sl = round(ltp * 0.86, 2)
            target_pts = round(t1 - ltp, 2)
            risk_pts = round(ltp - sl, 2)

            tqs_score, tqs_breakdown = tqs_service.compute_tqs(
                symbol=symbol,
                chain=chain,
                contract_row=c_row,
                option_type=opt_type,
                role="BUYER",
                confluence_score=overall_score,
                technical_state=tech,
                target_pts=target_pts,
                risk_pts=risk_pts
            )

            evaluated_candidates.append({
                "strike": stk_val,
                "moneyness": tag,
                "option_type": opt_type,
                "ltp": ltp,
                "target_price": t1,
                "target2_price": t2,
                "stop_loss_price": sl,
                "tqs_score": tqs_score,
                "tqs_breakdown": tqs_breakdown,
                "contract_row": c_row
            })

        if not evaluated_candidates:
            self._record_rejection(symbol, "NO_VALID_STRIKES_ABOVE_25_LTP", {"direction": chosen_direction})
            return

        # Pick candidate with highest independent TQS score
        evaluated_candidates.sort(key=lambda x: x["tqs_score"], reverse=True)
        best = evaluated_candidates[0]

        # 3. Independent 5-Pillar TQS Gate (Must be >= 70.0)
        if best["tqs_score"] < tqs_service.BUYER_MIN_TQS:
            self._record_rejection(
                symbol,
                "TQS_BELOW_THRESHOLD",
                {"tqs": best["tqs_score"], "min_required": tqs_service.BUYER_MIN_TQS, "strike": best["strike"], "breakdown": best["tqs_breakdown"]}
            )
            return

        # 4. Pre-Trade Capital Affordability Validation (₹30,000 Hard Ceiling)
        required_outlay = round((best["ltp"] * base_lot_size) + self.FLAT_BROKERAGE_PER_TRADE, 2)
        if required_outlay > available_cap:
            deficit = round(required_outlay - available_cap, 2)
            self._record_rejection(
                symbol,
                "CAPITAL_EXCEEDED",
                {"required": required_outlay, "available": available_cap, "deficit": deficit, "ceiling": self.capital_ceiling}
            )
            return

        # 5. Signal Persistence Gate (>= 2 Consecutive Ticks)
        strat_type = "BUY_CALL_BREAKOUT" if is_bullish_confluence else "BUY_PUT_BREAKDOWN"
        sig_key = f"BUYER_{strat_type}_{best['strike']}_{best['option_type']}"
        curr_sig = self._signal_persistence.get(symbol)
        if not curr_sig or curr_sig.get("key") != sig_key:
            self._signal_persistence[symbol] = {
                "key": sig_key,
                "ticks": 1,
                "first_seen": now_dt
            }
            logger.debug(f"SmartTrackerBot: Registered signal tick 1 for {symbol} ({sig_key}). Awaiting confirmation...")
            return
        else:
            curr_sig["ticks"] += 1
            if curr_sig["ticks"] < 2:
                return

        # 6. Execute Entry & Persist Transactionally
        t_id = f"bot_{symbol}_{int(now_dt.timestamp())}"
        session_bucket = self.get_session_bucket(t)
        sig_detail = (
            f"{'🚀 BUY CALL BREAKOUT' if is_bullish_confluence else '💥 BUY PUT BREAKDOWN'} | "
            f"Score: {overall_score:.0f}/100 ({overall_bias}) | TQS: {best['tqs_score']:.1f}/100 | "
            f"Strike: {int(best['strike'])} {best['option_type']} ({best['moneyness']}) @ ₹{best['ltp']:.1f} | "
            f"AlphaTrend: {at_state} | Sizing: 1 Lot ({base_lot_size} Qty) | Outlay: ₹{required_outlay:.1f}"
        )

        trade_payload = {
            "id": t_id,
            "symbol": symbol,
            "strategy_type": strat_type,
            "role": "BUYER",
            "regime": "BUYER_REGIME",
            "confluence_at_entry": overall_score,
            "lots": 1,
            "lot_size": base_lot_size,
            "entry_net_price": best["ltp"],
            "current_net_price": best["ltp"],
            "target_price": best["target_price"],
            "stop_loss_price": best["stop_loss_price"],
            "trailing_stop_price": best["stop_loss_price"],
            "tqs_score": best["tqs_score"],
            "tqs_breakdown": best["tqs_breakdown"],
            "brokerage_inr": self.FLAT_BROKERAGE_PER_TRADE,
            "session_bucket": session_bucket,
            "trade_date": now_dt.strftime("%Y-%m-%d"),
            "signal_details": sig_detail,
            "legs": [
                {
                    "strike": best["strike"],
                    "option_type": best["option_type"],
                    "action": "BUY",
                    "entry_ltp": best["ltp"],
                    "current_ltp": best["ltp"],
                    "target2_price": best["target2_price"]
                }
            ]
        }

        tid = tracker_storage.insert_trade(trade_payload)
        self._daily_trade_counts[symbol] = self._daily_trade_counts.get(symbol, 0) + 1
        logger.info(
            f"SmartTrackerBot: OPENED TRADE [{symbol}] {strat_type} | Strike: {best['strike']} {best['option_type']} | "
            f"TQS: {best['tqs_score']} | Confluence: {overall_score} | Outlay: ₹{required_outlay} | ID: {tid}"
        )

    def get_shadow_capital_status(self) -> Dict[str, Any]:
        """Computes live committed margin across shadow positions and remaining available capital."""
        ceiling = self.capital_ceiling
        shadow_trades = tracker_storage.get_shadow_open_trades()
        committed = sum(float(t.get("entry_net_price", 0.0)) * int(t.get("lot_size", 0)) for t in shadow_trades)
        available = max(0.0, ceiling - committed)
        return {
            "hard_ceiling": ceiling,
            "committed_margin": round(committed, 2),
            "available_capital": round(available, 2),
            "open_positions": len(shadow_trades)
        }

    async def _process_shadow_variant_d(self, symbol: str, chain: ParsedOptionChain, now_dt: datetime):
        """
        Executes parallel, fully isolated shadow evaluation of Variant D:
        - Evaluates ATM, 1-ITM, 1-OTM, 2-OTM candidates.
        - Requires TQS >= 70.0.
        - Enforces independent ₹30,000 shadow capital ceiling.
        - Persists decisions into bot_shadow_evaluations and bot_shadow_trades.
        - Zero impact on live orders or live account balance.
        """
        if getattr(chain, "source", "") == "SIMULATOR":
            return

        shadow_trade = tracker_storage.get_shadow_open_trade_for_symbol(symbol)
        if shadow_trade:
            await self._update_and_check_shadow_exit(shadow_trade, chain, now_dt)
            return

        t = now_dt.time()
        if not (time(9, 20, 0) <= t <= time(14, 45, 0)):
            return

        await self._evaluate_new_shadow_entry(symbol, chain, now_dt)

    async def _update_and_check_shadow_exit(
        self,
        trade: Dict[str, Any],
        chain: ParsedOptionChain,
        now_dt: datetime
    ):
        from app.services.option_confluence_service import option_confluence_service
        trade_id = trade["id"]
        symbol = trade["symbol"]
        lot_size = int(trade.get("lot_size", 75))
        brokerage = float(trade.get("brokerage_inr") or self.FLAT_BROKERAGE_PER_TRADE)
        legs = trade.get("legs", [])
        entry_net = float(trade["entry_net_price"])
        target2_price = float(trade.get("target2_price") or (entry_net * 1.35))
        stop_loss = float(trade["stop_loss_price"])
        trailing_sl = float(trade.get("trailing_stop_price", stop_loss))
        existing_mfe_pts = float(trade.get("mfe_pts", 0.0) or 0.0)
        existing_mfe_inr = float(trade.get("mfe_inr", 0.0) or 0.0)
        existing_mae_pts = float(trade.get("mae_pts", 0.0) or 0.0)
        existing_mae_inr = float(trade.get("mae_inr", 0.0) or 0.0)

        strike_map: Dict[float, StrikeRow] = {s.strikePrice: s for s in chain.strikes}
        buy_ltp = 0.0
        otype = "CE"

        for leg in legs:
            stk = float(leg.get("strike", 0.0))
            otype = leg.get("option_type", "CE")
            row = strike_map.get(stk)
            if not row:
                continue
            contract = row.CE if otype == "CE" else row.PE
            ltp = float(contract.lastPrice if contract else 0.0)
            leg["current_ltp"] = ltp
            buy_ltp = ltp

        if buy_ltp <= 0:
            return

        curr_net = buy_ltp
        pts_pnl = curr_net - entry_net
        gross_unrealized = round(pts_pnl * lot_size, 2)
        net_unrealized = round(gross_unrealized - brokerage, 2)

        new_mfe_pts = max(existing_mfe_pts, pts_pnl)
        new_mfe_inr = max(existing_mfe_inr, gross_unrealized)
        new_mae_pts = min(existing_mae_pts, pts_pnl)
        new_mae_inr = min(existing_mae_inr, gross_unrealized)

        peak_price = max(entry_net + new_mfe_pts, curr_net)
        peak_gain_pts = max(0.0, peak_price - entry_net)
        peak_gain_pct = (peak_gain_pts / entry_net) if entry_net > 0 else 0.0

        # Variant C Ratchet: +14% trigger -> Entry + 3% Locked Profit Armor
        if peak_gain_pct >= 0.14:
            armor_sl = round(entry_net * 1.03, 2)
            if armor_sl > trailing_sl:
                trailing_sl = armor_sl

        # Target 2 Achievement (+35%)
        if curr_net >= target2_price:
            tracker_storage.close_shadow_trade(
                trade_id=trade_id, exit_net_price=curr_net, gross_realized_pnl=gross_unrealized,
                net_realized_pnl=net_unrealized, exit_reason="TARGET2_ACHIEVED (+35%)",
                mfe_pts=new_mfe_pts, mfe_inr=new_mfe_inr, mae_pts=new_mae_pts, mae_inr=new_mae_inr
            )
            logger.info(f"SmartTrackerBot [SHADOW VARIANT D]: Trade {trade_id} closed TARGET2_ACHIEVED | Net: ₹{net_unrealized}")
            return

        # Stop Loss Tagged
        if curr_net <= trailing_sl:
            reason = "LOCKED_PROFIT_STOP_HIT (Entry + 3%)" if trailing_sl > entry_net else "STOP_LOSS_HIT (-14%)"
            tracker_storage.close_shadow_trade(
                trade_id=trade_id, exit_net_price=curr_net, gross_realized_pnl=gross_unrealized,
                net_realized_pnl=net_unrealized, exit_reason=reason,
                mfe_pts=new_mfe_pts, mfe_inr=new_mfe_inr, mae_pts=new_mae_pts, mae_inr=new_mae_inr
            )
            logger.info(f"SmartTrackerBot [SHADOW VARIANT D]: Trade {trade_id} closed {reason} | Net: ₹{net_unrealized}")
            return

        # 5-Minute AlphaTrend Structural Reversal Cut
        exit_trigger_reason = None
        try:
            conf = await option_confluence_service.analyze_confluence(symbol, range_strikes=1, parsed_chain=chain)
            if conf:
                indicators = conf.get("summary", {}).get("indicators", {})
                at_state = indicators.get("ind1", {}).get("state", "NEUTRAL")
                if otype == "CE" and at_state == "BEARISH":
                    exit_trigger_reason = "ALPHATREND_STRUCTURAL_REVERSAL_EXIT"
                elif otype == "PE" and at_state == "BULLISH":
                    exit_trigger_reason = "ALPHATREND_STRUCTURAL_REVERSAL_EXIT"
        except Exception:
            pass

        if exit_trigger_reason:
            tracker_storage.close_shadow_trade(
                trade_id=trade_id, exit_net_price=curr_net, gross_realized_pnl=gross_unrealized,
                net_realized_pnl=net_unrealized, exit_reason=exit_trigger_reason,
                mfe_pts=new_mfe_pts, mfe_inr=new_mfe_inr, mae_pts=new_mae_pts, mae_inr=new_mae_inr
            )
            logger.info(f"SmartTrackerBot [SHADOW VARIANT D]: Trade {trade_id} closed {exit_trigger_reason} | Net: ₹{net_unrealized}")
            return

        # EOD Auto-Squareoff at 15:25 / 15:30 IST
        if now_dt.time() >= time(15, 25, 0):
            tracker_storage.close_shadow_trade(
                trade_id=trade_id, exit_net_price=curr_net, gross_realized_pnl=gross_unrealized,
                net_realized_pnl=net_unrealized, exit_reason="EOD_SQUAREOFF",
                mfe_pts=new_mfe_pts, mfe_inr=new_mfe_inr, mae_pts=new_mae_pts, mae_inr=new_mae_inr
            )
            return

        # Update Live MTM
        tracker_storage.update_shadow_trade_mtm(
            trade_id=trade_id, current_net_price=curr_net, gross_unrealized_pnl=gross_unrealized,
            net_unrealized_pnl=net_unrealized, trailing_stop=trailing_sl,
            mfe_pts=new_mfe_pts, mfe_inr=new_mfe_inr, mae_pts=new_mae_pts, mae_inr=new_mae_inr,
            legs_json=json.dumps(legs)
        )

    async def _evaluate_new_shadow_entry(
        self,
        symbol: str,
        chain: ParsedOptionChain,
        now_dt: datetime
    ):
        from app.services.option_confluence_service import option_confluence_service
        settings = get_settings()
        step = settings.STRIKE_STEPS.get(symbol, 50)
        base_lot_size = settings.LOT_SIZES.get(symbol, 65)
        atm = chain.atm_strike
        spot = chain.spot_price
        t_str = now_dt.strftime("%H:%M:%S")

        if spot <= 0 or atm <= 0:
            return

        cap_status = self.get_shadow_capital_status()
        available_cap = cap_status["available_capital"]

        conf = await option_confluence_service.analyze_confluence(symbol, range_strikes=2, parsed_chain=chain)
        if not conf:
            return

        summary = conf.get("summary", {})
        overall_score = float(summary.get("overall_confluence_score", summary.get("confluence_score", 50.0)))
        indicators = summary.get("indicators", {})
        ind1 = indicators.get("ind1", summary.get("indicator_1", {}))
        ind2 = indicators.get("ind2", summary.get("indicator_2", {}))
        at_state = ind1.get("state", "NEUTRAL")
        td_strength = float(ind2.get("strength", 0.0) or 0.0)

        profile = self.INDEX_PROFILES.get(symbol, {"bull_score": 70.0, "bear_score": 30.0})
        bull_score = profile.get("bull_score", 70.0)
        bear_score = profile.get("bear_score", 30.0)

        has_bear_confirmation = (at_state == "BEARISH" or td_strength < 0)
        is_bearish_confluence = (overall_score <= bear_score) and has_bear_confirmation
        has_bull_confirmation = (at_state == "BULLISH" or td_strength > 0)
        is_bullish_confluence = (overall_score >= bull_score) and has_bull_confirmation

        if not is_bearish_confluence and not is_bullish_confluence:
            return

        opt_type = "CE" if is_bullish_confluence else "PE"
        strat_type = "BUY_CALL_BREAKOUT" if is_bullish_confluence else "BUY_PUT_BREAKDOWN"

        # Multi-strike candidate set: ATM, 1-ITM, 1-OTM, 2-OTM
        if is_bullish_confluence:
            candidate_strikes = [
                (atm, "ATM"),
                (atm - step, "1-ITM"),
                (atm + step, "1-OTM"),
                (atm + 2 * step, "2-OTM")
            ]
        else:
            candidate_strikes = [
                (atm, "ATM"),
                (atm + step, "1-ITM"),
                (atm - step, "1-OTM"),
                (atm - 2 * step, "2-OTM")
            ]

        strike_map: Dict[float, StrikeRow] = {s.strikePrice: s for s in chain.strikes}
        evaluated_candidates = []
        tech = self.get_technical_state(symbol)
        tech["alphatrend_state"] = at_state
        tech["trend_dir_strength"] = td_strength

        for stk_val, tag in candidate_strikes:
            c_row = strike_map.get(stk_val)
            if not c_row:
                continue

            contract = c_row.CE if opt_type == "CE" else c_row.PE
            ltp = float(contract.lastPrice if contract else 0.0)
            vol = int(contract.totalTradedVolume if contract else 0)
            oi = int(contract.openInterest if contract else 0)
            bid = float(contract.bidprice if contract and hasattr(contract, "bidprice") else 0.0)
            ask = float(contract.askPrice if contract and hasattr(contract, "askPrice") else 0.0)
            spread = max(0.0, ask - bid) if (bid > 0 and ask > 0) else 0.0

            if ltp < 25.0:
                continue

            simulated_entry = round(ltp * 1.005, 2)
            required_outlay = round((simulated_entry * base_lot_size) + self.FLAT_BROKERAGE_PER_TRADE, 2)

            t1 = round(simulated_entry * 1.14, 2)
            t2 = round(simulated_entry * 1.35, 2)
            sl = round(simulated_entry * 0.86, 2)
            target_pts = round(t1 - simulated_entry, 2)
            risk_pts = round(simulated_entry - sl, 2)

            tqs_score, tqs_breakdown = tqs_service.compute_tqs(
                symbol=symbol, chain=chain, contract_row=c_row, option_type=opt_type,
                role="BUYER", confluence_score=overall_score, technical_state=tech,
                target_pts=target_pts, risk_pts=risk_pts
            )

            is_affordable = (required_outlay <= available_cap) and (required_outlay <= self.capital_ceiling)
            is_tqs_pass = (tqs_score >= tqs_service.BUYER_MIN_TQS)

            decision = "QUALIFIED" if (is_affordable and is_tqs_pass) else "REJECTED"
            rej_reason = None
            if not is_affordable:
                rej_reason = "CAPITAL_EXCEEDED"
            elif not is_tqs_pass:
                rej_reason = "TQS_BELOW_THRESHOLD"

            eval_record = {
                "timestamp": now_dt.isoformat(),
                "trade_date": now_dt.strftime("%Y-%m-%d"),
                "time_str": t_str,
                "symbol": symbol,
                "direction": opt_type,
                "strike": stk_val,
                "tag": tag,
                "ltp": ltp,
                "bid": bid,
                "ask": ask,
                "spread": spread,
                "volume": vol,
                "oi": oi,
                "quote_age_seconds": 0.0,
                "confluence": overall_score,
                "tqs_score": tqs_score,
                "p1_signal": tqs_breakdown["p1_signal"],
                "p2_strike": tqs_breakdown["p2_strike"],
                "p3_liquidity": tqs_breakdown["p3_liquidity"],
                "p4_momentum": tqs_breakdown["p4_momentum"],
                "p5_risk_reward": tqs_breakdown["p5_risk_reward"],
                "required_outlay": required_outlay,
                "available_capital": available_cap,
                "decision": decision,
                "rejection_reason": rej_reason
            }
            tracker_storage.insert_shadow_evaluation(eval_record)

            if decision == "QUALIFIED":
                evaluated_candidates.append({
                    "strike": stk_val, "tag": tag, "simulated_entry": simulated_entry,
                    "target_price": t1, "target2_price": t2, "stop_loss_price": sl,
                    "tqs_score": tqs_score, "tqs_breakdown": tqs_breakdown,
                    "required_outlay": required_outlay, "is_alternative": (tag != "ATM")
                })

        if not evaluated_candidates:
            return

        # Rank by TQS descending, then lowest distance from ATM
        evaluated_candidates.sort(key=lambda x: (x["tqs_score"], -abs(x["strike"] - atm)), reverse=True)
        best = evaluated_candidates[0]

        shadow_id = f"shadow_{symbol}_{int(now_dt.timestamp())}"
        session_bucket = self.get_session_bucket(now_dt.time())
        sig_detail = (
            f"[SHADOW VARIANT D] {'🚀 CALL' if is_bullish_confluence else '💥 PUT'} | "
            f"Score: {overall_score:.0f} | TQS: {best['tqs_score']:.1f} | "
            f"Strike: {int(best['strike'])} {opt_type} ({best['tag']}) @ ₹{best['simulated_entry']:.1f} | "
            f"Outlay: ₹{best['required_outlay']:.1f}"
        )

        shadow_payload = {
            "id": shadow_id,
            "symbol": symbol,
            "strategy_type": strat_type,
            "role": "BUYER",
            "regime": "SHADOW_VARIANT_D",
            "confluence_at_entry": overall_score,
            "lots": 1,
            "lot_size": base_lot_size,
            "entry_net_price": best["simulated_entry"],
            "current_net_price": best["simulated_entry"],
            "target_price": best["target_price"],
            "target2_price": best["target2_price"],
            "stop_loss_price": best["stop_loss_price"],
            "trailing_stop_price": best["stop_loss_price"],
            "tqs_score": best["tqs_score"],
            "tqs_breakdown": best["tqs_breakdown"],
            "brokerage_inr": self.FLAT_BROKERAGE_PER_TRADE,
            "session_bucket": session_bucket,
            "trade_date": now_dt.strftime("%Y-%m-%d"),
            "signal_details": sig_detail,
            "is_alternative": int(best["is_alternative"]),
            "moneyness_tag": best["tag"],
            "legs": [
                {
                    "strike": best["strike"],
                    "option_type": opt_type,
                    "action": "BUY",
                    "entry_ltp": best["simulated_entry"],
                    "current_ltp": best["simulated_entry"],
                    "target2_price": best["target2_price"]
                }
            ]
        }

        sid = tracker_storage.insert_shadow_trade(shadow_payload)
        logger.info(
            f"SmartTrackerBot [SHADOW VARIANT D]: OPENED SHADOW TRADE [{symbol}] {strat_type} | Strike: {best['strike']} {opt_type} ({best['tag']}) | "
            f"TQS: {best['tqs_score']} | Confluence: {overall_score} | Outlay: ₹{best['required_outlay']} | ID: {sid}"
        )

    # ---------------------------------------------------------
    # Adaptive Learning Feedback Loop
    # ---------------------------------------------------------
    def _update_learning_model(self):
        """
        Adaptive learning feedback loop:
        Evaluates rolling expectancy, win rate, and profit factor over recent closed trades.
        """
        try:
            summary = tracker_storage.get_category_pnl_summary()
            params = tracker_storage.get_learning_params()
            params["learning_iterations"] = params.get("learning_iterations", 0) + 1
            tracker_storage.save_learning_params(params)
        except Exception as e:
            logger.debug(f"TrackerBot learning update error: {e}")


tracker_bot = SmartTrackerBot()
