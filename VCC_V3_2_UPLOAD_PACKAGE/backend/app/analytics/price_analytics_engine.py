"""
Price Analytics Engine for VCC V3.2.
Computes price confirmation score, direction score, velocity score, acceleration score,
wall interaction state, breakout pressure score, breakout status, and range compression.
Uses exact baseline business logic.
"""
from typing import Dict, Any, Optional
from app.domain.contracts import MarketSnapshot


class PriceAnalyticsEngine:

    @staticmethod
    def compute_price_analytics(
        snapshot: MarketSnapshot,
        index_data: Optional[Dict[str, Any]] = None,
        snap_5m: Optional[Any] = None,
        snap_15m: Optional[Any] = None,
        strongest_pe_strike: float = 0.0,
        strongest_ce_strike: float = 0.0,
        pe_chg_5: float = 0.0,
        ce_chg_5: float = 0.0
    ) -> Dict[str, Any]:
        spot_price = snapshot.spot.spot_price
        day_open = index_data.get("open", spot_price) if index_data else spot_price

        # Intraday open change % -> Direction score
        spot_chg_open_pct = ((spot_price - day_open) / max(1.0, day_open)) * 100.0
        direction_score = max(-100, min(100, int(round(spot_chg_open_pct * 120.0))))

        # 15m Velocity score
        spot_5m_ago = snap_5m.spot_price if snap_5m and hasattr(snap_5m, 'spot_price') else day_open
        spot_15m_ago = snap_15m.spot_price if snap_15m and hasattr(snap_15m, 'spot_price') else day_open
        spot_15m_chg = spot_price - spot_15m_ago
        velocity_score = max(-100, min(100, int(round((spot_15m_chg / max(1.0, spot_price * 0.002)) * 30.0))))

        # Acceleration score
        spot_5m_chg_current = spot_price - spot_5m_ago
        spot_5m_chg_prev = spot_5m_ago - (snap_15m.spot_price if snap_15m and hasattr(snap_15m, 'spot_price') else spot_5m_ago)
        accel_pts = spot_5m_chg_current - spot_5m_chg_prev
        accel_score = max(-100, min(100, int(round((accel_pts / max(1.0, spot_price * 0.001)) * 25.0))))

        # Wall Interaction State & Score
        has_ce = (strongest_ce_strike is not None and strongest_ce_strike > 0)
        has_pe = (strongest_pe_strike is not None and strongest_pe_strike > 0)

        dist_to_ce = (strongest_ce_strike - spot_price) if has_ce else 999999.0
        dist_to_pe = (spot_price - strongest_pe_strike) if has_pe else 999999.0

        if has_ce and abs(dist_to_ce) <= (spot_price * 0.001):
            wall_interaction_state = "TESTING RESISTANCE (CE)"
            wall_interaction_score = -20
        elif has_pe and abs(dist_to_pe) <= (spot_price * 0.001):
            wall_interaction_state = "TESTING SUPPORT (PE)"
            wall_interaction_score = +20
        elif has_ce and spot_price > strongest_ce_strike:
            wall_interaction_state = "ACCEPTED ABOVE RESISTANCE (BREAKOUT)"
            wall_interaction_score = +60
        elif has_pe and spot_price < strongest_pe_strike:
            wall_interaction_state = "ACCEPTED BELOW SUPPORT (BREAKDOWN)"
            wall_interaction_score = -60
        elif has_ce and dist_to_ce < 30 and spot_15m_chg > 0:
            wall_interaction_state = "APPROACHING RESISTANCE"
            wall_interaction_score = +15
        elif has_pe and dist_to_pe < 30 and spot_15m_chg < 0:
            wall_interaction_state = "APPROACHING SUPPORT"
            wall_interaction_score = -15
        else:
            wall_interaction_state = "RANGING BETWEEN WALLS" if (has_ce and has_pe) else "WALLS UNAVAILABLE"
            wall_interaction_score = 0

        # Price Confirmation Score
        price_conf_score = int(round(
            0.35 * direction_score +
            0.30 * velocity_score +
            0.15 * accel_score +
            0.20 * wall_interaction_score
        ))
        price_conf_score = max(-100, min(100, price_conf_score))

        price_conf_label = "STRONG BULLISH" if price_conf_score >= 40 else (
            "WEAK BULLISH" if price_conf_score >= 10 else (
                "WEAK BEARISH" if price_conf_score >= -40 else "STRONG BEARISH"
            )
        )

        # Breakout Pressure & Status
        breakout_pressure = max(10, min(99, int(50 + (pe_chg_5 - ce_chg_5) / 2500.0)))
        if has_ce and price_conf_score > 30 and spot_price >= strongest_ce_strike:
            breakout_status = "UPSIDE BREAKOUT CONFIRMED"
        elif has_pe and price_conf_score < -30 and spot_price <= strongest_pe_strike:
            breakout_status = "DOWNSIDE BREAKDOWN CONFIRMED"
        elif breakout_pressure >= 70 and price_conf_score < 10:
            breakout_status = "SETUP BUILDING / NOT CONFIRMED"
        elif (has_ce and abs(dist_to_ce) < 30) or (has_pe and abs(dist_to_pe) < 30):
            breakout_status = "BREAKOUT TESTING"
        else:
            breakout_status = "NO BREAKOUT"

        return {
            "score": price_conf_score,
            "label": price_conf_label,
            "direction_score": direction_score,
            "velocity_score": velocity_score,
            "acceleration_score": accel_score,
            "wall_interaction_state": wall_interaction_state,
            "wall_interaction_score": wall_interaction_score,
            "spot_chg_open_pct": round(spot_chg_open_pct, 2),
            "spot_15m_chg": round(spot_15m_chg, 2),
            "breakout_pressure": breakout_pressure,
            "breakout_status": breakout_status
        }


price_analytics_engine = PriceAnalyticsEngine()
