"""
Option Analytics Engine for VCC V3.2.
Computes ATM strike, PCR variants, strike concentration, support/resistance walls,
wall migration velocity (pts/hr), straddle premium & decay, and ATM pressure payload.
Uses exact baseline formulas.
"""
from typing import Dict, List, Any, Tuple, Optional
from app.domain.contracts import MarketSnapshot
from app.core.constants import system_config


class OptionAnalyticsEngine:

    @staticmethod
    def compute_atm_strike(spot_price: float, symbol: str) -> float:
        step = system_config.symbols.get_strike_step(symbol)
        return round(spot_price / step) * step

    @staticmethod
    def compute_option_analytics(
        snapshot: MarketSnapshot,
        db_snaps: Optional[List[Any]] = None,
        historical_snapshots: Optional[List[MarketSnapshot]] = None,
        previous_snapshot: Optional[MarketSnapshot] = None
    ) -> Dict[str, Any]:
        symbol = snapshot.symbol.upper()
        spot_price = snapshot.spot.spot_price
        chain = snapshot.option_chain
        atm_strike = chain.atm_strike if chain and chain.atm_strike > 0 else OptionAnalyticsEngine.compute_atm_strike(spot_price, symbol)
        from app.analytics.pcr_engine import pcr_engine
        pcr_res = pcr_engine.compute_pcr(snapshot)
        pcr_val = pcr_res["total_pcr"]
        pcr_status = pcr_res["pcr_status"]

        all_sorted = sorted(chain.strikes, key=lambda s: s.strike_price) if (chain and chain.strikes) else []
        atm_idx = 0
        min_diff = float('inf')
        for i, s in enumerate(all_sorted):
            d = abs(s.strike_price - atm_strike)
            if d < min_diff:
                min_diff = d
                atm_idx = i

        band_5 = all_sorted[max(0, atm_idx - 5):min(len(all_sorted), atm_idx + 6)] if all_sorted else []
        pe_oi_5 = sum((s.pe_tick.oi if hasattr(s, 'pe_tick') and s.pe_tick and s.pe_tick.oi is not None else getattr(s, 'pe_oi', 0) or 0) for s in band_5)
        ce_oi_5 = sum((s.ce_tick.oi if hasattr(s, 'ce_tick') and s.ce_tick and s.ce_tick.oi is not None else getattr(s, 'ce_oi', 0) or 0) for s in band_5)
        pe_chg_5 = sum((s.pe_tick.oi_change if hasattr(s, 'pe_tick') and s.pe_tick and s.pe_tick.oi_change is not None else getattr(s, 'pe_oi_change', 0) or 0) for s in band_5)
        ce_chg_5 = sum((s.ce_tick.oi_change if hasattr(s, 'ce_tick') and s.ce_tick and s.ce_tick.oi_change is not None else getattr(s, 'ce_oi_change', 0) or 0) for s in band_5)

        # Support Wall (Max Put OI <= ATM) vs Resistance Wall (Max Call OI >= ATM)
        from app.analytics.wall_engine import wall_engine
        wall_res = wall_engine.compute_walls(snapshot)
        strongest_pe_strike = wall_res["put_wall_strike"]
        strongest_ce_strike = wall_res["call_wall_strike"]

        # Option Positioning Score (-100 to +100)
        pe_ce_denom = max(1.0, float(pe_oi_5 + ce_oi_5))
        oi_ratio_score = ((pe_oi_5 - ce_oi_5) / pe_ce_denom) * 100.0

        chg_denom = max(1.0, float(abs(pe_chg_5) + abs(ce_chg_5)))
        oi_chg_score = ((pe_chg_5 - ce_chg_5) / chg_denom) * 100.0

        if pcr_val is not None:
            pcr_score = (pcr_val - 1.0) * 100.0
            option_positioning_score = int(round(0.40 * oi_chg_score + 0.35 * oi_ratio_score + 0.25 * pcr_score))
        else:
            # PCR is unavailable: exclude pcr_score from weighting to prevent silent bias
            option_positioning_score = int(round(0.55 * oi_chg_score + 0.45 * oi_ratio_score))

        option_positioning_score = max(-100, min(100, option_positioning_score))

        pos_label = "BULLISH" if option_positioning_score >= 25 else (
            "BEARISH" if option_positioning_score <= -25 else (
                "BULLISH / MIXED" if option_positioning_score > 0 else "BEARISH / MIXED"
            )
        )

        # ATM Pressure Score & Payload
        tot_ce_band = max(1, ce_oi_5)
        tot_pe_band = max(1, pe_oi_5)
        ce_press_score = int(round((tot_ce_band / max(1.0, tot_ce_band + tot_pe_band)) * 100.0))
        pe_press_score = int(round((tot_pe_band / max(1.0, tot_ce_band + tot_pe_band)) * 100.0))
        net_press_val = pe_press_score - ce_press_score
        net_press_label = f"+{net_press_val} PE" if net_press_val >= 0 else f"{net_press_val} CE"

        atm_pressure_payload = {
            "atm_strike": int(atm_strike),
            "ce_pressure": ce_press_score,
            "pe_pressure": pe_press_score,
            "net_pressure": net_press_val,
            "net_pressure_label": net_press_label,
            "bias": "BULLISH SUPPORT FLOOR" if net_press_val > 10 else ("BEARISH OVERHEAD RESISTANCE" if net_press_val < -10 else "NEUTRAL BALANCE")
        }

        # Straddle Analytics
        atm_obj = next((s for s in band_5 if s.strike_price == atm_strike), band_5[0] if band_5 else None)
        if atm_obj:
            ce_ltp = atm_obj.ce_tick.ltp if hasattr(atm_obj, 'ce_tick') else getattr(atm_obj, 'ce_ltp', 0.0)
            pe_ltp = atm_obj.pe_tick.ltp if hasattr(atm_obj, 'pe_tick') else getattr(atm_obj, 'pe_ltp', 0.0)
            straddle_curr = round(ce_ltp + pe_ltp, 2)
        else:
            straddle_curr = 0.0

        from app.analytics.wall_velocity_engine import wall_velocity_engine
        vel_res = wall_velocity_engine.compute_wall_velocity(
            current_snapshot=snapshot,
            historical_snapshots=historical_snapshots,
            previous_snapshot=previous_snapshot
        )

        return {
            "atm_strike": atm_strike,
            "pcr": pcr_val,
            "pcr_status": pcr_status,
            "pcr_details": pcr_res,
            "pe_oi_5m": pe_oi_5,
            "ce_oi_5m": ce_oi_5,
            "pe_chg_5m": pe_chg_5,
            "ce_chg_5m": ce_chg_5,
            "support_wall": strongest_pe_strike,
            "resistance_wall": strongest_ce_strike,
            "wall_migration_direction": vel_res["call_wall_migration_direction"] if vel_res["call_wall_migration_direction"] != "UNAVAILABLE" else vel_res["put_wall_migration_direction"],
            "call_wall_velocity": vel_res["call_wall_velocity"],
            "call_wall_velocity_status": vel_res["call_wall_velocity_status"],
            "put_wall_velocity": vel_res["put_wall_velocity"],
            "put_wall_velocity_status": vel_res["put_wall_velocity_status"],
            "wall_velocity_details": vel_res,
            "positioning_score": option_positioning_score,
            "positioning_label": pos_label,
            "atm_pressure": atm_pressure_payload,
            "straddle_premium": straddle_curr
        }


option_analytics_engine = OptionAnalyticsEngine()
