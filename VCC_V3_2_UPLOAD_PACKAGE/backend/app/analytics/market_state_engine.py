"""
Market State Engine for VCC V3.2.
Computes market session, operational state, execution permissions, and regime classification.
Uses exact baseline business rules.
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from app.domain.contracts import MarketSnapshot, MarketSession, MarketState
from app.services.market_hours import get_market_session_info, IST

ENTRY_MIN_CONFLUENCE = 70
ENTRY_MIN_PRICE_CONF = 50
BIAS_MIN_CONFLUENCE = 60
SETUP_MIN_CONFLUENCE = 50


class MarketStateEngine:

    @staticmethod
    def compute_market_state(
        snapshot: MarketSnapshot,
        final_confluence_score: float,
        price_conf_score: float,
        breakout_status: str,
        is_conflict: bool,
        now_dt: Optional[datetime] = None
    ) -> Dict[str, Any]:
        dt = now_dt or datetime.now(IST)
        session_info = get_market_session_info(now_dt=dt)
        session_state = session_info["session_state"]
        is_market_live = session_info["is_live"]

        if not is_market_live:
            operational_state = "MARKET CLOSED"
            execution_status = "DISABLED"
        elif is_conflict:
            operational_state = "SIGNAL CONFLICT / INVALIDATED"
            execution_status = "DISABLED"
        elif final_confluence_score < 35:
            operational_state = "NO SIGNAL"
            execution_status = "DISABLED"
        elif final_confluence_score < SETUP_MIN_CONFLUENCE:
            operational_state = "WATCH"
            execution_status = "DISABLED"
        elif final_confluence_score < BIAS_MIN_CONFLUENCE:
            operational_state = "SETUP DEVELOPING"
            execution_status = "DISABLED"
        elif final_confluence_score < ENTRY_MIN_CONFLUENCE:
            operational_state = "CONFIRMED BIAS"
            execution_status = "DISABLED"
        else:
            if price_conf_score >= ENTRY_MIN_PRICE_CONF and breakout_status in [
                "UPSIDE BREAKOUT CONFIRMED",
                "DOWNSIDE BREAKDOWN CONFIRMED"
            ]:
                operational_state = "ENTRY CONFIRMED"
                execution_status = "ENABLED"
            elif price_conf_score >= ENTRY_MIN_PRICE_CONF:
                operational_state = "ENTRY READY"
                execution_status = "ENABLED"
            else:
                operational_state = "CONFIRMED BIAS"
                execution_status = "DISABLED"

        # VIX Semantics & VIX > 22 Risk Breaker
        vix_val = snapshot.vix
        if vix_val is None or vix_val <= 0.0:
            volatility_state = "VIX_UNAVAILABLE"
            vix_status = "UNAVAILABLE"
            vix_breaker_active = False
        elif vix_val > 22.0:
            volatility_state = "EXTREME_VOLATILITY_RISK_HIGH"
            vix_status = "AVAILABLE"
            vix_breaker_active = True
            # VIX Risk Breaker Activates: Disable execution for option-selling strategies
            if execution_status == "ENABLED":
                execution_status = "DISABLED_VIX_RISK_HIGH"
        elif vix_val >= 18.0:
            volatility_state = "HIGH VOLATILITY"
            vix_status = "AVAILABLE"
            vix_breaker_active = False
        else:
            volatility_state = "NORMAL VIX"
            vix_status = "AVAILABLE"
            vix_breaker_active = False

        return {
            "session_state": session_state,
            "is_market_live": is_market_live,
            "execution_enabled": is_market_live and execution_status == "ENABLED",
            "execution_status": execution_status,
            "operational_state": operational_state,
            "volatility_state": volatility_state,
            "vix_status": vix_status,
            "vix_breaker_active": vix_breaker_active
        }


market_state_engine = MarketStateEngine()
