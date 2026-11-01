from datetime import datetime,timedelta
import sqlite3
import pytest
from app.core.market_hours import IST
from app.services.research_workbench import closed_bars,indicators,replay,ResearchWorkbench


def snapshots(n=390):
    start=datetime(2026,10,14,9,15,tzinfo=IST)
    return [dict(id=i,timestamp=(start+timedelta(minutes=i)).isoformat(),price=20000+i+((i%7)-3)*2,ce_oi=100000+i*10,pe_oi=120000+i*30) for i in range(n)]


def test_closed_five_minute_anchor_cutoff_and_missing_minutes():
    rows=snapshots();cutoff=datetime(2026,10,14,9,24,59,tzinfo=IST)
    bars=closed_bars(rows,cutoff)
    assert len(bars)==1 and bars[0]['closed_at'].endswith('09:20:00+05:30')
    full=closed_bars(rows,datetime(2026,10,14,15,40,tzinfo=IST))
    assert len(full)==77 and full[-1]['closed_at'].endswith('15:40:00+05:30')
    rows.pop(2)
    assert not closed_bars(rows,cutoff)[0]['complete']
    assert closed_bars(list(reversed(rows)),cutoff)==closed_bars(rows,cutoff)


def test_indicator_prefix_invariance_and_warmup():
    bars=closed_bars(snapshots(),datetime(2026,10,14,15,40,tzinfo=IST))
    full=indicators(bars)
    for n in (20,35,72):
        prefix=indicators(bars[:n])
        for name in full:assert prefix[name]==full[name][:n]
    assert not full['hull'][60]['ready'] and full['hull'][70]['ready']
    bars[50]['complete']=False
    assert not indicators(bars)['hull'][-1]['ready']


def test_next_open_entry_previous_stop_and_flip():
    bars=closed_bars(snapshots(30),datetime(2026,10,14,10,tzinfo=IST))
    s=[dict(direction=1,ready=True,atr=10) for b in bars]
    s[2]['direction']=-1
    result=replay(bars,s,mode='signal_flip')
    first=result['trades'][0]
    assert first['entry_at']==bars[1]['time'] and first['entry_price']==bars[1]['open']
    assert first['exit_at']==bars[3]['time'] and first['reason']=='SIGNAL_FLIP'
    assert result['result_kind']=='GROSS_INDEX_POINTS_NOT_OPTION_PNL'
    bars[2]['high']=100000
    bars[2]['low']=bars[2]['open']-1
    r=replay(bars,s,mode='trailing',atr_multiple=2)
    assert not any(t['exit_at']==bars[2]['time'] for t in r['trades']) # future high cannot ratchet same candle


def test_gaps_and_incomplete_buckets_are_unresolved():
    bars=closed_bars(snapshots(30),datetime(2026,10,14,10,tzinfo=IST))
    bars[2]['complete']=False
    s=[dict(direction=1,ready=True,atr=100) for b in bars]
    r=replay(bars,s,mode='signal_flip')
    assert r['unresolved']==1 and r['trades'][0]['points'] is None
    assert r['trades'][0]['exit_price'] is None
    bars.pop(2);s.pop(2)
    assert replay(bars,s,mode='signal_flip')['unresolved']==1


def test_read_only_repository_cache_isolation(tmp_path):
    path=tmp_path/'history.db';conn=sqlite3.connect(path)
    conn.executescript('CREATE TABLE intraday_snapshots(id INTEGER,symbol TEXT,trade_date TEXT,timestamp TEXT,spot REAL,ce_oi REAL,pe_oi REAL); CREATE TABLE intraday_strike_snapshots(id INTEGER,symbol TEXT,trade_date TEXT,timestamp TEXT,strike REAL,option_type TEXT,ltp REAL,oi REAL,volume REAL);')
    conn.executemany('INSERT INTO intraday_snapshots VALUES(?,?,?,?,?,?,?)',[(r['id'],'NIFTY','2026-10-14',r['timestamp'],r['price'],r['ce_oi'],r['pe_oi']) for r in snapshots()]);conn.commit();conn.close()
    service=ResearchWorkbench(path);cutoff=datetime(2026,10,14,15,40,tzinfo=IST)
    before=path.read_bytes();a=service.load('NIFTY','2026-10-14',cutoff);a['bars'].clear()
    assert len(service.load('NIFTY','2026-10-14',cutoff)['bars'])==77
    with service.connect() as c:
        with pytest.raises(sqlite3.OperationalError):c.execute('DELETE FROM intraday_snapshots')
    assert path.read_bytes()==before
    assert service.catalog()['sessions'][0]['symbol']=='NIFTY'


def test_signal_flip_fills_at_open_before_later_stop_and_entry_bar_stop():
    bars=closed_bars(snapshots(30),datetime(2026,10,14,10,tzinfo=IST))
    series=[dict(direction=1,ready=True,atr=10) for b in bars]
    series[1]['direction']=-1
    bars[2]['low']=1
    result=replay(bars,series,mode='trailing_flip')
    assert result['trades'][0]['reason']=='SIGNAL_FLIP'
    assert result['trades'][0]['exit_price']==bars[2]['open']
    bars[1]['low']=1
    result=replay(bars,series,mode='trailing')
    assert result['trades'][0]['reason']=='INITIAL_STOP'
    assert result['trades'][0]['exit_at']==bars[1]['time']


def test_policy_adapter_uses_five_minute_end_and_preserves_high_low():
    from app.services.research_workbench import policy_bars
    from app.services.strategy_policy import enrich
    import pandas as pd
    raw=[dict(symbol='NIFTY',trade_date='2026-10-14',minute=r['timestamp'],open=r['price'],high=r['price']+5,low=r['price']-5,spot=r['price'],ce_oi=r['ce_oi'],pe_oi=r['pe_oi'],last_observation=r['timestamp'],samples=1) for r in snapshots(180)]
    records=policy_bars(raw,datetime(2026,10,14,12,15,tzinfo=IST));frame=pd.DataFrame(records)
    for key in ['minute','last_observation']:frame[key]=pd.to_datetime(frame[key])
    features=enrich(frame,timeframe_minutes=5)
    assert features.iloc[0].decision_time.strftime('%H:%M')=='09:20'
    assert records[0]['high']==max(r['high'] for r in raw[:5])
    assert features.iloc[-1].range_ready and features.iloc[-1].contiguous


def test_research_api_auth_validation_and_read_only_contract():
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    from app.main import app
    c=TestClient(app)
    assert c.get('/api/research/catalog').status_code==401
    assert c.post('/api/access/login',json={'password':'test-only-long-password-123'}).status_code==200
    with patch('app.api.research.workbench.load',return_value={'trading_enabled':False,'bars':[]}) as load:
        assert c.get('/api/research/session?symbol=NIFTY&trade_date=2026-10-14').json()['trading_enabled'] is False
        assert c.get('/api/research/session?symbol=UNKNOWN&trade_date=2026-10-14').status_code==422
        assert c.get('/api/research/session?symbol=NIFTY&trade_date=2026-10-14&at=09:14').status_code==422
        assert c.get('/api/research/session?symbol=NIFTY&trade_date=2099-01-01').status_code==422
        assert c.get('/api/research/session?symbol=NIFTY&trade_date=2026-10-14&atr_multiple=nan').status_code==422
        assert c.get('/api/research/session?symbol=NIFTY&trade_date=2026-10-14&exit_mode=live').status_code==422
        assert load.call_count==1
    assert c.post('/api/research/session').status_code==405


def test_legacy_option_chart_excludes_developing_bar():
    from app.services.option_candle_service import OptionCandleService
    from unittest.mock import patch
    service=OptionCandleService();key=service._get_contract_key('NIFTY',20000,'CE')
    service._candles_5m[key]={f'2026-10-14 {t}':dict(datetime=f'2026-10-14 {t}',trade_date='2026-10-14',time=t,open=100,high=110,low=90,close=105,volume=100) for t in ['09:15','09:20']}
    with patch('app.services.option_candle_service.get_current_ist',return_value=datetime(2026,10,14,9,24,tzinfo=IST)):
        result=service.get_option_chart_data('NIFTY',20000,'CE')
    assert len(result['candles'])==1 and result['candles'][0]['time']=='09:15'
