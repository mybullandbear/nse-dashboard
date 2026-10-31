from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup, NavigableString
import logging
import re
import time
import random
import json
import os

logger = logging.getLogger(__name__)

# ── curl_cffi session — impersonates Chrome TLS fingerprint exactly ───────────
_SESSION = cffi_requests.Session(impersonate='chrome120')
_session_warmed = False

def _warm_session():
    """Visit Moneycontrol homepage once to pick up cookies."""
    global _session_warmed
    if _session_warmed:
        return
    try:
        logger.info("Warming session with Moneycontrol homepage...")
        _SESSION.get('https://www.moneycontrol.com/', timeout=15)
        time.sleep(random.uniform(0.8, 1.5))
        _session_warmed = True
        logger.info("Moneycontrol session warmed OK.")
    except Exception as e:
        logger.warning(f"Moneycontrol session warm-up failed: {e}")

def _cell_val(cols, idx):
    """Extract plain text from a td by index."""
    if idx >= len(cols):
        return ''
    p = cols[idx].find('p')
    raw = p.get_text() if p else cols[idx].get_text()
    return raw.strip().replace(',', '')

def fetch_table_data(url, limit=1000):
    """Fetch and parse gainer/loser table data from Moneycontrol."""
    _warm_session()
    try:
        response = _SESSION.get(
            url,
            headers={'Referer': 'https://www.moneycontrol.com/stocks/marketstats/'},
            timeout=20
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        table = None
        for t in soup.find_all('table'):
            text = t.get_text()
            if 'Stock Name' in text or 'Company Name' in text:
                table = t
                break

        if not table:
            logger.error(f"No data table found at {url}")
            return []

        rows = table.find_all('tr')
        data = []

        for row in rows[1:]:
            cols = row.find_all('td')
            if not cols or len(cols) < 3:
                continue

            try:
                name_tag = cols[0].find('a')
                name = ''
                href = ''
                if name_tag:
                    name = name_tag.get('title', '') or name_tag.get_text()
                    href = name_tag.get('href', '')
                if not name:
                    name = cols[0].get_text()
                name = re.sub(r'(Vol Shocker|52W High|52W Low|L\. Circuit|U\. Circuit)', '', name).strip()

                p_tag = cols[2].find('p')
                ltp = ''
                change = '0'
                pchange = '0'

                if p_tag:
                    for child in p_tag.children:
                        if isinstance(child, NavigableString):
                            ltp = str(child).strip().replace(',', '')
                            break

                    span = p_tag.find('span')
                    if span:
                        span_text = span.get_text(separator='', strip=True)
                        m = re.search(r'(-?[\d.]+)\s*\(\s*(-?[\d.]+)%\s*\)', span_text)
                        if m:
                            change = m.group(1)
                            pchange = m.group(2)
                        else:
                            nums = re.findall(r'-?[\d.]+', span_text)
                            change = nums[0] if nums else '0'
                            pchange = nums[1] if len(nums) > 1 else '0'

                high  = _cell_val(cols, 3)
                low   = _cell_val(cols, 4)
                open_ = _cell_val(cols, 5)
                vwap  = _cell_val(cols, 6)

                if not ltp:
                    ltp = vwap

                badge_btn = cols[0].find('button')
                badge = badge_btn.get_text().strip() if badge_btn else ''

                if not name:
                    continue

                data.append({
                    "symbol":  name,
                    "ltp":     ltp,
                    "change":  change,
                    "pChange": pchange,
                    "high":    high,
                    "low":     low,
                    "open":    open_,
                    "vwap":    vwap,
                    "badge":   badge,
                    "href":    href,
                })

                if len(data) >= limit:
                    break

            except Exception as e:
                logger.warning(f"Row parse error: {e}")
                continue

        logger.info(f"Fetched {len(data)} rows from {url}")
        return data

    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return []

def fetch_nextjs_stats(category: str):
    """Fallback scraper fetching Next.js page."""
    _warm_session()
    slug = 'top-gainers-nse' if category == 'top-gainers' else 'top-losers-nse'
    url = f"https://www.moneycontrol.com/stocks/market-stats/{slug}/?indexName=NIFTY%20500&id=7"
    try:
        logger.info(f"Fetching fallback Next.js page: {url}")
        response = _SESSION.get(
            url,
            headers={'Referer': 'https://www.moneycontrol.com/stocks/market-stats/'},
            timeout=20
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        next_data = soup.find('script', id='__NEXT_DATA__')
        if not next_data:
            logger.error("No __NEXT_DATA__ script found")
            return []
            
        js = json.loads(next_data.string)
        msData = js.get('props', {}).get('pageProps', {}).get('marketStatsData', {})
        overview = msData.get('marketStatsOverviewData', {})
        stock_list = overview.get('list', [])
        
        data = []
        for item in stock_list:
            symbol = item.get('stockName') or item.get('symbol')
            ltp = item.get('currentPrice') or '0'
            change = item.get('priceChange') or '0'
            pchange = item.get('currPerChange') or item.get('perChange') or '0'
            pchange = str(pchange).replace('%', '').strip()
            
            high = item.get('high') or '0'
            low = item.get('low') or '0'
            open_ = item.get('open') or '0'
            vwap = item.get('vwap') or '0'
            
            vol_multiplier = 1.0
            try:
                vol_multiplier = float(item.get('volMultiplier', 1.0))
            except ValueError:
                pass
            badge = ''
            if vol_multiplier > 1.5:
                badge = 'Vol Shocker'
                
            href = item.get('shareUrl') or ''
            if not href and item.get('slug'):
                href = f"https://www.moneycontrol.com/india/stockpricequote/{item['slug']}"
                
            data.append({
                "symbol": symbol,
                "ltp": ltp,
                "change": change,
                "pChange": pchange,
                "high": high,
                "low": low,
                "open": open_,
                "vwap": vwap,
                "badge": badge,
                "href": href
            })
            
        logger.info(f"Fallback Next.js scraper loaded {len(data)} stocks.")
        return data
    except Exception as e:
        logger.error(f"Error in Next.js fallback scraper for {category}: {e}")
        return []

def get_gainers_1d():
    res = fetch_table_data("https://www.moneycontrol.com/stocks/marketstats/nsegainer/index.php")
    if not res:
        res = fetch_nextjs_stats("top-gainers")
    return res

def get_losers_1d():
    res = fetch_table_data("https://www.moneycontrol.com/stocks/marketstats/nseloser/index.php")
    if not res:
        res = fetch_nextjs_stats("top-losers")
    return res

def get_gainers_5d():
    return fetch_table_data("https://www.moneycontrol.com/stocks/marketstats/nsegainer/weekly.php")

def get_losers_5d():
    return fetch_table_data("https://www.moneycontrol.com/stocks/marketstats/nseloser/weekly.php")

def get_fii_dii_data():
    """Scrapes FII & DII cash market gross and net values."""
    _warm_session()
    url = "https://www.moneycontrol.com/markets/fii-dii-data/cash/"
    try:
        response = _SESSION.get(
            url,
            headers={'Referer': 'https://www.moneycontrol.com/markets/fii-dii-data/'},
            timeout=15
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        next_script = soup.find('script', id='__NEXT_DATA__')
        if next_script:
            data = json.loads(next_script.string)
            fii_dii_data = data.get('props', {}).get('pageProps', {}).get('FiiDiiData', {}).get('fiiDiiData', [])
            if fii_dii_data:
                return fii_dii_data
        return []
    except Exception as e:
        logger.error(f"Error scraping FII/DII data: {e}")
        return []

_SECTORAL_INDEX_NAMES = {
    'NIFTY BANK', 'NIFTY IT', 'NIFTY PHARMA', 'NIFTY AUTO', 'NIFTY METAL',
    'NIFTY REALTY', 'NIFTY ENERGY', 'NIFTY FMCG', 'NIFTY PSE',
    'NIFTY MEDIA', 'NIFTY PRIVATE BANK', 'NIFTY PSU BANK',
    'NIFTY FINANCIAL SERVICES', 'NIFTY CONSUMER DURABLES',
    'NIFTY OIL & GAS', 'NIFTY HEALTHCARE INDEX',
    'NIFTY COMMODITIES', 'NIFTY INFRASTRUCTURE',
    'NIFTY INDIA DIGITAL', 'NIFTY INDIA DEFENCE',
    'NIFTY FINANCIAL SERVICES 25/50', 'NIFTY MIDSMALL HEALTHCARE',
    'NIFTY MIDSMALL FINANCIAL SERVICES', 'NIFTY MIDSMALL IT & TELECOM',
    'NIFTY 50', 'NIFTY NEXT 50', 'NIFTY MIDCAP 50', 'NIFTY MIDCAP 100',
    'NIFTY SMLCAP 100', 'NIFTY 500', 'INDIA VIX',
}

def get_market_overview_data():
    """Scrapes India VIX and Nifty 50 overview."""
    result = {"india_vix": None, "nifty": None}
    try:
        indices = get_nse_sectoral_indices()
        for idx in indices:
            name = idx.get('name', '').upper()
            if name == 'NIFTY 50':
                result['nifty'] = {
                    'value': str(idx.get('lastPrice', 0)),
                    'change': str(idx.get('change', 0)),
                    'pChange': str(idx.get('pChange', 0)),
                    'open': str(idx.get('open', 0)),
                    'high': str(idx.get('high', 0)),
                    'low': str(idx.get('low', 0)),
                    'previousClose': str(idx.get('previousClose', 0))
                }
            elif name == 'INDIA VIX':
                result['india_vix'] = {
                    'value': str(idx.get('lastPrice', 0)),
                    'change': str(idx.get('change', 0)),
                    'pChange': str(idx.get('pChange', 0)),
                    'open': str(idx.get('open', 0)),
                    'high': str(idx.get('high', 0)),
                    'low': str(idx.get('low', 0)),
                }
    except Exception as e:
        logger.error(f"Error getting market overview from NSE: {e}")
    return result

_NSE_SESSION = cffi_requests.Session(impersonate='chrome120')
_nse_session_warmed = False

_NSE_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Referer': 'https://www.nseindia.com/market-data/live-market-indices',
    'X-Requested-With': 'XMLHttpRequest',
    'Connection': 'keep-alive',
}

def _warm_nse_session():
    global _nse_session_warmed
    if _nse_session_warmed:
        return
    try:
        logger.info("Warming NSE session...")
        _NSE_SESSION.get('https://www.nseindia.com/', headers=_NSE_HEADERS, timeout=15)
        time.sleep(random.uniform(1.0, 2.0))
        _nse_session_warmed = True
        logger.info("NSE session warmed OK.")
    except Exception as e:
        logger.warning(f"NSE session warm-up failed: {e}")

def get_nse_sectoral_indices():
    """Fetches live sectoral index data from NSE India."""
    _warm_nse_session()
    global _nse_session_warmed
    api_url = 'https://www.nseindia.com/api/allIndices'

    for attempt in range(2):
        try:
            resp = _NSE_SESSION.get(api_url, headers=_NSE_HEADERS, timeout=15)
            if resp.status_code in (401, 403):
                _nse_session_warmed = False
                _warm_nse_session()
                continue
            resp.raise_for_status()
            data = resp.json()
            all_indices = data.get('data', [])
            if not all_indices:
                return []

            sectoral = []
            broad = []
            for idx in all_indices:
                name = idx.get('index', idx.get('indexSymbol', ''))
                if not name:
                    continue
                is_sectoral = name in _SECTORAL_INDEX_NAMES
                is_broad = name in {'NIFTY 50', 'NIFTY NEXT 50', 'NIFTY MIDCAP 50', 'NIFTY MIDCAP 100', 'NIFTY SMLCAP 100', 'NIFTY 500', 'INDIA VIX'}
                if not is_sectoral and not is_broad:
                    continue
                entry = {
                    'name': name,
                    'lastPrice': idx.get('last', 0),
                    'change': round(float(idx.get('variation', 0)), 2),
                    'pChange': round(float(idx.get('percentChange', 0)), 2),
                    'open': idx.get('open', 0),
                    'high': idx.get('high', 0),
                    'low': idx.get('low', 0),
                    'previousClose': idx.get('previousClose', 0),
                    'advances': idx.get('advances', 0),
                    'declines': idx.get('declines', 0),
                    'unchanged': idx.get('unchanged', 0),
                    'category': 'broad' if is_broad else 'sectoral',
                }
                if is_broad:
                    broad.append(entry)
                else:
                    sectoral.append(entry)
            sectoral.sort(key=lambda x: abs(x['pChange']), reverse=True)
            broad.sort(key=lambda x: abs(x['pChange']), reverse=True)
            return sectoral + broad
        except Exception as e:
            logger.error(f"Error fetching NSE sectoral indices: {e}")
            if attempt == 0:
                _nse_session_warmed = False
                _warm_nse_session()
    return []
