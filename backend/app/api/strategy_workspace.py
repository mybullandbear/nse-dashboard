"""Authenticated, read-only entry/exit previews; no orders or strategy activation."""
from app.services.research_workbench import policy_bars
from datetime import date,datetime,time
from dataclasses import asdict
import time as clock
import pandas as pd
from fastapi import APIRouter,Query,HTTPException
from app.core.config import get_settings
from app.core.market_hours import get_current_ist,get_session_info,IST
from app.db.storage import snapshot_storage
from app.services.strategy_policy import Policy,enrich,signals,size_plan,VERSION
from app.services.data_quality import UNSAFE_SOURCES

router=APIRouter(prefix='/api/strategy',tags=['strategy_workspace'])

@router.get('/workspace')
def workspace(family:str=Query('opening_range',pattern='^(opening_range|trend_pullback)$'),trade_date:date|None=None,at:time|None=None):
    settings=get_settings();now=get_current_ist();day=trade_date or now.date();replay=day!=now.date() or at is not None
    if at is not None and not time(9,15)<=at<=time(15,40):raise HTTPException(422,'Replay time must be within 09:15–15:40 IST')
    cutoff=datetime.combine(day,at or time(15,40),IST) if replay else now
    if cutoff>now:raise HTTPException(422,'Future replay observations are unavailable')
    policy=Policy(family=family,risk_fraction=settings.STRATEGY_RISK_FRACTION,daily_loss_fraction=settings.STRATEGY_DAILY_LOSS_FRACTION)
    from app.services.shonya_bot import shonya_bot
    from app.api.market import _chain_cache,_chain_cache_time
    from app.services.option_chain import parse_option_chain
    capital=shonya_bot.capital_ceiling;positions=shonya_bot.get_open_trades()
    deployed=sum(float(t.get('entry_price',0))*int(t.get('quantity',0)) for t in positions)
    history=shonya_bot.get_trade_history(limit=1000)
    realized=sum(float(t.get('net_pnl',0)) for t in history if str(t.get('exit_time',''))[:10]==now.date().isoformat())
    rows=[]
    for symbol in settings.TRACKED_SYMBOLS:
        raw=snapshot_storage.get_strategy_bars(symbol,day.isoformat(),cutoff.isoformat())
        reasons=['STRATEGY_NOT_FORWARD_VALIDATED']
        if replay:reasons.append('HISTORICAL_REPLAY_ONLY')
        session=get_session_info(now)
        if not replay and not session['is_market_open']:reasons.append('SESSION_CLOSED')
        if not settings.HOLIDAY_CALENDAR_VERIFIED:reasons.append('HOLIDAY_CALENDAR_UNVERIFIED')
        if realized<=-capital*policy.daily_loss_fraction:reasons.append('DAILY_LOSS_LIMIT')
        if len(positions)>=policy.max_positions:reasons.append('MAX_OPEN_POSITIONS')
        if any(t.get('symbol')==symbol for t in positions):reasons.append('POSITION_ALREADY_OPEN')
        row={'symbol':symbol,'lot_size':settings.LOT_SIZES[symbol],'setup':'WARMING_UP','execution':'BLOCKED','blockers':reasons,'plan':None,'evidence':{},'bars':len(raw)}
        if not raw:reasons.append('NO_RECORDED_SESSION_DATA');rows.append(row);continue
        raw=policy_bars(raw,cutoff)
        if not raw:reasons.append('NO_CLOSED_FIVE_MINUTE_BAR');rows.append(row);continue
        row['bars']=len(raw)
        b=pd.DataFrame(raw)
        for key in ['minute','last_observation']:b[key]=pd.to_datetime(b[key],format='mixed')
        f=enrich(b,timeframe_minutes=5);last=f.iloc[-1];direction=int(signals(f,policy)[-1])
        row.update(setup='BULLISH_SETUP' if direction>0 else 'BEARISH_SETUP' if direction<0 else 'WAIT',observed_at=last.last_observation.isoformat(),bar_closed_at=last.decision_time.isoformat())
        def n(value):return None if pd.isna(value) else round(float(value),2)
        row['evidence']={'spot':n(last.spot),'ema9':n(last.ema9),'ema21':n(last.ema21),'atr':n(last.atr),'opening_high':n(last.or_high),'opening_low':n(last.or_low),'momentum_atr':n(last.momentum),'oi_flow':n(last.oi_flow),'quality_ok':bool(last.quality_ok),'opening_range_ready':bool(last.range_ready)}
        if not bool(last.quality_ok):reasons.append('INCOMPLETE_OR_UNCHANGED_BARS')
        if not direction:reasons.append('ENTRY_RULES_NOT_MET')
        raw_chain=_chain_cache.get(symbol);age=clock.time()-_chain_cache_time.get(symbol,0)
        if replay or raw_chain is None or age>settings.CHAIN_FRESHNESS_TTL_SEC:reasons.append('NO_FRESH_EXECUTABLE_QUOTE')
        else:
            parsed=parse_option_chain({**raw_chain,'_terminal_source':'FYERS_LIVE'},symbol)
            if not parsed or parsed.source in UNSAFE_SOURCES:reasons.append('UNSAFE_QUOTE_SOURCE')
            elif direction:
                if not parsed.data_quality.get('exchange_timestamp_available'):reasons.append('EXCHANGE_TIMESTAMP_UNAVAILABLE')
                contract_row=min(parsed.strikes,key=lambda s:abs(s.strikePrice-parsed.spot_price));contract=contract_row.CE if direction>0 else contract_row.PE
                if not contract.contract_symbol or not contract.expiryDate or contract.expiryDate=='CURRENT':reasons.append('CONTRACT_METADATA_INCOMPLETE')
                if not 0<contract.bidprice<=contract.askPrice:reasons.append('BID_ASK_UNAVAILABLE')
                elif (contract.askPrice-contract.bidprice)/contract.askPrice>.02:reasons.append('SPREAD_TOO_WIDE')
                if contract.openInterest<10000 or contract.totalTradedVolume<=0:reasons.append('INSUFFICIENT_OBSERVED_LIQUIDITY')
                row['plan']=size_plan(symbol,contract.askPrice or contract.lastPrice,capital,policy,max(0,capital-deployed))
                row['plan'].update(option_type='CE' if direction>0 else 'PE',strike=contract_row.strikePrice,contract=contract.contract_symbol)
                if row['plan']['quantity']==0:reasons.append(row['plan']['reason'])
        if not replay and (now-last.last_observation.to_pydatetime()).total_seconds()>90:reasons.append('BAR_DATA_STALE')
        rows.append(row)
    return {'timeframe_minutes':5,'engine_version':VERSION+'-5m','validation_status':'UNVALIDATED_PAPER_PREVIEW','trading_enabled':False,'trade_date':day.isoformat(),'as_of':cutoff.isoformat(),'historical_replay':replay,'session':get_session_info(now),'policy':asdict(policy),'risk':{'capital':capital,'available':max(0,capital-deployed),'realized_today':realized,'risk_per_trade_inr':capital*policy.risk_fraction,'daily_loss_limit_inr':capital*policy.daily_loss_fraction,'open_positions':len(positions)},'lot_sizes':settings.LOT_SIZES,'rows':rows,'results_status':'NO_FRESH_OUT_OF_SAMPLE_VALIDATION'}
