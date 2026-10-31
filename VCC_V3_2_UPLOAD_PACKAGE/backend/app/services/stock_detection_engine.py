"""
Early Movement Detection Engine v2 for F&O & Cash Stocks
Computes EMS (Early Momentum Score) 0-100 per stock per refresh.
"""
import math
import logging
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

BUFFER_SIZE = 375  # Full trading session at 1-min intervals

class CircularBuffer:
    __slots__ = ('_buf', '_size', '_idx', '_count')

    def __init__(self, size=BUFFER_SIZE):
        self._buf = [None] * size
        self._size = size
        self._idx = 0
        self._count = 0

    def append(self, val):
        self._buf[self._idx] = val
        self._idx = (self._idx + 1) % self._size
        if self._count < self._size:
            self._count += 1

    def __len__(self):
        return self._count

    def __getitem__(self, i):
        if i < 0:
            i = self._count + i
        if i < 0 or i >= self._count:
            return None
        actual = (self._idx - self._count + i) % self._size
        return self._buf[actual]

    def last(self, n=1):
        n = min(n, self._count)
        return [self[-(n - j)] for j in range(n)]

def _sf(val, default=0.0):
    if val is None:
        return default
    try:
        return float(str(val).replace(',', '').replace('%', '').strip())
    except (ValueError, TypeError):
        return default

class StockHistory:
    def __init__(self):
        self.timestamps = CircularBuffer()
        self.ltp = CircularBuffer()
        self.vwap = CircularBuffer()
        self.high = CircularBuffer()
        self.low = CircularBuffer()
        self.pchange = CircularBuffer()
        self.rank_g = CircularBuffer()
        self.rank_l = CircularBuffer()
        self.vol_shocker = CircularBuffer()
        self.in_g1 = CircularBuffer()
        self.in_g5 = CircularBuffer()
        self.in_l1 = CircularBuffer()
        self.in_l5 = CircularBuffer()
        self.vdr = CircularBuffer()
        self.rp = CircularBuffer()
        self.rer = CircularBuffer()
        self.trigger_time = None
        self.vol_history = CircularBuffer()

class DetectionEngine:
    def __init__(self):
        self.history = defaultdict(StockHistory)
        self.session_start = None
        self.refresh_count = 0
        self._eps_cache = {}
        self._avg_vol_shockers = 0

    def reset_session(self):
        self.history.clear()
        self._eps_cache.clear()
        self.session_start = None
        self.refresh_count = 0
        self._avg_vol_shockers = 0

    def ingest(self, market_data, timestamp=None):
        if timestamp is None:
            timestamp = datetime.now()
        if self.session_start is None:
            self.session_start = timestamp
        self.refresh_count += 1

        g1 = market_data.get("gainers_1d", [])
        l1 = market_data.get("losers_1d", [])
        g5 = market_data.get("gainers_5d", [])
        l5 = market_data.get("losers_5d", [])

        g1_map = {x['symbol']: (i + 1, x) for i, x in enumerate(g1)}
        l1_map = {x['symbol']: (i + 1, x) for i, x in enumerate(l1)}
        g5_set = {x['symbol'] for x in g5}
        l5_set = {x['symbol'] for x in l5}

        all_stocks = {}
        for item in g1 + l1:
            if item['symbol'] not in all_stocks:
                all_stocks[item['symbol']] = item

        for sym, item in all_stocks.items():
            h = self.history[sym]
            p = _sf(item.get('ltp'))
            v = _sf(item.get('vwap'))
            hi = _sf(item.get('high'))
            lo = _sf(item.get('low'))

            h.timestamps.append(timestamp)
            h.ltp.append(p)
            h.vwap.append(v)
            h.high.append(hi)
            h.low.append(lo)
            h.pchange.append(_sf(item.get('pChange')))
            h.rank_g.append(g1_map[sym][0] if sym in g1_map else None)
            h.rank_l.append(l1_map[sym][0] if sym in l1_map else None)
            h.vol_shocker.append(1 if item.get('badge') == 'Vol Shocker' else 0)
            h.in_g1.append(1 if sym in g1_map else 0)
            h.in_g5.append(1 if sym in g5_set else 0)
            h.in_l1.append(1 if sym in l1_map else 0)
            h.in_l5.append(1 if sym in l5_set else 0)

            h.vdr.append((p - v) / v if v > 0 else 0)
            h.rp.append((p - lo) / (hi - lo) if hi > lo else 0.5)
            h.rer.append((hi - lo) / v if v > 0 else 0)

        alpha = self._session_alpha(timestamp)
        self._eps_cache.clear()
        for sym in all_stocks:
            h = self.history[sym]
            if len(h.ltp) >= 2:
                if h.trigger_time is None:
                    h.trigger_time = timestamp
                result = self._compute_eps(sym, alpha, all_stocks[sym], timestamp)
                self._eps_cache[sym] = result

    def get_top_opportunities(self, n=5):
        bulls = []
        bears = []
        for sym, r in self._eps_cache.items():
            if r['direction'] == 'bull' and r['eps'] > 30:
                bulls.append(r)
            elif r['direction'] == 'bear' and r['eps'] > 30:
                bears.append(r)

        def weighted_sort_key(x):
            age_score = {'Fresh': 4, 'Active': 3, 'Aging': 2, 'Late': 1}.get(x.get('signal_age_label', ''), 1)
            conf = x.get('confidence', 0)
            rel_vol = min(x.get('relative_volume', 1.0), 5.0)
            vwap_d = x.get('vwap_distance_pct', 5.0)
            vwap_score = max(0, 3.0 - abs(vwap_d))
            eps = x.get('eps', 0)
            trend = x.get('trend_strength', 0.5)
            mtf = {'Confirmed': 3, 'Mixed': 2, 'Conflict': 1}.get(x.get('mtf_status', ''), 1)
            return (
                conf * 0.25 +
                age_score * 15 * 0.20 +
                rel_vol * 20 * 0.15 +
                vwap_score * 25 * 0.12 +
                eps * 0.12 +
                trend * 100 * 0.08 +
                mtf * 25 * 0.08
            )

        bulls.sort(key=weighted_sort_key, reverse=True)
        bears.sort(key=weighted_sort_key, reverse=True)
        return {"top_gainers": bulls[:n], "top_losers": bears[:n]}

    def _session_alpha(self, t):
        if self.session_start is None:
            return 0.5
        elapsed = (t - self.session_start).total_seconds()
        total = 6.25 * 3600
        return min(max(elapsed / total, 0), 1)

    def _velocity(self, buf, w):
        n = len(buf)
        if n < w + 1:
            return 0
        cur = buf[-1]
        prev = buf[-(w + 1)]
        if cur is None or prev is None:
            return 0
        return cur - prev

    def _pct_velocity(self, buf, w):
        n = len(buf)
        if n < w + 1:
            return 0
        cur = buf[-1]
        prev = buf[-(w + 1)]
        if cur is None or prev is None or prev == 0:
            return 0
        return (cur - prev) / abs(prev) * 100

    def _acceleration(self, buf, w):
        n = len(buf)
        if n < 2 * w + 1:
            return 0
        v_now = self._velocity(buf, w)
        cur_old = buf[-(w + 1)]
        prev_old = buf[-(2 * w + 1)]
        if cur_old is None or prev_old is None:
            return 0
        v_old = cur_old - prev_old
        return v_now - v_old

    def _persistence(self, buf, w, condition_fn):
        n = len(buf)
        w = min(w, n - 1)
        if w <= 0:
            return 0
        count = 0
        for i in range(w):
            cur = buf[-(i + 1)]
            prev = buf[-(i + 2)]
            if cur is not None and prev is not None and condition_fn(cur, prev):
                count += 1
        return count / w

    def _compute_eps(self, sym, alpha, item, timestamp=None):
        h = self.history[sym]
        n = len(h.ltp)
        w = min(5, n - 1)
        wm = min(15, n - 1)

        pchg = _sf(item.get('pChange'))
        direction = 'bull' if pchg >= 0 else 'bear'

        features = {}
        features['vdr'] = h.vdr[-1] if h.vdr[-1] is not None else 0
        features['rp'] = h.rp[-1] if h.rp[-1] is not None else 0.5

        rank_buf = h.rank_g if direction == 'bull' else h.rank_l
        if n >= 2 and rank_buf[-1] is not None and rank_buf[-2] is not None:
            features['rank_v'] = rank_buf[-2] - rank_buf[-1]
        else:
            features['rank_v'] = 0

        features['pv'] = self._pct_velocity(h.ltp, w)
        features['vdv'] = self._velocity(h.vdr, w)
        features['rpv'] = self._velocity(h.rp, w)
        features['pa'] = self._acceleration(h.ltp, w) if n > 2 * w else 0
        features['vda'] = self._acceleration(h.vdr, w) if n > 2 * w else 0

        if n >= 3 and rank_buf[-1] is not None and rank_buf[-2] is not None and rank_buf[-3] is not None:
            rv_now = rank_buf[-2] - rank_buf[-1]
            rv_prev = rank_buf[-3] - rank_buf[-2]
            features['rank_a'] = rv_now - rv_prev
        else:
            features['rank_a'] = 0

        features['dp'] = self._persistence(h.ltp, wm, lambda c, p: c > p if direction == 'bull' else c < p)

        if direction == 'bull':
            features['vsp'] = self._persistence(h.vdr, wm, lambda c, _: c > 0)
        else:
            features['vsp'] = self._persistence(h.vdr, wm, lambda c, _: c < 0)

        features['hwf'] = self._persistence(h.high, wm, lambda c, p: c > p)

        features['list_entry'] = 0
        g1_buf = h.in_g1 if direction == 'bull' else h.in_l1
        if n >= 2 and g1_buf[-1] == 1 and g1_buf[-2] == 0:
            features['list_entry'] = 1

        features['vs_trans'] = 0
        if n >= 2 and h.vol_shocker[-1] == 1 and h.vol_shocker[-2] == 0:
            features['vs_trans'] = 1

        features['lp'] = ((h.in_g1[-1] or 0) + 2 * (h.in_g5[-1] or 0) + (h.in_l1[-1] or 0) + 2 * (h.in_l5[-1] or 0))
        features['srs'] = abs(pchg) - 2.0

        def norm(val, lo, hi):
            if hi == lo: return 0.5
            return max(0, min(1, (val - lo) / (hi - lo)))

        def dir_norm(val, lo, hi):
            if direction == 'bull': return norm(val, lo, hi)
            else: return norm(-val, lo, hi) if lo != hi else 0.5

        scores = {}
        scores['rank_a'] = norm(features['rank_a'], -3, 5)
        scores['vda'] = dir_norm(features['vda'], -0.01, 0.01)
        scores['vsp'] = features['vsp']
        scores['pa'] = dir_norm(features['pa'], -5, 5)
        scores['vs_trans'] = features['vs_trans']
        scores['dp'] = features['dp']
        scores['list_entry'] = features['list_entry']
        scores['hwf'] = features['hwf'] if direction == 'bull' else (1 - features['hwf'])
        scores['rpv'] = dir_norm(features['rpv'], -0.3, 0.3)
        scores['srs'] = norm(features['srs'], -3, 5)
        scores['vdr'] = dir_norm(features['vdr'], -0.02, 0.02)
        scores['lp'] = norm(features['lp'], 0, 5)

        weights = {
            'rank_a': 0.14 * (1 + 0.5 * (1 - alpha)),
            'vda': 0.13,
            'vsp': 0.12 * (1 + 0.3 * alpha),
            'pa': 0.11,
            'vs_trans': 0.09 * (1 + 0.5 * (1 - alpha)),
            'dp': 0.09 * (1 + 0.4 * alpha),
            'list_entry': 0.07 * (1 + 0.6 * (1 - alpha)),
            'hwf': 0.06,
            'rpv': 0.06,
            'srs': 0.05 * (1 + 0.3 * alpha),
            'vdr': 0.05,
            'lp': 0.03,
        }

        w_total = sum(weights.values())
        eps_raw = sum(scores.get(k, 0) * weights[k] for k in weights) / w_total * 100

        signal_age_min = 0
        signal_age_label = 'Fresh'
        trigger_time_str = ''
        if h.trigger_time and timestamp:
            signal_age_min = round((timestamp - h.trigger_time).total_seconds() / 60, 1)
            trigger_time_str = h.trigger_time.strftime('%H:%M')
            if signal_age_min <= 5: signal_age_label = 'Fresh'
            elif signal_age_min <= 10: signal_age_label = 'Active'
            elif signal_age_min <= 20: signal_age_label = 'Aging'
            else: signal_age_label = 'Late'

        age_penalty = 0
        if signal_age_min > 20: age_penalty = min(15, (signal_age_min - 20) * 0.5)
        elif signal_age_min > 10: age_penalty = (signal_age_min - 10) * 0.3

        ltp_f = _sf(item.get('ltp'))
        vwap_f = _sf(item.get('vwap'))
        vwap_distance_pct = 0
        vwap_distance_label = 'Fresh Entry'
        if vwap_f > 0:
            vwap_distance_pct = round(((ltp_f - vwap_f) / vwap_f) * 100, 2)
            abs_dist = abs(vwap_distance_pct)
            if abs_dist <= 0.50: vwap_distance_label = 'Fresh Entry'
            elif abs_dist <= 1.20: vwap_distance_label = 'Extended'
            else: vwap_distance_label = 'Chasing Risk'

        vol_shocker_count = sum(1 for i in range(min(n, 10)) if h.vol_shocker[-(i+1)] == 1)
        vol_shocker_total = min(n, 10)
        relative_volume = 1.0
        if vol_shocker_total > 0:
            vs_ratio = vol_shocker_count / vol_shocker_total
            relative_volume = round(0.8 + vs_ratio * 2.2, 1)
        if item.get('badge') == 'Vol Shocker':
            relative_volume = max(relative_volume, 2.0)

        rel_vol_label = 'Weak'
        if relative_volume >= 2.5: rel_vol_label = 'Shock'
        elif relative_volume >= 1.5: rel_vol_label = 'Strong'
        elif relative_volume >= 1.0: rel_vol_label = 'Normal'

        def trend_dir(buf, window):
            vals = buf.last(min(window, len(buf)))
            if len(vals) < 2: return 'neutral'
            trend_up = sum(1 for i in range(1, len(vals)) if vals[i] is not None and vals[i-1] is not None and vals[i] > vals[i-1])
            ratio = trend_up / (len(vals) - 1) if len(vals) > 1 else 0.5
            if ratio > 0.6: return 'bullish'
            elif ratio < 0.4: return 'bearish'
            return 'neutral'

        tf_short = trend_dir(h.ltp, 3)
        tf_med = trend_dir(h.ltp, 7)
        tf_long = trend_dir(h.ltp, 15)
        tf_vwap = 'bullish' if features['vsp'] > 0.6 else ('bearish' if features['vsp'] < 0.4 else 'neutral')
        mtf_trends = [tf_short, tf_med, tf_long, tf_vwap]
        target = 'bullish' if direction == 'bull' else 'bearish'
        aligned = sum(1 for t in mtf_trends if t == target)
        mtf_status = 'Confirmed' if aligned >= 3 else ('Mixed' if aligned >= 2 else 'Conflict')

        range_pct = round(features['rp'] * 100, 1)
        range_label = 'Healthy' if range_pct < 60 else ('Active' if range_pct < 80 else ('Extended' if range_pct < 90 else 'Exhaustion'))
        trend_strength = round(features['dp'] * 0.4 + features['vsp'] * 0.3 + scores.get('hwf', 0.5) * 0.3, 2)
        exhaustion = self._exhaustion_score(h, direction, features)

        dist_penalty = min(10, (abs(vwap_distance_pct) - 1.2) * 5) if abs(vwap_distance_pct) > 1.2 else 0
        range_penalty = min(10, (range_pct - 85) * 1.5) if range_pct > 85 else 0

        eps = max(0, min(100, round(eps_raw - age_penalty - dist_penalty - range_penalty, 1)))
        conf = self._enhanced_confidence(eps, features, signal_age_label, vwap_distance_label, rel_vol_label, mtf_status, exhaustion)
        signal_quality = self._signal_quality(signal_age_label, vwap_distance_label, rel_vol_label, mtf_status, exhaustion, range_pct, trend_strength, conf)

        reasons = []
        if features['dp'] > 0.65: reasons.append(f"Persist {features['dp']:.0%}")
        if features['vsp'] > 0.7: reasons.append('VWAP Lock')
        if features['list_entry']: reasons.append('New Entry')
        if features['vs_trans']: reasons.append('Vol Spike')
        if features['rank_a'] > 1: reasons.append('Rank ↑↑')
        if features['lp'] >= 3: reasons.append('1D+5D')
        if relative_volume >= 2.0: reasons.append('High Volume')
        if mtf_status == 'Confirmed': reasons.append('Trend Confirmed')

        return {
            'symbol': sym,
            'direction': direction,
            'eps': eps,
            'confidence': conf,
            'exhaustion': round(exhaustion, 2),
            'reasons': reasons,
            'ltp': item.get('ltp'),
            'vwap': item.get('vwap'),
            'pChange': item.get('pChange'),
            'high': item.get('high'),
            'low': item.get('low'),
            'sector': item.get('sector', ''),
            'badge': item.get('badge', ''),
            'is_fno': item.get('is_fno', False),
            'nse_symbol': item.get('nse_symbol', ''),
            'range_pct': range_pct,
            'trigger_time': trigger_time_str,
            'signal_age_min': signal_age_min,
            'signal_age_label': signal_age_label,
            'vwap_distance_pct': vwap_distance_pct,
            'vwap_distance_label': vwap_distance_label,
            'relative_volume': relative_volume,
            'rel_vol_label': rel_vol_label,
            'mtf_status': mtf_status,
            'range_label': range_label,
            'trend_strength': trend_strength,
            'signal_quality': signal_quality,
        }

    def _exhaustion_score(self, h, direction, f):
        n = len(h.ltp)
        if n < 5: return 0
        es = 0
        if direction == 'bull' and f.get('pa', 0) < -1: es += 0.3
        elif direction == 'bear' and f.get('pa', 0) > 1: es += 0.3
        rp = f.get('rp', 0.5)
        rpv = f.get('rpv', 0)
        if direction == 'bull' and rp > 0.92 and abs(rpv) < 0.02: es += 0.25
        elif direction == 'bear' and rp < 0.08 and abs(rpv) < 0.02: es += 0.25
        return min(es, 1.0)

    def _confidence(self, eps, f):
        if eps < 40: base = 25
        elif eps < 55: base = 40
        elif eps < 70: base = 55
        elif eps < 80: base = 70
        elif eps < 90: base = 82
        else: base = 90
        dp_mult = max(0.5, f.get('dp', 0.5))
        return min(95, round(base * dp_mult))

    def _enhanced_confidence(self, eps, f, age_label, vwap_label, vol_label, mtf, exhaustion):
        base = self._confidence(eps, f)
        if age_label == 'Fresh': base += 5
        elif age_label == 'Late': base -= 10
        if vwap_label == 'Fresh Entry': base += 4
        elif vwap_label == 'Chasing Risk': base -= 8
        if vol_label in ('Shock', 'Strong'): base += 4
        elif vol_label == 'Weak': base -= 5
        if mtf == 'Confirmed': base += 5
        elif mtf == 'Conflict': base -= 8
        if exhaustion > 0.6: base -= 10
        return max(10, min(95, round(base)))

    def _signal_quality(self, age, vwap_dist, vol, mtf, exhaustion, range_pct, trend_str, conf):
        if conf < 30 or (mtf == 'Conflict' and trend_str < 0.3):
            return {'status': 'Invalid', 'icon': '⚫', 'action': 'Avoid'}
        if exhaustion > 0.6 or range_pct > 90:
            return {'status': 'Exhaustion Risk', 'icon': '🔴', 'action': 'Avoid'}
        if mtf == 'Mixed' or (age == 'Aging' and vol in ('Normal', 'Weak')):
            return {'status': 'Watch', 'icon': '🟠', 'action': 'Wait'}
        if vwap_dist == 'Extended' or vwap_dist == 'Chasing Risk' or age == 'Late':
            return {'status': 'Extended', 'icon': '🟡', 'action': 'Caution'}
        return {'status': 'Valid / Fresh', 'icon': '🟢', 'action': 'Buy'}

detection_engine = DetectionEngine()
