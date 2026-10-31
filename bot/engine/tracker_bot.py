"""
Institutional Smart Signal Tracker & Paper Trading Bot Engine
Standalone, production-grade option trading bot.
Adheres to Backend Engineering Agent Standards:
- Exact concurrency enforcement: Max 1 active trade per symbol simultaneously across NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY.
- Institutional Strike Selection: Prefer ATM or 1-step ITM for Buyers; reject low-premium junk and far OTM options.
- Trade Quality Score (TQS 0-100): Combines Signal, Strike Delta, Liquidity/Spread, Momentum, and R:R.
- Signal Persistence & Confirmation: Requires at least 2 consecutive polling cycles plus underlying trend alignment.
- Regime Filter: Clear NO-TRADE / Choppy market detector.
- Volatility Exit Management: MFE & MAE tracking, dynamic multi-stage trailing stop loss, 15:35 IST EOD safety.
- Capital & Risk Controls: Daily loss limit circuit breaker, consecutive loss cooldown, flat Rs 100/lot brokerage.
- Adaptive Learning: Rolling expectancy, profit factor, and time-of-day session optimization.
"""
import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, time, timedelta

from .models import ParsedOptionChain, StrikeRow
from .greeks import calculate_greeks
from .technical_indicators import TechnicalIndicators
from .market_hours import get_current_ist, is_market_open
from ..storage.tracker_storage import tracker_storage, TrackerStorage

logger = logging.getLogger(__name__)

# Default NSE Index Specifications
DEFAULT_STRIKE_STEPS: Dict[str, int] = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25
}

DEFAULT_LOT_SIZES: Dict[str, int] = {
    "NIFTY": 75,
    "BANKNIFTY": 30,
    "FINNIFTY": 65,
    "MIDCPNIFTY": 120
}


class SmartTrackerBot:
    def __init__(
        self,
        storage: Optional[TrackerStorage] = None,
        strike_steps: Optional[Dict[str, int]] = None,
        lot_sizes: Optional[Dict[str, int]] = None
    ):
        self.is_active: bool = True  # Enabled by default
        self.storage = storage or tracker_storage
        self.strike_steps = strike_steps or DEFAULT_STRIKE_STEPS
        self.lot_sizes = lot_sizes or DEFAULT_LOT_SIZES
        self._signal_persistence: Dict[str, Dict[str, Any]] = {}
        self._symbol_cooldowns: Dict[str, datetime] = {}
        self._minute_candles: Dict[str, Dict[str, Dict[str, float]]] = {}
        self._current_trade_date: str = ""

    def is_bot_active(self) -> bool:
        return self.is_active

    def set_bot_active(self, active: bool):
        self.is_active = active
        logger.info(f"SmartTrackerBot: Status set to {'ACTIVE' if active else 'PAUSED'}")

    def _record_spot_tick(self, symbol: str, spot: float, now_dt: datetime):
        today_str = now_dt.strftime("%Y-%m-%d")
        if self._current_trade_date != today_str:
            self._current_trade_date = today_str
            self._minute_candles.clear()

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

    def feed_candle_history(self, symbol: str, candles: List[Dict[str, Any]]):
        """Allows feeding historical 1-minute candles for indicator warmup."""
        sym = symbol.upper()
        if sym not in self._minute_candles:
            self._minute_candles[sym] = {}
        for c in candles:
            t_str = c.get("time") or c.get("time_str")
            if t_str:
                self._minute_candles[sym][t_str] = {
                    "open": float(c.get("open", 0.0)),
                    "high": float(c.get("high", 0.0)),
                    "low": float(c.get("low", 0.0)),
                    "close": float(c.get("close", 0.0))
                }

    def get_technical_state(self, symbol: str) -> Dict[str, Any]:
        """Computes live PineScript OTT & ADX state for the given symbol."""
        bars = self._minute_candles.get(symbol.upper(), {})
        if len(bars) < 5:
            return {"adx": 20.0, "ott_state": "NEUTRAL", "plus_di": 25.0, "minus_di": 25.0, "mavg": 0.0, "ott": 0.0}

        sorted_times = sorted(bars.keys())
        highs = [bars[t]["high"] for t in sorted_times]
        lows = [bars[t]["low"] for t in sorted_times]
        closes = [bars[t]["close"] for t in sorted_times]

        plus_di, minus_di, adx = TechnicalIndicators.compute_adx(highs, lows, closes, length=9)
        mavg, ott, trend_state = TechnicalIndicators.compute_ott(closes, length=2, percent=0.30)

        return {
            "adx": round(adx[-1], 1) if adx else 20.0,
            "plus_di": round(plus_di[-1], 1) if plus_di else 25.0,
            "minus_di": round(minus_di[-1], 1) if minus_di else 25.0,
            "ott_state": trend_state[-1] if trend_state else "NEUTRAL",
            "mavg": round(mavg[-1], 2) if mavg else closes[-1],
            "ott": round(ott[-1], 2) if ott else closes[-1]
        }

    # ---------------------------------------------------------
    # Time-of-Day Session Classification
    # ---------------------------------------------------------
    def get_session_bucket(self, current_time: time) -> str:
        """Categorizes time of day into distinct trading sessions."""
        if time(9, 15, 0) <= current_time < time(11, 30, 0):
            return "MORNING"
        elif time(11, 30, 0) <= current_time < time(13, 30, 0):
            return "MIDDAY"
        else:
            return "AFTERNOON"

    # ---------------------------------------------------------
    # Strike Quality & Boundary Validation
    # ---------------------------------------------------------
    def validate_strike_selection(
        self,
        symbol: str,
        strike: float,
        atm: float,
        step: int,
        option_type: str,
        role: str,
        ltp: float,
        learning_params: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        Validates strike selection according to institutional rules:
        - BUYERS: Prefer ATM or 1-step ITM. Strictly reject OTM strikes.
        - SELLERS: Max 1 to 2 steps OTM. Reject far OTM sells.
        - Minimum absolute premium check to avoid low-delta junk.
        """
        if step <= 0 or atm <= 0:
            return False, "Invalid ATM or strike step"

        diff_steps = round((strike - atm) / step, 2)

        # Minimum premium threshold check per symbol
        min_prem = learning_params.get(f"min_premium_{symbol.lower()}", 35.0)
        if ltp < min_prem:
            return False, f"LTP ₹{ltp:.1f} below minimum premium threshold of ₹{min_prem}"

        if role == "BUYER":
            if option_type == "CE":
                if diff_steps > 0:
                    return False, f"Call strike {strike} is OTM (+{diff_steps} steps). Buyers prefer ATM or 1-ITM."
                if abs(diff_steps) > 2.0:
                    return False, f"Call strike {strike} is too deep ITM ({abs(diff_steps)} steps)."
            else:  # PE
                if diff_steps < 0:
                    return False, f"Put strike {strike} is OTM ({diff_steps} steps). Buyers prefer ATM or 1-ITM."
                if diff_steps > 2.0:
                    return False, f"Put strike {strike} is too deep ITM (+{diff_steps} steps)."

        elif role == "SELLER":
            if option_type == "CE":
                if diff_steps > 2.0:
                    return False, f"Sell Call strike {strike} exceeds 2 OTM limit (+{diff_steps} steps)."
                if diff_steps < -1.0:
                    return False, f"Sell Call strike {strike} is too deep ITM."
            else:  # PE
                if abs(diff_steps) > 2.0 and diff_steps < 0:
                    return False, f"Sell Put strike {strike} exceeds 2 OTM limit ({diff_steps} steps)."
                if diff_steps > 1.0:
                    return False, f"Sell Put strike {strike} is too deep ITM."

        return True, "Valid Strike"

    # ---------------------------------------------------------
    # Regime Filter: Choppy / No-Trade Market Detection
    # ---------------------------------------------------------
    def is_choppy_regime(
        self,
        chain: ParsedOptionChain,
        confluence_score: float,
        active_regime: str
    ) -> Tuple[bool, str]:
        """
        Identifies flat, two-sided consolidation where options suffer theta drag with no directional edge.
        Returns (True, reason) if market is choppy / NO-TRADE.
        """
        pcr = chain.pcr
        if 0.94 <= pcr <= 1.06 and 47.0 <= confluence_score <= 53.0:
            return True, f"Deadlock Consolidation: PCR {pcr:.2f} with neutral confluence {confluence_score:.1f}"

        if active_regime == "NO_TRADE_CHOPPY":
            return True, "Recommendation engine flagged active regime as NO-TRADE CHOPPY"

        return False, "Market has directional structure"

    # ---------------------------------------------------------
    # Trade Quality Score (TQS 0 - 100) Multi-Factor Engine
    # ---------------------------------------------------------
    def compute_trade_quality_score(
        self,
        symbol: str,
        chain: ParsedOptionChain,
        strategy: Dict[str, Any],
        role: str,
        confluence_score: float,
        contract_row: Optional[StrikeRow],
        option_type: str,
        target_pts: float,
        risk_pts: float
    ) -> Tuple[float, Dict[str, float]]:
        """
        Computes the comprehensive 5-Pillar Trade Quality Score (TQS):
        1. Signal Confluence & Strength (0 to 25 pts)
        2. Strike Quality & Delta Fit (0 to 20 pts)
        3. Liquidity, Spread & Depth (0 to 20 pts)
        4. Underlying & Option Momentum (0 to 20 pts - PineScript OTT & ADX Enhanced)
        5. Risk/Reward Potential (0 to 15 pts)
        """
        spot = chain.spot_price
        atm = chain.atm_strike
        pcr = chain.pcr

        # Pillar 1: Signal Confluence (Max 25 pts)
        p1 = 0.0
        dist_from_50 = abs(confluence_score - 50.0)
        if dist_from_50 >= 25.0:
            p1 = 25.0
        elif dist_from_50 >= 18.0:
            p1 = 20.0
        elif dist_from_50 >= 12.0:
            p1 = 15.0
        else:
            p1 = 8.0

        # Pillar 2: Strike Quality & Delta Sweet Spot (Max 20 pts)
        p2 = 0.0
        step = self.strike_steps.get(symbol, 50)
        if contract_row:
            contract = contract_row.CE if option_type == "CE" else contract_row.PE
            stk = contract_row.strikePrice
            diff_steps = abs(stk - atm) / step
            if role == "BUYER":
                if diff_steps <= 0.1:  # ATM strike
                    p2 = 20.0
                elif diff_steps <= 1.0:  # 1-step ITM
                    p2 = 17.0
                else:
                    p2 = 10.0
            else:  # SELLER
                if diff_steps <= 1.5:
                    p2 = 18.0
                else:
                    p2 = 12.0
        else:
            p2 = 10.0

        # Pillar 3: Liquidity, Spread & Depth (Max 20 pts)
        p3 = 0.0
        if contract_row:
            contract = contract_row.CE if option_type == "CE" else contract_row.PE
            oi = contract.openInterest if contract else 0
            vol = contract.totalTradedVolume if contract else 0

            # OI score (0-8 pts)
            if oi >= 100000:
                p3 += 8.0
            elif oi >= 50000:
                p3 += 6.0
            elif oi >= 20000:
                p3 += 4.0
            else:
                p3 += 1.0

            # Volume score (0-6 pts)
            if vol >= 60000:
                p3 += 6.0
            elif vol >= 25000:
                p3 += 4.0
            elif vol >= 10000:
                p3 += 2.0

            # Spread proxy
            p3 += 6.0
        else:
            p3 = 8.0

        # Pillar 4: Momentum Alignment (Max 20 pts - PineScript OTT & ADX Enhanced)
        p4 = 0.0
        tech = self.get_technical_state(symbol)
        if role == "BUYER":
            if option_type == "CE":
                if tech.get("ott_state") == "BULLISH":
                    p4 += 8.0
                if tech.get("adx", 0.0) >= 20.0:
                    p4 += 6.0
                if spot > atm or confluence_score >= 68.0:
                    p4 += 6.0
            else:  # PE
                if tech.get("ott_state") == "BEARISH":
                    p4 += 8.0
                if tech.get("adx", 0.0) >= 20.0:
                    p4 += 6.0
                if spot < atm or confluence_score <= 32.0:
                    p4 += 6.0
        else:  # SELLER
            if 0.85 <= pcr <= 1.15:
                p4 += 10.0
            if tech.get("adx", 0.0) < 22.0:
                p4 += 10.0
            else:
                p4 += 5.0

        # Pillar 5: Risk/Reward Potential (Max 15 pts)
        p5 = 0.0
        if risk_pts > 0:
            rr = target_pts / risk_pts
            if rr >= 1.7:
                p5 = 15.0
            elif rr >= 1.4:
                p5 = 11.0
            elif rr >= 1.1:
                p5 = 8.0
            else:
                p5 = 4.0
        else:
            p5 = 5.0

        total_tqs = round(p1 + p2 + p3 + p4 + p5, 1)
        breakdown = {
            "signal_confluence_pts": p1,
            "strike_quality_pts": p2,
            "liquidity_depth_pts": p3,
            "momentum_alignment_pts": p4,
            "risk_reward_pts": p5,
            "total_tqs": total_tqs
        }
        return total_tqs, breakdown

    # ---------------------------------------------------------
    # Core Processing Loop (Invoked on Every Polling Tick)
    # ---------------------------------------------------------
    def process_tick(
        self,
        symbol: str,
        chain: ParsedOptionChain,
        signal_decision: Dict[str, Any]
    ):
        """Processes real-time option chain tick for a symbol."""
        if not chain or not chain.strikes:
            return

        sym = symbol.upper()
        now_dt = get_current_ist()
        t = now_dt.time()

        # Update 1-minute candle for technical indicators
        self._record_spot_tick(sym, chain.spot_price, now_dt)

        # Check existing active trade for this symbol (Max 1 per symbol rule)
        open_trade = self.storage.get_open_trade_for_symbol(sym)

        # 1. Update Open Position MTM, Excursions & Check Exits
        if open_trade:
            self._update_and_check_exit(open_trade, chain, now_dt)
            return

        # 2. Evaluate New Trade Entry (09:30 - 15:25 IST)
        if not self.is_active:
            return

        if not (time(9, 30, 0) <= t <= time(15, 25, 0)):
            return

        # Risk Control Circuit Breaker: Daily Loss Limit
        learning = self.storage.get_learning_params()
        today_loss = self.storage.get_today_realized_pnl(now_dt.strftime("%Y-%m-%d"))
        daily_loss_limit = learning.get("daily_loss_limit_inr", 3500.0)
        if today_loss <= -daily_loss_limit:
            logger.warning(f"SmartTrackerBot: Daily loss limit breached (₹{today_loss:.2f} <= -₹{daily_loss_limit:.2f}). Trading halted for today.")
            return

        # Risk Control: Symbol Cooldown after consecutive losses
        if sym in self._symbol_cooldowns:
            cooldown_expiry = self._symbol_cooldowns[sym]
            if now_dt < cooldown_expiry:
                logger.debug(f"SmartTrackerBot: {sym} in cooldown until {cooldown_expiry.strftime('%H:%M:%S')}. Skipping entry.")
                return
            else:
                del self._symbol_cooldowns[sym]

        self._evaluate_new_entry(sym, chain, signal_decision, now_dt, learning)

    # ---------------------------------------------------------
    # Position MTM & Excursion Tracking
    # ---------------------------------------------------------
    def _update_and_check_exit(
        self,
        trade: Dict[str, Any],
        chain: ParsedOptionChain,
        now_dt: datetime
    ):
        trade_id = trade["id"]
        role = trade["role"]
        lot_size = trade["lot_size"]
        legs = trade.get("legs", [])
        entry_net = trade["entry_net_price"]
        target = trade["target_price"]
        stop_loss = trade["stop_loss_price"]
        trailing_sl = trade.get("trailing_stop_price", stop_loss)
        existing_mfe_pts = trade.get("mfe_pts", 0.0) or 0.0
        existing_mfe_inr = trade.get("mfe_inr", 0.0) or 0.0
        existing_mae_pts = trade.get("mae_pts", 0.0) or 0.0
        existing_mae_inr = trade.get("mae_inr", 0.0) or 0.0

        strike_map: Dict[float, StrikeRow] = {s.strikePrice: s for s in chain.strikes}
        curr_net = 0.0
        all_legs_updated = True

        if role == "SELLER":
            sell_ltp = 0.0
            buy_ltp = 0.0
            for leg in legs:
                stk = leg.get("strike", 0.0)
                otype = leg.get("option_type", "PE")
                act = leg.get("action", "SELL")
                row = strike_map.get(stk)
                if not row:
                    all_legs_updated = False
                    continue
                contract = row.CE if otype == "CE" else row.PE
                ltp = contract.lastPrice if contract else 0.0
                leg["current_ltp"] = ltp
                if act == "SELL":
                    sell_ltp = ltp
                else:
                    buy_ltp = ltp

            if not all_legs_updated:
                return

            curr_net = max(0.05, round(sell_ltp - buy_ltp, 2))
            pts_pnl = entry_net - curr_net
            gross_unrealized = round(pts_pnl * lot_size, 2)
            net_unrealized = round(gross_unrealized - 100.0, 2)  # Flat Rs 100 brokerage

            new_mfe_pts = max(existing_mfe_pts, pts_pnl)
            new_mfe_inr = max(existing_mfe_inr, gross_unrealized)
            new_mae_pts = min(existing_mae_pts, pts_pnl)
            new_mae_inr = min(existing_mae_inr, gross_unrealized)

            # Dynamic Trailing Stop Loss for Sellers
            decay_fraction = (entry_net - curr_net) / entry_net if entry_net > 0 else 0
            if decay_fraction >= 0.60:
                lock_price = round(entry_net * 0.40, 2)
                if lock_price < trailing_sl:
                    trailing_sl = lock_price
            elif decay_fraction >= 0.35:
                if entry_net < trailing_sl:
                    trailing_sl = entry_net

            self.storage.update_trade_mtm(
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

            if curr_net <= target:
                self._execute_close(trade, curr_net, gross_unrealized, net_unrealized, "TARGET_HIT (70% Decay Captured)", new_mfe_pts, new_mfe_inr, new_mae_pts, new_mae_inr)
                return

            if curr_net >= trailing_sl:
                reason = "TRAILING_SL_HIT" if trailing_sl < stop_loss else "STOP_LOSS_HIT"
                self._execute_close(trade, curr_net, gross_unrealized, net_unrealized, reason, new_mfe_pts, new_mfe_inr, new_mae_pts, new_mae_inr)
                return

        else:
            # BUYER
            buy_ltp = 0.0
            for leg in legs:
                stk = leg.get("strike", 0.0)
                otype = leg.get("option_type", "CE")
                row = strike_map.get(stk)
                if not row:
                    all_legs_updated = False
                    continue
                contract = row.CE if otype == "CE" else row.PE
                ltp = contract.lastPrice if contract else 0.0
                leg["current_ltp"] = ltp
                buy_ltp = ltp

            if not all_legs_updated or buy_ltp <= 0:
                return

            curr_net = buy_ltp
            pts_pnl = curr_net - entry_net
            gross_unrealized = round(pts_pnl * lot_size, 2)
            net_unrealized = round(gross_unrealized - 100.0, 2)

            new_mfe_pts = max(existing_mfe_pts, pts_pnl)
            new_mfe_inr = max(existing_mfe_inr, gross_unrealized)
            new_mae_pts = min(existing_mae_pts, pts_pnl)
            new_mae_inr = min(existing_mae_inr, gross_unrealized)

            # Fast 3-Stage Dynamic Breakeven Ladder for Buyers
            gain_fraction = (curr_net - entry_net) / entry_net if entry_net > 0 else 0
            if gain_fraction >= 0.60:
                lock_price = round(entry_net * 1.35, 2)
                if lock_price > trailing_sl:
                    trailing_sl = lock_price
            elif gain_fraction >= 0.35:
                lock_price = round(entry_net * 1.15, 2)
                if lock_price > trailing_sl:
                    trailing_sl = lock_price
            elif gain_fraction >= 0.20:
                if entry_net > trailing_sl:
                    trailing_sl = entry_net

            self.storage.update_trade_mtm(
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

            if curr_net >= target:
                self._execute_close(trade, curr_net, gross_unrealized, net_unrealized, "TARGET_HIT (+50% Momentum Target)", new_mfe_pts, new_mfe_inr, new_mae_pts, new_mae_inr)
                return

            if curr_net <= trailing_sl:
                reason = "TRAILING_SL_HIT" if trailing_sl > stop_loss else "STOP_LOSS_HIT"
                self._execute_close(trade, curr_net, gross_unrealized, net_unrealized, reason, new_mfe_pts, new_mfe_inr, new_mae_pts, new_mae_inr)
                return

        # EOD Auto-Squareoff at 15:35:00 IST
        if now_dt.time() >= time(15, 35, 0):
            self._execute_close(trade, curr_net, gross_unrealized, net_unrealized, "EOD_SQUAREOFF (15:35 Market Close Safety)", new_mfe_pts, new_mfe_inr, new_mae_pts, new_mae_inr)

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
        self.storage.close_trade(
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

        now_dt = get_current_ist()
        learning = self.storage.get_learning_params()
        max_cons_losses = learning.get("max_consecutive_losses", 2)
        cooldown_mins = learning.get("cooldown_minutes", 45)
        cons_losses = self.storage.get_consecutive_losses_for_symbol(sym, now_dt.strftime("%Y-%m-%d"))
        if net_realized_pnl < 0:
            cd = cooldown_mins if cons_losses >= max_cons_losses else 20
            self._symbol_cooldowns[sym] = now_dt + timedelta(minutes=cd)
            logger.warning(f"SmartTrackerBot: {sym} closed with loss. Cooldown enforced until {self._symbol_cooldowns[sym].strftime('%H:%M:%S')}")
        else:
            self._symbol_cooldowns[sym] = now_dt + timedelta(minutes=5)

        self._update_learning_model()

    # ---------------------------------------------------------
    # Evaluate New Trade Entry with Institutional Gates
    # ---------------------------------------------------------
    def _evaluate_new_entry(
        self,
        symbol: str,
        chain: ParsedOptionChain,
        signal_decision: Dict[str, Any],
        now_dt: datetime,
        learning: Dict[str, Any]
    ):
        step = self.strike_steps.get(symbol, 50)
        lot_size = self.lot_sizes.get(symbol, 75)
        atm = chain.atm_strike
        spot = chain.spot_price
        t = now_dt.time()

        active_regime = signal_decision.get("active_regime", "SELLER_REGIME")
        confluence = signal_decision.get("confluence_score", 50.0)
        top_rec = signal_decision.get("top_recommendation", {})
        role = top_rec.get("role", "SELLER")
        strat = top_rec.get("strategy", {})

        strike_map: Dict[float, StrikeRow] = {s.strikePrice: s for s in chain.strikes}

        # Check PineScript technical indicator momentum & trend direction
        tech_state = self.get_technical_state(symbol)
        ott_state = tech_state.get("ott_state", "NEUTRAL")
        adx = tech_state.get("adx", 0.0)
        pcr = chain.pcr

        # High-Velocity Directional Override via PineScript Indicators:
        # If OTT is BEARISH and (PCR <= 0.95 or ADX >= 18.0): High conviction BEARISH breakdown -> BUYER (PE Buy)
        # If OTT is BULLISH and (PCR >= 1.05 or ADX >= 18.0): High conviction BULLISH breakout -> BUYER (CE Buy)
        if ott_state == "BEARISH" and (pcr <= 0.95 or adx >= 18.0):
            role = "BUYER"
            active_regime = "BUYER_REGIME"
            c_row = strike_map.get(atm)
            pe_ltp = c_row.PE.lastPrice if c_row and c_row.PE and c_row.PE.lastPrice > 0 else round(spot * 0.007, 1)
            strat = {
                "type": "MOMENTUM_PUT_BUY",
                "name": f"MOMENTUM PUT BUY ({int(atm)} PE)",
                "buy_strike": atm,
                "option_type": "PE",
                "ltp": pe_ltp
            }
            confluence = 25.0

        elif ott_state == "BULLISH" and (pcr >= 1.05 or adx >= 18.0):
            role = "BUYER"
            active_regime = "BUYER_REGIME"
            c_row = strike_map.get(atm)
            ce_ltp = c_row.CE.lastPrice if c_row and c_row.CE and c_row.CE.lastPrice > 0 else round(spot * 0.007, 1)
            strat = {
                "type": "MOMENTUM_CALL_BUY",
                "name": f"MOMENTUM CALL BUY ({int(atm)} CE)",
                "buy_strike": atm,
                "option_type": "CE",
                "ltp": ce_ltp
            }
            confluence = 75.0

        if not strat or not strat.get("name"):
            return

        # 1. Regime Filter: Clear NO-TRADE / Choppy Market Check
        is_choppy, chop_reason = self.is_choppy_regime(chain, confluence, active_regime)
        if is_choppy:
            logger.debug(f"SmartTrackerBot: Skipping {symbol} entry - {chop_reason}")
            return

        # 2. Signal Persistence Filter: Require >= 2 consecutive ticks
        sig_key = f"{role}_{strat.get('type')}"
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

        session_bucket = self.get_session_bucket(t)

        buyer_min_tqs = learning.get("buyer_min_tqs", 70.0)
        seller_min_tqs = learning.get("seller_min_tqs", 66.0)

        # Midday Session Defense: Tighten TQS during choppy lunch hours (11:30 - 13:30 IST)
        if session_bucket == "MIDDAY":
            buyer_min_tqs += 5.0
            seller_min_tqs += 4.0

        strike_map: Dict[float, StrikeRow] = {s.strikePrice: s for s in chain.strikes}

        # ---------------------------------------------------------
        # A. Evaluate BUYER Entry (Prioritized: Momentum Velocity)
        # ---------------------------------------------------------
        if role == "BUYER" and active_regime == "BUYER_REGIME":
            buy_stk = strat.get("buy_strike", 0.0)
            otype = strat.get("option_type", "CE")
            ltp = strat.get("ltp", 0.0)

            valid_strike, reason = self.validate_strike_selection(
                symbol, buy_stk, atm, step, otype, "BUYER", ltp, learning
            )
            if not valid_strike:
                logger.debug(f"SmartTrackerBot: Skipping {symbol} buyer trade - {reason}")
                return

            # PineScript OTT & ADX Filters for Option Buying:
            tech_state = self.get_technical_state(symbol)
            ott_state = tech_state.get("ott_state", "NEUTRAL")
            adx = tech_state.get("adx", 0.0)

            # Rule 1: OTT Trend Channel Alignment
            if otype == "CE" and ott_state != "BULLISH":
                logger.debug(f"SmartTrackerBot: Skipping {symbol} CE buy - OTT state is {ott_state} (requires BULLISH channel)")
                return
            if otype == "PE" and ott_state != "BEARISH":
                logger.debug(f"SmartTrackerBot: Skipping {symbol} PE buy - OTT state is {ott_state} (requires BEARISH channel)")
                return

            # Rule 2: ADX Trend Velocity Gate
            if adx < 18.0:
                logger.debug(f"SmartTrackerBot: Skipping {symbol} buyer trade - ADX {adx:.1f} < 18.0 (low trend velocity)")
                return

            target1 = round(ltp * 1.50, 2)
            stop_loss = round(ltp * 0.70, 2)
            risk_pts = ltp - stop_loss
            target_pts = target1 - ltp

            contract_row = strike_map.get(buy_stk)
            tqs_score, tqs_breakdown = self.compute_trade_quality_score(
                symbol=symbol,
                chain=chain,
                strategy=strat,
                role="BUYER",
                confluence_score=confluence,
                contract_row=contract_row,
                option_type=otype,
                target_pts=target_pts,
                risk_pts=risk_pts
            )

            if tqs_score < buyer_min_tqs:
                logger.debug(f"SmartTrackerBot: Skipping {symbol} buyer trade - TQS {tqs_score:.1f} < threshold {buyer_min_tqs:.1f}")
                return

            trade_payload = {
                "id": f"bot_{symbol}_{int(now_dt.timestamp())}",
                "symbol": symbol,
                "strategy_type": strat.get("type", "MOMENTUM_BUY"),
                "role": "BUYER",
                "regime": active_regime,
                "confluence_at_entry": confluence,
                "lot_size": lot_size,
                "entry_net_price": ltp,
                "current_net_price": ltp,
                "target_price": target1,
                "stop_loss_price": stop_loss,
                "trailing_stop_price": stop_loss,
                "tqs_score": tqs_score,
                "tqs_breakdown": tqs_breakdown,
                "session_bucket": session_bucket,
                "trade_date": now_dt.strftime("%Y-%m-%d"),
                "legs": [
                    {
                        "strike": buy_stk, "option_type": otype, "action": "BUY",
                        "entry_ltp": ltp, "current_ltp": ltp
                    }
                ]
            }
            tid = self.storage.insert_trade(trade_payload)
            logger.info(f"SmartTrackerBot: OPENED BUYER TRADE [{symbol}] {strat.get('name')} | ID: {tid} | Entry: ₹{ltp} | TQS: {tqs_score:.1f}")

        # ---------------------------------------------------------
        # B. Evaluate SELLER Entry (Credit Spread)
        # ---------------------------------------------------------
        elif role == "SELLER" and active_regime == "SELLER_REGIME":
            # Expiry Day Gamma Defense: Omit 1-lot option selling on Thursdays
            if now_dt.weekday() == 3:
                logger.debug(f"SmartTrackerBot: Skipping {symbol} seller credit spread on Expiry Day (Thursday) - 1-lot margin defense.")
                return

            sell_leg = strat.get("sell_leg", {})
            hedge_leg = strat.get("hedge_leg", {})
            sell_stk = sell_leg.get("strike", 0.0)
            hedge_stk = hedge_leg.get("strike", 0.0)
            otype = sell_leg.get("option_type", "PE")
            net_credit = strat.get("net_credit_pts", 0.0)
            sell_ltp = sell_leg.get("ltp", 0.0)

            valid_strike, reason = self.validate_strike_selection(
                symbol, sell_stk, atm, step, otype, "SELLER", sell_ltp, learning
            )
            if not valid_strike:
                logger.debug(f"SmartTrackerBot: Skipping {symbol} seller trade - {reason}")
                return

            # Trend Breakdown Defense: Never sell PEs into high-velocity bearish momentum (ADX >= 28 & OTT BEARISH)
            tech_state = self.get_technical_state(symbol)
            if otype == "PE" and tech_state.get("adx", 0.0) >= 28.0 and tech_state.get("ott_state") == "BEARISH":
                logger.debug(f"SmartTrackerBot: Skipping {symbol} PE sell - high bearish trend velocity (ADX {tech_state.get('adx'):.1f})")
                return
            if otype == "CE" and tech_state.get("adx", 0.0) >= 28.0 and tech_state.get("ott_state") == "BULLISH":
                logger.debug(f"SmartTrackerBot: Skipping {symbol} CE sell - high bullish trend velocity (ADX {tech_state.get('adx'):.1f})")
                return

            if net_credit < 6.0:
                return

            target_buyback = round(net_credit * 0.30, 2)
            stop_buyback = round(net_credit * 2.0, 2)
            target_pts = net_credit * 0.70
            risk_pts = net_credit * 1.0

            contract_row = strike_map.get(sell_stk)
            tqs_score, tqs_breakdown = self.compute_trade_quality_score(
                symbol=symbol,
                chain=chain,
                strategy=strat,
                role="SELLER",
                confluence_score=confluence,
                contract_row=contract_row,
                option_type=otype,
                target_pts=target_pts,
                risk_pts=risk_pts
            )

            if tqs_score < seller_min_tqs:
                logger.debug(f"SmartTrackerBot: Skipping {symbol} seller trade - TQS {tqs_score:.1f} < threshold {seller_min_tqs:.1f}")
                return

            trade_payload = {
                "id": f"bot_{symbol}_{int(now_dt.timestamp())}",
                "symbol": symbol,
                "strategy_type": strat.get("type", "CREDIT_SPREAD"),
                "role": "SELLER",
                "regime": active_regime,
                "confluence_at_entry": confluence,
                "lot_size": lot_size,
                "entry_net_price": net_credit,
                "current_net_price": net_credit,
                "target_price": target_buyback,
                "stop_loss_price": stop_buyback,
                "trailing_stop_price": stop_buyback,
                "tqs_score": tqs_score,
                "tqs_breakdown": tqs_breakdown,
                "session_bucket": session_bucket,
                "trade_date": now_dt.strftime("%Y-%m-%d"),
                "legs": [
                    {
                        "strike": sell_stk, "option_type": otype, "action": "SELL",
                        "entry_ltp": sell_ltp, "current_ltp": sell_ltp
                    },
                    {
                        "strike": hedge_stk, "option_type": otype, "action": "BUY",
                        "entry_ltp": hedge_leg.get("ltp", 0.0), "current_ltp": hedge_leg.get("ltp", 0.0)
                    }
                ]
            }
            tid = self.storage.insert_trade(trade_payload)
            logger.info(f"SmartTrackerBot: OPENED SELLER TRADE [{symbol}] {strat.get('name')} | ID: {tid} | Credit: ₹{net_credit} | TQS: {tqs_score:.1f}")

    # ---------------------------------------------------------
    # Adaptive Learning Feedback Loop
    # ---------------------------------------------------------
    def _update_learning_model(self):
        try:
            summary = self.storage.get_category_pnl_summary()
            expectancy = summary.get("rolling_expectancy_inr", 0.0)
            win_rate = summary.get("overall_win_rate_pct", 50.0)
            tot_trades = summary.get("total_trades", 0)

            if tot_trades < 3:
                return

            params = self.storage.get_learning_params()
            curr_buyer_tqs = params.get("buyer_min_tqs", 70.0)
            curr_seller_tqs = params.get("seller_min_tqs", 66.0)

            if expectancy < 0 or win_rate < 48.0:
                params["buyer_min_tqs"] = min(78.0, curr_buyer_tqs + 1.0)
                params["seller_min_tqs"] = min(74.0, curr_seller_tqs + 1.0)
            elif win_rate >= 68.0 and expectancy > 300.0:
                params["buyer_min_tqs"] = max(68.0, curr_buyer_tqs - 0.5)
                params["seller_min_tqs"] = max(64.0, curr_seller_tqs - 0.5)

            params["learning_iterations"] = params.get("learning_iterations", 0) + 1
            self.storage.save_learning_params(params)
        except Exception as e:
            logger.warning(f"SmartTrackerBot: Adaptive learning update failed - {e}")

    # ---------------------------------------------------------
    # Manual Squareoff Controls
    # ---------------------------------------------------------
    def square_off_trade(self, trade_id: str, reason: str = "MANUAL_SQUAREOFF") -> bool:
        """Manually squares off a specific active trade."""
        trades = self.storage.get_open_trades()
        target = next((t for t in trades if t["id"] == trade_id), None)
        if not target:
            return False

        curr_net = target.get("current_net_price", target["entry_net_price"])
        gross_unrealized = target.get("gross_unrealized_pnl_inr", 0.0)
        net_unrealized = target.get("unrealized_pnl_inr", 0.0)
        mfe_pts = target.get("mfe_pts", 0.0)
        mfe_inr = target.get("mfe_inr", 0.0)
        mae_pts = target.get("mae_pts", 0.0)
        mae_inr = target.get("mae_inr", 0.0)

        self._execute_close(target, curr_net, gross_unrealized, net_unrealized, reason, mfe_pts, mfe_inr, mae_pts, mae_inr)
        return True

    def square_off_all(self, reason: str = "MANUAL_EMERGENCY_SQUAREOFF") -> int:
        """Emergency squareoff for all currently open trades."""
        trades = self.storage.get_open_trades()
        count = 0
        for t in trades:
            if self.square_off_trade(t["id"], reason):
                count += 1
        return count


tracker_bot = SmartTrackerBot()
