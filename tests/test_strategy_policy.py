from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch
import math
import pandas as pd
import numpy as np
import pytest
from fastapi.testclient import TestClient
from app.core.market_hours import is_market_open,get_session_info
from app.core.config import get_settings
from app.services.strategy_policy import Policy,ExitState,size_plan,enrich,signals
from app.main import app
from app.db.storage import SnapshotStorage

IST=ZoneInfo('Asia/Kolkata')
def t(h,m,s=0):return datetime(2026,11,2,h,m,s,tzinfo=IST)


def bars(n=70):
    minutes=pd.date_range('2026-11-02T09:15:00+05:30',periods=n,freq='min')
    close=25000+np.arange(n)*.5
    return pd.DataFrame({'symbol':'NIFTY','trade_date':'2026-11-02','minute':minutes,'spot':close,'high':close+.5,'low':close-.5,'ce_oi':10000+np.arange(n),'pe_oi':12000+2*np.arange(n),'last_observation':minutes+pd.Timedelta(seconds=59)})


def test_session_uses_1540_and_converts_utc():
    assert is_market_open(t(9,15))
    assert is_market_open(t(15,39,59))
    assert not is_market_open(t(15,40))
    assert is_market_open(t(9,15).astimezone(timezone.utc))
    assert get_session_info(t(15,40))['session_state']=='POST-MARKET'
    with patch.object(get_settings(),'EXCHANGE_HOLIDAYS',['2026-11-02']):
        assert not is_market_open(t(10,0))
        assert get_session_info(t(10,0))['session_state']=='EXCHANGE HOLIDAY'


def test_lot_quantities_are_preserved_and_risk_budget_enforced():
    assert get_settings().LOT_SIZES=={'NIFTY':65,'BANKNIFTY':30,'FINNIFTY':60,'MIDCPNIFTY':120,'SENSEX':20}
    for symbol,lot in get_settings().LOT_SIZES.items():
        p=size_plan(symbol,50,100000,Policy())
        assert p['quantity'] in [0,lot]
        assert p['planned_loss_inr']<=1000
    assert size_plan('NIFTY',500,100000,Policy())['quantity']==0
    assert size_plan('NIFTY',50,100000,Policy(),available=0)['quantity']==0
    assert size_plan('NIFTY',float('nan'),100000,Policy())['quantity']==0


@pytest.mark.parametrize('kwargs',[{'stop_pct':0},{'slippage':-.1},{'target_r':float('nan')},{'force_exit':'15:40'},{'holding_minutes':0},{'daily_loss_fraction':.001}])
def test_invalid_policy_is_rejected(kwargs):
    with pytest.raises(ValueError):Policy(**kwargs)


def test_trailing_stop_ratchets_and_fills_only_on_later_quote():
    state=ExitState(t(10,0),100,Policy())
    assert state.observe(t(10,1),121) is None
    previous_stop=state.stop
    assert previous_stop>100
    assert state.observe(t(10,2),115) is None
    assert state.stop>=previous_stop
    assert state.observe(t(10,3),105)=='STOP_OR_TRAIL'


def test_exit_for_session_and_unknown_quotes():
    assert ExitState(t(15,34),100,Policy()).observe(t(15,35).astimezone(timezone.utc),100)=='SESSION_EXIT'
    assert ExitState(t(10,0),100,Policy()).observe(t(10,2),100)=='UNPRICEABLE'
    assert ExitState(t(10,0),100,Policy()).observe(t(10,1),float('nan'))=='UNPRICEABLE'
    with pytest.raises(ValueError):ExitState(datetime(2026,11,2,10),100,Policy())


def test_features_and_signals_are_prefix_invariant():
    before=enrich(bars(55));after=enrich(bars(70))
    for family in ['opening_range','trend_pullback']:
        np.testing.assert_array_equal(signals(before,Policy(family=family)),signals(after,Policy(family=family))[:55])
    short=enrich(bars(10))
    assert not short.range_ready.any() and short.or_high.isna().all()
    assert enrich(bars(30)).quality_ok.iloc[-1]


def test_storage_uses_completed_bars_and_deterministic_ohlc(tmp_path):
    with patch.object(get_settings(),'DATABASE_PATH',str(tmp_path/'bars.db')):store=SnapshotStorage()
    # Deliberately insert out of timestamp order; IDs must not define OHLC.
    with patch('app.db.storage.get_current_ist',return_value=t(10,0,59)):store.save_snapshot('NIFTY',110,11,21,1,2,2.)
    with patch('app.db.storage.get_current_ist',return_value=t(10,0,1)):store.save_snapshot('NIFTY',100,10,20,1,2,2.)
    with patch('app.db.storage.get_current_ist',return_value=t(10,1,20)):store.save_snapshot('NIFTY',120,11,21,1,2,2.)
    rows=store.get_strategy_bars('NIFTY','2026-11-02',t(10,1,30).isoformat())
    assert len(rows)==1
    assert rows[0]['open']==100 and rows[0]['high']==110 and rows[0]['low']==100 and rows[0]['spot']==110


def test_workspace_is_authenticated_read_only_and_never_activates_trading():
    c=TestClient(app)
    assert c.get('/api/strategy/workspace').status_code==401
    assert c.get('/strategy').status_code==200
    assert c.post('/api/access/login',json={'password':'test-only-long-password-123'}).status_code==200
    with patch('app.api.strategy_workspace.snapshot_storage.get_strategy_bars',return_value=[]):
        data=c.get('/api/strategy/workspace').json()
    assert data['trading_enabled'] is False
    assert len(data['rows'])==5
    assert all(row['execution']=='BLOCKED' for row in data['rows'])
    assert data['lot_sizes']['NIFTY']==65


def test_paper_service_enforces_limits_and_never_widens_stop(tmp_path):
    from app.services.shonya_bot import ShonyaBot
    bot=ShonyaBot(str(tmp_path/'paper.db'))
    with patch('app.services.shonya_bot.get_current_ist',return_value=t(10,0)),patch('app.services.shonya_bot.is_market_open',return_value=True),patch('app.services.shonya_bot.fyers_service.resolve_option_symbol',return_value=None):
        assert not bot.place_trade('NIFTY',25000,'CE',entry_price=100)['success']
        trade=bot.place_trade('NIFTY',25000,'CE',entry_price=100,stop_loss=90)
        assert trade['success']
        assert not bot.modify_trade(trade['trade_id'],stop_loss=80)['success']
        assert bot.modify_trade(trade['trade_id'],stop_loss=95)['success']
        assert not bot.modify_trade(trade['trade_id'],target1=float('nan'))['success']
        with patch.object(bot,'get_trade_history',return_value=[{'exit_time':'2026-11-02 09:50:00','net_pnl':-3000}]):
            assert not bot.place_trade('BANKNIFTY',55000,'CE',entry_price=50,stop_loss=45)['success']
        with patch.object(bot,'get_open_trades',return_value=[{'id':'a'},{'id':'b'}]):
            assert not bot.place_trade('BANKNIFTY',55000,'CE',entry_price=50,stop_loss=45)['success']
    with patch('app.services.shonya_bot.is_market_open',return_value=False),patch('app.services.shonya_bot.fyers_service.resolve_option_symbol',return_value=None):
        assert not bot.place_trade('FINNIFTY',25000,'CE',entry_price=20,stop_loss=18)['success']


def test_portfolio_replay_enforces_shared_position_and_loss_limits(monkeypatch):
    import sys,importlib
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
    replay=importlib.import_module('evaluate_strategy_policies')
    rows=[]
    for symbol in ['NIFTY','BANKNIFTY','FINNIFTY']:
        for minute,price in [('09:59:30',20),('10:00:30',20),('10:01:30',1)]:
            rows.append({'symbol':symbol,'trade_date':'2026-11-02','timestamp':f'2026-11-02T{minute}+05:30','strike':25000.,'option_type':'CE','ltp':price,'oi':20000,'volume':1000})
    f=pd.DataFrame([{'symbol':s,'trade_date':'2026-11-02','decision_time':t(10,m),'spot':25000.} for m in [0,3] for s in ['NIFTY','BANKNIFTY','FINNIFTY']])
    monkeypatch.setattr(replay,'signals',lambda f,p:np.ones(len(f),dtype=int))
    result,ledger=replay.simulate(f,replay.Quotes(pd.DataFrame(rows)),Policy(daily_loss_fraction=.01))
    assert result['priced']['trades']==2
    assert result['blocked']['MAX_OPEN_POSITIONS']>=1
    assert result['blocked']['DAILY_LOSS_LIMIT']>=1
    assert all(p['quantity'] in get_settings().LOT_SIZES.values() for p in ledger)


def test_shadow_observations_are_versioned_deduplicated_and_never_trade(tmp_path):
    from app.services.strategy_shadow import ShadowRecorder
    from app.services.option_chain import ParsedOptionChain
    import sqlite3
    with patch.object(get_settings(),'DATABASE_PATH',str(tmp_path/'shadow.db')):storage=SnapshotStorage()
    recorder=ShadowRecorder(storage)
    chain=ParsedOptionChain(symbol='NIFTY',spot_price=25000,atm_strike=25000,expiry='TEST',pcr=1,pcr_atm_5=1,max_pain=25000,total_ce_oi=1,total_pe_oi=1,strikes=[])
    with patch.object(storage,'get_strategy_bars',return_value=[]),patch('app.services.shonya_bot.shonya_bot.place_trade') as order:
        recorder.observe(chain,t(10,0));recorder.observe(chain,t(10,0,30))
        chain.source='FROZEN';recorder.observe(chain,t(10,1))
        order.assert_not_called()
    with sqlite3.connect(storage.db_path) as conn:
        assert conn.execute('select count(*) from strategy_shadow_decisions').fetchone()[0]==4
        assert conn.execute("select count(*) from strategy_shadow_decisions where state='DATA_BLOCKED' and direction=0").fetchone()[0]==2


def test_paper_cooldown_day_count_and_ids_survive_restarts(tmp_path):
    from app.services.shonya_bot import ShonyaBot
    path=str(tmp_path/'cooldown.db');bot=ShonyaBot(path)
    with patch('app.services.shonya_bot.is_market_open',return_value=True),patch('app.services.shonya_bot.fyers_service.resolve_option_symbol',return_value=None):
        with patch('app.services.shonya_bot.get_current_ist',return_value=t(10,0)):
            first=bot.place_trade('NIFTY',25000,'CE',entry_price=50,stop_loss=45)
        assert first['success']
        with bot._get_conn() as conn:conn.execute("UPDATE shonya_trades SET status='CLOSED',exit_time='2026-11-02 10:01:00' WHERE id=?",(first['trade_id'],))
        bot=ShonyaBot(path)
        with patch('app.services.shonya_bot.get_current_ist',return_value=t(10,5)):
            assert 'cooldown' in bot.place_trade('NIFTY',25000,'CE',entry_price=50,stop_loss=45)['message'].lower()
        ids={first['trade_id']}
        for minute in [15,30]:
            with patch('app.services.shonya_bot.get_current_ist',return_value=t(10,minute)):
                trade=bot.place_trade('NIFTY',25000,'CE',entry_price=50,stop_loss=45)
            assert trade['success'];ids.add(trade['trade_id'])
            with bot._get_conn() as conn:conn.execute("UPDATE shonya_trades SET status='CLOSED',exit_time=? WHERE id=?",(f'2026-11-02 10:{minute:02d}:00',trade['trade_id']))
        assert len(ids)==3
        with patch('app.services.shonya_bot.get_current_ist',return_value=t(10,45)):
            assert 'three' in bot.place_trade('NIFTY',25000,'CE',entry_price=50,stop_loss=45)['message'].lower()
