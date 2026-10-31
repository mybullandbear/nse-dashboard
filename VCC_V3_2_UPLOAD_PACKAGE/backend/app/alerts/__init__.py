"""
Alerts Subsystem for VCC V3.2.
Provides async alert dispatching (Telegram, Push) with duplicate suppression and fail-safe network isolation.
"""
from app.alerts.telegram_alert_service import TelegramAlertService, telegram_alert_service

__all__ = ["TelegramAlertService", "telegram_alert_service"]
