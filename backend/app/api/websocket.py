"""
WebSocket Streaming Manager for Real-Time Terminal Telemetry
"""
import asyncio
import json
import logging
from typing import Set, Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.api.access_gate import get_token_from_request, is_token_valid
from app.core.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages active WebSocket client connections and broadcasting."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self.client_symbols: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        self.client_symbols[websocket] = "NIFTY"
        logger.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.client_symbols:
            del self.client_symbols[websocket]
        logger.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    def set_symbol(self, websocket: WebSocket, symbol: str):
        self.client_symbols[websocket] = symbol.upper()

    async def broadcast(self, message: Dict[str, Any]):
        payload = json.dumps(message)
        async def send(ws):
            try:
                await asyncio.wait_for(ws.send_text(payload), timeout=1.0)
            except Exception:
                self.disconnect(ws)
                try:
                    await asyncio.wait_for(ws.close(code=1013), timeout=0.2)
                except Exception:
                    pass
        await asyncio.gather(*(send(ws) for ws in tuple(self.active_connections)))


ws_manager = ConnectionManager()


@router.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    settings = get_settings()
    origin = websocket.headers.get("origin")
    own_origin = ("https" if websocket.url.scheme == "wss" else "http") + "://" + websocket.headers.get("host", "")
    token = get_token_from_request(websocket)
    if (origin and origin not in set(settings.ALLOWED_ORIGINS) | {own_origin}) or not is_token_valid(token):
        await websocket.close(code=1008)
        return
    if len(ws_manager.active_connections) >= 100:
        await websocket.close(code=1013)
        return
    await ws_manager.connect(websocket)
    try:
        while True:
            if not is_token_valid(token):
                await websocket.close(code=1008)
                break
            data = await asyncio.wait_for(websocket.receive_text(), timeout=60)
            if len(data) > 4096:
                await websocket.close(code=1009)
                break
            try:
                msg = json.loads(data)
                action = msg.get("action")
                if action == "subscribe":
                    symbol = msg.get("symbol", "NIFTY")
                    if symbol not in settings.TRACKED_SYMBOLS:
                        continue
                    ws_manager.set_symbol(websocket, symbol)
                    await websocket.send_text(json.dumps({
                        "type": "subscribed",
                        "symbol": symbol.upper()
                    }))
                elif action == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except Exception as e:
                logger.debug(f"Invalid WS message format: {e}")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket connection exception: {e}")
        ws_manager.disconnect(websocket)
    finally:
        ws_manager.disconnect(websocket)
