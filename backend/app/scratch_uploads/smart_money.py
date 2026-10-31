"""
Institutional Smart Money & Order Flow Intelligence
Tracks net option capital deployment in ₹ Crores and conviction score.
"""
from typing import Dict, Any, List
from app.services.option_chain import ParsedOptionChain


class SmartMoneyService:
    """Computes institutional premium flows and conviction velocity."""

    def __init__(self):
        self._last_computed: Dict[str, Dict[str, Any]] = {}

    def compute(self, chain: ParsedOptionChain) -> Dict[str, Any]:
        if not chain:
            return {
                "conviction_score": 50,
                "net_flow_cr": 0.0,
                "pe_flow_cr": 0.0,
                "ce_flow_cr": 0.0,
                "bias": "NEUTRAL",
                "label": "NEUTRAL FLOW"
            }

        atm = chain.atm_strike
        step = 50 if "BANK" not in chain.symbol else 100
        
        # Calculate capital deployment within ATM ± 5 strikes
        atm_strikes = [s for s in chain.strikes if abs(s.strikePrice - atm) <= (5 * step)]
        
        ce_value_cr = 0.0
        pe_value_cr = 0.0

        for s in atm_strikes:
            # Positive change in OI * LTP represents net new institutional capital deployment
            if s.CE.changeinOpenInterest > 0 and s.CE.lastPrice > 0:
                ce_value_cr += (s.CE.changeinOpenInterest * s.CE.lastPrice) / 10000000.0  # ₹ Crores
            if s.PE.changeinOpenInterest > 0 and s.PE.lastPrice > 0:
                pe_value_cr += (s.PE.changeinOpenInterest * s.PE.lastPrice) / 10000000.0  # ₹ Crores

        ce_value_cr = round(ce_value_cr, 2)
        pe_value_cr = round(pe_value_cr, 2)
        net_flow = round(pe_value_cr - ce_value_cr, 2)

        # Conviction score (0 to 100)
        # Put writing > Call writing means smart money is protecting lower strikes (bullish)
        tot_flow = max(1.0, ce_value_cr + pe_value_cr)
        flow_ratio = pe_value_cr / tot_flow
        conviction = int(max(10, min(95, round(flow_ratio * 100))))

        if net_flow > 15.0:
            bias = "STRONG BULLISH"
            label = "HEAVY PUT WRITING / SMART MONEY SUPPORT"
        elif net_flow > 4.0:
            bias = "MODERATE BULLISH"
            label = "MILD PUT ACCUMULATION"
        elif net_flow < -15.0:
            bias = "STRONG BEARISH"
            label = "HEAVY CALL WRITING / RESISTANCE WALL BUILDING"
        elif net_flow < -4.0:
            bias = "MODERATE BEARISH"
            label = "MILD CALL RESISTANCE"
        else:
            bias = "NEUTRAL"
            label = "BALANCED INSTITUTIONAL POSITIONING"

        from app.core.market_hours import get_current_ist
        res = {
            "symbol": chain.symbol,
            "timestamp": get_current_ist().isoformat(),
            "conviction_score": conviction,
            "net_flow_cr": net_flow,
            "pe_flow_cr": pe_value_cr,
            "ce_flow_cr": ce_value_cr,
            "bias": bias,
            "label": label
        }
        self._last_computed[chain.symbol.upper()] = res
        return res

    def get_smart_money_analysis(self, symbol: str) -> Dict[str, Any]:
        """Returns the latest smart money flow analysis for a symbol."""
        sym = symbol.upper()
        if sym in self._last_computed:
            return self._last_computed[sym]
        return {
            "symbol": sym,
            "conviction_score": 50,
            "net_flow_cr": 0.0,
            "pe_flow_cr": 0.0,
            "ce_flow_cr": 0.0,
            "bias": "NEUTRAL",
            "label": "NEUTRAL FLOW"
        }


smart_money_service = SmartMoneyService()
