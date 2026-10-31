"""Compare preserved indicator outputs to a committed baseline from the original revision."""
import hashlib
import json
from pathlib import Path
from app.services.technical_indicators import TechnicalIndicators as T


def test_indicator_baseline():
    base=Path(__file__).parent/'fixtures'/'indicators.json'
    fixture=json.loads(base.read_text())
    c=fixture['closes'];h=[x+2 for x in c];l=[x-2 for x in c]
    outputs={
        'ema':T.compute_ema(c,20),
        'rma':T.rma(c,14),
        'rsi':T.compute_rsi(c,14),
        'adx':T.compute_adx(h,l,c,14),
        'ott':T.compute_ott(c),
        'hull':T.compute_hull(c),
        'vwap':T.compute_vwap(h,l,c,[1000+i for i in range(len(c))]),
        'bollinger':T.compute_bollinger(c),
        'supertrend':T.compute_supertrend(h,l,c)
    }
    assert outputs==fixture['outputs'] or json.loads(json.dumps(outputs))==fixture['outputs']
