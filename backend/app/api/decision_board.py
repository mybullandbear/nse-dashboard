"""One read-only snapshot for every index on the desktop decision board.

No broker fetches, order routing, or indicator reimplementations. Research setup
and current data/execution eligibility are deliberately independent fields.
"""
from collections import OrderedDict
import copy
from datetime import date,datetime,time,timedelta
import threading
import time as clock
from fastapi import APIRouter,Query,HTTPException
from app.core.config import get_settings
from app.core.market_hours import IST,get_current_ist,get_session_info
from app.api.research import workbench
from app.services.research_workbench import number
from app.services.data_quality import UNSAFE_SOURCES

router=APIRouter(prefix='/api/dashboard',tags=['decision-board'])
_feature_cache=OrderedDict()
_feature_lock=threading.RLock()


def _features(day,cutoff,symbols):
    key=(day,cutoff.isoformat(),tuple(symbols))
    with _feature_lock:
        cached=_feature_cache.get(key)
        if cached and clock.monotonic()-cached[0]<60:
            _feature_cache.move_to_end(key);return copy.deepcopy(cached[1])
        rows=[]
        for symbol in symbols:
            result=workbench.load(symbol,day,cutoff)
            bars=result['bars'];studies=result['studies'];latest=bars[-1] if bars else None
            trends={k:[] for k in ['price','ce_oi','pe_oi','oi_flow','pcr','signal']}
            for i,b in enumerate(bars):
                for key2,field in [('price','close'),('ce_oi','ce_oi'),('pe_oi','pe_oi'),('pcr','pcr')]:trends[key2].append(b.get(field))
                previous=bars[i-1] if i else None
                flow=number((b['pe_oi']-previous['pe_oi'])-(b['ce_oi']-previous['ce_oi'])) if previous and b['time']==previous['closed_at'] and b['complete'] and previous['complete'] and all(x.get(k) is not None for x in (b,previous) for k in ['ce_oi','pe_oi']) else None
                trends['oi_flow'].append(flow)
                states=[v['series'][i] for v in studies.values() if v['series'][i]['ready']]
                trends['signal'].append(number(sum(s['direction'] for s in states)/len(states)) if states else None)
            states={k:v['series'][-1] for k,v in studies.items() if v['series']}
            ready=[s for s in states.values() if s['ready']]
            bulls=sum(s['direction']==1 for s in ready);bears=sum(s['direction']==-1 for s in ready)
            direction=1 if bulls>=3 else -1 if bears>=3 else 0
            flow=trends['oi_flow'][-1] if bars else None
            oi_agrees=flow is not None and flow*direction>0
            setup='CE_WATCH' if direction>0 and oi_agrees else 'PE_WATCH' if direction<0 and oi_agrees else 'WAIT'
            reason='Three native indicators and recent OI flow align' if setup!='WAIT' else 'Indicators disagree or OI does not confirm' if len(ready)>=3 else 'Indicator warmup or incomplete observations'
            opening=[b for b in bars if b['time'][11:16]<'09:30']
            opening_ready=len(opening)==3 and all(b['complete'] for b in opening)
            price=latest['close'] if latest else None
            range_high=max(b['high'] for b in opening) if opening_ready else None
            range_low=min(b['low'] for b in opening) if opening_ready else None
            range_state='ABOVE RANGE' if opening_ready and price>range_high else 'BELOW RANGE' if opening_ready and price<range_low else 'IN RANGE' if opening_ready else 'WARMUP'
            atr=states.get('hull',{}).get('atr')
            rows.append(dict(symbol=symbol,spot=price,session_change_pct=number((price/bars[0]['open']-1)*100) if bars else None,closed_at=latest['closed_at'] if latest else None,last_observation=latest['last_observation'] if latest else None,complete=bool(latest and latest['complete']),ce_oi=latest.get('ce_oi') if latest else None,pe_oi=latest.get('pe_oi') if latest else None,net_oi=number(latest['pe_oi']-latest['ce_oi']) if latest and latest.get('pe_oi') is not None and latest.get('ce_oi') is not None else None,oi_flow=flow,pcr=latest.get('pcr') if latest else None,signal=dict(direction=direction,bulls=bulls,bears=bears,ready=len(ready),total=4,setup=setup,reason=reason,indicators={k:dict(state=v['state'],ready=v['ready'],direction=v['direction']) for k,v in states.items()}),opening_range=dict(high=range_high,low=range_low,state=range_state),atr=atr,trends=trends,times=[b['closed_at'] for b in bars],quality=result['quality']))
        _feature_cache[key]=(clock.monotonic(),rows)
        while len(_feature_cache)>8:_feature_cache.popitem(last=False)
        return copy.deepcopy(rows)


@router.get('/board')
def board(trade_date:date|None=None,at:time|None=None):
    now=get_current_ist();settings=get_settings();session=get_session_info(now)
    if at and trade_date is None:raise HTTPException(422,'Choose a session date for a replay cutoff')
    if at and not time(9,15)<=at<=time(15,40):raise HTTPException(422,'Replay time must be 09:15–15:40 IST')
    if trade_date and trade_date>now.date():raise HTTPException(422,'Future sessions unavailable')
    with workbench.connect() as conn:
        dates=[r[0] for r in conn.execute('SELECT DISTINCT trade_date FROM intraday_snapshots WHERE trade_date<=? ORDER BY trade_date DESC LIMIT 40',(now.date().isoformat(),))]
    day=trade_date.isoformat() if trade_date else now.date().isoformat() if now.date().isoformat() in dates else dates[0] if dates else now.date().isoformat()
    historical=trade_date is not None or day!=now.date().isoformat()
    cutoff=datetime.combine(date.fromisoformat(day),at or time(15,40),IST) if historical else min(now,datetime.combine(now.date(),time(15,40),IST))
    if cutoff>now:raise HTTPException(422,'Future observations unavailable')
    # Five-minute features are immutable within an observation interval; receipt
    # freshness and live-chain source gates are recomputed on every response.
    cutoff=cutoff.replace(minute=(cutoff.minute//5)*5,second=0,microsecond=0)
    rows=_features(day,cutoff,settings.TRACKED_SYMBOLS)
    from app.api.market import _chain_cache,_chain_cache_time
    from app.services.option_chain import parse_option_chain
    from app.services.shonya_bot import shonya_bot
    from app.services.strategy_policy import Policy,size_plan
    positions=shonya_bot.get_open_trades()
    capital=shonya_bot.capital_ceiling
    available=max(0,capital-sum(float(p.get('entry_price',0))*int(p.get('quantity',0)) for p in positions))
    policy=Policy(risk_fraction=settings.STRATEGY_RISK_FRACTION,daily_loss_fraction=settings.STRATEGY_DAILY_LOSS_FRACTION)
    for row in rows:
        blockers=[]
        if historical:blockers.append('HISTORICAL_REPLAY')
        if not session['is_market_open']:blockers.append('SESSION_CLOSED')
        if not row['closed_at']:blockers.append('NO_RECORDED_DATA')
        elif not historical and (now-datetime.fromisoformat(row['closed_at'])).total_seconds()>390:blockers.append('CLOSED_BAR_STALE')
        if not row['complete']:blockers.append('INCOMPLETE_CANDLE')
        age=clock.time()-_chain_cache_time.get(row['symbol'],0)
        raw=_chain_cache.get(row['symbol'])
        row['quote_age_seconds']=number(age) if raw and age>=0 else None
        row['source']='HISTORICAL' if historical else 'UNAVAILABLE'
        row['current_spot']=None
        row['contract']=None
        row['paper_plan']=None
        if not historical and raw and 0<=age<=settings.CHAIN_FRESHNESS_TTL_SEC:
            parsed=parse_option_chain({**raw,'_terminal_source':raw.get('_terminal_source','CACHED_RECEIPT')},row['symbol'])
            if not raw.get('_terminal_source'):blockers.append('SOURCE_UNVERIFIED')
            if parsed:
                row['source']=parsed.source
                if parsed.source not in UNSAFE_SOURCES:row['current_spot']=number(parsed.spot_price)
                if parsed.source in UNSAFE_SOURCES:blockers.append('UNSAFE_QUOTE_SOURCE')
                if not parsed.data_quality.get('exchange_timestamp_available'):blockers.append('EXCHANGE_TIME_UNVERIFIED')
                if parsed.strikes:
                    strike=min(parsed.strikes,key=lambda s:abs(s.strikePrice-parsed.spot_price))
                    side='CE' if row['signal']['direction']>0 else 'PE' if row['signal']['direction']<0 else None
                    if side:
                        c=getattr(strike,side)
                        row['contract']=dict(strike=strike.strikePrice,side=side,ltp=number(c.lastPrice),bid=number(c.bidprice),ask=number(c.askPrice),expiry=c.expiryDate,symbol=c.contract_symbol)
                        if 0<c.bidprice<=c.askPrice:
                            row['paper_plan']=size_plan(row['symbol'],c.askPrice,capital,policy,available)
                        if not c.contract_symbol or not c.expiryDate or c.expiryDate=='CURRENT':blockers.append('CONTRACT_UNVERIFIED')
                        if not 0<c.bidprice<=c.askPrice:blockers.append('BID_ASK_UNAVAILABLE')
                        elif (c.askPrice-c.bidprice)/c.askPrice>.02:blockers.append('SPREAD_TOO_WIDE')
            else:blockers.append('QUOTE_PARSE_UNAVAILABLE')
        elif not historical:blockers.append('FRESH_QUOTE_UNAVAILABLE')
        if not settings.HOLIDAY_CALENDAR_VERIFIED:blockers.append('CALENDAR_UNVERIFIED')
        row['lot_size']=settings.LOT_SIZES[row['symbol']]
        row['blockers']=blockers+['UNVALIDATED_RESEARCH_SETUP','LIVE_ORDERS_DISABLED']
        row['data_ready']=not blockers
        row['guidance']=('REPLAY · '+row['signal']['setup'].replace('_',' ')) if historical else 'NO TRADE · DATA' if any(b in blockers for b in ['NO_RECORDED_DATA','INCOMPLETE_CANDLE','CLOSED_BAR_STALE','UNSAFE_QUOTE_SOURCE','FRESH_QUOTE_UNAVAILABLE','QUOTE_PARSE_UNAVAILABLE']) else 'SESSION CLOSED' if not session['is_market_open'] else row['signal']['setup'].replace('_',' ')
    return dict(version='decision-board-v1',as_of=cutoff.isoformat(),generated_at=now.isoformat(),trade_date=day,historical_replay=historical,available_dates=dates,session=session,rows=rows,risk=dict(capital=capital,available=available,risk_per_trade_inr=capital*policy.risk_fraction,open_positions=len(positions)),trading_enabled=False,signal_definition='At least 3 of 4 ready native indicators agree, with matching five-minute put-minus-call OI change. Watchlist context only.',sparkline_definition='Completed five-minute observations for this session. Each sparkline has its own vertical scale; gaps are preserved.')
