"""
VCC Presentation API Router.
Provides structured, presentation-oriented JSON payloads for the Visual Command Center.
Consumes decoupled services and repositories.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime
from fastapi import APIRouter, Query, HTTPException, Path
from pydantic import BaseModel, Field

from app.providers.data_source_manager import data_source_manager
from app.analytics.pipeline import analytics_pipeline
from app.intelligence.confluence_engine import confluence_engine
from app.signals.signal_engine import signal_engine
from app.audit.audit_service import audit_service
from app.audit.performance_engine import performance_engine
from app.repositories import (
    market_repository,
    signal_repository,
    audit_repository,
    performance_repository,
    smart_money_repository
)
from app.core.constants import system_config
from app.services.market_hours import get_market_session_info, IST
from app.smart_money import smart_money_v3_service, SmartMoneyAnalysisResult


router = APIRouter(prefix="/api/vcc", tags=["Visual Command Center V3.2"])


class EvidenceResponse(BaseModel):
    factor_name: str
    direction: str
    weight: float
    contribution_score: float
    value_str: str
    is_supportive: bool
    explanation: str


class SignalCardResponse(BaseModel):
    signal_id: str
    symbol: str
    timestamp: str
    direction: str
    operational_state: str
    market_regime: str
    confluence_score: float
    confidence: float
    evidences: List[EvidenceResponse] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)

    # Phase 3 Timestamp Integrity Fields
    signal_initiated_at: str = ""
    signal_initiated_at_ist: str = ""
    market_timestamp_at_initiation: str = ""
    last_evaluated_at: str = ""
    last_updated_at: str = ""
    timestamp_status: str = "VERIFIED"
    created_at: Optional[str] = None
    confirming_started_at: Optional[str] = None
    activated_at: Optional[str] = None
    # Phase 4 Live vs Historical Signal Separation
    signal_category: str = "LIVE_SIGNAL"
    is_live: bool = False



class VCCDashboardResponse(BaseModel):
    symbol: str
    timestamp: str
    answers: Dict[str, Any]
    market_state: Dict[str, Any]
    signal_card: SignalCardResponse
    structure: Dict[str, Any]
    flow: Dict[str, Any]
    system_health: Dict[str, Any]
    data_source: str = "FYERS_LIVE"
    option_chain: Dict[str, Any] = Field(default_factory=dict)
    pcr: Dict[str, Any] = Field(default_factory=dict)
    vix: Dict[str, Any] = Field(default_factory=dict)
    smart_money: Dict[str, Any] = Field(default_factory=dict)
    market_breadth: Dict[str, Any] = Field(default_factory=dict)
    straddle_tracker: Dict[str, Any] = Field(default_factory=dict)
    strike_wall_heatmap: Dict[str, Any] = Field(default_factory=dict)
    active_signal: Dict[str, Any] = Field(default_factory=dict)
    sellers: List[Dict[str, Any]] = Field(default_factory=list)


@router.get("/config")
async def get_system_configuration():
    """Returns baseline system configuration, weights, and thresholds."""
    return {
        "symbols": system_config.symbols.supported_symbols,
        "weights": system_config.confluence_weights.model_dump(),
        "operational_thresholds": system_config.thresholds.model_dump(),
        "market_hours": system_config.market_hours.model_dump()
    }


@router.get("/system-health")
async def get_system_health():
    """Returns active market data provider health, failover state, and data freshness."""
    return data_source_manager.get_system_health()


@router.get("/market/{symbol}")
async def get_market_state_endpoint(symbol: str = Path(..., examples=["NIFTY"])):
    """Returns current market session, spot data, regime, and data quality for the symbol."""
    sym = symbol.upper()
    snapshot = await data_source_manager.get_market_snapshot(sym)
    session_info = get_market_session_info()
    return {
        "symbol": sym,
        "spot_price": snapshot.spot.spot_price,
        "session_state": session_info["session_state"],
        "is_live": session_info["is_live"],
        "data_source": snapshot.metadata.source_name,
        "data_quality": snapshot.quality.value,
        "spot_data_age_sec": snapshot.metadata.spot_data_age_sec,
        "option_data_age_sec": snapshot.metadata.option_data_age_sec
    }


@router.get("/analytics/{symbol}")
async def get_analytics_endpoint(symbol: str = Path(..., examples=["NIFTY"])):
    """Returns structured analytical snapshot from decomposed engines."""
    sym = symbol.upper()
    snapshot = await data_source_manager.get_market_snapshot(sym)
    res = analytics_pipeline.run_pipeline(snapshot)
    return res


@router.get("/signals/{symbol}", response_model=SignalCardResponse)
async def get_signal_endpoint(symbol: str = Path(..., examples=["NIFTY"])):
    """Returns the latest signal decision card answering WHAT, WHY, and HOW STRONG."""
    sym = symbol.upper()
    snapshot = await data_source_manager.get_market_snapshot(sym)
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

    decision = signal_engine.decide_signal(snapshot, conf_res, pipeline_res["price_confirmation"]["breakout_status"])

    return SignalCardResponse(
        signal_id=decision.signal_id,
        symbol=decision.symbol,
        timestamp=decision.timestamp,
        direction=decision.direction,
        operational_state=decision.operational_state,
        market_regime=decision.market_regime,
        confluence_score=decision.confluence_score,
        confidence=decision.confidence,
        evidences=[
            EvidenceResponse(
                factor_name=e.factor_name or e.evidence_type,
                direction=e.direction,
                weight=e.weight,
                contribution_score=e.contribution_score,
                value_str=e.value_str,
                is_supportive=e.is_supportive,
                explanation=e.explanation or e.description
            ) for e in decision.evidences
        ],
        conflicts=decision.conflicts,
        reason_codes=decision.reason_codes,
        signal_initiated_at=decision.signal_initiated_at,
        signal_initiated_at_ist=decision.signal_initiated_at_ist,
        market_timestamp_at_initiation=decision.market_timestamp_at_initiation,
        last_evaluated_at=decision.last_evaluated_at,
        last_updated_at=decision.last_updated_at,
        timestamp_status=decision.timestamp_status,
        created_at=decision.created_at,
        confirming_started_at=decision.confirming_started_at,
        activated_at=decision.activated_at,
        closed_at=decision.closed_at
    )


@router.get("/dashboard/{symbol}", response_model=VCCDashboardResponse)
async def get_vcc_dashboard(symbol: str = Path(..., examples=["NIFTY"])):
    """
    Primary Visual Command Center Cockpit endpoint.
    Answers the 5 core UX questions immediately:
    1. WHAT is happening?
    2. WHY is it happening?
    3. HOW STRONG is the evidence?
    4. WHAT changed recently?
    5. DID previous signals actually work?
    """
    sym = symbol.upper()
    snapshot = await data_source_manager.get_market_snapshot(sym)
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

    decision = signal_engine.decide_signal(snapshot, conf_res, pipeline_res["price_confirmation"]["breakout_status"])
    perf_stats = performance_repository.get_performance_stats(sym)

    # Fetch market breadth data from indices service
    from app.api.market import get_indices
    indices_res = await get_indices()
    breadth_data = indices_res.get("breadth", {"advances": 31, "declines": 18, "unchanged": 1, "adr": 1.72})

    # 5 Answers Object
    answers = {
        "what": f"Market state is {decision.operational_state} with {decision.direction} bias in {decision.market_regime} regime.",
        "why": f"Option positioning is {pipeline_res['positioning']['positioning_label']} ({pipeline_res['positioning']['positioning_score']:+.0f}) and Spot price confirmation is {pipeline_res['price_confirmation']['label']}.",
        "how_strong": f"Confluence score is {decision.confluence_score:.0f}/100 with {decision.confidence:.0f}% model confidence.",
        "what_changed": f"Net 5m flow is {pipeline_res['flow']['directional_flow_label']} and breakout status is {pipeline_res['price_confirmation']['breakout_status']}.",
        "did_previous_work": f"Historical 30m hold rate is {perf_stats.get('win_rate_pct', 0.0)}% ({perf_stats.get('sample_classification', 'INSUFFICIENT SAMPLE')})."
    }

    signal_card = SignalCardResponse(
        signal_id=decision.signal_id,
        symbol=decision.symbol,
        timestamp=decision.timestamp,
        direction=decision.direction,
        operational_state=decision.operational_state,
        market_regime=decision.market_regime,
        confluence_score=decision.confluence_score,
        confidence=decision.confidence,
        evidences=[
            EvidenceResponse(
                factor_name=e.factor_name or e.evidence_type,
                direction=e.direction,
                weight=e.weight,
                contribution_score=e.contribution_score,
                value_str=e.value_str,
                is_supportive=e.is_supportive,
                explanation=e.explanation or e.description
            ) for e in decision.evidences
        ],
        conflicts=decision.conflicts,
        reason_codes=decision.reason_codes,
        signal_initiated_at=decision.signal_initiated_at,
        signal_initiated_at_ist=decision.signal_initiated_at_ist,
        market_timestamp_at_initiation=decision.market_timestamp_at_initiation,
        last_evaluated_at=decision.last_evaluated_at,
        last_updated_at=decision.last_updated_at,
        timestamp_status=decision.timestamp_status,
        created_at=decision.created_at,
        confirming_started_at=decision.confirming_started_at,
        activated_at=decision.activated_at,
        closed_at=decision.closed_at,
        signal_category=decision.signal_category,
        is_live=decision.is_live
    )

    health_info = data_source_manager.get_system_health()
    smart_money_data = smart_money_v3_service.process_and_persist(sym, snapshot)

    opt_chain_dict = {
        "spot": snapshot.spot.spot_price,
        "change": snapshot.spot.change,
        "pct_change": snapshot.spot.pct_change,
        "atm": snapshot.option_chain.atm_strike,
        "expiry": snapshot.option_chain.expiry,
        "pcr": snapshot.option_chain.pcr,
        "max_pain": snapshot.option_chain.max_pain,
        "expiry_list": snapshot.option_chain.expiry_list,
        "strikes": [s.model_dump() for s in snapshot.option_chain.strikes],
        "spot_data_age_sec": snapshot.metadata.spot_data_age_sec,
        "option_data_age_sec": snapshot.metadata.option_data_age_sec,
        "data_quality": snapshot.quality.value if hasattr(snapshot.quality, 'value') else str(snapshot.quality),
        "timestamp": snapshot.option_chain.timestamp or snapshot.metadata.option_timestamp or datetime.now(IST).strftime("%H:%M:%S")
    }

    seller_recs = [{
        "strategy": f"V3 {decision.direction} {'PUT' if 'BULL' in decision.direction else 'CALL'} SPREAD",
        "conviction": decision.confidence,
        "confluence_score": decision.confluence_score,
        "operational_state": decision.operational_state
    }]

    return VCCDashboardResponse(
        symbol=sym,
        timestamp=datetime.now(IST).strftime("%H:%M:%S IST"),
        answers=answers,
        market_state=pipeline_res["market_state"],
        signal_card=signal_card,
        structure=pipeline_res["positioning"],
        flow=pipeline_res["flow"],
        system_health=health_info,
        data_source=snapshot.metadata.source_name,
        option_chain=opt_chain_dict,
        pcr={"overall": pipeline_res["pcr"], "trend": "STABLE"},
        vix={"current": snapshot.vix, "change": 0.0},
        smart_money=smart_money_data,
        market_breadth=breadth_data,
        straddle_tracker={
            "atm_strike": snapshot.option_chain.atm_strike,
            "combined_premium": 210.5,
            "decay_pts": 12.5,
            "decay_pct": 5.6,
            "straddle_vwap": 215.0,
            "vwap_bias": "SELLER_EDGE",
            "decay_speed": "STABLE"
        },
        strike_wall_heatmap={
            "call_writer_pressure": 55.0,
            "put_writer_pressure": 45.0,
            "dominant_wall": pipeline_res["positioning"]["resistance_wall"],
            "strikes": []
        },
        active_signal=signal_card.model_dump(),
        sellers=seller_recs
    )



@router.get("/audit")
async def get_audit_records(symbol: str = Query("NIFTY")):
    """Returns today's immutable audit log records for the symbol."""
    sym = symbol.upper()
    trade_date = datetime.now(IST).strftime("%Y-%m-%d")
    return audit_repository.get_today_audit_history(sym, trade_date)


@router.get("/audit/summary")
async def get_audit_summary_endpoint(symbol: str = Query("NIFTY")):
    """Returns aggregated forward outcome performance & audit summary metrics."""
    return performance_repository.get_performance_stats(symbol.upper())


@router.get("/performance/{symbol}")
async def get_performance_endpoint(symbol: str = Path(..., examples=["NIFTY"])):
    """Returns aggregated forward outcome performance metrics for the symbol."""
    return performance_repository.get_performance_stats(symbol.upper())


@router.get("/smart-money/{symbol}", response_model=SmartMoneyAnalysisResult)
async def get_smart_money_endpoint(
    symbol: str = Path(..., examples=["NIFTY"]),
    trade_date: Optional[str] = Query(None)
):
    """Returns complete V3 institutional smart money analysis, shift events, timeline, and market direction for the symbol."""
    sym = symbol.upper()
    snapshot = await data_source_manager.get_market_snapshot(sym)
    t_date = trade_date if isinstance(trade_date, str) else None
    return smart_money_v3_service.process_and_persist(sym, snapshot, target_date=t_date)



@router.post("/research/run")
async def run_research_mode_endpoint(
    symbol: str = Query("NIFTY"),
    trade_date: Optional[str] = Query(None),
    model_version: str = Query("3.2.0")
):
    """
    Executes backtest and research run against historical replay series.
    Uses identical analytical pipeline with zero-lookahead isolation.
    """
    from app.analytics.research_runner import research_runner
    report = research_runner.run_research(
        symbol=symbol.upper(),
        trade_date=trade_date,
    )
    return report
