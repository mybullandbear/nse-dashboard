"""
Main FastAPI Application Server
NSE Options Terminal & Visual Command Center
Centralized Market Intelligence Architecture
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
from app.publishing.snapshot_api import router as snapshot_router
from app.api.matrix_dashboard_api import router as matrix_dashboard_router
from app.api.strategy_workspace import router as strategy_workspace_router

from app.services.option_chain import parse_option_chain
from app.services.oi_analyzer import oi_analyzer
from app.services.signal_engine import signal_engine
from app.services.tracker_bot import tracker_bot
from app.services.shonya_bot import shonya_bot
from app.services.strategy_shadow import shadow_recorder
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
    Background worker that runs during market hours (09:15 - 15:40 IST).
    Enforces single-flight caching, rate limit protection, and updates all engines.
    """
    logger.info("Starting Central Market Intelligence background poller...")
    loop_count = 0
    while True:
        try:
            is_open = is_market_open()
            symbols = settings.TRACKED_SYMBOLS

            if is_open:
                for sym in symbols:
                    try:
                        raw_chain, source = await fetch_live_chain_data(sym)
                        if raw_chain:
                            parsed = parse_option_chain(raw_chain, sym)
                            if parsed:
                                source = parsed.source
                            if parsed and source not in {"STALE_CACHE", "MARKET_CLOSED", "SIMULATOR", "FROZEN"}:
                                parsed.source = source
                                oi_data = oi_analyzer.analyze(parsed, record=False)
                                decision = signal_engine.evaluate(parsed, oi_data)
                                oi_analyzer.record_snapshot(parsed, decision)
                                try:
                                    option_candle_service.record_chain_ticks(parsed)
                                except Exception as e_c:
                                    logger.debug(f"Option candle tick error: {e_c}")
                                try:
                                    await shonya_bot.evaluate_tick_for_paper_entry(sym, parsed)
                                except Exception as e_shonya_eval:
                                    logger.debug(f"ShonyaBot eval error for {sym}: {e_shonya_eval}")
                                try:
                                    shonya_bot.update_positions_tick(chain_map={sym: parsed})
                                except Exception as e_shonya:
                                    logger.debug(f"ShonyaBot tick error: {e_shonya}")
                            if parsed:
                                try:
                                    await asyncio.to_thread(shadow_recorder.observe, parsed)
                                except Exception:
                                    logger.exception("Forward strategy observation failed for %s", sym)
                    except Exception as e_sym:
                        logger.debug(f"Poller error for {sym}: {e_sym}")
                    await asyncio.sleep(1.5)  # Stagger queries to respect broker rate limits
            else:
                logger.debug("Market is closed. Preserving rate limits.")

            # Enforce 30-day retention cleanup every ~30 minutes
            loop_count += 1
            if loop_count % 300 == 0:
                try:
                    snapshot_storage.cleanup_old_data(days_to_keep=30)
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
    try:
        snapshot_storage.cleanup_old_data(days_to_keep=30)
    except Exception as e:
        logger.warning(f"Initial retention purge note: {e}")

    poller_task = asyncio.create_task(background_market_poller())
    yield
    logger.info("Shutting down application...")
    poller_task.cancel()
    await asyncio.gather(poller_task, return_exceptions=True)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="Institutional-grade NSE Options Terminal and Decision Support System",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Access Protection Middleware with Localhost Loopback exemption
@app.middleware("http")
async def gate_protection_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS":
        return await call_next(request)

    public_api = {"/api/access/login", "/api/access/check", "/api/access/logout",
                  "/api/webhook/tradingview"}
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        allowed = set(settings.ALLOWED_ORIGINS) | {str(request.base_url).rstrip("/")}
        if origin and origin not in allowed:
            return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
    if path.startswith("/api/") and path not in public_api:
        if not is_token_valid(get_token_from_request(request)):
            return JSONResponse(status_code=401, content={"detail": "Authentication required"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# Include All Feature Routers
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
app.include_router(matrix_dashboard_router)
app.include_router(strategy_workspace_router)
app.include_router(ws_router)
app.include_router(snapshot_router)

# Mount Static Assets & PWA
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
    return {"status": "online", "message": "Dashboard files loaded."}

@app.get("/dashboard")
async def serve_matrix_dashboard():
    dashboard_file = os.path.join(static_dir, "matrix_dashboard.html")
    if os.path.exists(dashboard_file):
        return FileResponse(
            dashboard_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return JSONResponse(status_code=404, content={"detail": "Matrix Dashboard not found"})

@app.get("/strategy")
async def serve_strategy_desk():
    return FileResponse(os.path.join(static_dir, "strategy_workspace.html"), headers={"Cache-Control":"no-store"})

@app.get("/architecture")
async def serve_architecture_graph():
    arch_file = os.path.join(static_dir, "architecture.html")
    if os.path.exists(arch_file):
        return FileResponse(
            arch_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return JSONResponse(status_code=404, content={"detail": "Architecture viewer not found"})

@app.get("/api/architecture/graph")
async def get_architecture_graph():
    # Check .ua/knowledge-graph.json
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    ua_path = os.path.join(root_dir, ".ua", "knowledge-graph.json")
    if not os.path.exists(ua_path):
        # Fallback to local project root
        ua_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), ".ua", "knowledge-graph.json")
    if os.path.exists(ua_path):
        return FileResponse(ua_path, media_type="application/json")
    return JSONResponse(status_code=404, content={"detail": "Knowledge graph not found. Run /understand first."})


@app.get("/manifest.json")
async def serve_manifest():
    p = os.path.join(static_dir, "manifest.json")
    return FileResponse(p, media_type="application/manifest+json") if os.path.exists(p) else {}

@app.get("/sw.js")
async def serve_sw():
    p = os.path.join(static_dir, "sw.js")
    return FileResponse(p, media_type="application/javascript") if os.path.exists(p) else {}

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
        "active_ws_clients": len(ws_manager.active_connections)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
