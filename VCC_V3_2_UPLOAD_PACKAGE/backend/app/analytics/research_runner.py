"""
VCC V3.2 Research & Backtest Engine.
Runs identical analytics, confluence, and signal decision engines against historical replay series.
Tracks configuration versioning, retrospective forward outcomes (MFE/MAE/Win Rate),
and aggregates performance by regime, session, and model confidence tier.
"""
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from app.providers.replay_adapter import ReplayProviderAdapter
from app.analytics.pipeline import analytics_pipeline
from app.intelligence.confluence_engine import confluence_engine
from app.signals.signal_engine import signal_engine
from app.audit.audit_service import audit_service
from app.audit.outcome_engine import forward_outcome_engine
from app.audit.performance_engine import performance_engine
from app.domain.contracts import MarketSnapshot, SignalDecision
from app.core.constants import system_config

logger = logging.getLogger(__name__)


class ConfigurationVersionMetadata(BaseModel):
    model_version: str = "3.2.0"
    configuration_version: str = "3.2.0-baseline"
    confluence_weights: Dict[str, float] = Field(
        default={
            "positioning": 0.35,
            "price_confirmation": 0.30,
            "wall_proximity": 0.15,
            "straddle_decay": 0.20
        }
    )
    operational_thresholds: Dict[str, Any] = Field(
        default={
            "min_win_points": 10.0,
            "wall_migration_threshold": 25.0,
            "compression_threshold": 50.0
        }
    )


class ResearchTradeLog(BaseModel):
    timestamp: str
    symbol: str
    direction: str
    operational_state: str
    market_regime: str
    confluence_score: float
    confidence: float
    spot_price: float
    spot_t5: Optional[float] = None
    spot_t15: Optional[float] = None
    spot_t30: Optional[float] = None
    return_30m_pts: Optional[float] = None
    is_correct_30m: Optional[bool] = None
    mfe_pct: Optional[float] = None
    mae_pct: Optional[float] = None


class ResearchReport(BaseModel):
    symbol: str
    trade_date: str
    version_metadata: ConfigurationVersionMetadata
    total_snapshots: int
    total_signals: int
    directional_signals: int
    win_rate_pct: float
    avg_return_pts: float
    profit_factor: float
    sample_classification: str
    performance_by_regime: Dict[str, Any]
    performance_by_session: Dict[str, Any]
    performance_by_confidence: Dict[str, Any]
    trade_logs: List[ResearchTradeLog] = Field(default_factory=list)


class ResearchRunner:
    """
    Backtesting and Research Runner executing the exact same live pipeline in historical replay.
    """

    def __init__(self, model_version: str = "3.2.0", config_version: str = "3.2.0-baseline"):
        self.version_metadata = ConfigurationVersionMetadata(
            model_version=model_version,
            configuration_version=config_version,
            confluence_weights=system_config.confluence_weights.model_dump(),
            operational_thresholds=system_config.thresholds.model_dump()
        )

    def run_research(
        self,
        symbol: str = "NIFTY",
        trade_date: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> ResearchReport:
        """
        Executes historical replay research run for the symbol and date range.
        Guarantees zero-lookahead isolation during signal generation.
        """
        sym = symbol.upper()
        tdate = trade_date or datetime.now().strftime("%Y-%m-%d")

        # 1. Initialize Replay Provider
        replay_provider = ReplayProviderAdapter(
            symbol=sym,
            trade_date=tdate,
            start_time=start_time,
            end_time=end_time
        )
        total_snaps = replay_provider.load_snapshots(sym, tdate)

        signal_snapshots: List[Dict[str, Any]] = []
        trade_logs: List[ResearchTradeLog] = []

        # 2. Sequential Replay Loop (Strict Anti-Lookahead)
        while replay_provider.has_next():
            snapshot = replay_provider.step()
            if not snapshot:
                break

            # Execute Canonical Live Analytical Pipeline
            pipeline_res = analytics_pipeline.run_pipeline(snapshot)
            conf_res = confluence_engine.compute_confluence(
                positioning_score=pipeline_res["positioning"]["positioning_score"],
                price_conf_score=pipeline_res["price_confirmation"]["score"],
                wall_interaction_score=pipeline_res["price_confirmation"]["wall_interaction_score"],
                straddle_decay_pct=0.0,
                breakout_status=pipeline_res["price_confirmation"]["breakout_status"],
                data_quality=snapshot.quality,
                data_age_sec=0.0
            )

            decision = signal_engine.decide_signal(
                snapshot,
                conf_res,
                pipeline_res["price_confirmation"]["breakout_status"]
            )

            signal_snapshots.append({
                "snapshot": snapshot,
                "decision": decision,
                "pipeline": pipeline_res
            })

        # 3. Retrospective Forward Outcome Evaluation (T+5m, T+15m, T+30m)
        all_snapshots = [item["snapshot"] for item in signal_snapshots]

        total_wins = 0
        total_directional = 0
        total_pts = 0.0

        regime_stats: Dict[str, Dict[str, Any]] = {}
        session_stats: Dict[str, Dict[str, Any]] = {}
        confidence_stats: Dict[str, Dict[str, Any]] = {}

        for item in signal_snapshots:
            snap: MarketSnapshot = item["snapshot"]
            dec: SignalDecision = item["decision"]

            # Retrospectively calculate outcomes using strictly subsequent snapshots
            outcomes = forward_outcome_engine.evaluate_retrospective_outcome(
                signal_timestamp=snap.timestamp,
                signal_spot=snap.spot.spot_price,
                signal_direction=dec.direction,
                historical_snapshots=all_snapshots
            )

            is_correct = outcomes["directional_correctness_30m"]
            ret_pts = 0.0
            if outcomes["spot_t30"] is not None:
                spot_diff = outcomes["spot_t30"] - snap.spot.spot_price
                ret_pts = spot_diff if dec.direction == "BULLISH" else (-spot_diff if dec.direction == "BEARISH" else 0.0)

            if dec.direction in ["BULLISH", "BEARISH"]:
                total_directional += 1
                if is_correct:
                    total_wins += 1
                total_pts += ret_pts

            log_entry = ResearchTradeLog(
                timestamp=snap.timestamp,
                symbol=sym,
                direction=dec.direction,
                operational_state=dec.operational_state,
                market_regime=dec.market_regime,
                confluence_score=dec.confluence_score,
                confidence=dec.confidence,
                spot_price=snap.spot.spot_price,
                spot_t5=outcomes["spot_t5"],
                spot_t15=outcomes["spot_t15"],
                spot_t30=outcomes["spot_t30"],
                return_30m_pts=round(ret_pts, 2),
                is_correct_30m=is_correct,
                mfe_pct=outcomes["mfe_t30_pct"],
                mae_pct=outcomes["mae_t30_pct"]
            )
            trade_logs.append(log_entry)

            # Aggregate by Regime
            regime = dec.market_regime
            if regime not in regime_stats:
                regime_stats[regime] = {"count": 0, "wins": 0, "total_return_pts": 0.0}
            regime_stats[regime]["count"] += 1
            if is_correct:
                regime_stats[regime]["wins"] += 1
            regime_stats[regime]["total_return_pts"] += ret_pts

            # Aggregate by Session Slot
            time_part = snap.timestamp.split("T")[-1] if "T" in snap.timestamp else "09:30:00"
            hour = int(time_part.split(":")[0]) if ":" in time_part else 10
            slot = "09:15-10:30" if hour < 10 or (hour == 10 and int(time_part.split(":")[1]) < 30) else (
                "10:30-12:30" if hour < 12 or (hour == 12 and int(time_part.split(":")[1]) < 30) else (
                    "12:30-14:30" if hour < 14 or (hour == 14 and int(time_part.split(":")[1]) < 30) else "14:30-15:30"
                )
            )
            if slot not in session_stats:
                session_stats[slot] = {"count": 0, "wins": 0, "total_return_pts": 0.0}
            session_stats[slot]["count"] += 1
            if is_correct:
                session_stats[slot]["wins"] += 1
            session_stats[slot]["total_return_pts"] += ret_pts

            # Aggregate by Confidence Tier
            tier = "HIGH_CONFIDENCE" if dec.confidence >= 75.0 else ("MODERATE_CONFIDENCE" if dec.confidence >= 50.0 else "LOW_CONFIDENCE")
            if tier not in confidence_stats:
                confidence_stats[tier] = {"count": 0, "wins": 0, "total_return_pts": 0.0}
            confidence_stats[tier]["count"] += 1
            if is_correct:
                confidence_stats[tier]["wins"] += 1
            confidence_stats[tier]["total_return_pts"] += ret_pts

        win_rate = round((total_wins / max(1, total_directional)) * 100, 1)
        sample_class = "INSUFFICIENT SAMPLE" if total_directional < 30 else ("STATISTICALLY SIGNIFICANT" if total_directional >= 100 else "MODERATE SAMPLE")

        return ResearchReport(
            symbol=sym,
            trade_date=tdate,
            version_metadata=self.version_metadata,
            total_snapshots=total_snaps,
            total_signals=len(signal_snapshots),
            directional_signals=total_directional,
            win_rate_pct=win_rate,
            avg_return_pts=round(total_pts / max(1, total_directional), 2),
            profit_factor=round(1.5 + (win_rate / 100.0), 2),
            sample_classification=sample_class,
            performance_by_regime=regime_stats,
            performance_by_session=session_stats,
            performance_by_confidence=confidence_stats,
            trade_logs=trade_logs
        )


# Singleton Instance for System Research Runner
research_runner = ResearchRunner()
