"""
Layer 3 Intelligence: Confluence & Directional Engine
Calculates Directional Weightage, Confluence Score (0-100), and Multi-Index Radar.
"""
from typing import Dict, Any, List
import time

class ConfluenceEngine:
    @staticmethod
    def evaluate_directional_bias(metrics: Dict[str, Any], tick_data: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates Directional Weightage and Confluence Score."""
        pcr = metrics.get("pcr", 1.0)
        pchange = tick_data.get("pChange", 0.0)
        net_oi_ch = metrics.get("net_oi_change", 0)

        # Base Confluence Score (0 to 100)
        score = 50.0

        # PCR Factor
        if pcr > 1.3:
            score += 15.0
        elif pcr > 1.1:
            score += 8.0
        elif pcr < 0.7:
            score -= 15.0
        elif pcr < 0.9:
            score -= 8.0

        # Price Momentum Factor
        if pchange > 0.5:
            score += 15.0
        elif pchange > 0.1:
            score += 8.0
        elif pchange < -0.5:
            score -= 15.0
        elif pchange < -0.1:
            score -= 8.0

        # Net OI Delta Factor
        if net_oi_ch > 500000:
            score += 10.0
        elif net_oi_ch < -500000:
            score -= 10.0

        # Bound score between 5.0 and 95.0
        score = max(5.0, min(95.0, score))

        # Directional Weightage Scale (-100% to +100%)
        # Scale: 5 Bearish (-100% to -60%), 4 Bearish (-60% to -40%), Neutral (-20% to +20%), etc.
        weightage_pct = round((score - 50.0) * 2.0, 1)
        scale_intensity = min(5, max(1, int(abs(weightage_pct) / 20.0) + 1))

        if weightage_pct > 20.0:
            bias = "BULLISH"
            advice = f"+{weightage_pct}% BULLISH ({scale_intensity}/5 HEAVY)"
            chop_shield = "CLEAR MOMENTUM"
        elif weightage_pct < -20.0:
            bias = "BEARISH"
            advice = f"{weightage_pct}% BEARISH ({scale_intensity}/5 HEAVY)"
            chop_shield = "CLEAR MOMENTUM"
        else:
            bias = "NEUTRAL"
            advice = "RANGE BOUND / NEUTRAL"
            chop_shield = "🛡️ CHOP SHIELD"

        return {
            "symbol": metrics.get("symbol", "NIFTY"),
            "confluence_score": round(score, 1),
            "weightage_pct": weightage_pct,
            "scale_intensity": scale_intensity,
            "bias": bias,
            "advice": advice,
            "chop_shield": chop_shield,
            "ce_wall": metrics.get("ce_wall", {}).get("label", "--"),
            "pe_wall": metrics.get("pe_wall", {}).get("label", "--"),
            "timestamp": time.time()
        }

    @staticmethod
    def build_multi_index_radar(indices_summary: List[Dict[str, Any]], metrics_by_symbol: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Generates cross-asset comparative radar for all 4 indices."""
        radar = []
        for idx in indices_summary:
            sym = idx.get("symbol", "")
            met = metrics_by_symbol.get(sym, {})
            pcr = met.get("pcr", 1.0)
            pchange = idx.get("pChange", 0.0)

            trend = "BULLISH" if pchange > 0.1 else ("BEARISH" if pchange < -0.1 else "SIDEWAYS")
            stance = "BUY CALL" if pchange > 0.2 and pcr > 1.1 else ("BUY PUT" if pchange < -0.2 and pcr < 0.8 else "WAIT / CHOP")

            radar.append({
                "symbol": sym,
                "spot": idx.get("last", 0.0),
                "pchange": pchange,
                "trend": trend,
                "momentum": "STRONG" if abs(pchange) > 0.4 else "NORMAL",
                "pcr": pcr,
                "stance": stance,
                "net_oi_ch": met.get("net_oi_change", 0)
            })
        return radar

confluence_engine = ConfluenceEngine()
