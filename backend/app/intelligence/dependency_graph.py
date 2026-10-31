"""
Layer 3 Intelligence: Coordinated Dependency Graph
Orchestrates staged calculations without duplicate work.
"""
import time
import logging
from typing import Dict, Any, List
from app.market_data.instrument_state import IndexSymbol, NormalizedTick, OptionChainSnapshot
from app.state.market_state_store import market_state
from app.intelligence.metric_engine import metric_engine
from app.intelligence.confluence_engine import confluence_engine
from app.intelligence.shonya_engine import shonya_engine

logger = logging.getLogger(__name__)

class MarketIntelligenceEngine:
    def __init__(self):
        self._last_processed_version: Dict[str, int] = {}

    def process_chain_update(self, chain: OptionChainSnapshot):
        """Runs downstream calculations only when a new chain snapshot arrives."""
        symbol = chain.symbol
        
        # Step 1: Metric Engine (PCR, Walls, Corridor)
        metrics = metric_engine.compute_chain_metrics(chain)
        market_state.set_oi_analytics(symbol, metrics)

        # Step 2: Fetch current spot tick
        tick = market_state.get_tick(symbol)
        tick_data = {"pChange": tick.pchange if tick else chain.spot_pchange}

        # Step 3: Directional & Confluence Engine
        confluence_data = confluence_engine.evaluate_directional_bias(metrics, tick_data)
        market_state.set_confluence(symbol, {
            "symbol": symbol,
            "metrics": metrics,
            "confluence": confluence_data,
            "corridor": metrics.get("corridor", []),
            "timestamp": time.time()
        })
        market_state.set_directional(symbol, confluence_data)

        # Step 4: Shonya Decision Matrix
        shonya_decision = shonya_engine.evaluate_gates(confluence_data, symbol)
        market_state.update_shonya_state({
            "latest_decision": shonya_decision,
            "summary": shonya_engine.get_terminal_summary()
        })

    def process_index_ticks_batch(self, ticks: List[NormalizedTick]):
        """Processes batched ticks and updates cross-index radar."""
        for tick in ticks:
            market_state.update_tick(tick)

        all_indices = market_state.get_all_indices().get("indices", [])
        metrics_by_sym = {
            sym: market_state.get_oi_analytics(sym) or {}
            for sym in [IndexSymbol.NIFTY, IndexSymbol.BANKNIFTY, IndexSymbol.FINNIFTY, IndexSymbol.MIDCPNIFTY]
        }
        
        # Multi-Index Radar Table
        radar = confluence_engine.build_multi_index_radar(all_indices, metrics_by_sym)
        market_state.set_confluence("RADAR", {"radar": radar, "timestamp": time.time()})

intelligence_engine = MarketIntelligenceEngine()
