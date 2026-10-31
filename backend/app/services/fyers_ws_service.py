"""
Fyers Prime WebSocket v3 Streaming Engine
Zero-Latency Tick-by-Tick Market Telemetry via FyersDataSocket.
Feeds memory store and pushes to all connected browser clients instantly.
"""
import asyncio
import logging
import threading
import time
from typing import Optional, Dict, Any, List

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from fyers_apiv3.FyersWebsocket import data_ws
    HAS_FYERS_WS = True
except ImportError:
    data_ws = None
    HAS_FYERS_WS = False


class FyersWebSocketService:
    """
    Manages live tick streaming via Fyers WebSocket v3 (Fyers Prime).
    """

    def __init__(self):
        self.socket: Optional[Any] = None
        self.thread: Optional[threading.Thread] = None
        self.is_running: bool = False
        self.last_tick_time: float = 0.0
        self.subscribed_symbols: List[str] = [
            "NSE:NIFTY50-INDEX",
            "NSE:NIFTYBANK-INDEX",
            "NSE:FINNIFTY-INDEX",
            "NSE:MIDCPNIFTY-INDEX",
            "BSE:SENSEX-INDEX"
        ]
        self.latest_ticks: Dict[str, Dict[str, Any]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start(self, client_id: str, access_token: str, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Starts FyersDataSocket stream in a daemon background thread."""
        if not HAS_FYERS_WS:
            logger.warning("fyers_apiv3 WebSocket module not available.")
            return

        if not client_id or not access_token:
            logger.info("Fyers credentials missing. WebSocket stream deferred.")
            return

        if self.is_running and self.socket:
            logger.debug("FyersDataSocket already running.")
            return

        self._loop = loop

        # Fyers requires token in format: 'client_id:access_token' or 'access_token'
        clean_token = access_token.strip().strip('"').strip("'")
        if ":" in clean_token:
            clean_token = clean_token.split(":", 1)[1].strip()
        auth_token = f"{client_id}:{clean_token}"

        def on_message(message):
            try:
                self.last_tick_time = time.time()
                sym = message.get("symbol")
                if sym:
                    self.latest_ticks[sym] = message
                    # Push to FastAPI WS clients asynchronously
                    if self._loop and not self._loop.is_closed():
                        try:
                            from app.api.websocket import ws_manager
                            asyncio.run_coroutine_threadsafe(
                                ws_manager.broadcast({
                                    "type": "tick",
                                    "symbol": sym,
                                    "ltp": message.get("ltp"),
                                    "ch": message.get("ch"),
                                    "chp": message.get("chp"),
                                    "timestamp": time.strftime("%H:%M:%S")
                                }),
                                self._loop
                            )
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"Error handling Fyers WS tick: {e}")

        def on_error(message):
            logger.debug(f"Fyers WS Error: {message}")

        def on_close(message):
            logger.info(f"Fyers WS Closed: {message}")
            self.is_running = False

        def on_connect():
            logger.info("Fyers Prime WebSocket Connected! Subscribing to index symbols...")
            self.is_running = True
            try:
                self.socket.subscribe(symbols=self.subscribed_symbols, data_type="SymbolUpdate")
            except Exception as e:
                logger.error(f"Fyers WS subscription error: {e}")

        try:
            self.socket = data_ws.FyersDataSocket(
                access_token=auth_token,
                log_path="",
                litemode=False,
                reconnect=True,
                on_connect=on_connect,
                on_close=on_close,
                on_error=on_error,
                on_message=on_message,
                reconnect_retry=10
            )

            self.thread = threading.Thread(target=self.socket.connect, daemon=True, name="FyersPrimeWS")
            self.thread.start()
            self.is_running = True
            logger.info("Fyers Prime WebSocket thread started successfully.")
        except Exception as e:
            logger.warning(f"Could not initialize Fyers Prime WebSocket: {e}")

    def subscribe_symbols(self, symbols: List[str]):
        """Dynamically add symbols (e.g. ATM option strikes) to the live stream."""
        if self.socket and self.is_running:
            try:
                new_syms = [s for s in symbols if s not in self.subscribed_symbols]
                if new_syms:
                    self.socket.subscribe(symbols=new_syms, data_type="SymbolUpdate")
                    self.subscribed_symbols.extend(new_syms)
            except Exception as e:
                logger.debug(f"Error subscribing symbols to Fyers WS: {e}")

    def get_latest_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self.latest_ticks.get(symbol)

    def stop(self):
        if self.socket:
            try:
                self.socket.close_connection()
            except Exception:
                pass
            self.is_running = False


fyers_ws_service = FyersWebSocketService()
