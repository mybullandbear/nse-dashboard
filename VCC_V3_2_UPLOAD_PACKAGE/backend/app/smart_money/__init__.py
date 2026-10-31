"""
Modular Smart Money Subsystem for VCC V3.2.
Provides block trade shift detection, sm_bias_5 calculation, intraday timeline deduplication,
and fail-safe Telegram push alerts.
"""
from app.smart_money.models import SmartMoneyShiftEvent, SmartMoneyAnalysisResult, MarketDirectionDTO
from app.smart_money.detector import SmartMoneyDetector, smart_money_detector
from app.smart_money.scoring import SmartMoneyScorer, smart_money_scorer
from app.smart_money.timeline import SmartMoneyTimelineManager, smart_money_timeline_manager
from app.smart_money.service import ModularSmartMoneyService, smart_money_v3_service

__all__ = [
    "SmartMoneyShiftEvent",
    "SmartMoneyAnalysisResult",
    "MarketDirectionDTO",
    "SmartMoneyDetector",
    "smart_money_detector",
    "SmartMoneyScorer",
    "smart_money_scorer",
    "SmartMoneyTimelineManager",
    "smart_money_timeline_manager",
    "ModularSmartMoneyService",
    "smart_money_v3_service"
]
