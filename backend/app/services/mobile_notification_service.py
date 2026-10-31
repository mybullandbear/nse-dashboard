"""
Shonya Bot Mobile Notification Service
======================================
Dispatches real-time, rich trade notifications directly to trader's mobile phone:
1. 📱 Telegram Bot Direct Chat (Bot Token & Chat ID)
2. 🔔 ntfy.sh Lockscreen Push Notifications (Android / iOS)

Zero latency: Dispatched asynchronously via daemon worker threads to ensure
instant, non-blocking execution of broker & paper trading loops.
"""

import os
import json
import logging
import threading
import urllib.request
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

DEFAULT_TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8392685097:AAFnCGdGMcyjOlMScfqKLS6um9kY2wO7arA")
DEFAULT_TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "562973750")
DEFAULT_NTFY_TOPIC = os.getenv("NTFY_TOPIC", "mybull_radar_alerts_2026")
DASHBOARD_URL = "http://137.23.42.11:8000"


class MobileNotificationService:
    def __init__(
        self,
        bot_token: str = DEFAULT_TELEGRAM_BOT_TOKEN,
        chat_id: str = DEFAULT_TELEGRAM_CHAT_ID,
        ntfy_topic: str = DEFAULT_NTFY_TOPIC
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.ntfy_topic = ntfy_topic

    def _async_send(self, target_fn, *args, **kwargs):
        """Runs notification delivery in an isolated background thread."""
        t = threading.Thread(target=target_fn, args=args, kwargs=kwargs, daemon=True)
        t.start()

    def _send_telegram(self, text: str) -> bool:
        if not self.bot_token or not self.chat_id:
            return False
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return bool(data.get("ok"))
        except Exception as e:
            logger.warning(f"Telegram alert delivery error: {e}")
            return False

    def _send_ntfy(self, title: str, message: str, priority: int = 4, tags: str = "bell") -> bool:
        if not self.ntfy_topic:
            return False
        try:
            url = f"https://ntfy.sh/{self.ntfy_topic}"
            payload = {
                "topic": self.ntfy_topic,
                "title": title,
                "message": message,
                "priority": priority,
                "tags": [t.strip() for t in tags.split(",") if t.strip()],
                "click": DASHBOARD_URL,
                "actions": [
                    {
                        "action": "view",
                        "label": "Open Live Terminal",
                        "url": DASHBOARD_URL
                    }
                ]
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f"ntfy.sh push alert delivery error: {e}")
            return False

    # -------------------------------------------------------------
    # 1. TRADE ENTRY NOTIFICATION
    # -------------------------------------------------------------
    def notify_trade_entry(self, trade: Dict[str, Any]):
        """Dispatches rich alert when a new Shonya Bot trade is entered."""
        def _dispatch():
            sym = trade.get("symbol", "INDEX")
            strike = int(float(trade.get("strike", 0)))
            opt_type = trade.get("option_type", "CE")
            entry_p = float(trade.get("entry_price", 0.0))
            sl = float(trade.get("stop_loss", 0.0))
            lots = trade.get("lots", 1)
            qty = trade.get("quantity", 50)
            mode = trade.get("mode", trade.get("execution_mode", "PAPER"))
            cis = float(trade.get("cis_score", 50.0))
            pcr = float(trade.get("pcr", 1.0))
            entry_time = trade.get("entry_time", datetime.now().strftime("%H:%M:%S"))

            icon = "🟢" if opt_type == "CE" else "🔴"
            action_desc = "CALL BUY" if opt_type == "CE" else "PUT BUY"

            tg_text = (
                f"🚀 *SHONYA BOT: NEW TRADE INITIATED*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *Index:* `{sym}`\n"
                f"🏷️ *Contract:* *{strike} {opt_type}* (1-ITM)\n"
                f"{icon} *Direction:* *{action_desc}* | Mode: `{mode}`\n"
                f"💵 *Entry LTP:* `₹{entry_p:,.2f}`\n"
                f"🛡️ *Initial SL:* `₹{sl:,.2f}` (-15% Risk Floor)\n"
                f"📦 *Position Size:* `{lots} Lot ({qty} Qty)`\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 *3-Parameter Confluence Signals:*\n"
                f"• Composite CIS Score: *{cis:.1f} / 100*\n"
                f"• Breakout Indicator: *{'LONG (Bullish)' if opt_type=='CE' else 'SHORT (Bearish)'}*\n"
                f"• Proximity MAPO: *{'Bullish Stack' if opt_type=='CE' else 'Bearish Stack'}*\n"
                f"• Option Chain PCR: *{pcr:.2f}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ *Time:* `{entry_time}` IST\n"
                f"👉 [Open Live Terminal]({DASHBOARD_URL})"
            )

            ntfy_title = f"{icon} ShonyaBot: {sym} {strike} {opt_type} Entry @ ₹{entry_p:.1f}"
            ntfy_body = f"{action_desc} | SL: ₹{sl:.1f} | CIS: {cis:.1f} | PCR: {pcr:.2f} | {lots} Lot"

            self._send_telegram(tg_text)
            self._send_ntfy(ntfy_title, ntfy_body, priority=4, tags="rocket,chart_with_upwards_trend")

        self._async_send(_dispatch)

    # -------------------------------------------------------------
    # 2. BREAKEVEN ARMOR NOTIFICATION
    # -------------------------------------------------------------
    def notify_breakeven_armor(self, trade: Dict[str, Any]):
        """Dispatches alert when trade hits +20% and SL is ratcheted to entry + 2%."""
        def _dispatch():
            sym = trade.get("symbol", "INDEX")
            strike = int(float(trade.get("strike", 0)))
            opt_type = trade.get("option_type", "CE")
            entry_p = float(trade.get("entry_price", 0.0))
            curr_p = float(trade.get("current_price", entry_p))
            new_sl = float(trade.get("stop_loss", entry_p * 1.02))
            pts = curr_p - entry_p
            pct = (pts / max(0.1, entry_p)) * 100.0

            tg_text = (
                f"🛡️ *SHONYA BOT: BREAKEVEN ARMOR LOCKED*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *Position:* `{sym} {strike} {opt_type}`\n"
                f"📈 *Unrealized Gain:* `+{pts:,.2f} pts (+{pct:.1f}%)`\n"
                f"🔒 *Action:* Stop-Loss Ratcheted to `₹{new_sl:,.2f}` (Entry + 2%)\n"
                f"✅ *Risk is now ZERO. Riding runner to targets!* 🚀\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👉 [Open Live Terminal]({DASHBOARD_URL})"
            )

            ntfy_title = f"🛡️ Armor Locked: {sym} {strike} {opt_type} (+{pct:.1f}%)"
            ntfy_body = f"SL moved to ₹{new_sl:.1f} (Entry + 2%). Trade is now 100% Risk-Free!"

            self._send_telegram(tg_text)
            self._send_ntfy(ntfy_title, ntfy_body, priority=3, tags="shield,white_check_mark")

        self._async_send(_dispatch)

    # -------------------------------------------------------------
    # 3. TRADE EXIT / SQUARE-OFF NOTIFICATION
    # -------------------------------------------------------------
    def notify_trade_exit(self, trade: Dict[str, Any]):
        """Dispatches alert when Shonya Bot closes an open position."""
        def _dispatch():
            sym = trade.get("symbol", "INDEX")
            strike = int(float(trade.get("strike", 0)))
            opt_type = trade.get("option_type", "CE")
            entry_p = float(trade.get("entry_price", 0.0))
            exit_p = float(trade.get("exit_price", trade.get("current_price", entry_p)))
            net_pnl = float(trade.get("net_pnl", 0.0))
            pts = exit_p - entry_p
            pct = (pts / max(0.1, entry_p)) * 100.0
            reason = trade.get("exit_reason", "MANUAL_EXIT")
            exit_time = trade.get("exit_time", datetime.now().strftime("%H:%M:%S"))

            is_win = net_pnl > 0
            badge = "🎯 TARGET HARVESTED" if is_win else "🛑 STOP EXECUTED"
            icon = "✅" if is_win else "❌"
            pnl_str = f"+₹{net_pnl:,.2f}" if is_win else f"-₹{abs(net_pnl):,.2f}"

            tg_text = (
                f"🏁 *SHONYA BOT: TRADE SQUARED OFF*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *Position:* `{sym} {strike} {opt_type}`\n"
                f"{icon} *Result:* *{badge}*\n"
                f"💵 *Entry:* `₹{entry_p:,.2f}` ➔ *Exit:* `₹{exit_p:,.2f}`\n"
                f"📊 *Points:* `{pts:+,.2f} pts ({pct:+,.1f}%)`\n"
                f"💰 *Net Realized P&L:* *`{pnl_str}`*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🚪 *Exit Trigger:* `{reason}`\n"
                f"⏰ *Exit Time:* `{exit_time}` IST\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👉 [Open Live Terminal]({DASHBOARD_URL})"
            )

            ntfy_title = f"{icon} Trade Closed: {sym} {strike} {opt_type} ({pnl_str})"
            ntfy_body = f"Exit @ ₹{exit_p:.1f} ({pts:+,.1f} pts) | {reason}"

            self._send_telegram(tg_text)
            self._send_ntfy(ntfy_title, ntfy_body, priority=4 if is_win else 3, tags="checkered_flag,moneybag" if is_win else "octagonal_sign")

        self._async_send(_dispatch)

    # -------------------------------------------------------------
    # 4. DAILY EOD PERFORMANCE SUMMARY
    # -------------------------------------------------------------
    def notify_daily_summary(self, summary_stats: Dict[str, Any]):
        """Dispatches daily 15:30 EOD recap with total P&L, win rate, and trade count."""
        def _dispatch():
            date_str = summary_stats.get("date", datetime.now().strftime("%Y-%m-%d"))
            tot_trades = summary_stats.get("total_trades", 0)
            wins = summary_stats.get("wins", 0)
            losses = summary_stats.get("losses", 0)
            net_pnl = float(summary_stats.get("net_pnl", 0.0))
            win_rate = (wins / max(1, tot_trades)) * 100.0

            pnl_icon = "💰" if net_pnl >= 0 else "🔻"
            pnl_str = f"+₹{net_pnl:,.2f}" if net_pnl >= 0 else f"-₹{abs(net_pnl):,.2f}"

            tg_text = (
                f"📋 *SHONYA BOT: DAILY SESSION RECAP*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 *Date:* `{date_str}`\n"
                f"{pnl_icon} *Net Day P&L:* *`{pnl_str}`*\n"
                f"🎯 *Total Trades:* `{tot_trades}`\n"
                f"🏆 *Win Rate:* *`{win_rate:.1f}%`* ({wins}W / {losses}L)\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚡ *Strategy:* 3-Parameter Institutional Matrix\n"
                f"🛡️ *Risk Management:* Zero-Guess Dynamic Exits\n"
                f"👉 [View Detailed Ledger]({DASHBOARD_URL})"
            )

            ntfy_title = f"{pnl_icon} ShonyaBot EOD Recap: {pnl_str} ({win_rate:.0f}% WR)"
            ntfy_body = f"Total: {tot_trades} trades ({wins}W / {losses}L) | Net P&L: {pnl_str}"

            self._send_telegram(tg_text)
            self._send_ntfy(ntfy_title, ntfy_body, priority=3, tags="bar_chart,calendar")

        self._async_send(_dispatch)


# Singleton Instance
mobile_alerts = MobileNotificationService()
