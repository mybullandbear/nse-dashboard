from importlib.util import spec_from_file_location,module_from_spec
from pathlib import Path
import sys
import pandas as pd
import numpy as np

spec=spec_from_file_location('signal_research',Path(__file__).parents[1]/'scripts/research_signals.py')
r=module_from_spec(spec);sys.modules[spec.name]=r;spec.loader.exec_module(r)


def spot_data(n=60):
    timestamps=pd.date_range('2026-10-05T09:15:10+05:30',periods=n,freq='min')
    return pd.DataFrame({'id':range(n),'symbol':'NIFTY','trade_date':'2026-10-05','timestamp':timestamps.astype(str),'spot':25000+np.arange(n),'ce_oi':1000+np.arange(n),'pe_oi':1200+np.arange(n)*2,'pcr':1.2})


def test_signal_prefix_does_not_change_when_future_data_arrives():
    c=r.Candidate('test',persistence=2,min_momentum_atr=.5,oi_confirmation=True)
    short=r.minute_bars(spot_data(50));long=r.minute_bars(spot_data(60))
    np.testing.assert_array_equal(r.directions(short,c),r.directions(long,c)[:50])
    assert short.decision_time.iloc[0]>pd.to_datetime(spot_data().timestamp.iloc[0])


def test_quote_selection_never_uses_a_future_contract_snapshot():
    rows=[]
    for minute,price in [('09:45:10',100),('09:46:10',200)]:
        for typ in ['CE','PE']:
            rows.append({'symbol':'NIFTY','trade_date':'2026-10-05','timestamp':f'2026-10-05T{minute}+05:30','strike':25000.,'option_type':typ,'ltp':price,'oi':20000,'volume':1000})
    q=r.Quotes(pd.DataFrame(rows));t=pd.Timestamp('2026-10-05T09:46:00+05:30')
    assert q.at_signal('NIFTY','2026-10-05',t,'CE',25000).ltp==100


def test_quality_gate_blocks_persistent_unchanged_inputs():
    data=spot_data();data.loc[40:,['spot','ce_oi','pe_oi']]=data.loc[39,['spot','ce_oi','pe_oi']].to_numpy()
    bars=r.minute_bars(data)
    assert not bars.quality_ok.iloc[-1]
    assert r.directions(bars,r.Candidate('quality'))[-1]==0
