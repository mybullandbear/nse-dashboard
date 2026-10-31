"""
Stock Intelligence API Routes

Endpoints for stock gainers/losers, volume shockers, EMS stock recommendations,
sectoral heatmap, FII/DII flow, and historical charts.
"""
import os
import json
import logging
from datetime import datetime
import pytz
from typing import Optional, Dict, Any, List

from fastapi import APIRouter
from app.services.stock_scraper import (
    get_gainers_1d, get_losers_1d, get_gainers_5d, get_losers_5d,
    get_fii_dii_data, get_market_overview_data, get_nse_sectoral_indices, _SESSION as MC_SESSION
)
from app.services.stock_detection_engine import detection_engine
from app.services.stock_historical_fetcher import get_historical_data
from app.services.market_hours import is_market_open

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stocks", tags=["stocks"])

IST = pytz.timezone('Asia/Kolkata')

# Load F&O symbols set
FNO_SYMBOLS = set()
def load_fno_symbols():
    global FNO_SYMBOLS
    local_file = os.path.join(os.path.dirname(__file__), "..", "services", "fno_symbols.json")
    if os.path.exists(local_file):
        try:
            with open(local_file, "r", encoding="utf-8") as f_in:
                FNO_SYMBOLS = set(json.load(f_in))
                logger.info(f"Loaded {len(FNO_SYMBOLS)} F&O symbols for stock scanner.")
        except Exception as e:
            logger.error(f"Error loading local F&O symbols: {e}")

load_fno_symbols()

# In-memory cached market data for stocks
latest_stock_market_data: Dict[str, Any] = {
    "gainers_1d": [],
    "losers_1d":  [],
    "gainers_5d": [],
    "losers_5d":  [],
    "fii_dii": [],
    "early_opportunities": {"top_gainers": [], "top_losers": []},
    "market_intel": {},
    "sectoral_heatmap": [],
    "market_open": False,
    "last_updated": None,
}

SYMBOL_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "services", "stock_symbol_cache.json")
def load_symbol_cache():
    if os.path.exists(SYMBOL_CACHE_FILE):
        try:
            with open(SYMBOL_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading stock symbol cache: {e}")
    return {}

def save_symbol_cache(cache):
    try:
        with open(SYMBOL_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Error saving stock symbol cache: {e}")

SYMBOL_CACHE = load_symbol_cache()

def resolve_symbol_info(name: str, href: str):
    import re
    if not href:
        return {
            "nse_symbol": re.sub(r'[^A-Za-z0-9]', '', name).upper(),
            "sector": "Others"
        }
    if name in SYMBOL_CACHE:
        return SYMBOL_CACHE[name]
    try:
        from bs4 import BeautifulSoup
        res = MC_SESSION.get(href, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.content, 'html.parser')
        
        nse_symbol = None
        for li in soup.find_all('li', class_='clearfix'):
            span = li.find('span')
            if span and 'NSE:' in span.get_text():
                p = li.find('p')
                if p:
                    nse_symbol = p.get_text().strip()
                    break
        if not nse_symbol:
            nse_symbol = re.sub(r'[^A-Za-z0-9]', '', name).upper()
            
        sector = "Others"
        stock_name_div = soup.find('div', id='stockName')
        if stock_name_div:
            text = stock_name_div.get_text(separator=' ', strip=True)
            m = re.search(r'Sector\s*:\s*(.*?)\s*\|\s*Industry\s*:\s*(.*)', text)
            if m:
                sector = m.group(1).strip()
            else:
                m2 = re.search(r'Sector\s*:\s*([^|]*)', text)
                if m2:
                    sector = m2.group(1).strip()
                    
        info = {"nse_symbol": nse_symbol, "sector": sector}
        SYMBOL_CACHE[name] = info
        save_symbol_cache(SYMBOL_CACHE)
        return info
    except Exception as e:
        return {"nse_symbol": re.sub(r'[^A-Za-z0-9]', '', name).upper(), "sector": "Others"}

def update_stock_market_data():
    """Background polling function for stock market data."""
    open_flag = is_market_open()
    latest_stock_market_data["market_open"] = open_flag

    try:
        fii_dii = get_fii_dii_data()
        if fii_dii:
            latest_stock_market_data["fii_dii"] = fii_dii
    except Exception as e:
        logger.error(f"Error fetching FII/DII stock data: {e}")

    try:
        overview = get_market_overview_data()
        if overview:
            latest_stock_market_data["market_intel"].update(overview)
    except Exception as e:
        logger.error(f"Error fetching market overview: {e}")

    try:
        sectoral = get_nse_sectoral_indices()
        if sectoral:
            latest_stock_market_data["sectoral_heatmap"] = sectoral
    except Exception as e:
        logger.error(f"Error fetching sectoral heatmap: {e}")

    if not open_flag and latest_stock_market_data["last_updated"]:
        logger.info("Market closed – serving cached stock data.")
        return

    logger.info("Polling stock market data sets...")
    g1 = get_gainers_1d()
    l1 = get_losers_1d()
    g5 = get_gainers_5d()
    l5 = get_losers_5d()

    if any([g1, l1, g5, l5]):
        for item in (g1 + l1 + g5 + l5):
            info = resolve_symbol_info(item["symbol"], item.get("href"))
            item["nse_symbol"] = info["nse_symbol"]
            item["sector"] = info["sector"]
            item["is_fno"] = info["nse_symbol"] in FNO_SYMBOLS

        latest_stock_market_data["gainers_1d"]  = g1
        latest_stock_market_data["losers_1d"]   = l1
        latest_stock_market_data["gainers_5d"]  = g5
        latest_stock_market_data["losers_5d"]   = l5
        latest_stock_market_data["last_updated"] = datetime.now(IST).isoformat()

        try:
            detection_engine.ingest(latest_stock_market_data, datetime.now(IST))
            latest_stock_market_data["early_opportunities"] = detection_engine.get_top_opportunities(5)
        except Exception as e:
            logger.error(f"Detection engine ingest error: {e}")

        logger.info("Stock market data updated successfully.")


@router.get("/market-data")
def get_stock_market_data():
    """Get full stock market scanners, gainers/losers, EMS opportunities, FII/DII data."""
    return latest_stock_market_data

@router.get("/volume-breakouts")
def get_volume_breakouts():
    """Returns unique stocks with 'Vol Shocker' volume surge badge."""
    breakouts = {}
    for category in ["gainers_1d", "losers_1d", "gainers_5d", "losers_5d"]:
        for item in latest_stock_market_data.get(category, []):
            if item.get("badge") == "Vol Shocker":
                breakouts[item["symbol"]] = item
    return list(breakouts.values())

@router.get("/sector-heatmap")
def get_sector_heatmap():
    """Returns live NSE sectoral indices."""
    return latest_stock_market_data.get("sectoral_heatmap", [])

@router.get("/fii-dii")
def get_fii_dii():
    """Returns cash market FII & DII flow."""
    return latest_stock_market_data.get("fii_dii", [])

@router.get("/historical/{symbol}")
def get_stock_historical(symbol: str):
    """Returns 5-day chart data for the given symbol."""
    nse = symbol
    if symbol in SYMBOL_CACHE:
        nse = SYMBOL_CACHE[symbol]["nse_symbol"]
    return get_historical_data(nse)
