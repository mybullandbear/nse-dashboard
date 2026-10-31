"""
V3 Native Background Poller Processor.
Executes Data Provider -> Domain Snapshot -> Analytics Pipeline -> Confluence Engine -> Signal Engine -> Smart Money V3 -> Audit Service -> Persistence Repositories.
Zero legacy imports. Zero reliance on app.api.market or legacy engines.
"""
import logging
from datetime import datetime

from app.providers.data_source_manager import data_source_manager
from app.analytics.pipeline import analytics_pipeline
from app.intelligence.confluence_engine import confluence_engine
from app.signals.signal_engine import signal_engine
from app.smart_money import smart_money_v3_service
from app.audit.audit_service import audit_service
from app.repositories import market_repository
from app.services.market_hours import IST

logger = logging.getLogger(__name__)


async def refresh_v3_market_data(symbol: str):
    """
    Executes V3 background intelligence pipeline for a given index symbol.
    Persists throttled DB snapshots and immutable audit records.
    """
    sym = symbol.upper()
    try:
        snapshot = await data_source_manager.get_market_snapshot(sym)

        # Raw Option Chain Historical Capture (Phase 9B-0: REAL DATA ONLY)
        from app.repositories.raw_option_chain_repository import raw_option_chain_repository
        raw_option_chain_repository.save_snapshot_raw_chain(snapshot)

        pipeline_res = analytics_pipeline.run_pipeline(snapshot)

        conf_res = confluence_engine.compute_confluence(
            positioning_score=pipeline_res["positioning"]["positioning_score"],
            price_conf_score=pipeline_res["price_confirmation"]["score"],
            wall_interaction_score=pipeline_res["price_confirmation"]["wall_interaction_score"],
            straddle_decay_pct=0.0,
            breakout_status=pipeline_res["price_confirmation"]["breakout_status"],
            data_quality=snapshot.quality,
            data_age_sec=max(snapshot.metadata.spot_data_age_sec, snapshot.metadata.option_data_age_sec)
        )

        decision = signal_engine.decide_signal(
            snapshot,
            conf_res,
            pipeline_res["price_confirmation"]["breakout_status"]
        )

        # 1. Process & Persist Smart Money
        smart_money_v3_service.process_and_persist(sym, snapshot)

        # 2. Record Immutable Signal Audit Snapshot
        audit_service.record_signal_snapshot(
            snapshot=snapshot,
            decision=decision,
            positioning_score=pipeline_res["positioning"]["positioning_score"],
            price_conf_score=pipeline_res["price_confirmation"]["score"],
            net_flow_lakhs=pipeline_res["flow"]["net_flow_lakhs"],
            pcr=pipeline_res["pcr"],
            support_wall=pipeline_res["positioning"]["support_wall"],
            resistance_wall=pipeline_res["positioning"]["resistance_wall"],
            breakout_status=pipeline_res["price_confirmation"]["breakout_status"]
        )

        # 3. Throttled Intraday Market Snapshot Storage (30s interval) - Only during market hours or simulation mode
        from app.services.market_hours import is_market_open
        from app.config import get_settings
        settings = get_settings()
        if (is_market_open() or settings.VCC_SIMULATION_MODE) and snapshot.metadata.source_name != "SIMULATED":
            trade_date = datetime.now(IST).strftime("%Y-%m-%d")
            now_iso = datetime.now(IST).isoformat()
            market_repository.save_snapshot_throttled(
                sym, trade_date, now_iso, snapshot, pipeline_res, min_interval_sec=30.0
            )
    except Exception as e:
        logger.error(f"Error in refresh_v3_market_data for {sym}: {e}")
