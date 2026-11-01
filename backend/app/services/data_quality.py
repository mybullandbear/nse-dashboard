"""Causal protection against a repeatedly timestamped, unchanged market payload."""
import hashlib
import json
import threading
import time

UNSAFE_SOURCES=frozenset({'SIMULATOR','STALE_CACHE','MARKET_CLOSED','FROZEN','UNAVAILABLE'})

class MarketQualityGate:
    def __init__(self,freeze_seconds=180.,clock=time.monotonic):
        self.freeze_seconds=freeze_seconds;self.clock=clock
        self._state={};self._lock=threading.RLock()

    def inspect(self,chain):
        if chain is None:return None
        # Receipt timestamps are intentionally excluded: repeated polling is not a new quote.
        values=[chain.spot_price]+[(r.strikePrice,r.CE.lastPrice,r.PE.lastPrice,r.CE.bidprice,r.PE.bidprice,r.CE.askPrice,r.PE.askPrice,r.CE.openInterest,r.PE.openInterest,r.CE.totalTradedVolume,r.PE.totalTradedVolume) for r in sorted(chain.strikes,key=lambda r:r.strikePrice)]
        fingerprint=hashlib.sha256(json.dumps(values,separators=(',',':')).encode()).digest()
        now=self.clock();key=chain.symbol.upper()
        with self._lock:
            previous=self._state.get(key)
            changed_at=previous[1] if previous and previous[0]==fingerprint else now
            self._state[key]=(fingerprint,changed_at)
            if len(self._state)>32:self._state.pop(next(iter(self._state)))
        age=max(0.,now-changed_at)
        frozen=age>=self.freeze_seconds
        chain.data_quality={'status':'FROZEN' if frozen else 'OBSERVED','unchanged_seconds':round(age,2),'exchange_timestamp_available':False,'executable_quote_verified':False}
        if frozen and chain.source not in UNSAFE_SOURCES:chain.source='FROZEN'
        return chain

market_quality_gate=MarketQualityGate()
