"""Read-only private-data research benchmark: no credentials or outbound traffic.

PYTHONPATH=backend python scripts/benchmark_research.py --database /path/history.db --date 2026-10-14
"""
import argparse
from datetime import datetime,time,date
import json
from pathlib import Path
import statistics
from time import perf_counter
from app.core.market_hours import IST
from app.services.research_workbench import ResearchWorkbench


def main():
    p=argparse.ArgumentParser();p.add_argument('--database',required=True,type=Path);p.add_argument('--date',required=True,type=date.fromisoformat);args=p.parse_args()
    service=ResearchWorkbench(args.database);cutoff=datetime.combine(args.date,time(15,40),IST)
    result={}
    for symbol in ('NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX'):
        start=perf_counter();data=service.load(symbol,args.date.isoformat(),cutoff);cold=perf_counter()-start
        elapsed=[]
        for _ in range(10):
            start=perf_counter();service.load(symbol,args.date.isoformat(),cutoff);elapsed.append((perf_counter()-start)*1000)
        result[symbol]=dict(cold_ms=round(cold*1000,2),warm_p50_ms=round(statistics.median(elapsed),2),warm_max_ms=round(max(elapsed),2),bars=len(data['bars']))
    print(json.dumps(dict(local_only=True,production_sla=False,results=result),indent=2))

if __name__=='__main__':main()
