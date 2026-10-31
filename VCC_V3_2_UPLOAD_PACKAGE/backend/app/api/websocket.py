"""
WebSocket API for real-time data streaming.

Broadcasts market data, option chain updates, alerts, and recommendations
to connected clients at configurable intervals.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.cache import cache

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections and broadcasting."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._broadcast_task: asyncio.Task = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, data: dict):
        """Broadcast data to all connected clients."""
        if not self.active_connections:
            return

        message = json.dumps(data, default=str)
        dead = set()
        
        for ws in self.active_connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        
        self.active_connections -= dead

    async def start_broadcasting(self):
        """Start the broadcast loop."""
        if self._broadcast_task and not self._broadcast_task.done():
            return
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())

    async def _broadcast_loop(self):
        """Continuously broadcast cached data to clients."""
        while True:
            try:
                if self.active_connections:
                    # Gather latest data from cache
                    data = {}
                    
                    indices = await cache.get("indices")
                    if indices:
                        data["indices"] = indices

                    for symbol in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]:
                        dashboard = await cache.get(f"dashboard:{symbol}")
                        if dashboard:
                            data[f"dashboard_{symbol.lower()}"] = dashboard


                    oi_spurts = await cache.get("oi_spurts")
                    if oi_spurts:
                        data["oi_spurts"] = oi_spurts

                    alerts = await cache.get("alerts")
                    if alerts:
                        data["alerts"] = alerts

                    if data:
                        data["type"] = "update"
                        data["timestamp"] = datetime.now().isoformat()
                        await self.broadcast(data)

                await asyncio.sleep(1)  # High-frequency broadcast every 1 second
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
                await asyncio.sleep(5)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint for real-time data."""
    await manager.connect(websocket)
    
    try:
        # Send initial data
        indices = await cache.get("indices")
        if indices:
            await websocket.send_json({"type": "initial", "data": indices})

        # Keep connection alive and handle client messages
        while True:
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                data = json.loads(msg)
                
                # Handle subscription changes
                if data.get("type") == "subscribe":
                    symbol = (data.get("symbol") or "NIFTY").upper()
                    dashboard = await cache.get(f"dashboard:{symbol}")
                    if not dashboard:
                        from app.api.vcc import get_vcc_dashboard
                        vcc_res = await get_vcc_dashboard(symbol)
                        dashboard = vcc_res.model_dump() if hasattr(vcc_res, "model_dump") else vcc_res

                    if dashboard:
                        await websocket.send_json({
                            "type": "dashboard",
                            "symbol": symbol,
                            "data": dashboard,
                        })

            except asyncio.TimeoutError:
                # Send heartbeat
                try:
                    await websocket.send_json({"type": "heartbeat", "timestamp": datetime.now().isoformat()})
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        manager.disconnect(websocket)
