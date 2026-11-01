"""All repository tests are offline: no real broker, notification or HTTP traffic.

Apply process-wide guards before collecting app modules so delayed background
threads cannot transmit after a fixture has finished.
"""
import socket
import pytest

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex

def _offline_connect(sock,address):
    if sock.family in {socket.AF_INET,socket.AF_INET6}:
        raise RuntimeError('Outbound network is disabled in the test process')
    return _original_connect(sock,address)

def _offline_connect_ex(sock,address):
    if sock.family in {socket.AF_INET,socket.AF_INET6}:
        raise RuntimeError('Outbound network is disabled in the test process')
    return _original_connect_ex(sock,address)

def _offline_dns(*args,**kwargs):
    raise RuntimeError('External name resolution is disabled in the test process')

socket.socket.connect = _offline_connect
socket.socket.connect_ex = _offline_connect_ex
socket.getaddrinfo = _offline_dns
socket.gethostbyname = _offline_dns

@pytest.fixture(autouse=True)
def no_real_trade_notifications(monkeypatch):
    from unittest.mock import Mock
    from app.services.mobile_notification_service import mobile_alerts
    monkeypatch.setattr(mobile_alerts,'notify_trade_entry',Mock())
    monkeypatch.setattr(mobile_alerts,'notify_trade_exit',Mock())
