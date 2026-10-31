import asyncio
import time
from unittest.mock import AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api import access_gate as gate
from app.api.websocket import ConnectionManager, router as ws_router


def app_client():
    app = FastAPI()
    app.include_router(gate.router)
    app.include_router(ws_router)
    gate._sessions.clear()
    gate._attempts.clear()
    return TestClient(app)


def test_login_expiry_logout_and_cookie():
    c = app_client()
    assert not c.get('/api/access/check').json()['authenticated']
    assert c.post('/api/access/login', json={'password':'wrong'}).status_code == 401
    res = c.post('/api/access/login', json={'password':'test-only-long-password-123'})
    assert res.status_code == 200
    assert 'HttpOnly' in res.headers['set-cookie']
    assert 'SameSite=lax' in res.headers['set-cookie']
    assert 'token' not in res.json()
    token = c.cookies.get(gate.COOKIE_NAME)
    assert token and gate.is_token_valid(token)
    assert c.post('/api/access/logout').status_code == 200
    assert not gate.is_token_valid(token)
    gate._sessions[gate._digest('expired')] = time.monotonic()-1
    assert not gate.is_token_valid('expired')


def test_login_rate_limit_and_missing_config(monkeypatch):
    c = app_client()
    for _ in range(5):
        assert c.post('/api/access/login', json={'password':'wrong'}).status_code == 401
    assert c.post('/api/access/login', json={'password':'wrong'}).status_code == 429
    monkeypatch.setattr(gate.get_settings(), 'TERMINAL_PASSWORD', '')
    assert c.post('/api/access/login', json={'password':'x'}).status_code == 503


def test_websocket_rejects_unauthenticated_and_cross_origin():
    from starlette.websockets import WebSocketDisconnect
    import pytest
    c = app_client()
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect('/ws/live'):
            pass
    c.post('/api/access/login', json={'password':'test-only-long-password-123'})
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect('/ws/live', headers={'origin':'https://evil.example'}):
            pass
    with c.websocket_connect('/ws/live') as ws:
        ws.send_json({'action':'ping'})
        assert ws.receive_json() == {'type':'pong'}


def test_slow_websocket_does_not_block_fast_client():
    async def check():
        manager = ConnectionManager()
        slow = AsyncMock()
        fast = AsyncMock()
        async def hang(_):
            await asyncio.sleep(10)
        slow.send_text.side_effect = hang
        manager.active_connections = {slow, fast}
        task = asyncio.create_task(manager.broadcast({'type':'heartbeat'}))
        await asyncio.sleep(.05)
        fast.send_text.assert_awaited_once()
        await task
        assert slow not in manager.active_connections
    asyncio.run(check())
