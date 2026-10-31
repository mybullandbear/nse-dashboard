"""
Indian Standard Time (IST) & NSE Market Hours Utility
"""
from datetime import datetime, time, timezone, timedelta
from typing import Dict, Any

# Fixed IST Offset: UTC + 5 hours 30 minutes
IST = timezone(timedelta(hours=5, minutes=30))


def get_current_ist() -> datetime:
    """Returns the current datetime in IST timezone."""
    return datetime.now(IST)


def is_market_open(now_dt: datetime = None) -> bool:
    """
    Returns True if current time is within official NSE derivative market hours:
    Monday through Friday, 09:15:00 to 15:40:00 IST.
    """
    if now_dt is None:
        now_dt = get_current_ist()
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)

    # 0 = Monday, ..., 4 = Friday, 5 = Saturday, 6 = Sunday
    if now_dt.weekday() in (5, 6):
        return False

    current_time = now_dt.time()
    market_open = time(9, 15, 0)
    market_close = time(15, 40, 0)

    return market_open <= current_time <= market_close


def get_session_info(now_dt: datetime = None) -> Dict[str, Any]:
    """
    Returns detailed market session phase, human-readable labels, and execution flags.
    Updated for NSE 09:15 to 15:40 IST operating hours.
    """
    if now_dt is None:
        now_dt = get_current_ist()
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)

    t = now_dt.time()
    weekday = now_dt.weekday()

    if weekday in (5, 6):
        state = "WEEKEND CLOSED"
        is_live = False
    elif t < time(9, 0, 0):
        state = "OVERNIGHT CLOSED"
        is_live = False
    elif time(9, 0, 0) <= t < time(9, 15, 0):
        state = "PRE-MARKET"
        is_live = False
    elif time(9, 15, 0) <= t <= time(15, 40, 0):
        state = "LIVE MARKET"
        is_live = True
    else:
        state = "POST-MARKET CLOSED"
        is_live = False

    return {
        "state": state,
        "is_live": is_live,
        "current_time_ist": now_dt.strftime("%H:%M:%S"),
        "date_ist": now_dt.strftime("%Y-%m-%d"),
        "weekday": weekday
    }
