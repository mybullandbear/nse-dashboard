"""Deterministic, closed-bar entry rules and a paper-only execution policy.

This is a research/preview engine. It never calls a broker or enables ShonyaBot.
No heuristic strength is represented as a probability of profit.
"""
from dataclasses import dataclass,asdict
from datetime import time
import math
import pandas as pd
import numpy as np
from app.core.config import get_settings
from app.core.market_hours import IST

VERSION='orb-pullback-paper-v1'

@dataclass(frozen=True)
class Policy:
    family: str='opening_range'
    stop_pct: float=.20
    target_r: float=1.5
    holding_minutes: int=30
    trail_after_r: float=1.0
    trail_distance_pct: float=.12
    entry_start: str='09:45'
    entry_end: str='14:45'
    force_exit: str='15:35'
    persistence: int=2
    max_trades_per_symbol: int=3
    cooldown_minutes: int=10
    max_positions: int=2
    risk_fraction: float=.01
    daily_loss_fraction: float=.02
    fee: float=85.
    slippage: float=.005

    def __post_init__(self):
        if self.family not in {'opening_range','trend_pullback'}:raise ValueError('Unknown strategy family')
        if not all(math.isfinite(v) for v in [self.stop_pct,self.risk_fraction,self.target_r,self.slippage,self.fee,self.daily_loss_fraction,self.trail_distance_pct]):raise ValueError('Nonfinite risk policy')
        if not 0<self.stop_pct<1 or not 0<self.risk_fraction<=.02 or self.target_r<=0:raise ValueError('Invalid risk policy')
        if not 0<=self.slippage<=.05 or self.fee<0 or not self.risk_fraction<=self.daily_loss_fraction<=.05:raise ValueError('Invalid costs or daily loss ceiling')
        if not 0<self.trail_distance_pct<1 or self.holding_minutes<=0 or self.persistence<1:raise ValueError('Invalid exit or confirmation policy')
        if not '09:15'<=self.entry_start<self.entry_end<self.force_exit<'15:40':raise ValueError('Policy hours must be within the session')


def enrich(bars, timeframe_minutes=1):
    """Input timestamps are bar starts; decisions become available at bar ends."""
    parts=[]
    for _,b in bars.groupby(['symbol','trade_date'],sort=True):
        b=b.sort_values('minute').copy();b['decision_time']=b.minute+pd.Timedelta(minutes=timeframe_minutes)
        b['ema9']=b.spot.ewm(span=9,adjust=False).mean();b['ema21']=b.spot.ewm(span=21,adjust=False).mean()
        prev=b.spot.shift();tr=pd.concat([b.high-b.low,(b.high-prev).abs(),(b.low-prev).abs()],axis=1).max(axis=1)
        b['atr']=tr.ewm(alpha=1/14,adjust=False).mean().clip(lower=.01)
        opening=b.minute.dt.strftime('%H:%M').between('09:15','09:29')
        # The complete range is not exposed to any decision before 09:30.
        b['or_high']=np.where(b.decision_time.dt.strftime('%H:%M')>='09:30',b.loc[opening,'high'].max(),np.nan)
        b['or_low']=np.where(b.decision_time.dt.strftime('%H:%M')>='09:30',b.loc[opening,'low'].min(),np.nan)
        b['range_ready']=(b.decision_time.dt.strftime('%H:%M')>='09:30') & (int(opening.sum())==15//timeframe_minutes)
        b['momentum']=(b.spot-b.spot.shift(5))/b.atr
        b['oi_flow']=b.pe_oi.diff(5)-b.ce_oi.diff(5)
        b['trend_strength']=(b.ema9-b.ema21).abs()/b.atr
        b['prior_low']=b.low.shift();b['prior_high']=b.high.shift();b['prior_ema9']=b.ema9.shift()
        gap=b.minute.diff().dt.total_seconds().eq(60*timeframe_minutes)
        b['contiguous']=gap.rolling(29,min_periods=29).min().eq(1)
        same=b[['spot','ce_oi','pe_oi']].eq(b[['spot','ce_oi','pe_oi']].shift()).all(axis=1)
        b['unchanged']=same.groupby((~same).cumsum()).cumsum()
        b['quality_ok']=b.contiguous & (b.unchanged<3)
        if 'last_observation' in b:b['quality_ok'] &= (b.decision_time-b.last_observation).dt.total_seconds().between(0,30 if timeframe_minutes==1 else 90)
        if 'complete' in b:b['quality_ok'] &= b.complete.rolling(30,min_periods=30).min().eq(1)
        parts.append(b)
    return pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()


def signals(features,policy):
    b=features
    long=(b.ema9>b.ema21)&(b.momentum>=.5)&(b.oi_flow>0)&(b.trend_strength>=.25)
    short=(b.ema9<b.ema21)&(b.momentum<=-.5)&(b.oi_flow<0)&(b.trend_strength>=.25)
    if policy.family=='opening_range':
        long &= b.range_ready & (b.spot>b.or_high+.1*b.atr) & (b.spot-b.or_high<=1.5*b.atr)
        short &= b.range_ready & (b.spot<b.or_low-.1*b.atr) & (b.or_low-b.spot<=1.5*b.atr)
    else:
        long &= (b.prior_low<=b.prior_ema9+.2*b.atr)&(b.spot>b.prior_high)
        short &= (b.prior_high>=b.prior_ema9-.2*b.atr)&(b.spot<b.prior_low)
    d=pd.Series(np.where(long,1,np.where(short,-1,0)),index=b.index)
    # Breakout needs persistence. Pullback uses a discrete completed-bar trigger.
    persistence=policy.persistence if policy.family=='opening_range' else 1
    stable=d.groupby([b.symbol,b.trade_date]).transform(lambda x:x.rolling(persistence,min_periods=persistence).min().eq(x)&x.rolling(persistence,min_periods=persistence).max().eq(x))
    hours=b.decision_time.dt.strftime('%H:%M').between(policy.entry_start,policy.entry_end)
    return np.where(b.quality_ok & stable & hours,d,0)


def size_plan(symbol,premium,capital,policy,available=None):
    lot=get_settings().LOT_SIZES[symbol]
    if not all(math.isfinite(v) and v>0 for v in [premium,capital]):return {'lots':0,'quantity':0,'reason':'INVALID_PRICE_OR_CAPITAL'}
    available=capital if available is None else max(0,available)
    # Fee is conservatively charged once per lot in sizing; one-lot default cap.
    per_lot_risk=lot*premium*(policy.stop_pct+2*policy.slippage)+policy.fee
    lots=min(1,math.floor(capital*policy.risk_fraction/per_lot_risk),math.floor(available/(premium*(1+policy.slippage)*lot)))
    return {'lots':max(0,lots),'quantity':max(0,lots)*lot,'lot_size':lot,'entry_reference':round(premium,2),'stop':round(premium*(1-policy.stop_pct),2),'target':round(premium*(1+policy.stop_pct*policy.target_r),2),'one_lot_planned_loss_inr':round(per_lot_risk,2),'planned_loss_inr':round(max(0,lots)*per_lot_risk,2),'risk_budget_inr':round(capital*policy.risk_fraction,2),'reason':'WITHIN_LIMITS' if lots else 'ONE_LOT_EXCEEDS_RISK_OR_CAPITAL'}


class ExitState:
    def __init__(self,entry_time,entry_price,policy):
        if entry_time.tzinfo is None:raise ValueError("Timestamp requires timezone")
        entry_time=entry_time.astimezone(IST)
        self.entry_time=entry_time;self.entry=entry_price;self.policy=policy
        self.stop=entry_price*(1-policy.stop_pct);self.target=entry_price*(1+policy.stop_pct*policy.target_r)
        self.high=entry_price;self.last_time=entry_time

    def observe(self,t,price):
        if t.tzinfo is None:raise ValueError("Timestamp requires timezone")
        t=t.astimezone(IST)
        if t<=self.last_time:raise ValueError('Quotes must advance in time')
        if not math.isfinite(price) or price<=0:return 'UNPRICEABLE'
        if (t-self.last_time).total_seconds()>90:return 'UNPRICEABLE'
        self.last_time=t
        # Evaluate the stop previously known. Tightening applies to subsequent quotes.
        if price<=self.stop:return 'STOP_OR_TRAIL'
        if price>=self.target:return 'TARGET'
        if t.strftime('%H:%M')>=self.policy.force_exit:return 'SESSION_EXIT'
        if (t-self.entry_time).total_seconds()>=self.policy.holding_minutes*60:return 'TIME_EXIT'
        self.high=max(self.high,price)
        if self.high>=self.entry*(1+self.policy.stop_pct*self.policy.trail_after_r):
            self.stop=max(self.stop,self.entry*(1+2*self.policy.slippage),self.high*(1-self.policy.trail_distance_pct))
        return None
