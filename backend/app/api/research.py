"""Authenticated read-only research endpoints, shared closed candle service."""
from datetime import date,datetime,time
from fastapi import APIRouter,Query,HTTPException
from app.core.config import get_settings
from app.core.market_hours import IST,get_current_ist
from app.db.storage import snapshot_storage
from app.services.research_workbench import ResearchWorkbench

router=APIRouter(prefix='/api/research',tags=['research'])
workbench=ResearchWorkbench(snapshot_storage.db_path)

@router.get('/catalog')
def catalog():
    return workbench.catalog()

@router.get('/session')
def session(symbol:str,trade_date:date,at:time= time(15,40),exit_mode:str=Query('trailing_flip',pattern='^(trailing|signal_flip|trailing_flip)$'),atr_multiple:float=Query(2,ge=.5,le=5),oi_filter:bool=False,strike:float|None=Query(None,gt=0),option_type:str=Query('CE',pattern='^(CE|PE)$')):
    symbol=symbol.upper()
    if symbol not in get_settings().TRACKED_SYMBOLS: raise HTTPException(422,'Unsupported index')
    if not time(9,15)<=at<=time(15,40): raise HTTPException(422,'Time must be 09:15–15:40 IST')
    cutoff=datetime.combine(trade_date,at,IST)
    if cutoff>get_current_ist():raise HTTPException(422,'Future observations unavailable')
    return workbench.load(symbol,trade_date.isoformat(),cutoff,exit_mode,atr_multiple,oi_filter,strike,option_type)

@router.get('/compare')
def compare(trade_date:date,at:time=time(15,40),exit_mode:str=Query('trailing_flip',pattern='^(trailing|signal_flip|trailing_flip)$'),atr_multiple:float=Query(2,ge=.5,le=5),oi_filter:bool=False):
    if not time(9,15)<=at<=time(15,40):raise HTTPException(422,'Time must be 09:15–15:40 IST')
    cutoff=datetime.combine(trade_date,at,IST)
    if cutoff>get_current_ist():raise HTTPException(422,'Future observations unavailable')
    rows=[]
    for symbol in get_settings().TRACKED_SYMBOLS:
        result=workbench.load(symbol,trade_date.isoformat(),cutoff,exit_mode,atr_multiple,oi_filter)
        for name,study in result['studies'].items():
            research=study['research']
            rows.append(dict(symbol=symbol,indicator=name,closed_trades=research['closed_trades'],gross_index_points=research['gross_index_points'],win_rate=research['win_rate'],unresolved=research['unresolved']))
        if not result['bars']:rows.append(dict(symbol=symbol,indicator=None,closed_trades=0,gross_index_points=None,win_rate=None,unresolved=0))
    return dict(trade_date=trade_date.isoformat(),as_of=cutoff.isoformat(),rows=rows,result_kind='EXPLORATORY_GROSS_INDEX_POINTS',trading_enabled=False)
