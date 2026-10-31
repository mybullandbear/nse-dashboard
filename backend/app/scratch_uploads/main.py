"""
Main FastAPI Application Entry Point
NSE Options Terminal & Visual Command Center V4
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import get_settings
from app.core.market_hours import is_market_open, get_session_info
from app.services.fyers_service import fyers_service
from app.api.access_gate import router as access_gate_router, get_token_from_request, is_token_valid
from app.api.auth import router as auth_router
from app.api.market import router as market_router, fetch_live_chain_data
from app.api.oi_analytics import router as oi_router
from app.api.signals import router as signals_router
from app.api.smart_oi import router as smart_oi_router
from app.api.buildup_lab import router as buildup_lab_router
from app.api.price_vs_oi import router as price_vs_oi_router
from app.api.tracker_api import router as tracker_router
from app.api.option_chart_api import router as option_chart_router
from app.api.option_confluence_api import router as confluence_router
from app.api.tradingview_webhook import router as tv_router
from app.api.shonya_api import router as shonya_router
from app.api.websocket import router as ws_router, ws_manager
from app.services.option_chain import parse_option_chain
from app.services.oi_analyzer import oi_analyzer
from app.services.signal_engine import signal_engine
from app.services.tracker_bot import tracker_bot
from app.services.shonya_bot import shonya_bot
from app.services.option_candle_service import option_candle_service
from app.db.storage import snapshot_storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("terminal_main")
settings = get_settings()


async def background_market_poller():
    """
    Background worker that fetches live data STRICTLY during market hours (09:15 - 15:30 IST).
    Outside market hours, external API requests are halted to conserve rate limits and network.
    Enforces a 5-day retention policy periodically.
    """
    logger.info("Starting background market polling loop (Market-Hours-Only mode)...")
    loop_count = 0
    while True:
        try:
            is_open = is_market_open()
            symbols = settings.TRACKED_SYMBOLS

            # ONLY fetch live data during official market hours
            if is_open:
                for sym in symbols:
                    try:
                        raw_chain, source = await fetch_live_chain_data(sym)
                        if raw_chain:
                            parsed = parse_option_chain(raw_chain, sym)
                            if parsed:
                                oi_analyzer.record_snapshot(parsed)
                                try:
                                    option_candle_service.record_chain_ticks(parsed)
                                except Exception as e_c:
                                    logger.debug(f"Option candle tick error: {e_c}")
                                try:
                                    oi_data = oi_analyzer.analyze(parsed)
                                    sig = signal_engine.evaluate(parsed, oi_data)
                                    from app.services.smart_money import smart_money_service
                                    smart_money_service.compute(parsed)
                                    await tracker_bot.process_tick(sym, parsed, sig)
                                except Exception as e_bot:
                                    logger.debug(f"TrackerBot tick error for {sym}: {e_bot}")
                                try:
                                    await shonya_bot.evaluate_tick_for_paper_entry(sym, parsed)
                                except Exception as e_shonya_eval:
                                    logger.debug(f"ShonyaBot eval error for {sym}: {e_shonya_eval}")
                                try:
                                    shonya_bot.update_positions_tick(chain_map={sym: parsed})
                                except Exception as e_shonya:
                                    logger.debug(f"ShonyaBot tick error: {e_shonya}")
                    except Exception as e_sym:
                        logger.debug(f"Poller error for {sym}: {e_sym}")
                    await asyncio.sleep(1.2)  # Stagger queries so Fyers rate limits are never exceeded

                # Periodically evaluate Multi-Index Radar for mobile push alerts
                try:
                    from app.api.market import get_multi_index_radar
                    await get_multi_index_radar()
                except Exception as e_rad:
                    logger.debug(f"Radar alert poller error: {e_rad}")
            else:
                logger.debug("Market is closed. Skipping live option chain queries.")

            # Enforce 5-day retention cleanup every ~30 minutes
            loop_count += 1
            if loop_count % 300 == 0:
                try:
                    snapshot_storage.cleanup_old_data(days_to_keep=5)
                except Exception as e_clean:
                    logger.debug(f"Retention cleanup error: {e_clean}")

            # Broadcast heartbeat to WebSocket clients
            if ws_manager.active_connections:
                try:
                    session = get_session_info()
                    await ws_manager.broadcast({
                        "type": "heartbeat",
                        "session": session,
                        "fyers_active": fyers_service.is_configured()
                    })
                except Exception as e_bc:
                    logger.debug(f"Broadcast error: {e_bc}")

            sleep_time = settings.POLL_INTERVAL_LIVE if is_open else settings.POLL_INTERVAL_OFF_MARKET
            await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in background market poller: {e}")
            await asyncio.sleep(5.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Initializing {settings.APP_NAME} v{settings.VERSION}...")
    # Enforce 5-day retention policy on startup
    try:
        snapshot_storage.cleanup_old_data(days_to_keep=5)
    except Exception as e:
        logger.warning(f"Initial retention purge failed: {e}")

    poller_task = asyncio.create_task(background_market_poller())
    yield
    logger.info("Shutting down application...")
    poller_task.cancel()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Institutional-grade NSE Options Terminal and Decision Support System",
    lifespan=lifespan
)

# Enable CORS for local & remote access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Terminal Password Protection Middleware
@app.middleware("http")
async def gate_protection_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)

    # Whitelist public resources (auth endpoints, assets, health check, root page, webhooks)
    is_public = (
        path == "/" or
        path == "/health" or
        path == "/api/market/radar_push_test" or
        path.startswith("/api/access/") or
        path.startswith("/api/webhook/") or
        path.startswith("/api/fyers/callback") or
        path.startswith("/static/") or
        path.startswith("/docs") or
        path.startswith("/openapi.json")
    )

    if not is_public and path.startswith("/api/"):
        token = get_token_from_request(request)
        if not is_token_valid(token):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized: Access key required to access institutional terminal data."}
            )

    return await call_next(request)


# Include Routers
app.include_router(access_gate_router)
app.include_router(auth_router)
app.include_router(market_router)
app.include_router(oi_router)
app.include_router(signals_router)
app.include_router(smart_oi_router)
app.include_router(buildup_lab_router)
app.include_router(price_vs_oi_router)
app.include_router(tracker_router)
app.include_router(option_chart_router)
app.include_router(confluence_router)
app.include_router(tv_router)
app.include_router(shonya_router)
app.include_router(ws_router)

# Mount Static Assets & Frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def serve_dashboard():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(
            index_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {
        "status": "online",
        "app": settings.APP_NAME,
        "version": settings.VERSION,
        "message": "API running. Dashboard static files not found."
    }


@app.get("/health")
async def health_check():
    session = get_session_info()
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.VERSION,
        "market_session": session.get("session_state"),
        "is_market_open": session.get("is_market_open"),
        "current_time_ist": session.get("current_time_ist"),
        "fyers_configured": fyers_service.is_configured(),
        "fyers_client_id": fyers_service.client_id or "",
        "active_ws_clients": len(ws_manager.active_connections)
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
