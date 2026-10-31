import json
from unittest.mock import patch
from app.services import option_chain as module


def raw_chain():
    return {'records':{'underlyingValue':25000,'expiryDates':['CURRENT'],'data':[{'strikePrice':strike,'CE':{'openInterest':(i+1)*100,'lastPrice':100},'PE':{'openInterest':(10-i)*100,'lastPrice':110}} for i,strike in enumerate(range(24800,25250,50))]}}


def test_central_calculations_match_uncached_and_isolate_mutation():
    module._normalized_cache.clear()
    raw=raw_chain()
    baseline=module._parse_option_chain_uncached(raw,'NIFTY')
    with patch.object(module,'_parse_option_chain_uncached',wraps=module._parse_option_chain_uncached) as parser:
        first=module.parse_option_chain(raw,'NIFTY')
        first.strikes[0].CE.lastPrice=999
        second=module.parse_option_chain(raw,'NIFTY')
        assert parser.call_count==1
        assert second.strikes[0].CE.lastPrice==100
        for field in ['pcr','pcr_atm_5','max_pain','atm_strike','total_ce_oi','total_pe_oi']:
            assert getattr(second,field)==getattr(baseline,field)
        raw['records']['data'][0]['CE']['openInterest']+=100
        module.parse_option_chain(raw,'NIFTY')
        assert parser.call_count==2


def test_normalized_cache_is_bounded():
    module._normalized_cache.clear()
    for i in range(50):
        raw=raw_chain();raw['records']['underlyingValue']+=i
        module.parse_option_chain(raw,'NIFTY')
    assert len(module._normalized_cache)==32
