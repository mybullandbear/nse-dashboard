import asyncio
import json
import math
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api import market, access_gate
from app.services.fyers_service import fyers_service
from app.services.shonya_bot import ShonyaBot
from app.state.option_chain_cache import chain_coordinator


def authenticated_client():
    c = TestClient(app)
    assert c.post('/api/access/login',json={'password':'test-only-long-password-123'}).status_code == 200
    return c


def test_no_localhost_or_matrix_or_broker_bypass():
    c = TestClient(app, client=('127.0.0.1',1234))
    for path in ['/api/fyers/status','/api/matrix/summary','/api/architecture/graph','/api/market/session']:
        assert c.get(path).status_code == 401
    assert c.get('/docs').status_code == 404
    assert c.get('/health').status_code == 200


def test_origin_and_live_guards():
    c = authenticated_client()
    assert c.post('/api/shonya/mode',json={'mode':'LIVE'}).status_code == 403
    assert c.post('/api/shonya/toggle',json={'active':True},headers={'origin':'https://evil.example'}).status_code == 403
    broker = Mock()
    with patch.object(fyers_service,'fyers',broker):
        assert fyers_service.place_order('NIFTY',65,1)['s'] == 'error'
        assert fyers_service.exit_position('id')['s'] == 'error'
        assert fyers_service.exit_all_positions()['s'] == 'error'
    assert not broker.mock_calls


def test_webhook_requires_secret_and_does_not_accept_omission():
    c = TestClient(app)
    payload = {'symbol':'NIFTY','signal':'BUY_CE'}
    assert c.post('/api/webhook/tradingview',json=payload).status_code == 401
    with patch.object(access_gate.get_settings(),'TRADINGVIEW_WEBHOOK_SECRET','test-webhook-secret'):
        assert c.post('/api/webhook/tradingview',json=payload).status_code == 401
        assert c.post('/api/webhook/tradingview',json={**payload,'passphrase':'wrong'}).status_code == 401
        assert c.post('/api/webhook/tradingview',json={**payload,'passphrase':'test-webhook-secret'}).status_code == 200


def test_oauth_invalid_state_never_contacts_broker():
    c = authenticated_client()
    with patch.object(fyers_service,'authenticate_with_code') as exchange:
        assert c.get('/api/fyers/callback?code=x&state=forged').status_code == 400
        exchange.assert_not_called()


@pytest.mark.parametrize('symbol,step',[('NIFTY',50),('BANKNIFTY',100),('FINNIFTY',50),('MIDCPNIFTY',25),('SENSEX',100)])
def test_configured_atm_rounding(symbol,step):
    spot=24635
    res={'data':{'optionsChain':[{'strike_price':-1,'ltp':spot},{'strike_price':24600,'option_type':'CE','ltp':12}]}}
    snapshot=chain_coordinator._parse_fyers_chain(symbol,res)
    assert snapshot.atm_strike == round(spot/step)*step


def test_singleflight_and_unavailable_never_synthetic():
    async def check():
        market._chain_cache.clear();market._chain_cache_time.clear();market._in_flight_locks.clear()
        raw={'records':{'data':[{'test':True}]}}
        with patch.object(market,'is_market_open',return_value=True), patch.object(fyers_service,'is_configured',return_value=True), patch.object(fyers_service,'get_option_chain',return_value=raw) as fetch:
            result=await asyncio.gather(*(market.fetch_live_chain_data('NIFTY') for _ in range(30)))
            assert fetch.call_count == 1
            assert all(item[0]["records"] == raw["records"] and item[0]["_terminal_source"] == "FYERS_LIVE" for item in result)
        market._chain_cache.clear()
        with patch.object(fyers_service,'is_configured',return_value=False):
            assert await market.fetch_live_chain_data('NIFTY') == (None,'UNAVAILABLE')
    asyncio.run(check())


def test_paper_risk_and_restart(tmp_path):
    bot=ShonyaBot(str(tmp_path/'paper.db'))
    assert bot.trading_mode == 'PAPER' and not bot.is_active
    with pytest.raises(ValueError): bot.set_mode('LIVE')
    for args in [('INVALID',25000,'CE',1,100),('NIFTY',25000,'BAD',1,100),('NIFTY',25000,'CE',0,100),('NIFTY',25000,'CE',1,float('nan'))]:
        assert not bot.place_trade(*args)['success']
    with patch.object(fyers_service,'resolve_option_symbol',return_value=None):
        assert not bot.place_trade('NIFTY',25000,'CE')['success']
        assert not bot.place_trade('NIFTY',25000,'CE',entry_price=100,stop_loss=110)['success']
        assert bot.place_trade('NIFTY',25000,'CE',entry_price=100)['success']
        assert not bot.place_trade('NIFTY',25000,'CE',entry_price=100)['success']
    restarted=ShonyaBot(str(tmp_path/'paper.db'))
    assert len(restarted.get_open_trades())==1
