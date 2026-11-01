"""Read-only, chronological signal research. Never connects to a broker or edits the input.

Minute closes become available at the next minute boundary. Entries use the first
subsequent same-strike quote; exits use observed quotes, never idealized stop fills.
Missing expiry/bid/ask/trade IDs mean results are conditional premium replay, not
verified executable P&L. Original logged decisions cannot be recovered when absent.
"""
import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
import numpy as np
import pandas as pd

LOTS={'NIFTY':65,'BANKNIFTY':30,'FINNIFTY':60,'MIDCPNIFTY':120}

@dataclass(frozen=True)
class Candidate:
    name: str
    persistence: int=1
    min_momentum_atr: float=0.0
    oi_confirmation: bool=False
    quality_gate: bool=True


def minute_bars(frame,session_last_minute='15:29'):
    frame=frame.copy()
    frame['ts']=pd.to_datetime(frame.timestamp,format='mixed')
    frame=frame.sort_values(['symbol','ts','id'])
    frame['minute']=frame.ts.dt.floor('min')
    rows=[]
    for (symbol,date),g in frame.groupby(['symbol','trade_date'],sort=True):
        bars=g.groupby('minute').agg(spot=('spot','last'),high=('spot','max'),low=('spot','min'),ce_oi=('ce_oi','last'),pe_oi=('pe_oi','last'),pcr=('pcr','last'),last_observation=('ts','max'),samples=('spot','size')).reset_index()
        bars=bars[bars.minute.dt.strftime('%H:%M').between('09:15',session_last_minute)].copy()
        bars['symbol']=symbol;bars['trade_date']=date
        bars['decision_time']=bars.minute+pd.Timedelta(minutes=1)
        bars['ema_fast']=bars.spot.ewm(span=9,adjust=False).mean()
        bars['ema_slow']=bars.spot.ewm(span=21,adjust=False).mean()
        prev=bars.spot.shift()
        tr=pd.concat([bars.high-bars.low,(bars.high-prev).abs(),(bars.low-prev).abs()],axis=1).max(axis=1)
        bars['atr']=tr.ewm(alpha=1/14,adjust=False).mean().clip(lower=.01)
        bars['momentum']=(bars.spot-bars.spot.shift(5))/bars.atr
        bars['oi_flow']=bars.pe_oi.diff(5)-bars.ce_oi.diff(5)
        same=bars[['spot','ce_oi','pe_oi']].eq(bars[['spot','ce_oi','pe_oi']].shift()).all(axis=1)
        bars['unchanged_minutes']=same.groupby((~same).cumsum()).cumsum()
        bars['quality_ok']=(bars.unchanged_minutes<3)&((bars.decision_time-bars.last_observation).dt.total_seconds()<=30)&bars.minute.diff().dt.total_seconds().eq(60).rolling(6,min_periods=6).min().eq(1)
        bars['warm']=np.arange(len(bars))>=30
        rows.append(bars)
    return pd.concat(rows,ignore_index=True)


def directions(bars,candidate):
    b=bars
    direction=np.where((b.ema_fast>b.ema_slow)&(b.momentum>candidate.min_momentum_atr),1,np.where((b.ema_fast<b.ema_slow)&(b.momentum<-candidate.min_momentum_atr),-1,0))
    if candidate.oi_confirmation:direction=np.where(direction*b.oi_flow.to_numpy()>0,direction,0)
    direction=np.where(b.warm.to_numpy(),direction,0)
    if candidate.quality_gate:direction=np.where(b.quality_ok.to_numpy(),direction,0)
    if candidate.persistence>1:
        d=pd.Series(direction,index=b.index)
        stable=d.groupby([b.symbol,b.trade_date]).transform(lambda x:x.rolling(candidate.persistence,min_periods=candidate.persistence).min().eq(x)&x.rolling(candidate.persistence,min_periods=candidate.persistence).max().eq(x))
        direction=np.where(stable,direction,0)
    return direction


class Quotes:
    def __init__(self,options):
        self.snapshots={};self.contracts={}
        options=options.copy();options['ts']=pd.to_datetime(options.timestamp,format='mixed')
        for key,g in options.groupby(['symbol','trade_date']):
            g=g.sort_values(['ts','strike','option_type'])
            self.snapshots[key]={t:sub for t,sub in g.groupby('ts')}
            self.snapshots[(*key,'times')]=pd.DatetimeIndex(list(self.snapshots[key])).tz_convert('UTC').tz_localize(None).to_numpy()
            for (strike,typ),v in g.groupby(['strike','option_type']):
                self.contracts[(*key,float(strike),typ)]=v.sort_values('ts').reset_index(drop=True)

    def at_signal(self,symbol,date,t,typ,spot):
        key=(symbol,date);times=self.snapshots.get((*key,'times'))
        if times is None:return None
        idx=times.searchsorted(t.tz_convert('UTC').tz_localize(None).to_datetime64(),side='right')-1
        if idx<0:return None
        snap=list(self.snapshots[key].values())[idx]
        if (t-snap.ts.iloc[0]).total_seconds()>90:return None
        snap=snap[(snap.option_type==typ)&(snap.ltp>=20)&(snap.oi>=10000)&(snap.volume>0)]
        if snap.empty:return None
        return snap.iloc[(snap.strike-spot).abs().argmin()]


def replay(bars,quotes,candidate,slippage=.005,fee=85.):
    bars=bars.copy();bars['direction']=directions(bars,candidate)
    trades=[];rejections={'missing_quote':0,'capital':0,'gap_or_missing_exit':0}
    for (symbol,date),g in bars.groupby(['symbol','trade_date']):
        next_allowed=None;count=0
        for row in g.itertuples():
            if not row.direction or count>=3:continue
            if row.decision_time.strftime('%H:%M')<'09:45' or row.decision_time.strftime('%H:%M')>'14:45':continue
            if next_allowed is not None and row.decision_time<next_allowed:continue
            typ='CE' if row.direction>0 else 'PE'
            contract=quotes.at_signal(symbol,date,row.decision_time,typ,row.spot)
            if contract is None:rejections['missing_quote']+=1;continue
            seq=quotes.contracts[(symbol,date,float(contract.strike),typ)]
            future=seq[seq.ts>row.decision_time]
            if future.empty:rejections['missing_quote']+=1;continue
            entry=future.iloc[0]
            if not np.isfinite(entry.ltp) or entry.ltp<=0:
                rejections['missing_quote']+=1;continue
            if (entry.ts-row.decision_time).total_seconds()>90:rejections['missing_quote']+=1;continue
            qty=LOTS[symbol];buy=entry.ltp*(1+slippage)
            if buy*qty>30000:rejections['capital']+=1;continue
            limit=entry.ts+pd.Timedelta(minutes=20)
            expiry=entry.ts.normalize()+pd.Timedelta(hours=15,minutes=15)
            limit=min(limit,expiry)
            exit_row=None;reason='TIME';last=entry.ts
            economic=(entry.ltp,entry.volume,entry.oi);quote_changed_at=entry.ts
            for q in future.iloc[1:].itertuples():
                if (q.ts-last).total_seconds()>90:reason='GAP';break
                last=q.ts
                # A changing timestamp is not evidence that an unchanged contract traded.
                if not np.isfinite(q.ltp) or q.ltp<=0:reason='GAP';break
                observed=(q.ltp,q.volume,q.oi)
                if observed!=economic:
                    economic=observed;quote_changed_at=q.ts
                if candidate.quality_gate and (q.ts-quote_changed_at).total_seconds()>=180:
                    reason='FROZEN';break
                if q.ltp<=entry.ltp*.75:exit_row=q;reason='STOP';break
                if q.ltp>=entry.ltp*1.40:exit_row=q;reason='TARGET';break
                if q.ts>=limit:exit_row=q;break
            if exit_row is None:rejections['gap_or_missing_exit']+=1;next_allowed=limit+pd.Timedelta(minutes=10);continue
            sell=exit_row.ltp*(1-slippage);net=(sell-buy)*qty-fee
            trades.append({'candidate':candidate.name,'symbol':symbol,'date':date,'signal_time':row.decision_time.isoformat(),'entry_time':entry.ts.isoformat(),'exit_time':exit_row.ts.isoformat(),'strike':float(contract.strike),'option_type':typ,'entry_observed':float(entry.ltp),'exit_observed':float(exit_row.ltp),'quantity':qty,'entry_debit':float(buy*qty),'net_inr':float(net),'reason':reason})
            next_allowed=exit_row.ts+pd.Timedelta(minutes=10);count+=1
    # Shared 100k premium capital ceiling, deterministic timestamp/symbol ordering.
    accepted=[];open_positions=[]
    for trade in sorted(trades,key=lambda x:(x['entry_time'],x['symbol'])):
        open_positions=[x for x in open_positions if x['exit_time']>trade['entry_time']]
        if sum(x['entry_debit'] for x in open_positions)+trade['entry_debit']>100000:rejections['capital']+=1;continue
        accepted.append(trade);open_positions.append(trade)
    return accepted,rejections


def metrics(trades):
    if not trades:return {'trades':0,'net_inr':0.,'win_rate':None,'profit_factor':None,'max_drawdown_inr':0.,'mean_inr':None}
    t=pd.DataFrame(trades).sort_values('exit_time');p=t.net_inr.to_numpy();equity=np.r_[0,np.cumsum(p)]
    wins=p[p>0].sum();loss=-p[p<0].sum()
    return {'trades':len(t),'net_inr':round(float(p.sum()),2),'win_rate':round(float((p>0).mean()),4),'profit_factor':round(float(wins/loss),3) if loss else None,'max_drawdown_inr':round(float((np.maximum.accumulate(equity)-equity).max()),2),'mean_inr':round(float(p.mean()),2),'positive_days':int((t.groupby('date').net_inr.sum()>0).sum())}


def run(database,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    database=Path(database).resolve();conn=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
    integrity=conn.execute('pragma quick_check').fetchone()[0]
    spot=pd.read_sql_query('select * from intraday_snapshots',conn)
    options=pd.read_sql_query('select * from intraday_strike_snapshots',conn)
    signal_count=conn.execute('select count(*) from signal_history').fetchone()[0];conn.close()
    bars=minute_bars(spot);quotes=Quotes(options);dates=sorted(bars.trade_date.unique())
    if len(dates)<10:raise ValueError('Need at least ten distinct sessions for this predeclared 5/2/remainder split')
    split={'train':dates[:5],'validation':dates[5:7],'test':dates[7:]}
    candidates=[Candidate('ema_reference',quality_gate=False)]
    for persist in [1,2]:
        for momentum in [0.0,.5,1.0]:
            for oi in [False,True]:
                candidates.append(Candidate(f'quality_p{persist}_m{momentum:g}_oi{int(oi)}',persist,momentum,oi))
    # Holdout dates are never used for candidate selection.
    development=bars[bars.trade_date.isin(split['train']+split['validation'])]
    selection=[];cache={}
    for candidate in candidates:
        trades,rejections=replay(development,quotes,candidate)
        cache[candidate.name]=trades
        train=metrics([t for t in trades if t['date'] in split['train']]);validation=metrics([t for t in trades if t['date'] in split['validation']])
        selection.append({'parameters':asdict(candidate),'train':train,'validation':validation,'rejections':rejections})
    eligible=[x for x in selection[1:] if x['train']['trades']>=20 and x['validation']['trades']>=10 and x['train']['net_inr']>0]
    selected=max(eligible,key=lambda x:(x['validation']['net_inr'],-x['validation']['max_drawdown_inr'])) if eligible else None
    # Even when no model qualifies, evaluate the predeclared conservative challenger.
    selected_name=selected['parameters']['name'] if selected else 'quality_p2_m0.5_oi1'
    chosen=next(x for x in candidates if x.name==selected_name)
    testbars=bars[bars.trade_date.isin(split['test'])]
    comparisons=[];alltrades=[]
    for cand in [candidates[0],chosen]:
        for slip in [0.,.0025,.005,.01]:
            trades,reject=replay(testbars,quotes,cand,slippage=slip)
            comparisons.append({'candidate':cand.name,'slippage_per_side':slip,'roundtrip_fee_inr':85.,'metrics':metrics(trades),'rejections':reject})
            if slip==.005:alltrades+=trades
    audit={'integrity':integrity,'database_sha256':hashlib.file_digest(database.open('rb'),'sha256').hexdigest(),'spot_rows':len(spot),'option_rows':len(options),'signal_rows':signal_count,'symbols':sorted(spot.symbol.unique()),'dates':dates,'confluence_unique':sorted(float(x) for x in spot.confluence.unique()),'aggregate_volume_zero_fraction':float(((spot.ce_vol==0)&(spot.pe_vol==0)).mean()),'duplicate_option_keys':int(options.duplicated(['symbol','timestamp','strike','option_type']).sum()),'minute_bars':len(bars),'rejected_quality_bars':int((~bars.quality_ok).sum()),'rows_after_1530':int((spot.time_str>'15:30').sum()),'missing_fields':['expiry','contract identifier','bid/ask','exchange quote timestamp','order/fill records']}
    result={'audit':audit,'split':split,'selection':selection,'selected':asdict(chosen),'qualified_on_development':selected is not None,'test_comparisons':comparisons,'promotion':'SHADOW_ONLY; no automatic strategy replacement','limitations':['Only ten sessions; correlated indices are not independent trials.','Logged confluence is constant 50 and signal_history is empty; actual original signal performance is not recoverable.','EMA reference is a research comparator, not a reconstruction of ShonyaBot or the production confluence engine.','No expiry/bid-ask/fills; premium replay is conditional, with assumed historical lot sizes and fees.','Sampled quotes cannot reveal intra-minute stop touches.','Unpriceable trades are excluded and counted; this may bias results.','No calibrated confidence or promised future profitability.']}
    (output/'signal_research.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    pd.DataFrame(alltrades).to_csv(output/'holdout_trades_private.csv',index=False)
    print(json.dumps({'audit':audit,'split':split,'selected':asdict(chosen),'qualified_on_development':selected is not None,'test_comparisons':comparisons},indent=2))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('database');parser.add_argument('--output',required=True)
    args=parser.parse_args();run(args.database,args.output)
