"""
Canonical PCR Analytics Engine for VCC V3.2.
Provides authoritative, real-data-only Total PCR and ATM+-5 PCR calculations.
Strictly enforces:
1. MISSING DATA IS NOT ZERO (returns None / UNAVAILABLE).
2. CE OI <= 0 yields PCR UNAVAILABLE (no inf, nan, or 0.0 substitution).
3. Synthetic / Stale / Invalid option chains return PCR UNAVAILABLE.
"""
import math
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from app.domain.contracts import MarketSnapshot, DataQuality, DataStatus
from app.core.constants import system_config

logger = logging.getLogger(__name__)


class PCREngine:
    """
    Canonical PCR Engine for VCC V3.2.
    Single authoritative calculation path for Total PCR, ATM PCR, and ATM+-5 PCR.
    """

    @staticmethod
    def compute_pcr(snapshot: MarketSnapshot) -> Dict[str, Any]:
        """
        Computes canonical Total PCR, ATM PCR, and ATM+-5 PCR for a MarketSnapshot.
        Returns strongly-typed dict with explicit availability status.
        """
        # Quality & Real Data Gate
        if (
            not snapshot
            or not snapshot.metadata.is_real_data
            or snapshot.metadata.source_name == "SIMULATED"
            or snapshot.quality == DataQuality.INVALID
            or snapshot.metadata.is_stale
            or not snapshot.option_chain
            or not snapshot.option_chain.strikes
        ):
            return {
                "total_pcr": None,
                "atm_pcr": None,
                "atm_5_pcr": None,
                "total_pe_oi": None,
                "total_ce_oi": None,
                "pcr_status": "UNAVAILABLE",
                "pcr_interpretation": "UNAVAILABLE",
                "reason": "INVALID_OR_UNAVAILABLE_MARKET_FEED",
                "timestamp": snapshot.metadata.market_timestamp if snapshot else None
            }

        strikes = snapshot.option_chain.strikes
        spot_price = snapshot.spot.spot_price
        atm_strike = snapshot.option_chain.atm_strike
        symbol = snapshot.symbol.upper()
        strike_step = system_config.symbols.get_strike_step(symbol)

        # ----------------------------------------------------
        # 1. CANONICAL TOTAL PCR
        # ----------------------------------------------------
        valid_pe_ois = []
        valid_ce_ois = []

        for s in strikes:
            # Check PE OI
            if hasattr(s, "pe_tick") and s.pe_tick and s.pe_tick.oi is not None:
                valid_pe_ois.append(s.pe_tick.oi)
            elif hasattr(s, "pe_oi") and getattr(s, "pe_oi") is not None:
                valid_pe_ois.append(getattr(s, "pe_oi"))

            # Check CE OI
            if hasattr(s, "ce_tick") and s.ce_tick and s.ce_tick.oi is not None:
                valid_ce_ois.append(s.ce_tick.oi)
            elif hasattr(s, "ce_oi") and getattr(s, "ce_oi") is not None:
                valid_ce_ois.append(getattr(s, "ce_oi"))

        total_pe_oi = sum(valid_pe_ois) if valid_pe_ois else None
        total_ce_oi = sum(valid_ce_ois) if valid_ce_ois else None

        if total_pe_oi is None or total_ce_oi is None or total_ce_oi <= 0:
            total_pcr = None
            total_status = "UNAVAILABLE"
        else:
            total_pcr = round(total_pe_oi / total_ce_oi, 4)
            if math.isinf(total_pcr) or math.isnan(total_pcr):
                total_pcr = None
                total_status = "UNAVAILABLE"
            else:
                total_status = "AVAILABLE"

        # ----------------------------------------------------
        # 2. ATM PCR
        # ----------------------------------------------------
        atm_pe_ois = []
        atm_ce_ois = []
        for s in strikes:
            if s.strike_price == atm_strike:
                pe_val = s.pe_tick.oi if (hasattr(s, "pe_tick") and s.pe_tick and s.pe_tick.oi is not None) else getattr(s, "pe_oi", None)
                ce_val = s.ce_tick.oi if (hasattr(s, "ce_tick") and s.ce_tick and s.ce_tick.oi is not None) else getattr(s, "ce_oi", None)
                if pe_val is not None:
                    atm_pe_ois.append(pe_val)
                if ce_val is not None:
                    atm_ce_ois.append(ce_val)

        sum_atm_pe = sum(atm_pe_ois) if atm_pe_ois else None
        sum_atm_ce = sum(atm_ce_ois) if atm_ce_ois else None

        if sum_atm_pe is None or sum_atm_ce is None or sum_atm_ce <= 0:
            atm_pcr = None
        else:
            atm_pcr = round(sum_atm_pe / sum_atm_ce, 4)
            if math.isinf(atm_pcr) or math.isnan(atm_pcr):
                atm_pcr = None

        # ----------------------------------------------------
        # 3. ATM+-5 PCR (Window: ATM - 5*step to ATM + 5*step)
        # MISSING-STRIKE POLICY: Partial valid strike observations are permitted
        # as long as at least 1 valid PE and CE strike exist in the window.
        # ----------------------------------------------------
        band_5 = [s for s in strikes if abs(s.strike_price - atm_strike) <= (5 * strike_step + 1e-5)]
        pe_5_ois = []
        ce_5_ois = []

        for s in band_5:
            pe_val = s.pe_tick.oi if (hasattr(s, "pe_tick") and s.pe_tick and s.pe_tick.oi is not None) else getattr(s, "pe_oi", None)
            ce_val = s.ce_tick.oi if (hasattr(s, "ce_tick") and s.ce_tick and s.ce_tick.oi is not None) else getattr(s, "ce_oi", None)
            if pe_val is not None:
                pe_5_ois.append(pe_val)
            if ce_val is not None:
                ce_5_ois.append(ce_val)

        sum_pe_5 = sum(pe_5_ois) if pe_5_ois else None
        sum_ce_5 = sum(ce_5_ois) if ce_5_ois else None

        if sum_pe_5 is None or sum_ce_5 is None or sum_ce_5 <= 0:
            atm_5_pcr = None
        else:
            atm_5_pcr = round(sum_pe_5 / sum_ce_5, 4)
            if math.isinf(atm_5_pcr) or math.isnan(atm_5_pcr):
                atm_5_pcr = None

        # Interpretation
        if total_pcr is not None:
            if total_pcr < 0.6:
                interp = "EXTREME BEARISH"
            elif total_pcr < 0.8:
                interp = "BEARISH"
            elif total_pcr < 1.0:
                interp = "NEUTRAL"
            elif total_pcr < 1.2:
                interp = "BULLISH"
            else:
                interp = "EXTREME BULLISH"
        else:
            interp = "UNAVAILABLE"

        return {
            "total_pcr": total_pcr,
            "atm_pcr": atm_pcr,
            "atm_5_pcr": atm_5_pcr,
            "total_pe_oi": total_pe_oi,
            "total_ce_oi": total_ce_oi,
            "pcr_status": total_status,
            "pcr_interpretation": interp,
            "timestamp": snapshot.metadata.market_timestamp or snapshot.timestamp,
            "missing_strike_count": max(0, 11 - len(band_5)),
            "strike_window_size": len(band_5)
        }


pcr_engine = PCREngine()
