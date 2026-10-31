"""
Canonical Call Wall and Put Wall Analytics Engine for VCC V3.2.
Provides authoritative, real-data-only structural OI concentration calculation.
Strictly enforces:
1. K_call_wall = argmax CE_OI(K) for K >= ATM (actual available strikes with valid CE OI).
2. K_put_wall  = argmax PE_OI(K) for K <= ATM (actual available strikes with valid PE OI).
3. Independent wall availability (returns None / UNAVAILABLE when invalid or missing).
4. Deterministic tie-breaking (closest to ATM).
5. Zero fallback / zero synthetic strike substitution.
"""
import logging
from typing import Dict, List, Any, Optional, Tuple
from app.domain.contracts import MarketSnapshot, DataQuality

logger = logging.getLogger(__name__)


class WallEngine:
    """
    Canonical Wall Engine for VCC V3.2.
    Single authoritative calculation path for Structural Call Wall and Put Wall.
    """

    @staticmethod
    def compute_walls(snapshot: MarketSnapshot) -> Dict[str, Any]:
        """
        Computes canonical Call Wall and Put Wall for a MarketSnapshot.
        Returns strongly-typed dict with independent availability status.
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
                "call_wall_strike": None,
                "call_wall_oi": None,
                "call_wall_status": "UNAVAILABLE",
                "put_wall_strike": None,
                "put_wall_oi": None,
                "put_wall_status": "UNAVAILABLE",
                "atm_strike": snapshot.option_chain.atm_strike if (snapshot and snapshot.option_chain) else None,
                "market_timestamp": snapshot.metadata.market_timestamp if snapshot else None,
                "data_age_seconds": snapshot.metadata.data_age_seconds if snapshot else None,
                "valid_call_candidate_count": 0,
                "valid_put_candidate_count": 0,
                "tie_occurred_call": False,
                "tie_occurred_put": False,
                "reason": "INVALID_OR_UNAVAILABLE_MARKET_FEED"
            }

        strikes = snapshot.option_chain.strikes
        atm_strike = snapshot.option_chain.atm_strike

        # ----------------------------------------------------
        # 1. CANONICAL CALL WALL (Strikes K >= ATM with valid CE OI > 0)
        # ----------------------------------------------------
        call_candidates = []
        for s in strikes:
            if s.strike_price >= atm_strike:
                ce_oi = s.ce_tick.oi if (hasattr(s, "ce_tick") and s.ce_tick and s.ce_tick.oi is not None) else getattr(s, "ce_oi", None)
                if ce_oi is not None and ce_oi > 0:
                    call_candidates.append((s.strike_price, int(ce_oi)))

        if not call_candidates:
            call_wall_strike = None
            call_wall_oi = None
            call_wall_status = "UNAVAILABLE"
            tie_call = False
        else:
            max_ce_oi = max(c[1] for c in call_candidates)
            best_call_strikes = [c for c in call_candidates if c[1] == max_ce_oi]
            tie_call = len(best_call_strikes) > 1
            # Deterministic Tie-Break: Closest to ATM (smallest strike K >= ATM)
            best_call_strikes.sort(key=lambda c: c[0])
            call_wall_strike = float(best_call_strikes[0][0])
            call_wall_oi = int(best_call_strikes[0][1])
            call_wall_status = "AVAILABLE"

        # ----------------------------------------------------
        # 2. CANONICAL PUT WALL (Strikes K <= ATM with valid PE OI > 0)
        # ----------------------------------------------------
        put_candidates = []
        for s in strikes:
            if s.strike_price <= atm_strike:
                pe_oi = s.pe_tick.oi if (hasattr(s, "pe_tick") and s.pe_tick and s.pe_tick.oi is not None) else getattr(s, "pe_oi", None)
                if pe_oi is not None and pe_oi > 0:
                    put_candidates.append((s.strike_price, int(pe_oi)))

        if not put_candidates:
            put_wall_strike = None
            put_wall_oi = None
            put_wall_status = "UNAVAILABLE"
            tie_put = False
        else:
            max_pe_oi = max(p[1] for p in put_candidates)
            best_put_strikes = [p for p in put_candidates if p[1] == max_pe_oi]
            tie_put = len(best_put_strikes) > 1
            # Deterministic Tie-Break: Closest to ATM (largest strike K <= ATM)
            best_put_strikes.sort(key=lambda p: p[0], reverse=True)
            put_wall_strike = float(best_put_strikes[0][0])
            put_wall_oi = int(best_put_strikes[0][1])
            put_wall_status = "AVAILABLE"

        return {
            "call_wall_strike": call_wall_strike,
            "call_wall_oi": call_wall_oi,
            "call_wall_status": call_wall_status,
            "put_wall_strike": put_wall_strike,
            "put_wall_oi": put_wall_oi,
            "put_wall_status": put_wall_status,
            "atm_strike": atm_strike,
            "market_timestamp": snapshot.metadata.market_timestamp or snapshot.timestamp,
            "data_age_seconds": snapshot.metadata.data_age_seconds,
            "valid_call_candidate_count": len(call_candidates),
            "valid_put_candidate_count": len(put_candidates),
            "tie_occurred_call": tie_call,
            "tie_occurred_put": tie_put
        }


wall_engine = WallEngine()
