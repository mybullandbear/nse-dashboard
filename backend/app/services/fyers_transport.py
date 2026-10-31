"""Read-only Fyers v3 HTTP transport.

Protocol matches Fyers SDK 3.2.1's Config/SessionModel without its obsolete pinned
network dependencies. No exchange mutation methods are implemented.
"""
import hashlib
from types import SimpleNamespace
from urllib.parse import urlencode
import requests

API = 'https://api-t1.fyers.in/api/v3'
DATA_API = 'https://api-t1.fyers.in/data'
TIMEOUT = (3.05, 10)


def _response(method, url, **kwargs):
    try:
        response = requests.request(method, url, timeout=TIMEOUT, allow_redirects=False, **kwargs)
        data = response.json()
        if not isinstance(data, dict):
            return {'s':'error','code':-99,'message':'Invalid broker response'}
        return data
    except (requests.RequestException, ValueError):
        # Do not propagate URLs, auth codes, headers, tokens or broker error HTML.
        return {'s':'error','code':-99,'message':'Broker request unavailable'}


class SessionModel:
    def __init__(self, client_id=None, redirect_uri=None, response_type='code',
                 secret_key=None, grant_type='authorization_code', state=None, **kwargs):
        self.client_id=client_id; self.redirect_uri=redirect_uri
        self.response_type=response_type; self.secret_key=secret_key
        self.grant_type=grant_type; self.state=state; self.auth_token=None

    def generate_authcode(self):
        return API+'/generate-authcode?'+urlencode({'client_id':self.client_id,'redirect_uri':self.redirect_uri,'response_type':self.response_type,'state':self.state or ''})

    def set_token(self, token):
        self.auth_token=token

    def generate_token(self):
        app_hash=hashlib.sha256(f'{self.client_id}:{self.secret_key}'.encode()).hexdigest()
        return _response('POST',API+'/validate-authcode',json={'grant_type':self.grant_type,'appIdHash':app_hash,'code':self.auth_token})


class FyersModel:
    def __init__(self, client_id='', token='', **kwargs):
        self._headers={'Authorization':f'{client_id}:{token}','Content-Type':'application/json','version':'3'}

    def _get(self, path, data=None, market=False):
        return _response('GET',(DATA_API if market else API)+path,headers=self._headers,params=data or {})

    def quotes(self,data=None):return self._get('/quotes',data,True)
    def optionchain(self,data=None):return self._get('/options-chain-v3',data,True)
    def history(self,data=None):return self._get('/history',data,True)
    def get_profile(self):return self._get('/profile')
    def funds(self):return self._get('/funds')
    def positions(self):return self._get('/positions')


fyersModel=SimpleNamespace(FyersModel=FyersModel,SessionModel=SessionModel)
