"""
Analytics Pipeline Orchestrator for VCC V3.2.
Combines MarketStateEngine, OptionAnalyticsEngine, FlowAnalyticsEngine, and PriceAnalyticsEngine.
Consumes MarketSnapshot and HistoricalContextProvider.
Does NOT contain database, network, or UI dependencies.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime
from app.domain.contracts import MarketSnapshot, AnalyticalResult
from app.analytics.context_provider import HistoricalContextProvider, default_context_provider
from app.analytics.market_state_engine import MarketStateEngine
from app.analytics.option_analytics_engine import OptionAnalyticsEngine
from app.analytics.flow_analytics_engine import FlowAnalyticsEngine
from app.analytics.price_analytics_engine import PriceAnalyticsEngine
from app.core.constants import system_config
from app.services.market_hours import IST


class AnalyticsPipeline:

    def __init__(self, context_provider: Optional[HistoricalContextProvider] = None):
        self.context_provider = context_provider or default_context_provider

    def run_pipeline(
        self,
        snapshot: MarketSnapshot,
        index_data: Optional[Dict[str, Any]] = None,
        pcr_obj: Optional[Any] = None,
        vix_obj: Optional[Any] = None,
        override_now_dt: Optional[datetime] = None
    ) -> Dict[str, Any]:
        now_dt = override_now_dt or datetime.now(IST)
        symbol = snapshot.symbol.upper()
        trade_date = now_dt.strftime("%Y-%m-%d")

        # Query Historical Context
        db_snaps = self.context_provider.get_snapshots_today(symbol, trade_date)
        snap_5m = self.context_provider.get_snapshot_at_offset(symbol, now_dt, 300)
        snap_15m = self.context_provider.get_snapshot_at_offset(symbol, now_dt, 900)
        snap_30m = self.context_provider.get_snapshot_at_offset(symbol, now_dt, 1800)

        # 1. Option Analytics Engine
        opt_res = OptionAnalyticsEngine.compute_option_analytics(snapshot, db_snaps)

        # 2. Price Analytics Engine
        price_res = PriceAnalyticsEngine.compute_price_analytics(
            snapshot=snapshot,
            index_data=index_data,
            snap_5m=snap_5m,
            snap_15m=snap_15m,
            strongest_pe_strike=opt_res["support_wall"],
            strongest_ce_strike=opt_res["resistance_wall"],
            pe_chg_5=opt_res["pe_chg_5m"],
            ce_chg_5=opt_res["ce_chg_5m"]
        )

        # 3. Flow Analytics Engine
        flow_res = FlowAnalyticsEngine.compute_flow_analytics(
            snapshot=snapshot,
            strike_matrix=None,
            snap_5m=snap_5m,
            snap_15m=snap_15m,
            snap_30m=snap_30m
        )

        # 4. Confluence Scoring & Conflict Resolution
        option_positioning_score = opt_res["positioning_score"]
        price_conf_score = price_res["score"]

        is_conflict = False
        conflict_type = "NONE"
        conflict_details = []

        if option_positioning_score >= 20 and price_conf_score <= -15:
            is_conflict = True
            conflict_type = "POSITIONING vs PRICE CONFLICT"
            conflict_details.append(f"Option positioning is Bullish (+{option_positioning_score}), but Spot price momentum is Bearish ({price_conf_score}).")
        elif option_positioning_score <= -20 and price_conf_score >= 15:
            is_conflict = True
            conflict_type = "POSITIONING vs PRICE CONFLICT"
            conflict_details.append(f"Option positioning is Bearish ({option_positioning_score}), but Spot price momentum is Bullish (+{price_conf_score}).")

        pos_weight = system_config.confluence_weights.positioning  # 0.35 or baseline 0.60
        price_weight = system_config.confluence_weights.price_confirmation  # 0.30 or baseline 0.40
        weighted_signal = (0.60 * option_positioning_score) + (0.40 * price_conf_score)
        raw_confluence = 50 + int(round(weighted_signal / 2.0))
        raw_confluence = max(5, min(99, raw_confluence))

        if is_conflict:
            final_confluence_score = max(20, min(55, raw_confluence - 25))
            raw_label = "SIGNAL CONFLICT / UNCONFIRMED"
        else:
            final_confluence_score = raw_confluence
            if final_confluence_score >= 70:
                raw_label = "BULLISH CONFLUENCE"
            elif final_confluence_score <= 35:
                raw_label = "BEARISH CONFLUENCE"
            else:
                raw_label = "MODERATE / TWO-SIDED"

        # 5. Market State Engine
        state_res = MarketStateEngine.compute_market_state(
            snapshot=snapshot,
            final_confluence_score=final_confluence_score,
            price_conf_score=price_conf_score,
            breakout_status=price_res["breakout_status"],
            is_conflict=is_conflict,
            now_dt=now_dt
        )

        return {
            "symbol": symbol,
            "timestamp": now_dt.strftime("%H:%M:%S"),
            "spot_price": snapshot.spot.spot_price,
            "atm_strike": opt_res["atm_strike"],
            "pcr": opt_res["pcr"],
            "positioning": opt_res,
            "price_confirmation": price_res,
            "flow": flow_res,
            "market_state": state_res,
            "confluence": {
                "score": final_confluence_score,
                "label": raw_label,
                "is_conflict": is_conflict,
                "conflict_type": conflict_type,
                "conflict_details": conflict_details
            }
        }


analytics_pipeline = AnalyticsPipeline()
