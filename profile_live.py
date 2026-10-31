import time, sys
sys.path.insert(0, '/home/ubuntu/nse-dashboard/backend')
import asyncio
from app.services.fyers_service import fyers_service
from app.api.market import fetch_live_chain_data
from app.services.option_chain import parse_option_chain
from app.services.option_confluence_service import option_confluence_service

async def profile():
    symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]
    for sym in symbols:
        t0 = time.time()
        raw, src = await fetch_live_chain_data(sym)
        t_chain = time.time() - t0
        
        t1 = time.time()
        parsed = parse_option_chain(raw, sym) if raw else None
        t_parse = time.time() - t1
        
        t2 = time.time()
        conf = await option_confluence_service.analyze_confluence(sym, range_strikes=3, parsed_chain=parsed)
        t_conf = time.time() - t2
        
        print(f"{sym}: fetch_chain={t_chain:.2f}s (src={src}), parse={t_parse:.2f}s, conf={t_conf:.2f}s | TOTAL={time.time()-t0:.2f}s")

asyncio.run(profile())
