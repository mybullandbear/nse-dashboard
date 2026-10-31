import time, sys
sys.path.insert(0, '/home/ubuntu/nse-dashboard/backend')
import asyncio
from app.api.market import fetch_live_chain_data
from app.services.option_chain import parse_option_chain
from app.services.option_confluence_service import option_confluence_service

# Mock get_option_chart_data to return None
from app.services.option_candle_service import option_candle_service
orig_fn = option_candle_service.get_option_chart_data
option_candle_service.get_option_chart_data = lambda *args, **kwargs: None

async def test_speed():
    symbols = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX']
    t_all = time.time()
    for sym in symbols:
        t0 = time.time()
        raw, src = await fetch_live_chain_data(sym)
        parsed = parse_option_chain(raw, sym) if raw else None
        conf = await option_confluence_service.analyze_confluence(sym, range_strikes=3, parsed_chain=parsed)
        print(f"{sym}: taken {time.time()-t0:.3f}s")
    print(f"TOTAL FOR ALL 5 SYMBOLS: {time.time()-t_all:.3f}s")

asyncio.run(test_speed())
