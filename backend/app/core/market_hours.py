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
    
    now_dt = now_dt.astimezone(IST)
    from app.core.config import get_settings
    if now_dt.date().isoformat() in get_settings().EXCHANGE_HOLIDAYS:
        return False

    # 0 = Monday, ..., 4 = Friday, 5 = Saturday, 6 = Sunday
    if now_dt.weekday() in (5, 6):
        return False
    
    current_time = now_dt.time()
    market_open = time(9, 15, 0)
    market_close = time(15, 40, 0)
    
    return market_open <= current_time < market_close


def get_session_info(now_dt: datetime = None) -> Dict[str, Any]:
    """
    Returns detailed market session phase, human-readable labels, and execution flags.
    Updated for NSE 09:15 to 15:40 IST operating hours.
    """
    if now_dt is None:
        now_dt = get_current_ist()
    elif now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST)
        
    now_dt = now_dt.astimezone(IST)
    from app.core.config import get_settings
    settings = get_settings()
    t = now_dt.time()
    weekday = now_dt.weekday()
    
    if now_dt.date().isoformat() in settings.EXCHANGE_HOLIDAYS:
        state = "EXCHANGE HOLIDAY"
        is_live = False
    elif weekday in (5, 6):
        state = "WEEKEND CLOSED"
        is_live = False
    elif t < time(9, 0, 0):
        state = "OVERNIGHT CLOSED"
        is_live = False
    elif time(9, 0, 0) <= t < time(9, 15, 0):
        state = "PRE-MARKET"
        is_live = False
    elif time(9, 15, 0) <= t < time(15, 40, 0):
        state = "LIVE MARKET"
        is_live = True
    elif time(15, 40, 0) <= t <= time(16, 0, 0):
        state = "POST-MARKET"
        is_live = False
    else:
        state = "MARKET CLOSED"
        is_live = False
        
    return {
        "session_state": state,
        "normal_open": "09:15",
        "normal_close": "15:40",
        "calendar_status": "VERIFIED" if settings.HOLIDAY_CALENDAR_VERIFIED else "WEEKDAY_RULES_ONLY",
        "is_market_open": is_live,
        "current_time_ist": now_dt.strftime("%H:%M:%S"),
        "current_date_ist": now_dt.strftime("%Y-%m-%d"),
        "timestamp_iso": now_dt.isoformat(),
        "weekday": now_dt.strftime("%A")
    }
