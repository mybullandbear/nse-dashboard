import requests
import logging
import time

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
    'Accept': 'application/json',
}

_history_cache = {}
CACHE_EXPIRY_SECONDS = 600

def get_historical_data(nse_symbol: str):
    """
    Fetch historical close prices for a given NSE symbol from Yahoo Finance.
    Returns a list of dicts: [{"time": int, "price": float}]
    """
    if not nse_symbol:
        return []

    yahoo_symbol = nse_symbol.upper()
    if not yahoo_symbol.endswith('.NS'):
        yahoo_symbol = f"{yahoo_symbol}.NS"

    now = time.time()
    if yahoo_symbol in _history_cache:
        cached = _history_cache[yahoo_symbol]
        if now - cached["timestamp"] < CACHE_EXPIRY_SECONDS:
            logger.info(f"Serving cached historical data for {yahoo_symbol}")
            return cached["data"]

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_symbol}?range=5d&interval=15m"
    try:
        logger.info(f"Fetching historical data from Yahoo Finance for {yahoo_symbol}")
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.raise_for_status()
        data = res.json()

        chart_data = data.get('chart', {}).get('result', [])
        if not chart_data:
            return []

        result = chart_data[0]
        timestamps = result.get('timestamp', [])
        indicators = result.get('indicators', {}).get('quote', [{}])[0]
        closes = indicators.get('close', [])

        points = []
        for t, c in zip(timestamps, closes):
            if t is not None and c is not None:
                points.append({
                    "time": t,
                    "price": round(float(c), 2)
                })

        _history_cache[yahoo_symbol] = {
            "timestamp": now,
            "data": points
        }
        return points

    except Exception as e:
        logger.error(f"Error fetching historical data for {yahoo_symbol}: {e}")
        if yahoo_symbol in _history_cache:
            return _history_cache[yahoo_symbol]["data"]
        return []
