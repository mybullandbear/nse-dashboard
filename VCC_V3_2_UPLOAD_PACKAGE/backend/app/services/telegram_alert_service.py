"""
Telegram Push Notification Dispatcher
Sends real-time institutional Smart Money alerts directly to Telegram subscribers.
"""
import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

async def send_telegram_alert(message: str, bot_token: str = None, chat_id: str = None) -> bool:
    """Send an HTML-formatted alert message to a Telegram chat."""
    settings = get_settings()
    token = bot_token or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    cid = chat_id or getattr(settings, "TELEGRAM_CHAT_ID", "")

    if not token or not cid:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                logger.info("Successfully dispatched Telegram push alert")
                return True
            else:
                logger.warning(f"Telegram API responded with status {resp.status_code}: {resp.text}")
                return False
    except Exception as e:
        logger.error(f"Error sending Telegram alert: {e}")
        return False
