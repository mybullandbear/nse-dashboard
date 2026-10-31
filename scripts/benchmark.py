"""Offline, credential-free benchmark. Run from repository root with PYTHONPATH=backend."""
import asyncio
import json
import statistics
import time
from app.services.technical_indicators import TechnicalIndicators
from app.api.access_gate import _sessions, _digest, is_token_valid
from app.state.option_chain_cache import chain_coordinator
from app.api.websocket import ConnectionManager
from app.services.option_chain import parse_option_chain, _parse_option_chain_uncached


def measure(fn, iterations=500):
    for _ in range(20): fn()
    values=[]
    for _ in range(iterations):
        t=time.perf_counter();fn();values.append((time.perf_counter()-t)*1000)
    values.sort()
    return {'iterations':iterations,'p50_ms':round(statistics.median(values),4),'p95_ms':round(values[int(.95*len(values))],4)}


def run():
    closes=[24000+i*.2+(i%7) for i in range(500)]
    raw={'data':{'optionsChain':[{'strike_price':-1,'ltp':24500}]+[{'strike_price':23000+i*50,'option_type':side,'ltp':100,'oi':1000} for i in range(61) for side in ['CE','PE']]}}
    normalized={'records':{'underlyingValue':24500,'data':[{'strikePrice':23000+i*50,'CE':{'openInterest':1000},'PE':{'openInterest':1500}} for i in range(61)]}}
    _sessions[_digest('benchmark-only')]=time.monotonic()+60
    result={
        'scope':'Offline microbenchmarks; not production latency or broker throughput',
        'indicator_ema_500':measure(lambda:TechnicalIndicators.compute_ema(closes,20)),
        'chain_parse_61_strikes':measure(lambda:chain_coordinator._parse_fyers_chain('NIFTY',raw)),
        'normalized_uncached_61_strikes':measure(lambda:_parse_option_chain_uncached(normalized,'NIFTY')),
        'normalized_cached_61_strikes':measure(lambda:parse_option_chain(normalized,'NIFTY')),
        'session_validation':measure(lambda:is_token_valid('benchmark-only'),1000)
    }
    class Client:
        async def send_text(self,payload): pass
    async def broadcast():
        manager=ConnectionManager();manager.active_connections={Client() for _ in range(100)}
        t=time.perf_counter()
        for _ in range(30): await manager.broadcast({'type':'heartbeat'})
        return round((time.perf_counter()-t)*1000/30,4)
    result['broadcast_100_clients_mean_ms']=asyncio.run(broadcast())
    print(json.dumps(result,indent=2))

if __name__=='__main__':run()
