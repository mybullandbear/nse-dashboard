"""
Layer 4: Shared Output Snapshot API
Publishes precomputed versioned snapshots to all frontend consumers.
"""
from fastapi import APIRouter, Query
from app.state.market_state_store import market_state
from app.state.option_chain_cache import chain_coordinator
from app.intelligence.dependency_graph import intelligence_engine

router = APIRouter(prefix="/api/market", tags=["market_state"])

@router.get("/state/{symbol}")
async def get_market_state(symbol: str = "NIFTY", version: int = Query(0)):
    """
    Returns the canonical precomputed market state.
    Zero upstream calls are made if the current version matches the cached snapshot.
    """
    sym = symbol.upper()
    current_version = market_state._global_version

    # If client passed identical version and state has not changed, return 304-style flag
    if version > 0 and version == current_version:
        return {"status": "NOT_MODIFIED", "version": current_version}

    snapshot = market_state.get_full_snapshot(sym)
    return {
        "status": "OK",
        "data": snapshot
    }

@router.get("/radar")
async def get_multi_index_radar():
    """Returns the precomputed cross-index command radar table."""
    radar = market_state.get_confluence("RADAR")
    return radar or {"radar": []}

@router.get("/chain/{symbol}")
async def get_full_option_chain(symbol: str = "NIFTY"):
    """Returns the cached normalized option chain with single-flight guarantee."""
    sym = symbol.upper()
    chain = await chain_coordinator.get_or_fetch(sym)
    return chain.model_dump() if chain else {"strikes": {}}
