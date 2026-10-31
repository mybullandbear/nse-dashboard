"""
WebSocket Streaming Manager for Real-Time Terminal Telemetry
"""
import asyncio
import json
import logging
from typing import Set, Dict, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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
        disconnected = set()
        for ws in self.active_connections:
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                disconnected.add(ws)

        for ws in disconnected:
            self.disconnect(ws)


ws_manager = ConnectionManager()


@router.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                action = msg.get("action")
                if action == "subscribe":
                    symbol = msg.get("symbol", "NIFTY")
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
