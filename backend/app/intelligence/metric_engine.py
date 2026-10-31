"""
Layer 3 Intelligence: Metric Engine
Calculates PCR, Institutional OI Walls, Max Pain, and ATM ± 2 Corridor.
"""
from typing import Dict, Any, List
from app.market_data.instrument_state import OptionChainSnapshot

class MetricEngine:
    @staticmethod
    def compute_chain_metrics(chain: OptionChainSnapshot) -> Dict[str, Any]:
        """Calculates institutional positioning from a normalized option chain snapshot."""
        if not chain or not chain.strikes:
            return {}

        total_ce_oi = 0
        total_pe_oi = 0
        total_ce_oich = 0
        total_pe_oich = 0

        max_ce_oi = -1
        max_pe_oi = -1
        ce_wall_strike = 0.0
        pe_wall_strike = 0.0

        for strike, data in chain.strikes.items():
            total_ce_oi += data.ce_oi
            total_pe_oi += data.pe_oi
            total_ce_oich += data.ce_oich
            total_pe_oich += data.pe_oich

            if data.ce_oi > max_ce_oi:
                max_ce_oi = data.ce_oi
                ce_wall_strike = strike

            if data.pe_oi > max_pe_oi:
                max_pe_oi = data.pe_oi
                pe_wall_strike = strike

        # Put/Call Ratio (PCR)
        pcr = round(total_pe_oi / max(1, total_ce_oi), 2)
        pcr_sentiment = "BULLISH" if pcr > 1.2 else ("BEARISH" if pcr < 0.8 else "NEUTRAL")

        # Writer Pressure percentage
        total_oi = max(1, total_ce_oi + total_pe_oi)
        pe_writer_pct = round((total_pe_oi / total_oi) * 100, 1)
        ce_writer_pct = round((total_ce_oi / total_oi) * 100, 1)

        # ATM ± 2 Corridor
        sorted_strikes = sorted(list(chain.strikes.keys()))
        atm = chain.atm_strike
        atm_idx = min(range(len(sorted_strikes)), key=lambda i: abs(sorted_strikes[i] - atm)) if sorted_strikes else 0

        corridor_start = max(0, atm_idx - 2)
        corridor_end = min(len(sorted_strikes), atm_idx + 3)
        corridor_strikes = [chain.strikes[s] for s in sorted_strikes[corridor_start:corridor_end]]

        return {
            "symbol": chain.symbol,
            "spot_price": chain.spot_price,
            "spot_change": chain.spot_change,
            "spot_pchange": chain.spot_pchange,
            "atm_strike": atm,
            "pcr": pcr,
            "pcr_sentiment": pcr_sentiment,
            "pe_writer_pct": pe_writer_pct,
            "ce_writer_pct": ce_writer_pct,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "net_oi_change": total_pe_oich - total_ce_oich,
            "ce_wall": {
                "strike": ce_wall_strike,
                "oi": max_ce_oi,
                "label": f"{int(ce_wall_strike)} CE"
            },
            "pe_wall": {
                "strike": pe_wall_strike,
                "oi": max_pe_oi,
                "label": f"{int(pe_wall_strike)} PE"
            },
            "corridor": [s.model_dump() for s in corridor_strikes],
            "timestamp": chain.timestamp
        }

metric_engine = MetricEngine()
