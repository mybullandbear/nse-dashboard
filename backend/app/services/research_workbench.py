"""Read-only five-minute research. Native indicators; no broker calls or orders."""
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
import copy
import math
import sqlite3
import threading
import time
from app.core.market_hours import IST
from app.services.technical_indicators import TechnicalIndicators as TI

VERSION = 'closed5m-v1'
INDICATORS = {'hull': 70, 'alphatrend': 28, 'shonya': 30, 'ott': 20}


def number(value):
    return round(float(value), 6) if value is not None and math.isfinite(float(value)) else None


def closed_bars(rows, cutoff):
    """Sampled OHLC, session anchored; incomplete five-minute buckets never leak."""
    groups = {}
    for row in sorted(rows, key=lambda r: (r['timestamp'], r['id'])):
        ts = datetime.fromisoformat(row['timestamp']).astimezone(IST)
        minute = ts.hour * 60 + ts.minute
        if ts >= cutoff or not 555 <= minute < 940:
            continue
        start = ts.replace(hour=9, minute=15, second=0, microsecond=0) + timedelta(minutes=((minute-555)//5)*5)
        if start + timedelta(minutes=5) > cutoff:
            continue
        price = float(row['price'])
        if not math.isfinite(price) or price <= 0:
            continue
        key = start.isoformat()
        if key not in groups:
            groups[key] = dict(time=key, closed_at=(start+timedelta(minutes=5)).isoformat(), open=float(row.get('open',price)), high=float(row.get('high',price)), low=float(row.get('low',price)), close=price, minutes=set(), samples=0)
        b = groups[key]
        b.update(high=max(b['high'],float(row.get('high',price))), low=min(b['low'],float(row.get('low',price))), close=price, last_observation=row.get('last_observation',ts.isoformat()))
        b['minutes'].add(minute); b['samples'] += 1
        for field in ('ce_oi', 'pe_oi', 'oi', 'volume'):
            if field in row: b[field] = number(row[field])
    out = []
    for b in groups.values():
        b['complete'] = len(b.pop('minutes')) == 5
        if 'ce_oi' in b:
            ce, pe = b['ce_oi'], b['pe_oi']
            b['pcr'] = number(pe / ce) if ce and pe is not None else None
        out.append(b)
    return out


def indicators(bars):
    if not bars: return {}
    c = [b['close'] for b in bars]; h = [b['high'] for b in bars]; l = [b['low'] for b in bars]
    hull = TI.compute_hull(c); alpha = TI.compute_alphatrend(h, l, c, volumes=None); shonya = TI.compute_shonya(c)
    ma, ott, states = TI.compute_ott(c)
    _, _, adx = TI.compute_adx(h, l, c)
    tr = [h[0]-l[0]] + [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1,len(c))]
    atr = TI.rma(tr, 14)
    values = {'hull': (hull['trend_state'], hull['mhull'], hull['shull']), 'alphatrend': (alpha['trend_state'], alpha['alphatrend'], alpha['alphatrend_lag2']), 'shonya': (shonya['trend_state'], shonya['basis'], shonya['lower']), 'ott': (states, ma, ott)}
    result = {}
    for name, (state, line, reference) in values.items():
        series = []
        for i, b in enumerate(bars):
            # Require a contiguous observed warmup, including the current bucket.
            start = max(0, i-INDICATORS[name]+1)
            warm = i+1 >= INDICATORS[name] and all(x['complete'] for x in bars[start:i+1])
            adjacent = all(bars[j]['time'] == bars[j-1]['closed_at'] or bars[j]['time'][:10] != bars[j-1]['time'][:10] for j in range(start+1,i+1))
            ready = warm and adjacent
            direction = (1 if state[i] == 'BULLISH' else -1 if state[i] == 'BEARISH' else 0) if ready else 0
            series.append(dict(direction=direction, ready=ready, state=state[i] if ready else 'WARMUP_OR_GAP', line=number(line[i]) if ready else None, reference=number(reference[i]) if ready else None, atr=number(atr[i]), adx=number(adx[i]), upper=number(shonya['upper'][i]) if name=='shonya' and ready else None))
        result[name] = series
    return result


def replay(bars, series, mode='trailing_flip', atr_multiple=2.0, oi_filter=False):
    """Index point research only. Closed-bar decisions fill next observed bar open.

    Stops use the previous bar's ratchet, gap fills use opening price, and no
    re-entry follows an intrabar exit in the same bucket. No option P&L claims.
    """
    trades, position, pending = [], None, None
    def finish(bar, price, reason):
        nonlocal position
        trades.append(dict(**position, exit_at=bar['closed_at'] if reason=='SESSION_EXIT' else bar['time'], exit_price=number(price), reason=reason, points=number((price-position['entry_price'])*position['direction'])))
        position = None
    for i, b in enumerate(bars):
        s = series[i]
        if i and b['time'] != bars[i-1]['closed_at'] and position:
            finish(b, position['entry_price'], 'UNRESOLVED_GAP'); trades[-1]['points'] = None; trades[-1]['exit_price'] = None
            break
        if i and b['time'][:10] != bars[i-1]['time'][:10]: pending = None
        exited = False
        if position and not b['complete']:
            finish(b,position['entry_price'],'UNRESOLVED_INCOMPLETE_BUCKET'); trades[-1]['points'] = None; trades[-1]['exit_price'] = None
            break
        if position:
            d, stop = position['direction'], position['stop']
            hit = (b['low'] <= stop if d>0 else b['high'] >= stop)
            if pending == 'exit':
                finish(b,b['open'],'SIGNAL_FLIP'); exited = True
            elif mode != 'signal_flip' and hit:
                fill = min(b['open'],stop) if d>0 else max(b['open'],stop)
                finish(b, fill, 'TRAILING_STOP'); exited = True
        if pending in (1,-1) and position is None and not exited:
            d = pending; distance = max(float(series[i-1]['atr'] or 0)*atr_multiple, .01)
            position = dict(entry_at=b['time'], entry_price=b['open'], direction=d, stop=b['open']-d*distance)
        pending = None
        if position and not b['complete']:
            finish(b,position['entry_price'],'UNRESOLVED_INCOMPLETE_BUCKET'); trades[-1]['points'] = None; trades[-1]['exit_price'] = None; exited = True
            break
        if position and position['entry_at']==b['time'] and mode != 'signal_flip':
            d, stop = position['direction'], position['stop']
            if (b['low']<=stop if d>0 else b['high']>=stop):
                finish(b,stop,'INITIAL_STOP'); exited = True
        if position:
            d = position['direction']; distance = max(float(s['atr'] or 0)*atr_multiple,.01)
            if b['complete']:
                position['stop'] = max(position['stop'],b['close']-distance) if d>0 else min(position['stop'],b['close']+distance)
            if b['closed_at'][11:16] >= '15:35': finish(b,b['close'],'SESSION_EXIT'); exited = True
            elif mode != 'trailing' and s['ready'] and s['direction'] == -d: pending = 'exit'
        elif not exited and s['ready'] and b['complete'] and b['closed_at'][11:16] < '15:00':
            direction = s['direction']
            if oi_filter and i:
                prev = bars[i-1]
                if all(b.get(k) is not None and prev.get(k) is not None for k in ('ce_oi','pe_oi')):
                    flow = (b['pe_oi']-prev['pe_oi'])-(b['ce_oi']-prev['ce_oi'])
                    if flow*direction <= 0: direction = 0
                else: direction = 0
            pending = direction or None
    points = [t['points'] for t in trades if t['points'] is not None]
    return dict(trades=trades, open_position=position, closed_trades=len(points), unresolved=sum(t['points'] is None for t in trades), gross_index_points=number(sum(points)), win_rate=number(100*sum(p>0 for p in points)/len(points)) if points else None, result_kind='GROSS_INDEX_POINTS_NOT_OPTION_PNL', costs_included=False, halted=any(t['points'] is None for t in trades))


class ResearchWorkbench:
    def __init__(self, db_path):
        self.path = Path(db_path); self.lock = threading.RLock(); self.cache = OrderedDict()

    def connect(self):
        conn = sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        return conn

    def catalog(self):
        with self.connect() as conn:
            rows = conn.execute('SELECT symbol,trade_date,COUNT(*) samples FROM intraday_snapshots GROUP BY symbol,trade_date ORDER BY trade_date DESC,symbol LIMIT 200').fetchall()
        return dict(sessions=[dict(r) for r in rows], indicators=list(INDICATORS), timeframe_minutes=5, version=VERSION)

    def load(self, symbol, day, cutoff, mode='trailing_flip', atr_multiple=2.0, oi_filter=False, strike=None, option_type='CE'):
        # WAL metadata is included; live changes expire in five seconds as well.
        stamp = tuple((p.stat().st_mtime_ns,p.stat().st_size) if p.exists() else None for p in (self.path,Path(str(self.path)+'-wal')))
        key = (symbol,day,cutoff.isoformat(),mode,atr_multiple,oi_filter,strike,option_type,stamp)
        with self.lock:
            cached = self.cache.get(key)
            if cached and time.monotonic()-cached[0]<5:
                self.cache.move_to_end(key); return copy.deepcopy(cached[1])
            result = self._load(symbol,day,cutoff,mode,atr_multiple,oi_filter,strike,option_type)
            self.cache[key] = (time.monotonic(), result)
            while len(self.cache)>16: self.cache.popitem(last=False)
            return copy.deepcopy(result)

    def _load(self,symbol,day,cutoff,mode,atr_multiple,oi_filter,strike,option_type):
        with self.connect() as conn:
            dates = [r[0] for r in conn.execute('SELECT DISTINCT trade_date FROM intraday_snapshots WHERE symbol=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 8',(symbol,day))]
            rows = []
            if dates:
                rows = [dict(r) for r in conn.execute('SELECT id,timestamp,spot price,ce_oi,pe_oi FROM intraday_snapshots WHERE symbol=? AND trade_date BETWEEN ? AND ? AND timestamp<? ORDER BY timestamp,id',(symbol,min(dates),day,cutoff.isoformat()))]
            available = [float(r[0]) for r in conn.execute('SELECT DISTINCT strike FROM intraday_strike_snapshots WHERE symbol=? AND trade_date=? AND timestamp<? ORDER BY strike',(symbol,day,cutoff.isoformat()))]
            option_rows = []
            if strike is not None and strike in available:
                option_rows = [dict(r) for r in conn.execute('SELECT id,timestamp,ltp price,oi,volume FROM intraday_strike_snapshots WHERE symbol=? AND trade_date=? AND strike=? AND option_type=? AND timestamp<? ORDER BY timestamp,id',(symbol,day,strike,option_type,cutoff.isoformat()))]
        all_bars = closed_bars(rows,cutoff); all_signals = indicators(all_bars)
        indexes = [i for i,b in enumerate(all_bars) if b['time'][:10] == day]
        bars = [all_bars[i] for i in indexes]
        studies = {}
        for name, full_series in all_signals.items():
            series = [full_series[i] for i in indexes]
            studies[name] = dict(series=series, research=replay(bars,series,mode,atr_multiple,oi_filter))
        ob = closed_bars(option_rows,cutoff)
        return dict(version=VERSION,symbol=symbol,trade_date=day,as_of=cutoff.isoformat(),timeframe_minutes=5,bars=bars,studies=studies,available_strikes=available,option=dict(strike=strike,option_type=option_type,bars=ob,studies=indicators(ob),expiry_verified=False),parameters=dict(exit_mode=mode,atr_multiple=atr_multiple,oi_filter=oi_filter),trading_enabled=False,quality=dict(sampled_ohlc=True,incomplete_bars=sum(not b['complete'] for b in bars),warmup_sessions=len(dates),volume_available=False,limitations=['Sampled snapshots can miss exchange intrabar extremes.','Index points exclude costs and are not option returns.','Historical option expiry, bid/ask and fills are unverified.','OI put-minus-call change is a positioning proxy, not a calibrated probability.']))


def policy_bars(records, cutoff):
    """Adapt the canonical storage minute bars to shared closed five-minute OHLC."""
    if not records: return []
    rows = [dict(r, id=i, timestamp=r['minute'], price=r['spot']) for i,r in enumerate(records)]
    bars = closed_bars(rows, cutoff)
    return [dict(b, symbol=records[0]['symbol'], trade_date=records[0]['trade_date'], minute=b['time'], spot=b['close']) for b in bars]
