"""Versioned forward observations for unvalidated strategies; never places orders."""
from app.services.research_workbench import policy_bars
from dataclasses import asdict
import json
import threading
import pandas as pd
from app.services.strategy_policy import Policy,enrich,signals,VERSION
from app.services.data_quality import UNSAFE_SOURCES
from app.core.market_hours import get_current_ist
from app.core.config import get_settings

class ShadowRecorder:
    def __init__(self,storage=None):
        self.storage=storage;self.last_seen={};self.lock=threading.RLock()

    def observe(self,chain,now=None):
        if chain is None:return
        now=now or get_current_ist();minute=now.isoformat()[:16];symbol=chain.symbol
        observation_key=(now.replace(minute=(now.minute//5)*5,second=0,microsecond=0).isoformat(),chain.source in UNSAFE_SOURCES)
        with self.lock:
            if self.last_seen.get(symbol)==observation_key:return
            if self.storage is None:
                from app.db.storage import snapshot_storage
                self.storage=snapshot_storage
            rows=[] if chain.source in UNSAFE_SOURCES else self.storage.get_strategy_bars(symbol,now.date().isoformat(),now.isoformat())
            rows=policy_bars(rows,now)
            features=None
            if rows:
                frame=pd.DataFrame(rows)
                for key in ['minute','last_observation']:frame[key]=pd.to_datetime(frame[key],format='mixed')
                features=enrich(frame,timeframe_minutes=5)
            settings=get_settings()
            quote_reference={"lot_size":settings.LOT_SIZES.get(symbol),"exchange_timestamp_verified":False}
            if chain.strikes:
                atm=min(chain.strikes,key=lambda r:abs(r.strikePrice-chain.atm_strike))
                quote_reference["strike"]=atm.strikePrice
                for side in ["CE","PE"]:
                    contract=getattr(atm,side)
                    quote_reference[side]={"symbol":contract.contract_symbol,"expiry":contract.expiryDate,"ltp":contract.lastPrice,"bid":contract.bidprice,"ask":contract.askPrice,"oi":contract.openInterest,"volume":contract.totalTradedVolume}
            observations=[]
            for family in ['opening_range','trend_pullback']:
                policy=Policy(family=family,risk_fraction=settings.STRATEGY_RISK_FRACTION,daily_loss_fraction=settings.STRATEGY_DAILY_LOSS_FRACTION);direction=0;bar_close=None;inputs={}
                if chain.source in UNSAFE_SOURCES:state='DATA_BLOCKED'
                elif features is None or features.empty:state='WARMING_UP'
                else:
                    row=features.iloc[-1];bar_close=row.decision_time.isoformat()
                    for key in ['spot','ema9','ema21','atr','or_high','or_low','momentum','oi_flow']:
                        inputs[key]=None if pd.isna(row[key]) else float(row[key])
                    direction=int(signals(features,policy)[-1])
                    state='BULLISH_SETUP' if direction>0 else 'BEARISH_SETUP' if direction<0 else 'WAIT'
                    if not row.quality_ok:state='DATA_BLOCKED'
                observations.append((symbol,minute,now.isoformat(),bar_close,VERSION+'-5m',family,state,direction,chain.source,json.dumps(inputs,allow_nan=False),json.dumps(asdict(policy)),json.dumps(chain.data_quality),json.dumps(quote_reference)))
            with self.storage._get_connection() as conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS strategy_shadow_decisions(
                    id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
                    observation_minute TEXT NOT NULL, observed_at TEXT NOT NULL, bar_close_time TEXT,
                    engine_version TEXT NOT NULL,family TEXT NOT NULL,state TEXT NOT NULL,
                    direction INTEGER NOT NULL,source TEXT NOT NULL,inputs_json TEXT NOT NULL,
                    policy_json TEXT NOT NULL,quality_json TEXT NOT NULL,quote_reference_json TEXT NOT NULL,
                    UNIQUE(symbol,observation_minute,engine_version,family))""")
                conn.executemany("""INSERT OR IGNORE INTO strategy_shadow_decisions
                    (symbol,observation_minute,observed_at,bar_close_time,engine_version,family,state,direction,source,inputs_json,policy_json,quality_json,quote_reference_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",observations)
            self.last_seen[symbol]=observation_key
            if len(self.last_seen)>32:self.last_seen.pop(next(iter(self.last_seen)))

shadow_recorder=ShadowRecorder()
