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
from typing import List, Dict, Any, Tuple


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


if __name__ == "__main__":
    closes = [100.0, 101.0, 102.5, 103.0, 102.0, 101.5, 99.0, 98.0, 97.5, 99.0, 101.0, 104.0, 105.0]
    mavg, ott, state = TechnicalIndicators.compute_ott(closes, length=2, percent=1.4)
    print("OTT Test:", list(zip(closes, [round(m, 2) for m in mavg], [round(o, 2) for o in ott], state)))
