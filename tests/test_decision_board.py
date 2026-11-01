from datetime import datetime
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from app.core.market_hours import IST
from app.api import decision_board as board
from app.services.research_workbench import ResearchWorkbench


def database(tmp_path):
    import sqlite3
    path=tmp_path/'board.db';conn=sqlite3.connect(path)
    conn.executescript('CREATE TABLE intraday_snapshots(id INTEGER,symbol TEXT,trade_date TEXT,timestamp TEXT,spot REAL,ce_oi REAL,pe_oi REAL); CREATE TABLE intraday_strike_snapshots(id INTEGER,symbol TEXT,trade_date TEXT,timestamp TEXT,strike REAL,option_type TEXT,ltp REAL,oi REAL,volume REAL);')
    from datetime import timedelta
    rows=[];start=datetime(2026,10,14,9,15,tzinfo=IST)
    for i in range(385):rows.append((i,'NIFTY','2026-10-14',(start+timedelta(minutes=i)).isoformat(),20000+i,100000+i*10,120000+i*40))
    conn.executemany('INSERT INTO intraday_snapshots VALUES(?,?,?,?,?,?,?)',rows);conn.commit();conn.close()
    return path


def response(tmp_path):
    service=ResearchWorkbench(database(tmp_path));board._feature_cache.clear()
    with patch.object(board,'workbench',service),patch.object(board,'get_current_ist',return_value=datetime(2026,11,1,10,tzinfo=IST)):
        return board.board()


def test_five_indices_missing_data_replay_and_immutable_cache(tmp_path):
    result=response(tmp_path)
    assert len(result['rows'])==5 and result['historical_replay']
    row=result['rows'][0];assert row['symbol']=='NIFTY' and row['lot_size']==65
    assert len(row['trends']['price'])==77 and row['ce_oi']==103840
    assert row['oi_flow']==150 and row['signal']['setup']=='CE_WATCH'
    assert row['signal']['ready']==4 and row['guidance']=='REPLAY · CE WATCH'
    assert row['opening_range']['state']=='ABOVE RANGE'
    assert result['rows'][-1]['closed_at'] is None and 'NO_RECORDED_DATA' in result['rows'][-1]['blockers']
    assert result['trading_enabled'] is False
    row['trends']['price'].clear()
    cached=next(iter(board._feature_cache.values()))[1]
    assert len(cached[0]['trends']['price'])==77


def test_board_api_auth_and_future_cutoffs(tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app
    c=TestClient(app);assert c.get('/api/dashboard/board').status_code==401
    assert c.post('/api/access/login',json={'password':'test-only-long-password-123'}).status_code==200
    service=ResearchWorkbench(database(tmp_path));board._feature_cache.clear()
    with patch.object(board,'workbench',service):
        assert c.get('/api/dashboard/board?trade_date=2099-01-01').status_code==422
        assert c.get('/api/dashboard/board?at=12:00').status_code==422
        assert c.get('/api/dashboard/board?trade_date=2026-10-14&at=09:14').status_code==422
        data=c.get('/api/dashboard/board?trade_date=2026-10-14&at=10:24').json()
        assert data['as_of'].endswith('10:20:00+05:30')
        assert data['rows'][0]['closed_at'].endswith('10:20:00+05:30')
    assert c.post('/api/dashboard/board').status_code==405


def test_current_session_without_quote_blocks_guidance_and_never_calls_broker(tmp_path):
    service=ResearchWorkbench(database(tmp_path));board._feature_cache.clear()
    from app.api import market
    with patch.object(board,'workbench',service),patch.object(board,'get_current_ist',return_value=datetime(2026,10,14,15,37,tzinfo=IST)),patch.dict(market._chain_cache,{},clear=True),patch('app.services.fyers_service.fyers_service.get_option_chain') as broker:
        result=board.board();broker.assert_not_called()
    assert result['historical_replay'] is False
    row=result['rows'][0]
    assert row['guidance']=='NO TRADE · DATA' and row['signal']['setup']=='CE_WATCH'
    assert 'FRESH_QUOTE_UNAVAILABLE' in row['blockers']


def test_gap_has_no_five_minute_oi_inference(tmp_path):
    service=ResearchWorkbench(database(tmp_path))
    with service.path.open('rb') as f:before=f.read()
    result=service.load('NIFTY','2026-10-14',datetime(2026,10,14,15,40,tzinfo=IST))
    result['bars'].pop(4)
    for study in result['studies'].values():study['series'].pop(4)
    board._feature_cache.clear()
    with patch.object(board.workbench,'load',return_value=result):
        row=board._features('2026-10-14',datetime(2026,10,14,15,40,tzinfo=IST),['NIFTY'])[0]
    assert row['trends']['oi_flow'][4] is None
    assert service.path.read_bytes()==before


@pytest.mark.parametrize('source,expected_current',[('FROZEN',None),('FYERS_LIVE',25000)])
def test_current_quotes_never_override_closed_bar_signals_or_unsafe_gates(tmp_path,source,expected_current):
    import time
    from app.api import market
    from app.services.option_chain import ParsedOptionChain
    chain=ParsedOptionChain(symbol='NIFTY',spot_price=25000,atm_strike=25000,expiry='TEST',pcr=1,pcr_atm_5=1,max_pain=25000,total_ce_oi=1,total_pe_oi=1,strikes=[],source=source)
    service=ResearchWorkbench(database(tmp_path));board._feature_cache.clear()
    with patch.object(board,'workbench',service),patch.object(board,'get_current_ist',return_value=datetime(2026,10,14,15,37,tzinfo=IST)),patch.dict(market._chain_cache,{'NIFTY':{'_terminal_source':source}},clear=True),patch.dict(market._chain_cache_time,{'NIFTY':time.time()},clear=True),patch('app.services.option_chain.parse_option_chain',return_value=chain):
        result=board.board()
    row=result['rows'][0]
    assert row['current_spot']==expected_current
    assert row['spot']!=25000 and row['closed_at'].endswith('15:35:00+05:30')
    assert row['signal']['setup']=='CE_WATCH' and not result['trading_enabled']
    if source=='FROZEN':assert row['guidance']=='NO TRADE · DATA'
