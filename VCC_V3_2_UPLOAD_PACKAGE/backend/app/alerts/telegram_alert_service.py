"""
Modular Telegram Alert Service for VCC V3.2.
Provides HTML alert formatting, duplicate alert protection, and non-blocking fail-safe network dispatching.
"""
import logging
import hashlib
from typing import Optional, Set
import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class TelegramAlertService:
    def __init__(self):
        self._sent_hashes: Set[str] = set()

    def _compute_hash(self, symbol: str, shift_text: str, trade_date: str) -> str:
        raw = f"{symbol.upper()}:{trade_date}:{shift_text.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def is_duplicate(self, symbol: str, shift_text: str, trade_date: str) -> bool:
        h = self._compute_hash(symbol, shift_text, trade_date)
        return h in self._sent_hashes

    def mark_sent(self, symbol: str, shift_text: str, trade_date: str):
        h = self._compute_hash(symbol, shift_text, trade_date)
        self._sent_hashes.add(h)

    def format_smart_money_message(
        self,
        symbol: str,
        time_str: str,
        shift_text: str,
        shift_type: str,
        spot_price: float
    ) -> str:
        emoji = "🚀" if shift_type == "BULL" else "🔴" if shift_type == "BEAR" else "⚡"
        return (
            f"<b>{emoji} SMART MONEY ALERT ({symbol.upper()})</b>\n\n"
            f"🕒 <b>Time:</b> {time_str} IST\n"
            f"🏛️ <b>Shift:</b> {shift_text}\n"
            f"📊 <b>Market Bias:</b> {shift_type}\n"
            f"🎯 <b>Spot Price:</b> ₹{spot_price:,.2f}"
        )

    async def send_alert(
        self,
        message: str,
        symbol: Optional[str] = None,
        shift_text: Optional[str] = None,
        trade_date: Optional[str] = None,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None
    ) -> bool:
        """
        Sends HTML formatted push alert.
        Returns True if sent, False if duplicate or failed.
        Guaranteed NEVER to raise an exception.
        """
        try:
            if symbol and shift_text and trade_date:
                if self.is_duplicate(symbol, shift_text, trade_date):
                    logger.debug(f"Suppressing duplicate Telegram alert for {symbol}: {shift_text}")
                    return False

            settings = get_settings()
            token = bot_token or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
            cid = chat_id or getattr(settings, "TELEGRAM_CHAT_ID", "")

            if not token or not cid:
                logger.debug("Telegram credentials not configured. Skipping alert dispatch.")
                if symbol and shift_text and trade_date:
                    self.mark_sent(symbol, shift_text, trade_date)
                return False

            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": cid,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }

            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"Successfully dispatched Telegram push alert for {symbol or 'SYSTEM'}")
                    if symbol and shift_text and trade_date:
                        self.mark_sent(symbol, shift_text, trade_date)
                    return True
                else:
                    logger.warning(f"Telegram API status {resp.status_code}: {resp.text}")
                    return False
        except Exception as e:
            logger.error(f"Telegram alert error (isolated failure): {e}")
            return False


telegram_alert_service = TelegramAlertService()
