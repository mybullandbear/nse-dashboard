"""
Technical Indicator Suite: Pure Python implementation of PineScript
'Merged Rite Option Game with ADX, CPR, and OTT'
Includes:
- True Range & ATR
- DMI (+DI, -DI) & ADX
- RiteTrend Dynamic Channel
- OTT (Optimized Trend Tracker with Chande Momentum VAR)
"""
import math
from typing import List, Dict, Any, Tuple, Optional


class TechnicalIndicators:
    @staticmethod
    def rma(values: List[float], length: int) -> List[float]:
        """Wilder's RMA (equivalent to ta.rma in TradingView)"""
        out = []
        if not values or length <= 0:
            return out
        alpha = 1.0 / length
        rma_val = None
        for i, val in enumerate(values):
            if val is None:
                out.append(0.0)
                continue
            if rma_val is None:
                if i < length - 1:
                    out.append(0.0)
                    continue
                # Initial SMA for first 'length' bars
                rma_val = sum(values[i - length + 1 : i + 1]) / length
            else:
                rma_val = alpha * val + (1.0 - alpha) * rma_val
            out.append(rma_val)
        return out

    @staticmethod
    def compute_adx(highs: List[float], lows: List[float], closes: List[float], length: int = 14) -> Tuple[List[float], List[float], List[float]]:
        """Computes plusDI, minusDI, and ADX(length)"""
        n = len(closes)
        if n < length + 1:
            return [0.0] * n, [0.0] * n, [0.0] * n

        tr_list = [0.0]
        plus_dm_list = [0.0]
        minus_dm_list = [0.0]

        for i in range(1, n):
            h, l = highs[i], lows[i]
            prev_h, prev_l, prev_c = highs[i - 1], lows[i - 1], closes[i - 1]

            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            tr_list.append(tr)

            up = h - prev_h
            down = prev_l - l
            plus_dm = max(up - down, 0.0) if up > down and up > 0 else 0.0
            minus_dm = max(down - up, 0.0) if down > up and down > 0 else 0.0
            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)

        tr_rma = TechnicalIndicators.rma(tr_list, length)
        plus_dm_rma = TechnicalIndicators.rma(plus_dm_list, length)
        minus_dm_rma = TechnicalIndicators.rma(minus_dm_list, length)

        plus_di = []
        minus_di = []
        dx_list = []

        for i in range(n):
            trur = tr_rma[i]
            p_di = (100.0 * plus_dm_rma[i] / trur) if trur > 0 else 0.0
            m_di = (100.0 * minus_dm_rma[i] / trur) if trur > 0 else 0.0
            plus_di.append(p_di)
            minus_di.append(m_di)

            denom = p_di + m_di
            dx = (abs(p_di - m_di) / denom * 100.0) if denom > 0 else 0.0
            dx_list.append(dx)

        adx = TechnicalIndicators.rma(dx_list, length)
        return plus_di, minus_di, adx

    @staticmethod
    def compute_rsi(closes: List[float], length: int = 14) -> List[float]:
        """Standard RSI(14)"""
        n = len(closes)
        if n < length + 1:
            return [50.0] * n

        gains = [0.0]
        losses = [0.0]
        for i in range(1, n):
            diff = closes[i] - closes[i - 1]
            gains.append(max(diff, 0.0))
            losses.append(max(-diff, 0.0))

        avg_gain = TechnicalIndicators.rma(gains, length)
        avg_loss = TechnicalIndicators.rma(losses, length)

        rsi = []
        for i in range(n):
            al = avg_loss[i]
            if al == 0:
                rsi.append(100.0 if avg_gain[i] > 0 else 50.0)
            else:
                rs = avg_gain[i] / al
                rsi.append(100.0 - (100.0 / (1.0 + rs)))
        return rsi

    @staticmethod
    def compute_ott(closes: List[float], length: int = 2, percent: float = 1.4) -> Tuple[List[float], List[float], List[str]]:
        """
        Computes OTT (Optimized Trend Tracker by Anıl Özekşi) using VAR (Chande Momentum Oscillator MA)
        Returns: (MAvg, OTT, trend_state)
        trend_state: 'BULLISH' if MAvg > OTT else 'BEARISH'
        """
        n = len(closes)
        if n == 0:
            return [], [], []

        # VAR Calculation
        valpha = 2.0 / (length + 1)
        vud1 = [0.0]
        vdd1 = [0.0]
        for i in range(1, n):
            diff = closes[i] - closes[i - 1]
            vud1.append(diff if diff > 0 else 0.0)
            vdd1.append(-diff if diff < 0 else 0.0)

        var_list = []
        var_prev = closes[0]

        for i in range(n):
            start_idx = max(0, i - 8)
            vUD = sum(vud1[start_idx : i + 1])
            vDD = sum(vdd1[start_idx : i + 1])
            denom = vUD + vDD
            vCMO = ((vUD - vDD) / denom) if denom > 0 else 0.0

            var_val = (valpha * abs(vCMO) * closes[i]) + ((1.0 - valpha * abs(vCMO)) * var_prev)
            var_list.append(var_val)
            var_prev = var_val

        mavg = var_list
        fark = [m * percent * 0.01 for m in mavg]

        long_stop = [mavg[0] - fark[0]]
        short_stop = [mavg[0] + fark[0]]
        direction = [1]
        ott_list = []
        trend_state = []

        for i in range(n):
            if i == 0:
                mt = long_stop[0]
                ott = mt * (200.0 + percent) / 200.0
                ott_list.append(ott)
                trend_state.append("BULLISH" if mavg[0] > ott else "BEARISH")
                continue

            ls = mavg[i] - fark[i]
            ls_prev = long_stop[i - 1]
            cur_ls = max(ls, ls_prev) if mavg[i] > ls_prev else ls
            long_stop.append(cur_ls)

            ss = mavg[i] + fark[i]
            ss_prev = short_stop[i - 1]
            cur_ss = min(ss, ss_prev) if mavg[i] < ss_prev else ss
            short_stop.append(cur_ss)

            dir_prev = direction[i - 1]
            if dir_prev == -1 and mavg[i] > ss_prev:
                cur_dir = 1
            elif dir_prev == 1 and mavg[i] < ls_prev:
                cur_dir = -1
            else:
                cur_dir = dir_prev
            direction.append(cur_dir)

            mt = cur_ls if cur_dir == 1 else cur_ss
            ott = mt * (200.0 + percent) / 200.0 if mavg[i] > mt else mt * (200.0 - percent) / 200.0
            ott_list.append(ott)
            trend_state.append("BULLISH" if mavg[i] > ott else "BEARISH")

        return mavg, ott_list, trend_state

    @staticmethod
    def compute_ema(values: List[float], length: int) -> List[float]:
        """Exponential Moving Average (EMA) matching ta.ema in TradingView/PineScript"""
        n = len(values)
        if n == 0:
            return []
        if length <= 1:
            return [float(v) for v in values]
        out = [float(values[0])]
        multiplier = 2.0 / (length + 1)
        for i in range(1, n):
            ema = (float(values[i]) - out[-1]) * multiplier + out[-1]
            out.append(ema)
        return out

    @staticmethod
    def compute_wma(values: List[float], length: int) -> List[float]:
        """Weighted Moving Average (WMA) matching ta.wma in TradingView/PineScript"""
        n = len(values)
        if n == 0:
            return []
        if length <= 1:
            return [float(v) for v in values]
        out = []
        w_sum = length * (length + 1) // 2
        for i in range(n):
            if i < length - 1:
                k = i + 1
                cur_w = k * (k + 1) // 2
                acc = sum((k - idx) * values[i - idx] for idx in range(k))
                out.append(acc / cur_w)
            else:
                acc = sum((length - idx) * values[i - idx] for idx in range(length))
                out.append(acc / w_sum)
        return out

    @staticmethod
    def compute_hull(
        closes: List[float],
        mode: str = "Ehma",
        length: int = 34,
        length_mult: float = 2.0
    ) -> Dict[str, Any]:
        """
        Hull Suite Indicator by mybullandbear / InSilico
        Matches PineScript in indicators/Hull.md:
        - Mode "Ehma": EMA(2*EMA(src, len/2) - EMA(src, len), round(sqrt(len)))
        - Mode "Hma":  WMA(2*WMA(src, len/2) - WMA(src, len), round(sqrt(len)))
        - Mode "Thma": WMA(3*WMA(src, len/3) - WMA(src, len/2) - WMA(src, len), len/2)
        - MHULL = HULL[0]
        - SHULL = HULL[2]
        - Trend: BULLISH if MHULL > SHULL else (BEARISH if MHULL < SHULL else NEUTRAL)
        - Alert / Signals: crossover(MHULL, SHULL) -> BUY, crossunder(MHULL, SHULL) -> SELL
        """
        n = len(closes)
        if n == 0:
            return {
                "mhull": [],
                "shull": [],
                "trend_state": [],
                "buy_signals": [],
                "sell_signals": [],
                "curr_mhull": 0.0,
                "curr_shull": 0.0,
                "curr_state": "NEUTRAL"
            }

        eff_len = max(2, int(length * length_mult))
        eff_len = min(eff_len, max(4, n))

        mode_clean = (mode or "Ehma").capitalize()
        if mode_clean == "Hma":
            len1 = max(1, int(round(eff_len / 2)))
            len2 = max(1, int(eff_len))
            sqrt_len = max(1, int(round(math.sqrt(eff_len))))
            wma_half = TechnicalIndicators.compute_wma(closes, len1)
            wma_full = TechnicalIndicators.compute_wma(closes, len2)
            diff = [2.0 * wma_half[i] - wma_full[i] for i in range(n)]
            hull = TechnicalIndicators.compute_wma(diff, sqrt_len)
        elif mode_clean == "Thma":
            half_len = max(2, int(round(eff_len / 2)))
            len3 = max(1, int(round(half_len / 3)))
            len2 = max(1, int(round(half_len / 2)))
            len1 = max(1, int(half_len))
            wma3 = TechnicalIndicators.compute_wma(closes, len3)
            wma2 = TechnicalIndicators.compute_wma(closes, len2)
            wma1 = TechnicalIndicators.compute_wma(closes, len1)
            diff = [3.0 * wma3[i] - wma2[i] - wma1[i] for i in range(n)]
            hull = TechnicalIndicators.compute_wma(diff, len1)
        else:  # Default "Ehma"
            len1 = max(1, int(round(eff_len / 2)))
            len2 = max(1, int(eff_len))
            sqrt_len = max(1, int(round(math.sqrt(eff_len))))
            ema_half = TechnicalIndicators.compute_ema(closes, len1)
            ema_full = TechnicalIndicators.compute_ema(closes, len2)
            diff = [2.0 * ema_half[i] - ema_full[i] for i in range(n)]
            hull = TechnicalIndicators.compute_ema(diff, sqrt_len)

        mhull = [round(h, 2) for h in hull]
        shull = []
        for i in range(n):
            if i >= 2:
                shull.append(round(hull[i - 2], 2))
            else:
                shull.append(round(hull[0], 2))

        trend_state = []
        buy_signals = [False] * n
        sell_signals = [False] * n

        for i in range(n):
            m_v = mhull[i]
            s_v = shull[i]
            if m_v > s_v:
                st = "BULLISH"
            elif m_v < s_v:
                st = "BEARISH"
            else:
                st = trend_state[-1] if trend_state else "NEUTRAL"
            trend_state.append(st)

            if i >= 1:
                prev_m = mhull[i - 1]
                prev_s = shull[i - 1]
                if prev_m <= prev_s and m_v > s_v:
                    buy_signals[i] = True
                elif prev_m >= prev_s and m_v < s_v:
                    sell_signals[i] = True

        return {
            "mhull": mhull,
            "shull": shull,
            "trend_state": trend_state,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals,
            "curr_mhull": mhull[-1] if mhull else 0.0,
            "curr_shull": shull[-1] if shull else 0.0,
            "curr_state": trend_state[-1] if trend_state else "NEUTRAL"
        }

    @staticmethod
    def compute_vwap(highs: List[float], lows: List[float], closes: List[float], volumes: List[float]) -> List[float]:
        """Intraday Volume Weighted Average Price (VWAP)"""
        n = len(closes)
        if n == 0:
            return []
        vwap = []
        cum_tp_vol = 0.0
        cum_vol = 0.0
        for i in range(n):
            tp = (highs[i] + lows[i] + closes[i]) / 3.0
            vol = max(1.0, float(volumes[i])) if volumes and i < len(volumes) else 1.0
            cum_tp_vol += tp * vol
            cum_vol += vol
            vwap.append(round(cum_tp_vol / cum_vol, 2) if cum_vol > 0 else tp)
        return vwap

    @staticmethod
    def compute_bollinger(closes: List[float], length: int = 20, mult: float = 2.0) -> Tuple[List[float], List[float], List[float]]:
        """Bollinger Bands (Upper, Middle, Lower)"""
        n = len(closes)
        if n == 0:
            return [], [], []
        upper, middle, lower = [], [], []
        for i in range(n):
            if i < length - 1:
                subset = closes[: i + 1]
            else:
                subset = closes[i - length + 1 : i + 1]
            m = sum(subset) / len(subset)
            variance = sum((x - m) ** 2 for x in subset) / len(subset)
            std = math.sqrt(variance)
            middle.append(round(m, 2))
            upper.append(round(m + mult * std, 2))
            lower.append(round(max(0.0, m - mult * std), 2))
        return upper, middle, lower

    @staticmethod
    def compute_supertrend(highs: List[float], lows: List[float], closes: List[float], period: int = 10, multiplier: float = 3.0) -> Tuple[List[float], List[str]]:
        """SuperTrend (10, 3) - returns (trend_line, direction ['BULLISH'/'BEARISH'])"""
        n = len(closes)
        if n == 0:
            return [], []
        if n < period:
            return [closes[i] for i in range(n)], ["NEUTRAL"] * n

        tr_list = [highs[0] - lows[0]]
        for i in range(1, n):
            h, l, prev_c = highs[i], lows[i], closes[i - 1]
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            tr_list.append(tr)
        atr = TechnicalIndicators.rma(tr_list, period)

        upper_band = []
        lower_band = []
        st_line = []
        direction = []

        for i in range(n):
            hl2 = (highs[i] + lows[i]) / 2.0
            basic_upper = hl2 + (multiplier * atr[i])
            basic_lower = hl2 - (multiplier * atr[i])

            if i == 0:
                upper_band.append(basic_upper)
                lower_band.append(basic_lower)
                st_line.append(basic_upper)
                direction.append("BEARISH" if closes[0] < hl2 else "BULLISH")
                continue

            prev_upper = upper_band[i - 1]
            prev_close = closes[i - 1]
            if basic_upper < prev_upper or prev_close > prev_upper:
                final_upper = basic_upper
            else:
                final_upper = prev_upper
            upper_band.append(final_upper)

            prev_lower = lower_band[i - 1]
            if basic_lower > prev_lower or prev_close < prev_lower:
                final_lower = basic_lower
            else:
                final_lower = prev_lower
            lower_band.append(final_lower)

            prev_st = st_line[i - 1]
            prev_dir = direction[i - 1]

            if prev_dir == "BULLISH":
                if closes[i] < final_lower:
                    cur_dir = "BEARISH"
                    cur_st = final_upper
                else:
                    cur_dir = "BULLISH"
                    cur_st = final_lower
            else:
                if closes[i] > final_upper:
                    cur_dir = "BULLISH"
                    cur_st = final_lower
                else:
                    cur_dir = "BEARISH"
                    cur_st = final_upper

            direction.append(cur_dir)
            st_line.append(round(cur_st, 2))

        return st_line, direction


    @staticmethod
    def compute_mfi(highs: List[float], lows: List[float], closes: List[float], volumes: List[float], length: int = 14) -> List[float]:
        """Money Flow Index (MFI) with 0-100 normalization"""
        n = len(closes)
        if n == 0:
            return []
        if n < length + 1 or not volumes or sum(volumes) == 0:
            return TechnicalIndicators.compute_rsi(closes, length)

        tp = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
        pos_mf = [0.0] * n
        neg_mf = [0.0] * n

        for i in range(1, n):
            rmf = tp[i] * volumes[i]
            if tp[i] > tp[i - 1]:
                pos_mf[i] = rmf
            elif tp[i] < tp[i - 1]:
                neg_mf[i] = rmf

        mfi = [50.0] * n
        for i in range(length, n):
            p_sum = sum(pos_mf[i - length + 1 : i + 1])
            n_sum = sum(neg_mf[i - length + 1 : i + 1])
            if n_sum == 0:
                mfi[i] = 100.0 if p_sum > 0 else 50.0
            else:
                mr = p_sum / n_sum
                mfi[i] = round(100.0 - (100.0 / (1.0 + mr)), 2)
        return mfi

    @staticmethod
    def compute_alphatrend(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: Optional[List[float]] = None,
        coeff: float = 1.0,
        ap: int = 14
    ) -> Dict[str, Any]:
        """
        AlphaTrend Indicator by mybullandbear
        Returns:
            - alphatrend: List[float]
            - alphatrend_lag2: List[float]
            - trend_state: List[str] ('BULLISH' / 'BEARISH')
            - buy_signals: List[bool]
            - sell_signals: List[bool]
        """
        n = len(closes)
        if n == 0:
            return {"alphatrend": [], "alphatrend_lag2": [], "trend_state": [], "buy_signals": [], "sell_signals": []}

        tr_list = [highs[0] - lows[0]]
        for i in range(1, n):
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            tr_list.append(tr)

        # ATR = SMA(tr, ap)
        atr = []
        for i in range(n):
            start = max(0, i - ap + 1)
            sub = tr_list[start : i + 1]
            atr.append(sum(sub) / len(sub) if sub else 1.0)

        # Momentum condition: MFI >= 50 if volume data available, else RSI >= 50
        has_vol = volumes is not None and len(volumes) == n and sum(volumes) > 0
        if has_vol:
            mfi = TechnicalIndicators.compute_mfi(highs, lows, closes, volumes, length=ap)
            cond = [m >= 50.0 for m in mfi]
        else:
            rsi = TechnicalIndicators.compute_rsi(closes, length=ap)
            cond = [r >= 50.0 for r in rsi]

        up_t = [lows[i] - atr[i] * coeff for i in range(n)]
        down_t = [highs[i] + atr[i] * coeff for i in range(n)]

        alpha_trend = [closes[0]]
        for i in range(1, n):
            prev_at = alpha_trend[i - 1]
            if cond[i]:
                # upT < nz(AlphaTrend[1]) ? nz(AlphaTrend[1]) : upT
                val = prev_at if up_t[i] < prev_at else up_t[i]
            else:
                # downT > nz(AlphaTrend[1]) ? nz(AlphaTrend[1]) : downT
                val = prev_at if down_t[i] > prev_at else down_t[i]
            alpha_trend.append(round(val, 2))

        # Lag 2 series
        alpha_trend_lag2 = []
        for i in range(n):
            if i >= 2:
                alpha_trend_lag2.append(alpha_trend[i - 2])
            else:
                alpha_trend_lag2.append(alpha_trend[0])

        trend_state = []
        buy_signals = [False] * n
        sell_signals = [False] * n

        for i in range(n):
            if i >= 2:
                if alpha_trend[i] > alpha_trend_lag2[i]:
                    st = "BULLISH"
                elif alpha_trend[i] < alpha_trend_lag2[i]:
                    st = "BEARISH"
                else:
                    st = trend_state[-1] if trend_state else "NEUTRAL"

                # Crossover / Crossunder signals
                if i >= 1:
                    prev_at = alpha_trend[i - 1]
                    prev_lag = alpha_trend_lag2[i - 1]
                    if prev_at <= prev_lag and alpha_trend[i] > alpha_trend_lag2[i]:
                        buy_signals[i] = True
                    elif prev_at >= prev_lag and alpha_trend[i] < alpha_trend_lag2[i]:
                        sell_signals[i] = True
            else:
                st = "BULLISH" if closes[i] >= alpha_trend[i] else "BEARISH"
            trend_state.append(st)

        return {
            "alphatrend": alpha_trend,
            "alphatrend_lag2": alpha_trend_lag2,
            "trend_state": trend_state,
            "buy_signals": buy_signals,
            "sell_signals": sell_signals
        }

    @staticmethod
    def compute_shonya(
        closes: List[float],
        len_val: int = 14,
        grav_len: int = 19,
        decay_rate: float = 0.96,
        mad_len: int = 24,
        trail_min: float = 1.0,
        trail_max: float = 1.0
    ) -> Dict[str, Any]:
        """
        Shonya Gravity Adaptive Cloud Indicator by mybullandbear
        Returns:
            - basis: List[float]
            - upper: List[float]
            - lower: List[float]
            - trend_state: List[str] ('BULLISH' / 'BEARISH')
            - gravity: List[float]
            - pull: List[float]
        """
        n = len(closes)
        if n == 0:
            return {"basis": [], "upper": [], "lower": [], "trend_state": [], "gravity": [], "pull": []}

        basis = TechnicalIndicators.compute_ema(closes, len_val)

        # Mean Absolute Deviation
        mean = []
        mad = []
        for i in range(n):
            start = max(0, i - mad_len + 1)
            sub = closes[start : i + 1]
            m = sum(sub) / len(sub)
            mean.append(m)
            m_devs = [abs(c - m) for c in sub]
            mad.append(sum(m_devs) / len(m_devs) if m_devs else 1.0)

        gravity_list = []
        pull_list = []
        upper_list = []
        lower_list = []
        trend_state = []

        cur_gravity = 0.0
        last_signal = 1 if closes[0] >= basis[0] else -1

        for i in range(n):
            if i >= grav_len:
                velocity = basis[i] - basis[i - grav_len]
                prev_vel = (basis[i - 1] - basis[i - 1 - grav_len]) if (i - 1 >= grav_len) else velocity
            else:
                velocity = basis[i] - basis[0]
                prev_vel = velocity

            accel = velocity - prev_vel
            m_val = mad[i] if mad[i] > 0 else 1.0
            norm_accel = abs(accel) / m_val

            if norm_accel > 0.01:
                cur_gravity = min(norm_accel * 8.0, 2.0)
            else:
                cur_gravity = cur_gravity * decay_rate

            cur_pull = min(cur_gravity / 1.5, 1.0)
            trail_mult = trail_max - (trail_max - trail_min) * cur_pull
            up_val = basis[i] + mad[i] * trail_mult
            dn_val = basis[i] - mad[i] * trail_mult

            # Signal crossover logic
            if i >= 1:
                prev_c = closes[i - 1]
                prev_up = upper_list[-1]
                prev_dn = lower_list[-1]
                if prev_c <= prev_up and closes[i] > up_val:
                    last_signal = 1
                elif prev_c >= prev_dn and closes[i] < dn_val:
                    last_signal = -1

            gravity_list.append(round(cur_gravity, 3))
            pull_list.append(round(cur_pull, 3))
            upper_list.append(round(up_val, 2))
            lower_list.append(round(dn_val, 2))
            trend_state.append("BULLISH" if last_signal == 1 else "BEARISH")

        return {
            "basis": [round(b, 2) for b in basis],
            "upper": upper_list,
            "lower": lower_list,
            "trend_state": trend_state,
            "gravity": gravity_list,
            "pull": pull_list
        }

    @staticmethod
    def compute_trend_direction(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        di_len: int = 14,
        mean_lb: int = 360,
        slope: float = 0.18,
        smooth_len: int = 3,
        osc_scale: float = 2.5,
        osc_smooth_len: int = 7
    ) -> Dict[str, Any]:
        """
        Trend Direction & Logistic Momentum Oscillator by mybullandbear
        Returns:
            - strength: List[float] (-1.0 to +1.0)
            - s_sma: List[float]
            - s_ema: List[float]
            - trend_state: List[str] ('BULLISH' / 'BEARISH' / 'NEUTRAL')
            - strength_latest: float
        """
        n = len(closes)
        if n == 0:
            return {"strength": [], "s_sma": [], "s_ema": [], "trend_state": [], "strength_latest": 0.0}

        plus_di, minus_di, adx = TechnicalIndicators.compute_adx(highs, lows, closes, length=di_len)

        eff_mean_lb = min(n, max(5, mean_lb))

        def _logistic_prob(series: List[float]) -> List[float]:
            prob_raw = []
            for i in range(n):
                start = max(0, i - eff_mean_lb + 1)
                sub = series[start : i + 1]
                mean_val = sum(sub) / len(sub) if sub else 0.0
                z = (series[i] - mean_val) * slope
                z_clamped = max(-20.0, min(20.0, z))
                prob = 1.0 / (1.0 + math.exp(-z_clamped))
                prob_raw.append(prob)
            return TechnicalIndicators.compute_ema(prob_raw, smooth_len)

        p_plus = _logistic_prob(plus_di)
        p_minus = _logistic_prob(minus_di)
        p_adx = _logistic_prob(adx)

        strength_bound = []
        for i in range(n):
            net_dir = p_plus[i] - p_minus[i]
            s_raw = net_dir * p_adx[i] * osc_scale
            # tanh(x)
            s_bound = math.tanh(s_raw)
            strength_bound.append(s_bound)

        strength = TechnicalIndicators.compute_ema(strength_bound, smooth_len)

        # SMA & EMA of strength
        s_sma = []
        for i in range(n):
            start = max(0, i - osc_smooth_len + 1)
            sub = strength[start : i + 1]
            s_sma.append(sum(sub) / len(sub) if sub else 0.0)
        s_ema = TechnicalIndicators.compute_ema(strength, osc_smooth_len)

        trend_state = []
        for i in range(n):
            st_val = strength[i]
            ema_val = s_ema[i]
            if st_val > 0.08:
                trend_state.append("BULLISH" if st_val >= ema_val else "WEAK_BULLISH")
            elif st_val < -0.08:
                trend_state.append("BEARISH" if st_val <= ema_val else "WEAK_BEARISH")
            else:
                trend_state.append("NEUTRAL")

        latest = round(strength[-1], 3) if strength else 0.0

        return {
            "strength": [round(s, 3) for s in strength],
            "s_sma": [round(s, 3) for s in s_sma],
            "s_ema": [round(s, 3) for s in s_ema],
            "trend_state": trend_state,
            "strength_latest": latest
        }

    @staticmethod
    def compute_proximity(
        closes: List[float],
        i_min: int = 10,
        i_max: int = 100,
        i_smooth: int = 9
    ) -> Dict[str, Any]:
        """
        Moving Averages Proximity Oscillator (MAPO) by LuxAlgo
        Returns:
            - per: List[float] (0 to 100%) - % of MAs price is above
            - len_idx: List[float] (0 to 100%) - closest MA length
            - trend_state: List[str] ('BULLISH' / 'BEARISH' / 'NEUTRAL')
            - per_latest: float
        """
        n = len(closes)
        if n == 0:
            return {"per": [], "len_idx": [], "trend_state": [], "per_latest": 50.0}

        cum = [0.0] * n
        running = 0.0
        for i in range(n):
            running += closes[i]
            cum[i] = running

        eff_max = min(i_max, max(i_min + 5, n))
        total_mas = max(1, eff_max - i_min + 1)

        raw_per = []
        raw_len = []

        for idx in range(n):
            c = closes[idx]
            above_count = 0
            min_ae = float('inf')
            closest_len = i_min

            for length in range(i_min, eff_max + 1):
                if idx >= length:
                    ma = (cum[idx] - cum[idx - length]) / length
                else:
                    ma = cum[idx] / (idx + 1)

                if c > ma:
                    above_count += 1
                ae = abs(c - ma)
                if ae <= min_ae:
                    min_ae = ae
                    closest_len = length

            raw_per.append(above_count)
            raw_len.append(closest_len)

        # Smoothing
        def _sma_list(arr: List[float], sm: int) -> List[float]:
            res = []
            for i in range(n):
                start = max(0, i - sm + 1)
                sub = arr[start : i + 1]
                res.append(sum(sub) / len(sub) if sub else 0.0)
            return res

        sm_per = _sma_list(raw_per, i_smooth)
        sm_len = _sma_list(raw_len, i_smooth)

        # Normalize 0 to 100
        norm_per = [round((p / total_mas) * 100.0, 1) for p in sm_per]
        norm_len = [round(((l - i_min) / max(1, (eff_max - i_min))) * 100.0, 1) for l in sm_len]

        trend_state = []
        for p in norm_per:
            if p >= 60.0:
                trend_state.append("BULLISH")
            elif p <= 40.0:
                trend_state.append("BEARISH")
            else:
                trend_state.append("NEUTRAL")

        latest_per = norm_per[-1] if norm_per else 50.0
        prev_per = norm_per[-2] if len(norm_per) >= 2 else latest_per
        proximity_slope = round(latest_per - prev_per, 1)
        is_buy_cross = bool(latest_per > 50.0 and prev_per <= 50.0) if len(norm_per) >= 2 else False
        is_sell_cross = bool(latest_per < 50.0 and prev_per >= 50.0) if len(norm_per) >= 2 else False

        if latest_per >= 80.0:
            zone = "STRONG_BULLISH"
        elif latest_per >= 60.0:
            zone = "BULLISH"
        elif latest_per >= 40.0:
            zone = "NEUTRAL"
        elif latest_per >= 20.0:
            zone = "BEARISH"
        else:
            zone = "STRONG_BEARISH"

        return {
            "per": norm_per,
            "len_idx": norm_len,
            "trend_state": trend_state,
            "per_latest": latest_per,
            "proximity_slope": proximity_slope,
            "is_buy_cross": is_buy_cross,
            "is_sell_cross": is_sell_cross,
            "zone": zone
        }

    @staticmethod
    def compute_breakout_tracker(
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: Optional[List[float]] = None,
        piv_left: int = 10,
        piv_right: int = 3,
        atr_len: int = 14,
        brk_buf: float = 0.10,
        fail_buf: float = 0.50,
        close_pct: float = 0.60,
        use_body: bool = True,
        use_vol: bool = True,
        vol_len: int = 20,
        vol_mult: float = 1.2,
        use_trend: bool = False,
        trend_len: int = 100,
        use_trail: bool = True,
        trail_mult: float = 3.0,
        en_long: bool = True,
        en_short: bool = True,
        keep_bias: bool = True
    ) -> Dict[str, Any]:
        """
        Pure Python implementation of PineScript 'Breakout Tracker' (BRK-TRK).
        
        - Levels come from confirmed pivots (ta.pivothigh / ta.pivotlow) with piv_left & piv_right confirmation delay.
        - Breakout = Candle close beyond level + brk_buf * ATR.
        - Filters: Strong candle close position (closePct) & optional Volume surge (volMult * volMA).
        - Trade management: Tracks failure (close back through level - fail_buf * ATR) or ATR trailing exit (trail_mult * ATR).
        - Zero repainting: Evaluated only on closed candles with confirmed pivot delays.
        """
        n = len(closes)
        min_bars = max(piv_left + piv_right + 2, atr_len + 1)
        if n < min_bars:
            last_c = closes[-1] if closes else 0.0
            return {
                "state": "FLAT",
                "bias": "NEUTRAL",
                "signal": "HOLD",
                "breakout_level": round(last_c, 2),
                "entry_price": None,
                "fail_level": None,
                "trail_level": None,
                "open_pnl_atr": 0.0,
                "res_level": None,
                "sup_level": None,
                "atr": 0.0,
                "bias_dir": 0,
                "in_long": False,
                "in_short": False
            }

        # 1. ATR(atr_len) via Wilder's RMA
        tr_list = [highs[0] - lows[0]]
        for i in range(1, n):
            h, l, prev_c = highs[i], lows[i], closes[i - 1]
            tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
            tr_list.append(tr)
        atr_series = TechnicalIndicators.rma(tr_list, atr_len)

        # 2. Volume SMA(vol_len)
        vol_ma = [0.0] * n
        has_volume = volumes is not None and len(volumes) == n and any(v > 0 for v in volumes)
        if has_volume and volumes is not None:
            cum_vol = [0.0] * n
            running_v = 0.0
            for i, v in enumerate(volumes):
                running_v += v
                cum_vol[i] = running_v
                if i >= vol_len:
                    vol_ma[i] = (cum_vol[i] - cum_vol[i - vol_len]) / vol_len
                else:
                    vol_ma[i] = cum_vol[i] / (i + 1)

        # 3. Optional Trend EMA(trend_len)
        ema_trend = [0.0] * n
        if use_trend:
            alpha_t = 2.0 / (trend_len + 1)
            e_val = closes[0]
            for i, c in enumerate(closes):
                e_val = alpha_t * c + (1.0 - alpha_t) * e_val
                ema_trend[i] = e_val

        # 4. Confirmed Pivot Highs and Lows (Strict delay of piv_right bars to match PineScript)
        ph = [None] * n
        pl = [None] * n
        for i in range(piv_left + piv_right, n):
            p_idx = i - piv_right
            val_h = highs[p_idx]
            val_l = lows[p_idx]

            is_ph = True
            for k in range(p_idx - piv_left, p_idx):
                if highs[k] >= val_h:
                    is_ph = False
                    break
            if is_ph:
                for k in range(p_idx + 1, p_idx + piv_right + 1):
                    if highs[k] > val_h:
                        is_ph = False
                        break
            if is_ph:
                ph[i] = val_h

            is_pl = True
            for k in range(p_idx - piv_left, p_idx):
                if lows[k] <= val_l:
                    is_pl = False
                    break
            if is_pl:
                for k in range(p_idx + 1, p_idx + piv_right + 1):
                    if lows[k] < val_l:
                        is_pl = False
                        break
            if is_pl:
                pl[i] = val_l

        # 5. Persistent State Machine Simulation across Bars
        res_lvl: Optional[float] = None
        res_used: bool = True
        sup_lvl: Optional[float] = None
        sup_used: bool = True

        in_long: bool = False
        long_lvl: Optional[float] = None
        long_entry: Optional[float] = None
        long_fail: Optional[float] = None
        long_trail: Optional[float] = None
        long_atr: Optional[float] = None

        in_short: bool = False
        short_lvl: Optional[float] = None
        short_entry: Optional[float] = None
        short_fail: Optional[float] = None
        short_trail: Optional[float] = None
        short_atr: Optional[float] = None

        bias_dir: int = 0
        bias_lvl: Optional[float] = None

        buy_sig = False
        sell_sig = False
        x_long_fail = False
        x_long_trail = False
        x_short_fail = False
        x_short_trail = False

        for i in range(n):
            c_bar = closes[i]
            h_bar = highs[i]
            l_bar = lows[i]
            a_bar = atr_series[i] if atr_series[i] > 0 else (h_bar - l_bar or 1.0)
            rng = h_bar - l_bar
            pos = (c_bar - l_bar) / rng if rng > 0 else 0.5

            buy_sig = False
            sell_sig = False
            x_long_fail = False
            x_long_trail = False
            x_short_fail = False
            x_short_trail = False

            # Step 1: Update levels from newly confirmed pivots
            if ph[i] is not None:
                res_lvl = ph[i]
                res_used = False
            if pl[i] is not None:
                sup_lvl = pl[i]
                sup_used = False

            # Step 2: Manage open trades (exits first)
            if in_long:
                if long_fail is not None and c_bar < long_fail:
                    x_long_fail = True
                elif use_trail and long_trail is not None and c_bar < long_trail:
                    x_long_trail = True
                else:
                    if long_trail is not None:
                        long_trail = max(long_trail, c_bar - trail_mult * a_bar)
                    else:
                        long_trail = c_bar - trail_mult * a_bar
                if x_long_fail or x_long_trail:
                    in_long = False

            if in_short:
                if short_fail is not None and c_bar > short_fail:
                    x_short_fail = True
                elif use_trail and short_trail is not None and c_bar > short_trail:
                    x_short_trail = True
                else:
                    if short_trail is not None:
                        short_trail = min(short_trail, c_bar + trail_mult * a_bar)
                    else:
                        short_trail = c_bar + trail_mult * a_bar
                if x_short_fail or x_short_trail:
                    in_short = False

            # Step 3: New Breakouts
            vol_ok = (not use_vol) or (not has_volume) or (volumes is not None and volumes[i] > 0 and volumes[i] > vol_ma[i] * vol_mult)
            long_ok = (
                en_long
                and not in_long
                and not in_short
                and res_lvl is not None
                and not res_used
                and (c_bar > res_lvl + brk_buf * a_bar)
                and (not use_body or pos >= close_pct)
                and vol_ok
                and (not use_trend or c_bar > ema_trend[i])
            )
            short_ok = (
                en_short
                and not in_short
                and not in_long
                and sup_lvl is not None
                and not sup_used
                and (c_bar < sup_lvl - brk_buf * a_bar)
                and (not use_body or pos <= 1.0 - close_pct)
                and vol_ok
                and (not use_trend or c_bar < ema_trend[i])
            )

            if long_ok and res_lvl is not None:
                buy_sig = True
                in_long = True
                long_lvl = res_lvl
                long_entry = c_bar
                long_atr = a_bar
                long_fail = res_lvl - fail_buf * a_bar
                long_trail = c_bar - trail_mult * a_bar
                res_used = True
                bias_dir = 1
                bias_lvl = res_lvl

            elif short_ok and sup_lvl is not None:
                sell_sig = True
                in_short = True
                short_lvl = sup_lvl
                short_entry = c_bar
                short_atr = a_bar
                short_fail = sup_lvl + fail_buf * a_bar
                short_trail = c_bar + trail_mult * a_bar
                sup_used = True
                bias_dir = -1
                bias_lvl = sup_lvl

        # Final Snapshot Outputs
        curr_state = "LONG" if in_long else ("SHORT" if in_short else "FLAT")
        if keep_bias:
            curr_bias = "BULLISH" if bias_dir == 1 else ("BEARISH" if bias_dir == -1 else "NEUTRAL")
        else:
            curr_bias = "BULLISH" if in_long else ("BEARISH" if in_short else "NEUTRAL")

        if buy_sig:
            curr_signal = "BUY"
        elif sell_sig:
            curr_signal = "SELL"
        elif x_long_fail or x_short_fail:
            curr_signal = "FAIL"
        elif x_long_trail or x_short_trail:
            curr_signal = "TRAIL"
        elif in_long or in_short:
            curr_signal = "RUNNING"
        else:
            curr_signal = "HOLD"

        latest_close = closes[-1]
        if in_long and long_entry and long_atr:
            open_pnl_atr = round((latest_close - long_entry) / long_atr, 2)
        elif in_short and short_entry and short_atr:
            open_pnl_atr = round((short_entry - latest_close) / short_atr, 2)
        else:
            open_pnl_atr = 0.0

        act_lvl = long_lvl if in_long else (short_lvl if in_short else bias_lvl)
        act_entry = long_entry if in_long else (short_entry if in_short else None)
        act_fail = long_fail if in_long else (short_fail if in_short else None)
        act_trail = long_trail if in_long else (short_trail if in_short else None)

        return {
            "name": "Breakout Tracker",
            "shorttitle": "BRK-TRK",
            "state": curr_state,                     # "LONG" | "SHORT" | "FLAT"
            "bias": curr_bias,                       # "BULLISH" | "BEARISH" | "NEUTRAL"
            "signal": curr_signal,                   # "BUY" | "SELL" | "FAIL" | "TRAIL" | "RUNNING" | "HOLD"
            "breakout_level": round(act_lvl, 1) if act_lvl else None,
            "entry_price": round(act_entry, 1) if act_entry else None,
            "fail_level": round(act_fail, 1) if act_fail else None,
            "trail_level": round(act_trail, 1) if act_trail else None,
            "open_pnl_atr": open_pnl_atr,
            "res_level": round(res_lvl, 1) if res_lvl else None,
            "sup_level": round(sup_lvl, 1) if sup_lvl else None,
            "atr": round(atr_series[-1], 1) if atr_series else 0.0,
            "bias_dir": bias_dir,
            "in_long": in_long,
            "in_short": in_short
        }


