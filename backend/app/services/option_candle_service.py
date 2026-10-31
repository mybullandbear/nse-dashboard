"""
Option Candlestick & PineScript Engine Service
Maintains real-time and historical 5-minute OHLCV candlestick series for option contracts.
Specifically monitors ATM +- 2 strikes (Top 5 active strikes per index):
- [ATM-2, ATM-1, ATM, ATM+1, ATM+2] for both CE and PE
- Evaluates PineScript OTT (Optimized Trend Tracker) & ADX directly on the Option Chart
- Generates Option-level BUY (Close crosses above OTT) and EXIT (Close crosses below OTT) signals
- Powers both the Interactive Dashboard Option Chart and automated Bot Execution
"""
import math
import logging
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, time, timedelta

from app.core.config import get_settings
from app.core.market_hours import get_current_ist, is_market_open
from app.services.option_chain import ParsedOptionChain, StrikeRow
from app.services.technical_indicators import TechnicalIndicators
from app.db.storage import snapshot_storage

logger = logging.getLogger(__name__)


class OptionCandleService:
    def __init__(self):
        # In-memory store: { "NIFTY_23100_CE": { "09:15": {open, high, low, close, volume}, ... } }
        self._candles_5m: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._contract_stats: Dict[str, Dict[str, Any]] = {}
        self._current_trade_date: str = ""
        self._warmed_up_contracts: set = set()
        # High-frequency tick window for 30s Option Premium Confirmation Gate (Anti-Falling Knife)
        # { "NIFTY_23100_CE": [(epoch_ts, ltp), ...] }
        self._recent_ticks: Dict[str, List[Tuple[float, float]]] = {}

    def _get_contract_key(self, symbol: str, strike: float, option_type: str) -> str:
        return f"{symbol.upper()}_{int(strike)}_{option_type.upper()}"

    def record_chain_ticks(self, chain: ParsedOptionChain, now_dt: Optional[datetime] = None):
        """
        Records live ticks from ParsedOptionChain for ATM +- 2 strikes into 5-minute option candles.
        Invoked on every polling cycle in the background loop.
        """
        if not chain or not chain.strikes:
            return

        now = now_dt or get_current_ist()
        today_str = now.strftime("%Y-%m-%d")
        if self._current_trade_date != today_str:
            # Check if this new date is in the same weekly expiry cycle
            same_cycle = False
            if self._current_trade_date:
                try:
                    same_dates = snapshot_storage.get_same_expiry_dates(chain.symbol, today_str)
                    if self._current_trade_date in same_dates:
                        same_cycle = True
                except Exception:
                    pass

            self._current_trade_date = today_str
            if not same_cycle:
                # Fresh weekly expiry cycle starting, clear old expired contracts
                self._candles_5m.clear()
                self._warmed_up_contracts.clear()

        # Only record within market hours
        t = now.time()
        if not (time(9, 15, 0) <= t <= time(15, 40, 0)):
            return

        sym = chain.symbol.upper()
        spot = chain.spot_price
        atm = chain.atm_strike
        step = get_settings().STRIKE_STEPS.get(sym, 50)

        # 5 active strikes: ATM-2, ATM-1, ATM, ATM+1, ATM+2
        target_strikes = [
            atm - (2 * step),
            atm - step,
            atm,
            atm + step,
            atm + (2 * step)
        ]

        # Calculate 5-minute bucket: e.g. 09:16 -> 09:15, 09:24 -> 09:20
        bucket_min = (now.minute // 5) * 5
        bucket_time_str = f"{now.hour:02d}:{bucket_min:02d}"

        for row in chain.strikes:
            stk = row.strikePrice
            if stk not in target_strikes:
                continue

            # Record CE tick
            if row.CE and row.CE.lastPrice > 0:
                ce_key = self._get_contract_key(sym, stk, "CE")
                self._contract_stats[ce_key] = {
                    "oi": row.CE.openInterest,
                    "oi_chg": row.CE.changeinOpenInterest,
                    "pChange": row.CE.pChange,
                    "volume": row.CE.totalTradedVolume
                }
                # Record high-frequency tick for 30s premium confirmation gate
                now_epoch = now.timestamp()
                if ce_key not in self._recent_ticks:
                    self._recent_ticks[ce_key] = []
                self._recent_ticks[ce_key].append((now_epoch, row.CE.lastPrice))
                # Prune older than 90 seconds
                cutoff = now_epoch - 90.0
                self._recent_ticks[ce_key] = [t for t in self._recent_ticks[ce_key] if t[0] >= cutoff]

                self._update_candle(
                    symbol=sym,
                    strike=stk,
                    option_type="CE",
                    ltp=row.CE.lastPrice,
                    volume=row.CE.totalTradedVolume,
                    time_str=bucket_time_str,
                    now_dt=now
                )

            # Record PE tick
            if row.PE and row.PE.lastPrice > 0:
                pe_key = self._get_contract_key(sym, stk, "PE")
                self._contract_stats[pe_key] = {
                    "oi": row.PE.openInterest,
                    "oi_chg": row.PE.changeinOpenInterest,
                    "pChange": row.PE.pChange,
                    "volume": row.PE.totalTradedVolume
                }
                # Record high-frequency tick for 30s premium confirmation gate
                now_epoch = now.timestamp()
                if pe_key not in self._recent_ticks:
                    self._recent_ticks[pe_key] = []
                self._recent_ticks[pe_key].append((now_epoch, row.PE.lastPrice))
                cutoff = now_epoch - 90.0
                self._recent_ticks[pe_key] = [t for t in self._recent_ticks[pe_key] if t[0] >= cutoff]

                self._update_candle(
                    symbol=sym,
                    strike=stk,
                    option_type="PE",
                    ltp=row.PE.lastPrice,
                    volume=row.PE.totalTradedVolume,
                    time_str=bucket_time_str,
                    now_dt=now
                )

    def _update_candle(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        ltp: float,
        volume: int,
        time_str: str,
        now_dt: datetime
    ):
        contract_key = self._get_contract_key(symbol, strike, option_type)
        if contract_key not in self._candles_5m:
            self._candles_5m[contract_key] = {}
            # Warm up from SQLite if not warmed up
            self._warmup_from_storage(symbol, strike, option_type, now_dt)

        today_str = now_dt.strftime("%Y-%m-%d")
        dt_key = f"{today_str} {time_str}"
        bars = self._candles_5m[contract_key]
        if dt_key not in bars:
            bars[dt_key] = {
                "time": time_str,
                "datetime": dt_key,
                "trade_date": today_str,
                "open": ltp,
                "high": ltp,
                "low": ltp,
                "close": ltp,
                "volume": volume
            }
        else:
            b = bars[dt_key]
            b["high"] = max(b["high"], ltp)
            b["low"] = min(b["low"], ltp)
            b["close"] = ltp
            b["volume"] = max(b["volume"], volume)

    def _warmup_from_storage(self, symbol: str, strike: float, option_type: str, now_dt: datetime):
        """Warm up 5-minute option candles from SQLite recorded snapshots across all trading sessions of the SAME EXPIRY."""
        today_str = now_dt.strftime("%Y-%m-%d")
        contract_key = self._get_contract_key(symbol, strike, option_type)
        if contract_key in self._warmed_up_contracts:
            return

        self._warmed_up_contracts.add(contract_key)
        try:
            expiry_dates = snapshot_storage.get_same_expiry_dates(symbol, today_str)
            if not expiry_dates:
                expiry_dates = [today_str]

            placeholders = ",".join(["?"] * len(expiry_dates))
            with snapshot_storage._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(f"""
                    SELECT trade_date, time_str, ltp, volume
                    FROM intraday_strike_snapshots
                    WHERE symbol = ? AND trade_date IN ({placeholders}) AND strike = ? AND option_type = ?
                    ORDER BY trade_date ASC, id ASC
                """, [symbol.upper()] + expiry_dates + [strike, option_type.upper()])
                rows = cursor.fetchall()
                if not rows:
                    return

                bars = self._candles_5m.setdefault(contract_key, {})
                for r in rows:
                    t_date = r["trade_date"]
                    t_str = r["time_str"]
                    ltp = float(r["ltp"])
                    vol = int(r["volume"])

                    # Parse hour & minute
                    parts = t_str.split(":")
                    if len(parts) == 2:
                        hh = int(parts[0])
                        mm = (int(parts[1]) // 5) * 5
                        b_str = f"{hh:02d}:{mm:02d}"
                        dt_key = f"{t_date} {b_str}"

                        if dt_key not in bars:
                            bars[dt_key] = {
                                "time": b_str if t_date == today_str else f"{t_date[5:]} {b_str}",
                                "datetime": dt_key,
                                "trade_date": t_date,
                                "open": ltp,
                                "high": ltp,
                                "low": ltp,
                                "close": ltp,
                                "volume": vol
                            }
                        else:
                            b = bars[dt_key]
                            b["high"] = max(b["high"], ltp)
                            b["low"] = min(b["low"], ltp)
                            b["close"] = ltp
                            b["volume"] = max(b["volume"], vol)
        except Exception as e:
            logger.debug(f"Option candle warmup error for {contract_key}: {e}")

    # ---------------------------------------------------------
    # PineScript Option Chart Calculation
    # ---------------------------------------------------------
    def get_option_chart_data(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        ott_length: int = 2,
        ott_percent: float = 0.30,
        adx_length: int = 9
    ) -> Dict[str, Any]:
        """
        Returns full candlestick series and PineScript indicators calculated directly on the option contract:
        - 5-Minute OHLCV candles
        - PineScript OTT & Moving Average series
        - PineScript ADX, +DI, -DI series
        - Buy & Exit Signal markers
        - Current live trigger status
        """
        sym = symbol.upper()
        otype = option_type.upper()
        now_dt = get_current_ist()
        contract_key = self._get_contract_key(sym, strike, otype)

        if contract_key not in self._candles_5m:
            self._candles_5m[contract_key] = {}
            self._warmup_from_storage(sym, strike, otype, now_dt)

        bars = self._candles_5m.get(contract_key, {})
        sorted_times = sorted(bars.keys())

        candles: List[Dict[str, Any]] = []
        for t in sorted_times:
            candles.append(bars[t])

        if len(candles) < 2:
            return {
                "symbol": sym,
                "strike": strike,
                "option_type": otype,
                "contract_key": contract_key,
                "timeframe": "5m",
                "candles": candles,
                "indicators": {
                    "ott": [],
                    "mavg": [],
                    "trend_state": [],
                    "alphatrend": [],
                    "alphatrend_lag2": [],
                    "trend_direction": [],
                    "trend_direction_ema": [],
                    "proximity_per": [],
                    "hull": [],
                    "hull_lag2": [],
                    "hull_state": [],
                    "adx": [],
                    "plus_di": [],
                    "minus_di": []
                },
                "signals": [],
                "current_state": {
                    "close": candles[-1]["close"] if candles else 0.0,
                    "ott": 0.0,
                    "mavg": 0.0,
                    "ott_state": "NEUTRAL",
                    "alphatrend": 0.0,
                    "alphatrend_state": "NEUTRAL",
                    "trend_direction": 0.0,
                    "trend_direction_state": "NEUTRAL",
                    "proximity": 50.0,
                    "hull": 0.0,
                    "hull_lag2": 0.0,
                    "hull_state": "NEUTRAL",
                    "adx": 0.0,
                    "signal_trigger": "AWAITING_DATA"
                }
            }

        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]
        closes = [c["close"] for c in candles]
        volumes = [c.get("volume", 0) for c in candles]

        # 1. Compute PineScript OTT overlay
        mavg, ott, trend_state = TechnicalIndicators.compute_ott(
            closes=closes,
            length=ott_length,
            percent=ott_percent
        )

        # 2. Compute PineScript AlphaTrend directly on option candles
        at_res = TechnicalIndicators.compute_alphatrend(
            highs=highs,
            lows=lows,
            closes=closes,
            volumes=volumes,
            coeff=1.0,
            ap=14
        )
        alphatrend = at_res["alphatrend"]
        alphatrend_lag2 = at_res["alphatrend_lag2"]
        at_state = at_res["trend_state"]

        # 3. Compute PineScript TrendDirection (Logistic Momentum & Tanh)
        td_res = TechnicalIndicators.compute_trend_direction(
            highs=highs,
            lows=lows,
            closes=closes,
            di_len=14,
            mean_lb=min(len(closes), 60)
        )
        trend_direction = td_res["strength"]
        trend_direction_ema = td_res["s_ema"]
        td_state = td_res["trend_state"]
        td_strength = td_res["strength_latest"]

        # 4. Compute Proximity MAPO (0-100%)
        prox_res = TechnicalIndicators.compute_proximity(
            closes=closes,
            i_min=10,
            i_max=min(len(closes), 60)
        )
        proximity_per = prox_res["per"]

        # 5. Compute PineScript Hull Suite (EHMA 34x2) directly on option candles
        hull_res = TechnicalIndicators.compute_hull(
            closes=closes,
            mode="Ehma",
            length=34,
            length_mult=2.0
        )
        hull_series = hull_res["mhull"]
        hull_lag2 = hull_res["shull"]
        hull_trend_state = hull_res["trend_state"]
        curr_hull_val = hull_res["curr_mhull"]
        curr_shull_val = hull_res["curr_shull"]
        curr_hull_st = hull_res["curr_state"]

        # 6. Detect Crossover Signals (AlphaTrend & OTT Confirmation)
        signals: List[Dict[str, Any]] = []
        for i in range(1, len(candles)):
            prev_c = closes[i - 1]
            curr_c = closes[i]
            prev_at = alphatrend[i - 1]
            curr_at = alphatrend[i]

            # AlphaTrend crossover / OTT crossover
            if (prev_c <= prev_at and curr_c > curr_at) or (at_res["buy_signals"][i]):
                signals.append({
                    "index": i,
                    "time": candles[i]["time"],
                    "type": "BUY",
                    "price": curr_c,
                    "description": f"Option crossed above AlphaTrend @ ₹{curr_c:.2f}"
                })
            elif (prev_c >= prev_at and curr_c < curr_at) or (at_res["sell_signals"][i]):
                signals.append({
                    "index": i,
                    "time": candles[i]["time"],
                    "type": "EXIT",
                    "price": curr_c,
                    "description": f"Option fell below AlphaTrend @ ₹{curr_c:.2f}"
                })

        curr_close = closes[-1]
        curr_ott = round(ott[-1], 2) if ott else curr_close
        curr_mavg = round(mavg[-1], 2) if mavg else curr_close
        curr_state = trend_state[-1] if trend_state else "NEUTRAL"
        curr_at_val = round(alphatrend[-1], 2) if alphatrend else curr_close
        curr_at_st = at_state[-1] if at_state else "NEUTRAL"

        # Trigger determination based on AlphaTrend & TrendDirection (replacing legacy ADX)
        if curr_close > curr_at_val and td_strength > 0.08:
            signal_trigger = "OPTION_BUY_CONFIRMED"
        elif curr_close < curr_at_val or td_strength < -0.15:
            signal_trigger = "OPTION_EXIT_SIGNAL"
        else:
            signal_trigger = "NEUTRAL_HOLD"

        stats = self._contract_stats.get(contract_key, {})
        oi = stats.get("oi", 0)
        oi_chg = stats.get("oi_chg", 0)
        pchange = stats.get("pChange", 0.0)

        if pchange >= 0 and oi_chg >= 0:
            buildup = "LONG_BUILDUP"
        elif pchange >= 0 and oi_chg < 0:
            buildup = "SHORT_COVERING"
        elif pchange < 0 and oi_chg >= 0:
            buildup = "SHORT_BUILDUP"
        else:
            buildup = "LONG_UNWINDING"

        return {
            "symbol": sym,
            "strike": strike,
            "option_type": otype,
            "contract_key": contract_key,
            "timeframe": "5m",
            "candles": candles,
            "indicators": {
                "ott": [round(x, 2) for x in ott],
                "mavg": [round(x, 2) for x in mavg],
                "trend_state": trend_state,
                "alphatrend": alphatrend,
                "alphatrend_lag2": alphatrend_lag2,
                "alphatrend_state": at_state,
                "trend_direction": trend_direction,
                "trend_direction_ema": trend_direction_ema,
                "trend_direction_state": td_state,
                "proximity_per": proximity_per,
                "hull": hull_series,
                "hull_lag2": hull_lag2,
                "hull_state": hull_trend_state,
                "adx": [round(abs(s) * 50.0, 1) for s in trend_direction]  # backwards-compatible proxy
            },
            "signals": signals,
            "current_state": {
                "close": curr_close,
                "ott": curr_ott,
                "mavg": curr_mavg,
                "ott_state": curr_state,
                "alphatrend": curr_at_val,
                "alphatrend_state": curr_at_st,
                "trend_direction": td_strength,
                "trend_direction_state": td_state[-1] if td_state else "NEUTRAL",
                "proximity": proximity_per[-1] if proximity_per else 50.0,
                "hull": curr_hull_val,
                "hull_lag2": curr_shull_val,
                "hull_state": curr_hull_st,
                "adx": round(abs(td_strength) * 50.0, 1),  # backwards-compatible proxy
                "oi": oi,
                "oi_chg": oi_chg,
                "buildup": buildup,
                "distance_pts": round(curr_close - curr_at_val, 2),
                "distance_pct": round(((curr_close - curr_at_val) / max(0.1, curr_at_val)) * 100.0, 2),
                "signal_trigger": signal_trigger
            }
        }

    # ---------------------------------------------------------
    # Bot Execution Hooks: Option-Chart Confirmation
    # ---------------------------------------------------------
    def is_option_confirmed_by_ott(self, symbol: str, strike: float, option_type: str) -> Tuple[bool, str]:
        """
        Verifies if the option contract's own 5-minute chart has confirmed Close > OTT.
        Used by SmartTrackerBot to gate trade entry.
        """
        chart_data = self.get_option_chart_data(symbol, strike, option_type)
        curr = chart_data.get("current_state", {})
        close = curr.get("close", 0.0)
        ott = curr.get("ott", 0.0)
        adx = curr.get("adx", 0.0)
        ott_state = curr.get("ott_state", "NEUTRAL")

        if close <= 0 or ott <= 0:
            return True, "Insufficient option candle history, falling back to spot indicators"

        if close > ott and ott_state == "BULLISH":
            return True, f"Option chart confirms breakout above OTT (LTP ₹{close:.1f} > OTT ₹{ott:.1f}, ADX {adx:.1f})"
        else:
            return False, f"Option chart is below OTT (LTP ₹{close:.1f} <= OTT ₹{ott:.1f})"

    def should_exit_by_option_ott(self, symbol: str, strike: float, option_type: str) -> Tuple[bool, str]:
        """
        Checks if the option contract has dropped below its own OTT line on the 5-minute chart.
        Used by SmartTrackerBot as a dynamic option-level Trailing SL.
        """
        chart_data = self.get_option_chart_data(symbol, strike, option_type)
        curr = chart_data.get("current_state", {})
        close = curr.get("close", 0.0)
        ott = curr.get("ott", 0.0)

        if close <= 0 or ott <= 0:
            return False, "Insufficient option candle history"

        if close < ott:
            return True, f"Option price crossed below its 5-min OTT line (LTP ₹{close:.1f} < OTT ₹{ott:.1f})"
        return False, "Option is holding above OTT line"

    # ---------------------------------------------------------
    # Strike-Level PineScript Signal Classifier (ATM +- 2)
    # ---------------------------------------------------------
    def classify_strike_signal(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        spot: float,
        atm: float,
        ltp: float,
        pchange: float,
        oi: int,
        oi_chg: int,
        volume: int = 0,
        chart_data: Optional[Dict[str, Any]] = None,
        spot_ott_state: str = "NEUTRAL"
    ) -> Dict[str, Any]:
        """
        Classifies whether an ATM +- 2 option strike is in:
        - BUY (Momentum Breakout): Option Close > OTT, OTT state Bullish, Long Buildup / Short Covering
        - SELL (Institutional Writing): Option Close <= OTT, Short Buildup defense
        - EXIT (Breakdown / Unwinding): Price below OTT line, Long Unwinding
        - HOLD (Neutral consolidation)
        """
        sym = symbol.upper()
        otype = option_type.upper()

        # 1. Institutional Buildup Classification
        if pchange >= 0 and oi_chg >= 0:
            buildup = "LONG_BUILDUP"
        elif pchange >= 0 and oi_chg < 0:
            buildup = "SHORT_COVERING"
        elif pchange < 0 and oi_chg >= 0:
            buildup = "SHORT_BUILDUP"
        else:
            buildup = "LONG_UNWINDING"

        # 2. Retrieve 5-minute candle OTT and ADX
        if chart_data is None:
            chart_data = self.get_option_chart_data(sym, strike, otype)

        curr = chart_data.get("current_state", {})
        ott = curr.get("ott", 0.0)
        adx = curr.get("adx", 20.0)
        ott_state = curr.get("ott_state", "NEUTRAL")
        candles = chart_data.get("candles", [])

        # 3. PineScript Decision Logic
        if ott > 0 and len(candles) >= 2:
            is_above_ott = ltp > ott
            if otype == "CE":
                if is_above_ott and ott_state == "BULLISH" and buildup in ("LONG_BUILDUP", "SHORT_COVERING") and spot_ott_state != "BEARISH":
                    action = "BUY"
                    badge = "BUY 🟢"
                    cls = "sig-buy"
                    reason = f"Bullish OTT Breakout (₹{ltp:.1f} > OTT ₹{ott:.1f}) + {buildup.replace('_', ' ')}"
                elif (not is_above_ott or ott_state == "BEARISH") and buildup == "SHORT_BUILDUP" and strike >= (atm - 0.1):
                    action = "SELL"
                    badge = "SELL 🛡️"
                    cls = "sig-sell"
                    reason = f"Decaying Under OTT (₹{ltp:.1f} <= OTT ₹{ott:.1f}) + Institutional Call Resistance"
                elif (not is_above_ott) and buildup == "LONG_UNWINDING":
                    action = "EXIT"
                    badge = "EXIT ⚠️"
                    cls = "sig-exit"
                    reason = f"Under OTT (₹{ltp:.1f} < OTT ₹{ott:.1f}) + Long Unwinding"
                else:
                    action = "HOLD"
                    badge = "HOLD"
                    cls = "sig-hold"
                    reason = f"Neutral ({buildup.replace('_', ' ')}, ADX {adx:.1f})"
            else:  # PE
                if is_above_ott and ott_state == "BULLISH" and buildup in ("LONG_BUILDUP", "SHORT_COVERING") and spot_ott_state != "BULLISH":
                    action = "BUY"
                    badge = "BUY 🟢"
                    cls = "sig-buy"
                    reason = f"Bullish OTT Breakout (₹{ltp:.1f} > OTT ₹{ott:.1f}) + {buildup.replace('_', ' ')}"
                elif (not is_above_ott or ott_state == "BEARISH") and buildup == "SHORT_BUILDUP" and strike <= (atm + 0.1):
                    action = "SELL"
                    badge = "SELL 🛡️"
                    cls = "sig-sell"
                    reason = f"Decaying Under OTT (₹{ltp:.1f} <= OTT ₹{ott:.1f}) + Put Writer Floor Defense"
                elif (not is_above_ott) and buildup == "LONG_UNWINDING":
                    action = "EXIT"
                    badge = "EXIT ⚠️"
                    cls = "sig-exit"
                    reason = f"Under OTT (₹{ltp:.1f} < OTT ₹{ott:.1f}) + Long Unwinding"
                else:
                    action = "HOLD"
                    badge = "HOLD"
                    cls = "sig-hold"
                    reason = f"Neutral ({buildup.replace('_', ' ')}, ADX {adx:.1f})"
        else:
            # Fallback based on intraday momentum & OI buildup
            if buildup in ("LONG_BUILDUP", "SHORT_COVERING") and pchange > 0:
                action = "BUY"
                badge = "BUY 🟢"
                cls = "sig-buy"
                reason = f"Intraday {buildup.replace('_', ' ')}"
            elif buildup == "SHORT_BUILDUP":
                action = "SELL"
                badge = "SELL 🛡️"
                cls = "sig-sell"
                reason = f"Intraday Writer Short Buildup"
            elif buildup == "LONG_UNWINDING":
                action = "EXIT"
                badge = "EXIT ⚠️"
                cls = "sig-exit"
                reason = f"Intraday Long Unwinding"
            else:
                action = "HOLD"
                badge = "HOLD"
                cls = "sig-hold"
                reason = f"Intraday Consolidation"

        return {
            "action": action,
            "badge": badge,
            "cls": cls,
            "reason": reason,
            "ott": ott,
            "ott_state": ott_state,
            "adx": adx,
            "buildup": buildup,
            "alphatrend": curr.get("alphatrend", ltp),
            "alphatrend_state": curr.get("alphatrend_state", "NEUTRAL"),
            "trend_direction": curr.get("trend_direction", 0.0),
            "trend_direction_state": curr.get("trend_direction_state", "NEUTRAL"),
            "hull": curr.get("hull", ltp),
            "hull_state": curr.get("hull_state", "NEUTRAL")
        }

    def get_atm2_matrix(
        self,
        symbol: str,
        chain: ParsedOptionChain,
        spot_ott_state: str = "NEUTRAL"
    ) -> Dict[str, Any]:
        """
        Builds complete ATM +- 2 strikes matrix (Top 5 active strikes) with Call & Put
        PineScript signals, OI, Delta OI, and strike-level bias.
        """
        sym = symbol.upper()
        spot = chain.spot_price
        atm = chain.atm_strike
        step = get_settings().STRIKE_STEPS.get(sym, 50)

        strike_tags = [
            (atm - (2 * step), "ATM-2"),
            (atm - step, "ATM-1"),
            (atm, "ATM"),
            (atm + step, "ATM+1"),
            (atm + (2 * step), "ATM+2")
        ]

        strike_map = {s.strikePrice: s for s in chain.strikes}
        matrix_rows = []
        buying_strikes = []
        selling_strikes = []

        for stk, tag in strike_tags:
            row = strike_map.get(stk)
            ce_data = row.CE if row else None
            pe_data = row.PE if row else None

            ce_ltp = ce_data.lastPrice if ce_data else 0.0
            ce_oi = ce_data.openInterest if ce_data else 0
            ce_oi_chg = ce_data.changeinOpenInterest if ce_data else 0
            ce_pchg = ce_data.pChange if ce_data else 0.0
            ce_vol = ce_data.totalTradedVolume if ce_data else 0

            pe_ltp = pe_data.lastPrice if pe_data else 0.0
            pe_oi = pe_data.openInterest if pe_data else 0
            pe_oi_chg = pe_data.changeinOpenInterest if pe_data else 0
            pe_pchg = pe_data.pChange if pe_data else 0.0
            pe_vol = pe_data.totalTradedVolume if pe_data else 0

            ce_sig = self.classify_strike_signal(
                symbol=sym,
                strike=stk,
                option_type="CE",
                spot=spot,
                atm=atm,
                ltp=ce_ltp,
                pchange=ce_pchg,
                oi=ce_oi,
                oi_chg=ce_oi_chg,
                volume=ce_vol,
                spot_ott_state=spot_ott_state
            )

            pe_sig = self.classify_strike_signal(
                symbol=sym,
                strike=stk,
                option_type="PE",
                spot=spot,
                atm=atm,
                ltp=pe_ltp,
                pchange=pe_pchg,
                oi=pe_oi,
                oi_chg=pe_oi_chg,
                volume=pe_vol,
                spot_ott_state=spot_ott_state
            )

            oi_diff = ce_oi - pe_oi
            strike_pcr = round(pe_oi / max(1, ce_oi), 2)

            # Net Institutional Bias
            if ce_sig["action"] == "BUY":
                buying_strikes.append(f"{int(stk)} CE [{tag}]")
            if pe_sig["action"] == "BUY":
                buying_strikes.append(f"{int(stk)} PE [{tag}]")
            if ce_sig["action"] == "SELL":
                selling_strikes.append(f"{int(stk)} CE [{tag}]")
            if pe_sig["action"] == "SELL":
                selling_strikes.append(f"{int(stk)} PE [{tag}]")

            if ce_sig["action"] == "BUY" and pe_sig["action"] != "BUY":
                bias = "BULLISH CALL BUYING"
            elif pe_sig["action"] == "BUY" and ce_sig["action"] != "BUY":
                bias = "BEARISH PUT BUYING"
            elif ce_sig["action"] == "SELL" and pe_sig["action"] != "SELL":
                bias = "CALL WRITING (RESISTANCE)"
            elif pe_sig["action"] == "SELL" and ce_sig["action"] != "SELL":
                bias = "PUT WRITING (SUPPORT)"
            else:
                bias = "BALANCED / STRADDLE"

            # Strike-Specific Hull Suite Evaluation (Independent entity)
            ce_hull_val = ce_sig.get("hull", ce_ltp)
            ce_hull_state = ce_sig.get("hull_state", "NEUTRAL")
            pe_hull_val = pe_sig.get("hull", pe_ltp)
            pe_hull_state = pe_sig.get("hull_state", "NEUTRAL")

            if ce_hull_state == "BULLISH" and pe_hull_state == "BEARISH":
                hull_sig_label = "🟢 BULLISH"
                hull_sig_cls = "hull-pill-bull"
                hull_sig_action = "BULLISH"
            elif pe_hull_state == "BULLISH" and ce_hull_state == "BEARISH":
                hull_sig_label = "🔴 BEARISH"
                hull_sig_cls = "hull-pill-bear"
                hull_sig_action = "BEARISH"
            elif ce_hull_state == "BULLISH":
                hull_sig_label = "▲ CE BULL"
                hull_sig_cls = "hull-pill-bull"
                hull_sig_action = "CE_BULL"
            elif pe_hull_state == "BULLISH":
                hull_sig_label = "▼ PE BULL"
                hull_sig_cls = "hull-pill-bear"
                hull_sig_action = "PE_BULL"
            else:
                hull_sig_label = "◆ NEUTRAL"
                hull_sig_cls = "hull-pill-neutral"
                hull_sig_action = "NEUTRAL"

            strike_hull_sig = {
                "strike": stk,
                "label": hull_sig_label,
                "cls": hull_sig_cls,
                "action": hull_sig_action,
                "ce_hull": round(ce_hull_val, 2),
                "ce_state": ce_hull_state,
                "pe_hull": round(pe_hull_val, 2),
                "pe_state": pe_hull_state,
                "tooltip": f"Hull Suite: CE ₹{ce_hull_val:.1f} ({ce_hull_state}) | PE ₹{pe_hull_val:.1f} ({pe_hull_state})"
            }

            matrix_rows.append({
                "strike": stk,
                "tag": tag,
                "label": f"{int(stk)} [{tag}]",
                "ce": {
                    "ltp": ce_ltp,
                    "oi": ce_oi,
                    "oi_chg": ce_oi_chg,
                    "pChange": ce_pchg,
                    "volume": ce_vol,
                    **ce_sig
                },
                "pe": {
                    "ltp": pe_ltp,
                    "oi": pe_oi,
                    "oi_chg": pe_oi_chg,
                    "pChange": pe_pchg,
                    "volume": pe_vol,
                    **pe_sig
                },
                "hull_signal": strike_hull_sig,
                "oi_difference": oi_diff,
                "strike_pcr": strike_pcr,
                "bias": bias
            })

        return {
            "symbol": sym,
            "spot": spot,
            "atm": atm,
            "step": step,
            "strikes": matrix_rows,
            "buying_strikes": buying_strikes,
            "selling_strikes": selling_strikes,
            "buying_count": len(buying_strikes),
            "selling_count": len(selling_strikes)
        }

    def check_option_premium_gate(
        self,
        symbol: str,
        strike: float,
        option_type: str,
        window_seconds: int = 30
    ) -> Dict[str, Any]:
        """
        Evaluates the 30-Second Option Premium Confirmation Gate (Anti-Falling Knife Entry Gate).
        Inspired by AI-Trader:
        Catches the 'falling knife' entry pattern where the index triggers an entry,
        but the option contract we are about to buy is actively repricing down.
        """
        key = self._get_contract_key(symbol, strike, option_type)
        ticks = self._recent_ticks.get(key, [])
        if not ticks or len(ticks) < 2:
            return {
                "is_confirmed": True,
                "is_falling_knife": False,
                "momentum_pct": 0.0,
                "status_label": "CONFIRMED (STABLE)",
                "badge_class": "badge-neutral"
            }

        now_epoch = ticks[-1][0]
        curr_price = ticks[-1][1]

        # Oldest tick within the window
        window_ticks = [t for t in ticks if t[0] >= now_epoch - window_seconds]
        if not window_ticks:
            window_ticks = ticks[-3:]

        start_price = window_ticks[0][1]
        if start_price <= 0:
            pct_change = 0.0
        else:
            pct_change = round(((curr_price - start_price) / start_price) * 100.0, 2)

        # A falling knife occurs when option premium is dumping (> 0.8% drop in 30 seconds)
        is_falling = (pct_change <= -0.8)
        is_confirmed = (pct_change > -0.5)

        if is_falling:
            status_label = f"KNIFE FALL ({pct_change:+.1f}%)"
            badge_class = "badge-bear"
        elif pct_change >= 0.5:
            status_label = f"RISING FLOW (+{pct_change:.1f}%)"
            badge_class = "badge-active"
        else:
            status_label = f"STEADY ({pct_change:+.1f}%)"
            badge_class = "badge-neutral"

        return {
            "is_confirmed": is_confirmed,
            "is_falling_knife": is_falling,
            "momentum_pct": pct_change,
            "status_label": status_label,
            "badge_class": badge_class
        }


option_candle_service = OptionCandleService()
