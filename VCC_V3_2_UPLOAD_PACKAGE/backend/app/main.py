"""
Main FastAPI Application Entry Point for NSE Options Terminal.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

import sqlalchemy
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.market import router as market_router
from app.api.websocket import router as ws_router, manager as ws_manager
from app.api.auth import router as auth_router
from app.api.smart_money import router as smart_money_router
from app.api.stocks import router as stocks_router, update_stock_market_data
from app.api.vcc import router as vcc_router
from app.config import get_settings
from app.services.nse_fetcher import nse
from app.api.market import get_indices, get_oi_spurts, refresh_fyers_live_data
from app.services.v3_background_poller import refresh_v3_market_data
from app.db import init_db, cleanup_old_data
from app.services.market_hours import is_market_open

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)
settings = get_settings()


async def fyers_live_polling_loop():
    """Live data polling task for Fyers API & terminal background updates.
    
    CRITICAL: Only persist DB snapshots during actual market hours (09:00-15:45 IST)
    to prevent stale mock data from polluting the intraday timeline graphs.
    Outside market hours, only refresh Fyers quotes for index tickers (no DB writes).
    """
    logger.info("Starting live background data polling loop...")
    while True:
        try:
            if is_market_open():
                # 1. Refresh live Fyers quotes
                await refresh_fyers_live_data()

                # 2. Refresh V3 intelligence & persist intraday DB snapshots for tracked symbols
                for symbol in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]:
                    try:
                        await refresh_v3_market_data(symbol)
                    except Exception as e_sym:
                        logger.warning(f"V3 background refresh error for {symbol}: {e_sym}")

                await asyncio.sleep(3.0)

            else:
                # Outside market hours: only refresh Fyers quotes for live index prices (no DB writes)
                await refresh_fyers_live_data()
                await asyncio.sleep(15.0)
        except Exception as e:
            logger.error(f"Error in live polling loop: {e}")
            await asyncio.sleep(5.0)


async def nse_slow_polling_loop():
    """Background poller (30s) for slow web-scraped NSE data during market hours."""
    logger.info("Starting background NSE web data polling loop...")
    while True:
        try:
            if is_market_open():
                await get_indices()
                await get_oi_spurts()
                await asyncio.sleep(30.0)
            else:
                # Outside market hours: pause web scraping & sleep for 60 seconds
                await asyncio.sleep(60.0)
        except Exception as e:
            logger.error(f"Error in background NSE polling: {e}")
            await asyncio.sleep(10.0)


async def stock_polling_loop():
    """Background poller (60s) for Moneycontrol stock gainers/losers & EMS opportunities."""
    logger.info("Starting background Stock Market Intelligence polling loop...")
    while True:
        try:
            # Always run initial sync or sync when market is open
            await asyncio.to_thread(update_stock_market_data)
            if is_market_open():
                await asyncio.sleep(60.0)
            else:
                await asyncio.sleep(300.0)
        except Exception as e:
            logger.error(f"Error in stock polling loop: {e}")
            await asyncio.sleep(30.0)


async def db_cleanup_loop():
    """Periodic database maintenance task running every 4 hours (market data <= 7 days, signals <= 30 days)."""
    logger.info("Starting background DB storage cleanup loop...")
    while True:
        try:
            cleanup_old_data(market_days_to_keep=7, signal_days_to_keep=30)
        except Exception as e:
            logger.error(f"Error in DB cleanup loop: {e}")
        await asyncio.sleep(4 * 3600)  # Every 4 hours


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup and shutdown events."""
    logger.info("Starting NSE Options Terminal API...")
    
    # Initialize Persistent Database & Storage Pruning (4-day max retention)
    init_db()

    # Start WebSocket broadcasting loop
    await ws_manager.start_broadcasting()
    
    # Start high-frequency live Fyers task, background slow NSE task, stock polling task, DB cleanup task, and Telegram interactive bot
    from app.services.telegram_bot_service import telegram_bot_service
    fyers_task = asyncio.create_task(fyers_live_polling_loop())
    nse_task = asyncio.create_task(nse_slow_polling_loop())
    stock_task = asyncio.create_task(stock_polling_loop())
    cleanup_task = asyncio.create_task(db_cleanup_loop())
    tg_bot_task = asyncio.create_task(telegram_bot_service.start_polling())
    
    yield
    
    logger.info("Shutting down NSE Options Terminal API...")
    fyers_task.cancel()
    nse_task.cancel()
    stock_task.cancel()
    cleanup_task.cancel()
    tg_bot_task.cancel()
    await nse.close()


app = FastAPI(
    title=settings.APP_NAME,
    description="Institutional-grade decision support system for intraday option sellers.",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(market_router)
app.include_router(vcc_router)
app.include_router(ws_router)
app.include_router(auth_router)
app.include_router(smart_money_router)
app.include_router(stocks_router)


# Mount Static Files for Bloomberg Terminal Web UI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def serve_dashboard():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "NSE Options Terminal API Running"}


@app.get("/health")
async def health_check():
    import sqlalchemy
    from app.providers.data_source_manager import data_source_manager
    from app.services.market_hours import is_market_open
    from app.db.database import SessionLocal
    
    db_ok = False
    try:
        db = SessionLocal()
        db.execute(sqlalchemy.text("SELECT 1"))
        db.close()
        db_ok = True
    except Exception:
        pass

    sys_health = data_source_manager.get_system_health()
    active_prov = sys_health.active_provider if hasattr(sys_health, "active_provider") else (sys_health.get("active_provider") if isinstance(sys_health, dict) else "unknown")
    health_dict = sys_health.model_dump() if hasattr(sys_health, "model_dump") else (sys_health if isinstance(sys_health, dict) else {})
    return {
        "status": "healthy" if db_ok else "degraded",
        "app": "NSE Alpha-Sell Options Terminal & Visual Command Center",
        "database_connected": db_ok,
        "market_session_open": is_market_open(),
        "active_provider": active_prov,
        "websocket_clients": len(ws_manager.active_connections),
        "system_health": health_dict
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
