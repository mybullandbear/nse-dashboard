from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
import json
import sqlite3
import pytest
from app.services.option_chain import ParsedOptionChain,StrikeRow,StrikeContract
from app.services.data_quality import MarketQualityGate
from app.services.oi_analyzer import OIAnalyzer
from app.services.signal_engine import SignalEngine
from app.db.storage import SnapshotStorage
from app.core.config import get_settings


def chain(spot=25000,premium=100):
    return ParsedOptionChain(symbol='NIFTY',spot_price=spot,atm_strike=round(spot/50)*50,expiry='2026-11-03',pcr=1.2,pcr_atm_5=1.2,max_pain=25000,total_ce_oi=100,total_pe_oi=120,strikes=[StrikeRow(strikePrice=k,CE=StrikeContract(strikePrice=k,lastPrice=premium,openInterest=100,totalTradedVolume=1000),PE=StrikeContract(strikePrice=k,lastPrice=premium,openInterest=120,totalTradedVolume=1200)) for k in [25000,25050]])


def clock(h,m):return datetime(2026,11,2,h,m,tzinfo=ZoneInfo('Asia/Kolkata'))


def test_frozen_quote_gate_ignores_receipt_timestamp_and_recovers():
    t=[0.];gate=MarketQualityGate(clock=lambda:t[0]);c=chain()
    assert gate.inspect(c.model_copy(deep=True)).source=='LIVE'
    t[0]=179.;assert gate.inspect(c.model_copy(deep=True)).source=='LIVE'
    t[0]=181.;fresh=c.model_copy(deep=True);fresh.timestamp='new receipt time'
    assert gate.inspect(fresh).source=='FROZEN'
    changed=c.model_copy(deep=True);changed.strikes[0].CE.totalTradedVolume+=1
    assert gate.inspect(changed).source=='LIVE'
    assert changed.data_quality['unchanged_seconds']==0


def test_straddle_open_is_observed_fixed_strike_and_vwap_not_fabricated():
    analyzer=OIAnalyzer()
    with patch('app.services.oi_analyzer.get_current_ist',return_value=clock(9,16)),patch.object(analyzer,'record_snapshot'):
        a=analyzer.analyze(chain())['straddle']
    assert a['estimated_open']==200 and a['decay_pct']==0
    assert a['straddle_vwap'] is None
    c=chain(25050,80)
    with patch('app.services.oi_analyzer.get_current_ist',return_value=clock(10,0)),patch.object(analyzer,'record_snapshot'):
        b=analyzer.analyze(c)['straddle']
    assert b['reference_strike']==25000
    assert b['decay_pct']==20


def test_midday_start_has_no_invented_open():
    a=OIAnalyzer()
    with patch('app.services.oi_analyzer.get_current_ist',return_value=clock(12,0)),patch.object(a,'record_snapshot'):
        s=a.analyze(chain())['straddle']
    assert s['estimated_open'] is None and s['decay_pct'] is None and s['status']=='UNAVAILABLE'


def test_recorder_has_defined_atm_real_volume_and_unknown_score():
    a=OIAnalyzer()
    with patch('app.services.oi_analyzer.get_current_ist',return_value=clock(10,0)),patch.object(a,'_ensure_morning_history'),patch('app.services.oi_analyzer.snapshot_storage') as store:
        a.record_snapshot(chain())
        assert store.save_snapshot.call_args.kwargs['confluence'] is None
        assert store.save_snapshot.call_args.kwargs['ce_vol']==2000
        assert store.save_strike_snapshots.call_count==1
        assert sum(x['is_atm'] for x in store.save_strike_snapshots.call_args.args[1])==2


def test_actual_decisions_are_persisted_without_rewriting_past(tmp_path):
    with patch.object(get_settings(),'DATABASE_PATH',str(tmp_path/'audit.db')):
        storage=SnapshotStorage()
    c=chain()
    with patch('app.services.signal_engine.trade_engine.evaluate_trades',return_value={}),patch('app.db.storage.snapshot_storage',storage),patch('app.services.oi_analyzer.snapshot_storage',storage),patch('app.services.oi_analyzer.get_current_ist',return_value=clock(10,0)),patch('app.db.storage.get_current_ist',return_value=clock(10,0)):
        analyzer=OIAnalyzer();analyzer.record_snapshot(c)
        decision=SignalEngine().evaluate(c,{'straddle':{'decay_pct':None}})
        SignalEngine().evaluate(c,{'straddle':{'decay_pct':None}})
        analyzer.record_snapshot(c,decision)
    conn=sqlite3.connect(storage.db_path)
    assert conn.execute('select count(*) from signal_history').fetchone()[0]==1
    audit=json.loads(conn.execute('select decision_json from decision_audit').fetchone()[0])
    assert audit['model_version']=='confluence-v2-observed-decay'
    rows=conn.execute('select confluence from intraday_snapshots order by id').fetchall()
    assert rows[0][0] is None and rows[1][0]==decision['confluence_score']
    assert audit['confidence_kind'].startswith('HEURISTIC')


def test_frozen_chain_cannot_emit_trade_recommendation():
    c=chain();c.source='FROZEN'
    d=SignalEngine().evaluate(c,{})
    assert d['direction']=='NEUTRAL' and d['operational_state']=='DATA UNAVAILABLE'


def test_new_quote_metadata_preserves_missing_fields_as_null(tmp_path):
    with patch.object(get_settings(),'DATABASE_PATH',str(tmp_path/'metadata.db')):
        storage=SnapshotStorage()
    with patch('app.db.storage.get_current_ist',return_value=clock(10,0)):
        storage.save_strike_snapshots('NIFTY',[{'strike':25000,'option_type':'CE','ltp':100,'expiry_date':'2026-11-03','source':'LIVE'}])
    with sqlite3.connect(storage.db_path) as conn:
        assert conn.execute('select expiry_date,contract_symbol,bid,ask,source from intraday_strike_snapshots').fetchone()==('2026-11-03',None,None,None,'LIVE')


def test_test_process_cannot_send_outbound_notifications():
    import socket
    with pytest.raises(RuntimeError,match='disabled'):
        socket.getaddrinfo('api.telegram.org',443)
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        with pytest.raises(RuntimeError,match='disabled'):
            sock.connect(('192.0.2.1',443))
