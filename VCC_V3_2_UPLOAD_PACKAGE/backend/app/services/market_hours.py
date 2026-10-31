"""
Indian Stock Market Hours & Authoritative Session Engine Module.
Timezone: Asia/Kolkata (IST, UTC+05:30)

Authoritative Session Definitions:
- PRE_MARKET:    09:00:00 <= time < 09:15:00 IST
- LIVE_MARKET:   09:15:00 <= time < 15:15:00 IST
- POST_MARKET:   15:15:00 <= time < 15:40:00 IST
- MARKET_CLOSED: All other times, weekends (Sat/Sun), or NSE trading holidays

Window Definitions:
1. BUSINESS SESSION: 09:00:00 - 15:40:00 IST (PRE_MARKET + LIVE_MARKET + POST_MARKET)
2. DATA COLLECTION WINDOW: 09:00:00 - 15:40:00 IST
3. PROVIDER AVAILABILITY WINDOW: 09:00:00 - 15:40:00 IST
4. SIGNAL GENERATION WINDOW: 09:15:00 - 15:15:00 IST (LIVE_MARKET only)
5. AUDIT WINDOW: 15:15:00 - 15:40:00 IST (POST_MARKET analysis & audit batching)
"""
from datetime import datetime, timezone, timedelta, time
from enum import Enum
from typing import Dict, List, Any, Optional, Set
import logging

logger = logging.getLogger(__name__)

# Indian Standard Time (UTC+05:30)
IST = timezone(timedelta(hours=5, minutes=30))


class MarketSessionState(str, Enum):
    PRE_MARKET = "PRE_MARKET"
    LIVE_MARKET = "LIVE_MARKET"
    POST_MARKET = "POST_MARKET"
    MARKET_CLOSED = "MARKET_CLOSED"


# Official NSE Trading Holidays (YYYY-MM-DD format)
NSE_HOLIDAYS: Set[str] = {
    # 2025 Holidays
    "2025-01-26", "2025-02-26", "2025-03-14", "2025-03-31", "2025-04-10",
    "2025-04-14", "2025-04-18", "2025-05-01", "2025-08-15", "2025-08-27",
    "2025-10-02", "2025-10-21", "2025-10-22", "2025-11-05", "2025-12-25",
    # 2026 Holidays
    "2026-01-26", "2026-03-06", "2026-03-30", "2026-04-03", "2026-04-14",
    "2026-05-01", "2026-06-05", "2026-07-06", "2026-08-15", "2026-10-02",
    "2026-10-20", "2026-11-09", "2026-11-10", "2026-11-24", "2026-12-25"
}


def get_ist_now() -> datetime:
    """Get current datetime in Indian Standard Time (IST)."""
    return datetime.now(IST)


def is_nse_holiday(date_str: str) -> bool:
    """Check if a given date string (YYYY-MM-DD) is an NSE trading holiday."""
    return date_str in NSE_HOLIDAYS


def get_market_session_info(force_open: bool = False, now_dt: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Authoritative Market Session Engine for NSE Regular Derivatives.
    - PRE_MARKET: Mon-Fri 09:00:00 - 09:15:00 IST
    - LIVE_MARKET: Mon-Fri 09:15:00 - 15:15:00 IST
    - POST_MARKET: Mon-Fri 15:15:00 - 15:40:00 IST
    - MARKET_CLOSED: Outside hours, weekends, or holidays

    Exact boundaries:
    - 08:59:59 -> MARKET_CLOSED
    - 09:00:00 -> PRE_MARKET
    - 09:14:59 -> PRE_MARKET
    - 09:15:00 -> LIVE_MARKET
    - 15:14:59 -> LIVE_MARKET
    - 15:15:00 -> POST_MARKET
    - 15:39:59 -> POST_MARKET
    - 15:40:00 -> MARKET_CLOSED
    """
    if force_open:
        return {
            "session_state": MarketSessionState.LIVE_MARKET.value,
            "is_live": True,
            "signal_generation_allowed": True,
            "data_collection_allowed": True,
            "post_market_analysis_allowed": False,
            "status_text": "LIVE MARKET (FORCED)",
            "is_weekend": False,
            "is_holiday": False
        }

    now_ist = now_dt or datetime.now(IST)
    if now_ist.tzinfo is None:
        now_ist = now_ist.replace(tzinfo=IST)

    date_str = now_ist.strftime("%Y-%m-%d")

    # 1. Holiday Check
    if is_nse_holiday(date_str):
        return {
            "session_state": MarketSessionState.MARKET_CLOSED.value,
            "is_live": False,
            "signal_generation_allowed": False,
            "data_collection_allowed": False,
            "post_market_analysis_allowed": False,
            "status_text": f"MARKET CLOSED (NSE HOLIDAY: {date_str})",
            "is_weekend": False,
            "is_holiday": True
        }

    # 2. Weekend Check (5 = Sat, 6 = Sun)
    if now_ist.weekday() >= 5:
        return {
            "session_state": MarketSessionState.MARKET_CLOSED.value,
            "is_live": False,
            "signal_generation_allowed": False,
            "data_collection_allowed": False,
            "post_market_analysis_allowed": False,
            "status_text": "MARKET CLOSED (WEEKEND)",
            "is_weekend": True,
            "is_holiday": False
        }

    # 3. Intraday Window Time Check
    current_time = now_ist.time()
    t_pre_start = time(9, 0, 0)
    t_live_start = time(9, 15, 0)
    t_live_end = time(15, 15, 0)
    t_post_end = time(15, 40, 0)

    if t_pre_start <= current_time < t_live_start:
        return {
            "session_state": MarketSessionState.PRE_MARKET.value,
            "is_live": False,
            "signal_generation_allowed": False,
            "data_collection_allowed": True,
            "post_market_analysis_allowed": False,
            "status_text": "PRE-MARKET (09:00:00 - 09:15:00 IST)",
            "is_weekend": False,
            "is_holiday": False
        }
    elif t_live_start <= current_time < t_live_end:
        return {
            "session_state": MarketSessionState.LIVE_MARKET.value,
            "is_live": True,
            "signal_generation_allowed": True,
            "data_collection_allowed": True,
            "post_market_analysis_allowed": False,
            "status_text": "LIVE MARKET (09:15:00 - 15:15:00 IST)",
            "is_weekend": False,
            "is_holiday": False
        }
    elif t_live_end <= current_time < t_post_end:
        return {
            "session_state": MarketSessionState.POST_MARKET.value,
            "is_live": False,
            "signal_generation_allowed": False,
            "data_collection_allowed": True,
            "post_market_analysis_allowed": True,
            "status_text": "POST-MARKET (15:15:00 - 15:40:00 IST)",
            "is_weekend": False,
            "is_holiday": False
        }
    else:
        return {
            "session_state": MarketSessionState.MARKET_CLOSED.value,
            "is_live": False,
            "signal_generation_allowed": False,
            "data_collection_allowed": False,
            "post_market_analysis_allowed": False,
            "status_text": "MARKET CLOSED",
            "is_weekend": False,
            "is_holiday": False
        }


def is_market_open(force_open: bool = False, now_dt: Optional[datetime] = None) -> bool:
    """Check if current time in IST is within LIVE_MARKET trading hours (09:15:00 - 15:15:00 IST)."""
    info = get_market_session_info(force_open=force_open, now_dt=now_dt)
    return info["is_live"]


def is_signal_generation_allowed(force_open: bool = False, now_dt: Optional[datetime] = None) -> bool:
    """Check if signal generation is permitted (strictly LIVE_MARKET window)."""
    info = get_market_session_info(force_open=force_open, now_dt=now_dt)
    return info["signal_generation_allowed"]


def is_business_session(now_dt: Optional[datetime] = None) -> bool:
    """Check if current IST time falls within the overall business operating window (09:00:00 - 15:40:00 IST)."""
    info = get_market_session_info(now_dt=now_dt)
    return info["session_state"] in [
        MarketSessionState.PRE_MARKET.value,
        MarketSessionState.LIVE_MARKET.value,
        MarketSessionState.POST_MARKET.value
    ]


def is_data_collection_window(now_dt: Optional[datetime] = None) -> bool:
    """Check if market data collection is permitted (09:00:00 - 15:40:00 IST)."""
    info = get_market_session_info(now_dt=now_dt)
    return info["data_collection_allowed"]


def is_provider_available_window(now_dt: Optional[datetime] = None) -> bool:
    """Check if external providers are expected to be available (09:00:00 - 15:40:00 IST)."""
    info = get_market_session_info(now_dt=now_dt)
    return info["data_collection_allowed"]


def is_audit_window(now_dt: Optional[datetime] = None) -> bool:
    """Check if post-market audit window is active (15:15:00 - 15:40:00 IST)."""
    info = get_market_session_info(now_dt=now_dt)
    return info["post_market_analysis_allowed"]
