"""Exploratory policy study on already-inspected data; no promotion or broker calls."""
import argparse,json,sqlite3,hashlib
from pathlib import Path
from dataclasses import asdict
import pandas as pd
import numpy as np
from app.services.strategy_policy import Policy,enrich,signals,size_plan,ExitState
from research_signals import Quotes,minute_bars,metrics,directions,Candidate


def simulate(features,quotes,policy,capital=100000.,control=False):
    b=features.copy()
    if control:
        # Risk-matched comparator: same entry eligibility, sizing and exits.
        b['direction']=np.where((b.ema9>b.ema21)&(b.momentum>.5)&b.quality_ok,1,np.where((b.ema9<b.ema21)&(b.momentum<-.5)&b.quality_ok,-1,0))
    else:b['direction']=signals(b,policy)
    accepted=[];unpriced=[];blocked={};cash=capital;unresolved_lock=False
    def reject(reason):blocked[reason]=blocked.get(reason,0)+1
    for date,day in b.groupby('trade_date',sort=True):
        open_positions=[];cooldowns={};counts={};realized=0.;day_failed=unresolved_lock
        for row in day.sort_values(['decision_time','symbol']).itertuples():
            remaining=[]
            for position in open_positions:
                if position['exit_ts']<=row.decision_time:
                    if position['unpriceable']:
                        unpriced.append(position);day_failed=True;unresolved_lock=True
                    else:
                        accepted.append(position);realized+=position['net_inr'];cash+=position['net_inr']
                else:remaining.append(position)
            open_positions=remaining
            if not row.direction:continue
            hhmm=row.decision_time.strftime('%H:%M')
            if not policy.entry_start<=hhmm<=policy.entry_end:continue
            if day_failed:reject('UNRESOLVED_QUOTE_DAY_LOCK');continue
            if realized<=-capital*policy.daily_loss_fraction:reject('DAILY_LOSS_LIMIT');continue
            if len(open_positions)>=policy.max_positions:reject('MAX_OPEN_POSITIONS');continue
            if any(p['symbol']==row.symbol for p in open_positions):continue
            if counts.get(row.symbol,0)>=policy.max_trades_per_symbol:reject('MAX_DAILY_TRADES');continue
            if row.symbol in cooldowns and row.decision_time<cooldowns[row.symbol]:continue
            typ='CE' if row.direction>0 else 'PE';contract=quotes.at_signal(row.symbol,date,row.decision_time,typ,row.spot)
            if contract is None:reject('NO_PRIOR_QUOTE');continue
            seq=quotes.contracts[(row.symbol,date,float(contract.strike),typ)];future=seq[seq.ts>row.decision_time]
            if future.empty:reject('NO_ENTRY_QUOTE');continue
            entry=future.iloc[0]
            if (entry.ts-row.decision_time).total_seconds()>90 or entry.ltp<=0:reject('ENTRY_QUOTE_STALE');continue
            available=cash-sum(p['entry_debit'] for p in open_positions)
            plan=size_plan(row.symbol,float(entry.ltp),capital,policy,available)
            if not plan['quantity']:reject(plan['reason']);continue
            state=ExitState(entry.ts,float(entry.ltp),policy);last_fields=(entry.ltp,entry.oi,entry.volume);changed_at=entry.ts
            result=None;exit_ts=entry.ts;exit_price=None
            for q in future.iloc[1:].itertuples():
                exit_ts=q.ts;fields=(q.ltp,q.oi,q.volume)
                if fields!=last_fields:changed_at=q.ts;last_fields=fields
                if (q.ts-changed_at).total_seconds()>=180:result='UNPRICEABLE';break
                result=state.observe(q.ts,float(q.ltp))
                if result:
                    if result!='UNPRICEABLE':exit_price=float(q.ltp)
                    break
            if result is None:result='UNPRICEABLE';exit_ts=entry.ts+pd.Timedelta(minutes=policy.holding_minutes)
            debit=float(entry.ltp)*(1+policy.slippage)*plan['quantity']
            net=None if exit_price is None else (exit_price*(1-policy.slippage)-entry.ltp*(1+policy.slippage))*plan['quantity']-policy.fee
            trade={'symbol':row.symbol,'date':date,'signal_time':row.decision_time.isoformat(),'entry_time':entry.ts.isoformat(),'exit_time':exit_ts.isoformat(),'exit_ts':exit_ts,'quantity':plan['quantity'],'strike':float(contract.strike),'option_type':typ,'entry_observed':float(entry.ltp),'exit_observed':exit_price,'entry_debit':debit,'planned_loss_inr':plan['planned_loss_inr'],'net_inr':net,'reason':result,'unpriceable':exit_price is None}
            open_positions.append(trade);counts[row.symbol]=counts.get(row.symbol,0)+1;cooldowns[row.symbol]=exit_ts+pd.Timedelta(minutes=policy.cooldown_minutes)
        # Report all entered positions. Unknown outcomes never disappear from counts.
        for p in open_positions:
            if p['unpriceable']:unpriced.append(p);unresolved_lock=True
            else:accepted.append(p);cash+=p['net_inr']
    measured=metrics(accepted)
    stress=sum(p['entry_debit']+policy.fee for p in unpriced)
    return {'priced':measured,'unpriceable_entries':len(unpriced),'unpriceable_premium_at_risk_inr':round(sum(p['entry_debit'] for p in unpriced),2),'zero_recovery_stress_net_inr':round(measured['net_inr']-stress,2),'blocked':blocked},accepted+unpriced


def run(db,out):
    db=Path(db).resolve();out=Path(out);out.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)
    raw=pd.read_sql_query('select * from intraday_snapshots',c);options=pd.read_sql_query('select * from intraday_strike_snapshots',c);c.close()
    bars=minute_bars(raw,session_last_minute='15:39');features=enrich(bars);quotes=Quotes(options);dates=sorted(features.trade_date.unique());dev=dates[:7];diagnostic=dates[7:]
    policies=[Policy(family=f,stop_pct=s,target_r=t) for f in ['opening_range','trend_pullback'] for s in [.15,.20] for t in [1.5,2.0]]
    rows=[];trades=[]
    for p in policies:
        development,_=simulate(features[features.trade_date.isin(dev)],quotes,p)
        later,ledger=simulate(features[features.trade_date.isin(diagnostic)],quotes,p)
        rows.append({'policy':asdict(p),'development':development,'later_exploratory':later})
        if p.stop_pct==.20 and p.target_r==1.5:
            trades.extend([{**t,'policy':p.family,'exit_ts':t['exit_ts'].isoformat()} for t in ledger])
    control,_=simulate(features[features.trade_date.isin(diagnostic)],quotes,Policy(),control=True)
    sensitivity=[]
    for cap in [100000.,250000.]:
        for family in ['opening_range','trend_pullback']:
            for slip in [.005,.01]:
                p=Policy(family=family,slippage=slip)
                res,_=simulate(features[features.trade_date.isin(diagnostic)],quotes,p,capital=cap)
                sensitivity.append({'capital':cap,'family':family,'slippage_each_side':slip,'result':res})
    result={'status':'EXPLORATORY_UNVALIDATED','dataset_previously_inspected':True,'input_sha256':hashlib.file_digest(db.open('rb'),'sha256').hexdigest(),'development_dates':dev,'later_dates':diagnostic,'control':control,'policies':rows,'sensitivity':sensitivity,'normal_session':'09:15–15:40 IST','promotion':'NONE; fresh forward paper sessions required','limitations':['This dataset has already informed prior research; later dates are not a fresh independent holdout.','Missing expiry, executable bid/ask and fills; outcomes are conditional quote replay.','Priceable P&L excludes unresolved entries; report both counts and zero-recovery stress scenario.','Closed-trade drawdown is not mark-to-market drawdown.','Configured lot sizes are preserved; fees/slippage are explicit assumptions.']}
    (out/'strategy_policy_results.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    pd.DataFrame(trades).to_csv(out/'strategy_policy_trades_private.csv',index=False)
    print(json.dumps({'control':control,'policies':[{k:v for k,v in x.items()} for x in rows],'sensitivity':sensitivity},indent=2))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('database');p.add_argument('--output',required=True);a=p.parse_args();run(a.database,a.output)
