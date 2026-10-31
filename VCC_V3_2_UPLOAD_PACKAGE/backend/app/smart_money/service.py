"""
Modular Smart Money Service Orchestrator for VCC V3.2.
Coordinates detection, scoring, timeline management, persistence, and non-blocking alert dispatch.
Contains zero low-level SQL queries (delegates to repository layer).
"""
import logging
from datetime import datetime, date, timezone, timedelta
from typing import Dict, List, Any, Optional, Union

from app.domain.contracts import MarketSnapshot, OptionChainSnapshot, SpotData, DataQuality, DataSourceMetadata

from app.repositories.smart_money_repository import smart_money_repository
from app.repositories.market_repository import market_repository
from app.alerts.telegram_alert_service import telegram_alert_service
from app.services.market_hours import is_market_open, IST
from app.smart_money.models import SmartMoneyAnalysisResult, SmartMoneyShiftEvent
from app.smart_money.detector import smart_money_detector
from app.smart_money.scoring import smart_money_scorer
from app.smart_money.timeline import smart_money_timeline_manager

logger = logging.getLogger(__name__)


class ModularSmartMoneyService:

    def __init__(self):
        self.detector = smart_money_detector
        self.scorer = smart_money_scorer
        self.timeline_manager = smart_money_timeline_manager
        self.repository = smart_money_repository
        self.market_repo = market_repository
        self.alert_service = telegram_alert_service

    def _ensure_snapshot(self, symbol: str, chain_or_snapshot: Any) -> MarketSnapshot:
        if isinstance(chain_or_snapshot, MarketSnapshot):
            return chain_or_snapshot
        
        # If passed an OptionChain object or duck-typed chain
        chain = chain_or_snapshot if hasattr(chain_or_snapshot, 'strikes') else None
        spot_price = float(getattr(chain, 'spot_price', 24500.0)) if chain else 24500.0
        atm_strike = float(getattr(chain, 'atm_strike', 24500.0)) if chain else 24500.0

        return MarketSnapshot(
            symbol=symbol.upper(),
            timestamp=datetime.now(IST).isoformat(),
            spot=SpotData(symbol=symbol.upper(), spot_price=spot_price, timestamp=datetime.now(IST).isoformat()),
            expiry="28-AUG-2026",
            option_chain=chain if isinstance(chain, OptionChainSnapshot) else OptionChainSnapshot(symbol=symbol.upper(), expiry="28-AUG-2026", spot_price=spot_price, atm_strike=atm_strike, strikes=getattr(chain, 'strikes', [])),
            quality=DataQuality.GOOD,
            metadata=DataSourceMetadata(source_name="V3_WRAPPER", spot_data_age_sec=0.0, option_data_age_sec=0.0)
        )


    def process_and_persist(
        self,
        symbol: str,
        chain_or_snapshot: Any,
        pcr: Any = None,
        vix: Any = None,
        target_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Main V3 entry point: Analyzes MarketSnapshot/Chain, detects single-strike shifts,
        persists records via repository, dispatches Telegram alerts safely, and returns analysis result dictionary.
        """
        sym = symbol.upper()
        now_ist = datetime.now(IST)
        today_str = target_date or now_ist.strftime("%Y-%m-%d")
        now_iso = now_ist.isoformat()

        snapshot = self._ensure_snapshot(sym, chain_or_snapshot)

        # 1. Compute Conviction & Market Direction Scoring
        scoring_res = self.scorer.compute_scoring(sym, snapshot)

        # Check whether Smart Money processing is allowed
        from app.config import get_settings
        settings = get_settings()
        is_sim_mode = settings.VCC_SIMULATION_MODE

        is_valid_live_feed = (
            is_market_open()
            and snapshot.metadata.source_name != "SIMULATED"
            and snapshot.quality != DataQuality.INVALID
        )

        if not is_sim_mode and not is_valid_live_feed:
            # Market Closed or Invalid/Synthetic feed: Do NOT process or persist new shifts
            res_dto = self.get_smart_money_data(sym, target_date=today_str, snapshot=snapshot, scoring_res=scoring_res)
            return res_dto.model_dump()

        # 2. Detect Block Trade & Single-Strike Shifts
        detected_events = self.detector.detect_shifts(
            symbol=sym,
            snapshot=snapshot,
            trade_date=today_str,
            now_iso=now_iso,
            put_conviction=scoring_res["put_conviction"],
            call_conviction=scoring_res["call_conviction"]
        )

        # 3. Persist Shifts & Dispatch Non-Blocking Telegram Alerts
        for event in detected_events:
            saved_id = self.repository.save_shift({
                "trade_date": event.trade_date,
                "timestamp": event.timestamp,
                "symbol": event.symbol,
                "shift_text": event.shift_text,
                "shift_type": event.shift_type,
                "strike_price": event.strike_price,
                "option_type": event.option_type,
                "oi_change": event.oi_change,
                "conviction_score": event.conviction_score
            })

            # Non-blocking Telegram alert (isolated from pipeline errors)
            if saved_id > 0 and snapshot and snapshot.option_chain:
                try:
                    time_str = now_iso.split('T')[1][:5] if 'T' in now_iso else now_iso[:5]
                    msg = self.alert_service.format_smart_money_message(
                        symbol=sym,
                        time_str=time_str,
                        shift_text=event.shift_text,
                        shift_type=event.shift_type,
                        spot_price=snapshot.spot.spot_price if snapshot.spot else 0.0
                    )

                    import asyncio
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(
                            self.alert_service.send_alert(
                                message=msg,
                                symbol=sym,
                                shift_text=event.shift_text,
                                trade_date=today_str
                            )
                        )
                    except RuntimeError:
                        pass
                except Exception as ex_alert:
                    logger.warning(f"Smart Money alert dispatch warning: {ex_alert}")

        # 4. Throttled Market Snapshot Persistence (Max 1 write per 30 seconds during market hours)
        if is_market_open() and snapshot and snapshot.option_chain:
            try:
                self.market_repo.save_snapshot_throttled(
                    symbol=sym,
                    trade_date=today_str,
                    now_iso=now_iso,
                    snapshot=snapshot,
                    scoring_res=scoring_res,
                    min_interval_sec=30.0
                )
            except Exception as ex_snap:
                logger.warning(f"Market snapshot throttle save warning: {ex_snap}")

        # 5. Fetch Today's Shifts & Timelines for REST Presentation Payload
        res_dto = self.get_smart_money_data(sym, target_date=today_str, snapshot=snapshot, scoring_res=scoring_res)
        return res_dto.model_dump()

    def get_smart_money_data(
        self,
        symbol: str,
        target_date: Optional[str] = None,
        snapshot: Optional[MarketSnapshot] = None,
        scoring_res: Optional[Dict[str, Any]] = None
    ) -> SmartMoneyAnalysisResult:
        """
        Fetches today's stored shifts, constructs intraday timeline,
        and returns complete SmartMoneyAnalysisResult object.
        """
        sym = symbol.upper()
        today_str = target_date or date.today().isoformat()

        if not snapshot and not scoring_res:
            snapshot = self._ensure_snapshot(sym, None)

        if not scoring_res:
            scoring_res = self.scorer.compute_scoring(sym, snapshot)

        db_shifts = self.repository.get_today_shifts(sym, today_str)
        db_snapshots = self.market_repo.get_today_snapshots(sym, today_str)

        shift_list = []
        for s in db_shifts:
            ts_formatted = s.get("timestamp", "").split('T')[1][:8] if 'T' in str(s.get("timestamp", "")) else str(s.get("timestamp", ""))
            shift_list.append({
                "id": s.get("id", 0),
                "time": ts_formatted,
                "text": s.get("shift_text", ""),
                "type": s.get("shift_type", "BULL"),
                "symbol": s.get("symbol", sym),
                "strike": s.get("strike_price"),
                "option_type": s.get("option_type"),
                "oi_change": s.get("oi_change"),
                "conviction_score": s.get("conviction_score")
            })

        spot_fallback = snapshot.spot.spot_price if snapshot and snapshot.spot else 0.0
        timeline_data = self.timeline_manager.build_timeline(db_snapshots, spot_fallback=spot_fallback)

        call_conv_str = f"{scoring_res['call_conviction']:.0f}%" if isinstance(scoring_res['call_conviction'], (int, float)) else str(scoring_res['call_conviction'])
        put_conv_str = f"{scoring_res['put_conviction']:.0f}%" if isinstance(scoring_res['put_conviction'], (int, float)) else str(scoring_res['put_conviction'])

        return SmartMoneyAnalysisResult(
            symbol=sym,
            date=today_str,
            last_updated=datetime.now(IST).strftime("%H:%M:%S"),
            smart_money_score=scoring_res["smart_money_score"],
            call_conviction=call_conv_str,
            put_conviction=put_conv_str,
            expected_decay=scoring_res["expected_decay"],
            call_wall_strike=scoring_res["call_wall_strike"],
            put_wall_strike=scoring_res["put_wall_strike"],
            net_bias=scoring_res["net_bias"],
            top_oi_distribution=scoring_res["top_oi_distribution"],
            oi_chart_data=scoring_res["oi_chart_data"],
            intraday_timeline=timeline_data,
            shifts=shift_list,
            market_direction=scoring_res["market_direction"],
            is_database_connected=True
        )


smart_money_v3_service = ModularSmartMoneyService()
