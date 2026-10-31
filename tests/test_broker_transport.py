from unittest.mock import patch, Mock
from app.services.fyers_transport import FyersModel, SessionModel, API, DATA_API, TIMEOUT
import requests
import pytest

@pytest.mark.parametrize('method,path,base',[('quotes','/quotes',DATA_API),('optionchain','/options-chain-v3',DATA_API),('history','/history',DATA_API),('get_profile','/profile',API),('funds','/funds',API),('positions','/positions',API)])
def test_read_only_protocol(method,path,base):
    client=FyersModel(client_id='test-client',token='test-token')
    with patch('app.services.fyers_transport.requests.request',return_value=Mock(json=lambda:{'s':'ok'})) as req:
        assert getattr(client,method)()=={'s':'ok'}
        args,kwargs=req.call_args
        assert args==('GET',base+path)
        assert kwargs['timeout']==TIMEOUT and not kwargs['allow_redirects']
        assert kwargs['headers']['Authorization']=='test-client:test-token'
    assert not hasattr(client,'place_order')
    assert not hasattr(client,'exit_position')


def test_oauth_hash_and_timeout_redaction():
    import hashlib
    session=SessionModel(client_id='c',secret_key='s',redirect_uri='https://example.test/callback',state='test-state')
    assert 'state=test-state' in session.generate_authcode()
    session.set_token('test-code')
    with patch('app.services.fyers_transport.requests.request',return_value=Mock(json=lambda:{'s':'ok'})) as req:
        session.generate_token()
        assert req.call_args.kwargs['json']['appIdHash']==hashlib.sha256(b'c:s').hexdigest()
    with patch('app.services.fyers_transport.requests.request',side_effect=requests.Timeout('secret-response')):
        assert 'secret-response' not in str(session.generate_token())
