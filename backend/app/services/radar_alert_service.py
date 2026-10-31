"""
Radar Mobile Push Notification Service via ntfy.sh
Sends instant, free mobile push notifications when Multi-Index Command Radar directives change.
No Telegram required. Direct to Android / iOS lock-screen.
"""
import urllib.request
import json
import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Default public topic - user can subscribe on phone with this exact topic name
DEFAULT_NTFY_TOPIC = "mybull_radar_alerts_2026"
DASHBOARD_URL = "http://137.23.42.11:8000"

class RadarAlertService:
    def __init__(self, topic: str = DEFAULT_NTFY_TOPIC):
        self.topic = topic
        self.last_directives: Dict[str, Optional[str]] = {
            "NIFTY": None,
            "BANKNIFTY": None,
            "FINNIFTY": None,
            "MIDCPNIFTY": None
        }
        self.last_alert_time: Dict[str, float] = {
            "NIFTY": 0.0,
            "BANKNIFTY": 0.0,
            "FINNIFTY": 0.0,
            "MIDCPNIFTY": 0.0
        }
        self.cooldown_seconds = 45.0  # Prevent spam if hovering near threshold

    def send_push_notification(self, title: str, message: str, priority: str = "high", tags: str = "bell", click_url: str = DASHBOARD_URL) -> bool:
        """Sends a JSON POST to ntfy.sh with rich metadata (emojis, actions, click url)."""
        try:
            priority_map = {
                "min": 1,
                "low": 2,
                "default": 3,
                "high": 4,
                "urgent": 5,
                "max": 5
            }
            p_val = priority_map.get(priority.lower(), 4)
            tag_list = [t.strip() for t in tags.split(",") if t.strip()] if isinstance(tags, str) else list(tags)

            payload_dict = {
                "topic": self.topic,
                "title": title,
                "message": message,
                "priority": p_val,
                "tags": tag_list,
                "click": click_url,
                "actions": [
                    {
                        "action": "view",
                        "label": "Open Terminal",
                        "url": click_url
                    }
                ]
            }

            req_data = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                "https://ntfy.sh",
                data=req_data,
                headers={"Content-Type": "application/json; charset=utf-8"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    logger.info(f"Mobile push alert sent successfully to topic [{self.topic}]: {title}")
                    return True
                else:
                    logger.warning(f"ntfy.sh returned status {resp.status}")
                    return False
        except Exception as e:
            logger.error(f"Error sending mobile push alert to ntfy.sh: {e}")
            return False

    def check_and_notify(self, indices_data: list) -> None:
        """
        Evaluates current index directives against previous state.
        Fires specific, detailed push notification when directive changes.
        """
        now = time.time()
        for idx in indices_data:
            sym = idx.get("symbol")
            if not sym or sym not in self.last_directives:
                continue

            current_dir = idx.get("action", "STANDBY")
            prev_dir = self.last_directives.get(sym)

            # Initialize state on startup without blasting alerts
            if prev_dir is None:
                self.last_directives[sym] = current_dir
                continue

            # Check if directive changed
            if current_dir != prev_dir:
                # Check cooldown
                if now - self.last_alert_time.get(sym, 0.0) < self.cooldown_seconds:
                    continue

                self.last_directives[sym] = current_dir
                self.last_alert_time[sym] = now

                # Compile rich detailed message
                spot = idx.get("spot_price", 0.0)
                pchange = idx.get("spot_pchange", 0.0)
                pchange_str = f"+{pchange:.2f}%" if pchange > 0 else f"{pchange:.2f}%"
                conf = idx.get("confluence_score", 50.0)
                pcr = idx.get("pcr", 1.0)
                regime = idx.get("market_regime", "RANGE-BOUND")
                tot_bias = idx.get("tot_oi_bias", "BALANCED")
                tot_diff = idx.get("net_oi_diff_lakhs", 0.0)
                oi_bias = idx.get("oi_bias", "BALANCED")
                net_flow_k = idx.get("net_oi_chg_k", 0.0)
                sup = idx.get("key_support", 0)
                res = idx.get("key_resistance", 0)
                max_pain = idx.get("max_pain", 0)
                alpha = idx.get("alphatrend", "NEUTRAL")
                trend = idx.get("trend_direction", "SIDEWAYS")
                hull = idx.get("hull_state", "NEUTRAL")

                arrow_alpha = "▲" if alpha == "BULLISH" else ("▼" if alpha == "BEARISH" else "►")
                arrow_trend = "▲" if trend == "UP" else ("▼" if trend == "DOWN" else "►")
                arrow_hull = "▲" if hull == "BULLISH" else ("▼" if hull == "BEARISH" else "►")

                if current_dir == "BUY_CALL":
                    title = f"🚀 {sym}: BUY CE DIRECTIVE (BREAKOUT)"
                    priority = "urgent"
                    tags = "rocket,chart_with_upwards_trend,green_circle"
                    action_summary = "Bullish momentum breakout confirmed by institutional flow."
                elif current_dir == "BUY_PUT":
                    title = f"💥 {sym}: BUY PE DIRECTIVE (BREAKDOWN)"
                    priority = "urgent"
                    tags = "warning,chart_with_downwards_trend,red_circle"
                    action_summary = "Bearish breakdown confirmed by institutional call writing."
                else:
                    title = f"⚪ {sym}: DIRECTIVE CHANGED TO STANDBY"
                    priority = "default"
                    tags = "hourglass,yellow_circle"
                    action_summary = "Momentum consolidated. Move to cash / protect profits."

                message = (
                    f"🎯 DIRECTIVE: {current_dir.replace('_', ' ')} (from {prev_dir.replace('_', ' ')})\n"
                    f"💰 Spot Price: {spot:,.1f} ({pchange_str})\n"
                    f"🧠 Confluence: {conf:.1f}/100 [{regime}]\n"
                    f"📈 PCR: {pcr:.2f}\n"
                    f"🧱 Total OI: {tot_bias.replace('_', ' ')} ({tot_diff}L)\n"
                    f"⚡ Flow (Intraday): {oi_bias.replace('_', ' ')} ({net_flow_k:+.1f}k)\n"
                    f"🛡️ Key Walls: S: {sup:,.0f} | R: {res:,.0f} | Pain: {max_pain:,.0f}\n"
                    f"🏹 Technicals: Alpha {alpha} {arrow_alpha} | Trend {trend} {arrow_trend} | Hull {hull} {arrow_hull}\n"
                    f"💡 Note: {action_summary}\n"
                    f"🕒 Time: {time.strftime('%H:%M:%S IST')}"
                )

                self.send_push_notification(title=title, message=message, priority=priority, tags=tags)

    def send_test_alert(self) -> bool:
        """Sends an immediate verification alert to confirm phone reception."""
        title = "🔔 RADAR MOBILE ALERT: VERIFICATION TEST"
        message = (
            "✅ SUCCESS: Mobile push notification pipeline is active!\n\n"
            "Whenever NIFTY, BANKNIFTY, FINNIFTY, or MIDCPNIFTY changes Directive (BUY CE, BUY PE, or STANDBY), "
            "your phone will immediately ring with full institutional metrics.\n\n"
            "👉 Tap this notification to open your live dashboard."
        )
        return self.send_push_notification(
            title=title,
            message=message,
            priority="urgent",
            tags="white_check_mark,bell,iphone",
            click_url=DASHBOARD_URL
        )

radar_alert_service = RadarAlertService()
