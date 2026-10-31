"""
Flow Analytics Engine for VCC V3.2.
Computes CE flow, PE flow, net directional flow (₹ Lakhs), total activity,
and flow acceleration status.
Uses exact baseline formulas.
"""
from typing import Dict, List, Any, Optional
from app.domain.contracts import MarketSnapshot


class FlowAnalyticsEngine:

    @staticmethod
    def compute_flow_analytics(
        snapshot: MarketSnapshot,
        strike_matrix: Optional[List[Dict[str, Any]]] = None,
        snap_5m: Optional[Any] = None,
        snap_15m: Optional[Any] = None,
        snap_30m: Optional[Any] = None
    ) -> Dict[str, Any]:
        pe_bullish_lakhs = 0.0
        pe_bearish_lakhs = 0.0
        ce_bullish_lakhs = 0.0
        ce_bearish_lakhs = 0.0

        if strike_matrix:
            for row in strike_matrix:
                pe_act = row.get("pe_action", "")
                pe_doi = row.get("pe_doi_5m_lakhs", 0.0)
                ce_act = row.get("ce_action", "")
                ce_doi = row.get("ce_doi_5m_lakhs", 0.0)

                if "WRITING" in pe_act or "UNWINDING" in pe_act:
                    pe_bullish_lakhs += abs(pe_doi)
                elif "BUILDUP" in pe_act or "COVERING" in pe_act:
                    pe_bearish_lakhs -= abs(pe_doi)

                if "WRITING" in ce_act or "UNWINDING" in ce_act:
                    ce_bearish_lakhs -= abs(ce_doi)
                elif "BUILDUP" in ce_act or "COVERING" in ce_act:
                    ce_bullish_lakhs += abs(ce_doi)

        total_bullish_flow = round(pe_bullish_lakhs + ce_bullish_lakhs, 2)
        total_bearish_flow = round(pe_bearish_lakhs + ce_bearish_lakhs, 2)

        # Fallback if matrix actions are zero
        if total_bullish_flow == 0.0 and total_bearish_flow == 0.0:
            pe_chg = sum(s.pe_tick.oi_change if hasattr(s, 'pe_tick') else getattr(s, 'pe_oi_change', 0) for s in snapshot.option_chain.strikes) if snapshot.option_chain and snapshot.option_chain.strikes else 0
            ce_chg = sum(s.ce_tick.oi_change if hasattr(s, 'ce_tick') else getattr(s, 'ce_oi_change', 0) for s in snapshot.option_chain.strikes) if snapshot.option_chain and snapshot.option_chain.strikes else 0
            total_bullish_flow = round(max(0.0, pe_chg / 100000.0), 2)
            total_bearish_flow = round(-max(0.0, ce_chg / 100000.0), 2)

        pe_flow_lakhs = total_bullish_flow
        ce_flow_lakhs = total_bearish_flow
        net_flow_lakhs = round(total_bullish_flow + total_bearish_flow, 2)
        total_activity_lakhs = round(total_bullish_flow + abs(total_bearish_flow), 2)

        net_flow_current = round((total_bullish_flow + total_bearish_flow) * 100000.0, 2)
        net_flow_5m_ago = (snap_5m.total_pe_chg - snap_5m.total_ce_chg) if (snap_5m and hasattr(snap_5m, 'total_pe_chg')) else (net_flow_current * 0.8)
        net_flow_15m_ago = (snap_15m.total_pe_chg - snap_15m.total_ce_chg) if (snap_15m and hasattr(snap_15m, 'total_pe_chg')) else (net_flow_current * 0.5)

        velocity_5m = net_flow_current - net_flow_5m_ago
        velocity_15m = net_flow_5m_ago - net_flow_15m_ago
        acceleration = velocity_5m - velocity_15m

        if acceleration > 5000:
            flow_status = "ACCELERATING"
        elif acceleration < -5000:
            flow_status = "DECELERATING"
        else:
            flow_status = "STABLE"

        return {
            "pe_flow_lakhs": pe_flow_lakhs,
            "ce_flow_lakhs": ce_flow_lakhs,
            "net_flow_lakhs": net_flow_lakhs,
            "total_activity_lakhs": total_activity_lakhs,
            "directional_flow_label": f"{'+' if net_flow_lakhs >= 0 else ''}{net_flow_lakhs}L {'BULLISH' if net_flow_lakhs >= 0 else 'BEARISH'}",
            "flow_velocity": round(velocity_5m / 1000.0, 1),
            "flow_status": flow_status
        }


flow_analytics_engine = FlowAnalyticsEngine()
