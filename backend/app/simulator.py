"""
High-Fidelity Market Simulator & Fallback Ingestion Engine
Serves realistic options market data when offline, off-market, or when live broker feeds are unavailable.
"""
import math
import random
from typing import Dict, Any, List
from datetime import datetime

BASE_SPOTS = {
    "NIFTY": 23240.80,
    "BANKNIFTY": 56171.85,
    "FINNIFTY": 25216.15,
    "MIDCPNIFTY": 14283.05,
    "SENSEX": 81520.50
}

STRIKE_STEPS = {
    "NIFTY": 50,
    "BANKNIFTY": 100,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "SENSEX": 100
}


class MarketSimulator:
    """Generates deterministic, high-fidelity synthetic market data for fallback/offline use."""

    def get_indices(self) -> Dict[str, Any]:
        """Returns live ticker cards for the 5 tracked indices."""
        indices = []
        for sym, base in BASE_SPOTS.items():
            name_map = {
                "NIFTY": "NIFTY 50",
                "BANKNIFTY": "BANK NIFTY",
                "FINNIFTY": "FIN NIFTY",
                "MIDCPNIFTY": "MIDCAP NIFTY",
                "SENSEX": "BSE SENSEX"
            }
            chg = round(base * 0.0045, 2)
            pct = 0.45
            indices.append({
                "symbol": sym,
                "name": name_map.get(sym, sym),
                "last": base,
                "change": chg,
                "percent_change": pct,
                "open": round(base - chg, 2),
                "high": round(base * 1.006, 2),
                "low": round(base * 0.994, 2),
                "previous_close": round(base - chg, 2),
                "timestamp": datetime.now().isoformat()
            })

        return {
            "source": "SIMULATOR",
            "indices": indices,
            "vix": {"current": 13.5, "change": -0.15, "percent_change": -1.1},
            "breadth": {"advances": 32, "declines": 18, "ratio": 1.78}
        }

    def get_option_chain(self, symbol: str = "NIFTY") -> Dict[str, Any]:
        """Generates realistic full option chain for symbol."""
        sym = symbol.upper()
        spot = BASE_SPOTS.get(sym, 23240.80)
        step = STRIKE_STEPS.get(sym, 50)
        atm = round(spot / step) * step

        strikes_data = []
        tot_ce_oi = 0
        tot_pe_oi = 0

        # Generate 41 strikes (ATM ± 20)
        for i in range(-20, 21):
            strike = int(atm + (i * step))
            dist = strike - spot

            # Realistic OI curve peaking at major round numbers / OTM walls
            ce_base = max(10000, int(150000 * math.exp(-0.5 * ((strike - (atm + 3 * step)) / (4 * step)) ** 2)))
            pe_base = max(10000, int(170000 * math.exp(-0.5 * ((strike - (atm - 3 * step)) / (4 * step)) ** 2)))

            ce_oi = ce_base + (strike % 500 == 0) * 80000
            pe_oi = pe_base + (strike % 500 == 0) * 95000

            ce_oi_chg = int(ce_oi * 0.08 * (1 if dist > 0 else -0.3))
            pe_oi_chg = int(pe_oi * 0.12 * (1 if dist < 0 else -0.2))

            # Pricing
            ce_iv = max(9.0, min(24.0, 13.5 + (dist / 100.0) * 0.1))
            ce_intrinsic = max(0.0, spot - strike)
            ce_time_val = max(5.0, (140.0 - abs(dist) * 0.4))
            ce_ltp = round(ce_intrinsic + ce_time_val, 2)

            pe_iv = max(9.0, min(24.0, 14.0 - (dist / 100.0) * 0.1))
            pe_intrinsic = max(0.0, strike - spot)
            pe_time_val = max(5.0, (140.0 - abs(dist) * 0.4))
            pe_ltp = round(pe_intrinsic + pe_time_val, 2)

            tot_ce_oi += ce_oi
            tot_pe_oi += pe_oi

            strikes_data.append({
                "strikePrice": float(strike),
                "expiryDate": "CURRENT",
                "CE": {
                    "strikePrice": float(strike),
                    "lastPrice": ce_ltp,
                    "change": round(ce_ltp * 0.03, 2),
                    "pChange": 3.0,
                    "openInterest": ce_oi,
                    "changeinOpenInterest": ce_oi_chg,
                    "totalTradedVolume": ce_oi * 3,
                    "impliedVolatility": round(ce_iv, 1),
                    "bidprice": round(ce_ltp - 0.5, 2),
                    "askPrice": round(ce_ltp + 0.5, 2)
                },
                "PE": {
                    "strikePrice": float(strike),
                    "lastPrice": pe_ltp,
                    "change": round(-pe_ltp * 0.025, 2),
                    "pChange": -2.5,
                    "openInterest": pe_oi,
                    "changeinOpenInterest": pe_oi_chg,
                    "totalTradedVolume": pe_oi * 3,
                    "impliedVolatility": round(pe_iv, 1),
                    "bidprice": round(pe_ltp - 0.5, 2),
                    "askPrice": round(pe_ltp + 0.5, 2)
                }
            })

        return {
            "records": {
                "underlyingValue": spot,
                "expiryDates": ["CURRENT", "NEXT_WEEK", "MONTH_END"],
                "data": strikes_data,
                "total_ce_oi": tot_ce_oi,
                "total_pe_oi": tot_pe_oi,
                "pcr": round(tot_pe_oi / max(1, tot_ce_oi), 3)
            },
            "filtered": {
                "data": strikes_data
            }
        }

    def get_intraday_timeline(self, symbol: str = "NIFTY") -> List[Dict[str, Any]]:
        """Generates realistic time series from 09:15 to 15:40 IST."""
        sym = symbol.upper()
        base_spot = BASE_SPOTS.get(sym, 23240.80)

        times = [
            "09:15", "09:30", "09:45", "10:00", "10:15", "10:30", "10:45",
            "11:00", "11:15", "11:30", "11:45", "12:00", "12:15", "12:30",
            "12:45", "13:00", "13:15", "13:30", "13:45", "14:00", "14:15",
            "14:30", "14:45", "15:00", "15:15", "15:30", "15:40"
        ]

        timeline = []
        base_ce = 14500000
        base_pe = 16800000

        for idx, t in enumerate(times):
            frac = idx / (len(times) - 1)
            spot_drift = math.sin(frac * math.pi * 2.2) * (base_spot * 0.003) + (frac * base_spot * 0.0015)
            curr_spot = round(base_spot + spot_drift, 2)

            growth = 0.70 + (0.30 * (idx + 1) / len(times))
            c_oi = int(base_ce * growth + (math.sin(idx * 0.6) * 350000))
            p_oi = int(base_pe * growth + (math.cos(idx * 0.4) * 480000))

            timeline.append({
                "time": t,
                "timestamp": f"2026-09-20T{t}:00",
                "spot": curr_spot,
                "ce_oi": c_oi,
                "pe_oi": p_oi,
                "ce_oi_chg": int((c_oi - base_ce * 0.70) * 0.4),
                "pe_oi_chg": int((p_oi - base_pe * 0.70) * 0.4),
                "diff_oi": c_oi - p_oi,
                "pcr": round(p_oi / max(1, c_oi), 2)
            })

        return timeline


market_simulator = MarketSimulator()
