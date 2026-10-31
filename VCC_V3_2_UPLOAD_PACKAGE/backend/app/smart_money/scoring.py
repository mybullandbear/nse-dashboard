"""
Smart Money Conviction, Bias & Direction Scoring Engine for VCC V3.2.
Computes sm_bias_5, ATM ± 5 strike band analysis, market direction score, and actionable trade guide.
Pure analytical module independent of database or network.
"""
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple

from app.domain.contracts import MarketSnapshot
from app.smart_money.models import MarketDirectionDTO

IST = timezone(timedelta(hours=5, minutes=30))


class SmartMoneyScorer:

    def __init__(self):
        self._direction_tracker: Dict[str, dict] = {}

    def compute_scoring(
        self,
        symbol: str,
        snapshot: MarketSnapshot
    ) -> Dict[str, Any]:
        """
        Computes Call/Put writing conviction, Call/Put walls, sm_bias_5,
        market direction score, and actionable trade recommendations.
        """
        sym = symbol.upper()

        if not snapshot or not snapshot.option_chain or not snapshot.option_chain.strikes:
            return self._get_fallback_scoring(sym)

        chain = snapshot.option_chain
        strikes = chain.strikes
        all_strikes_sorted = sorted(strikes, key=lambda s: s.strike_price)
        atm_strike = chain.atm_strike

        # 1. Find ATM Index
        atm_idx = 0
        min_diff = float('inf')
        for i, s in enumerate(all_strikes_sorted):
            diff = abs(s.strike_price - atm_strike)
            if diff < min_diff:
                min_diff = diff
                atm_idx = i

        # 2. ATM ± 15 Band Conviction
        start_band_idx = max(0, atm_idx - 10)
        end_band_idx = min(len(all_strikes_sorted), atm_idx + 11)
        atm_band_strikes = all_strikes_sorted[start_band_idx:end_band_idx]

        def _get_raw_val(s, attr, tick_name, tick_attr) -> Optional[float]:
            v = getattr(s, attr, None)
            if v is not None:
                return float(v)
            tk = getattr(s, tick_name, None)
            if tk is not None:
                tv = getattr(tk, tick_attr, None)
                if tv is not None:
                    return float(tv)
            return None

        ce_oi_vals = [_get_raw_val(s, 'ce_oi', 'ce_tick', 'oi') for s in atm_band_strikes]
        pe_oi_vals = [_get_raw_val(s, 'pe_oi', 'pe_tick', 'oi') for s in atm_band_strikes]

        valid_ce_oi = [v for v in ce_oi_vals if v is not None]
        valid_pe_oi = [v for v in pe_oi_vals if v is not None]

        # If all OI observations across the band are unavailable, trigger explicit fallback
        if not valid_ce_oi and not valid_pe_oi:
            return self._get_fallback_scoring(sym)

        total_ce_oi = sum(valid_ce_oi) if valid_ce_oi else 0.0
        total_pe_oi = sum(valid_pe_oi) if valid_pe_oi else 0.0

        ce_chg_vals = [_get_raw_val(s, 'ce_oi_change', 'ce_tick', 'oi_change') for s in atm_band_strikes]
        pe_chg_vals = [_get_raw_val(s, 'pe_oi_change', 'pe_tick', 'oi_change') for s in atm_band_strikes]

        valid_ce_chg = [v for v in ce_chg_vals if v is not None]
        valid_pe_chg = [v for v in pe_chg_vals if v is not None]

        total_ce_chg = sum(valid_ce_chg) if valid_ce_chg else 0.0
        total_pe_chg = sum(valid_pe_chg) if valid_pe_chg else 0.0

        # Dual-Factor Bounded Conviction Model
        tot_oi_band = total_pe_oi + total_ce_oi
        if tot_oi_band == 0.0:
            s_pos = 50.0
        else:
            s_pos = min(100.0, max(0.0, (total_pe_oi / tot_oi_band) * 100.0))

        tot_chg_denom = max(10000.0, abs(total_pe_chg) + abs(total_ce_chg))
        s_flow = min(100.0, max(0.0, 50.0 + ((total_pe_chg - total_ce_chg) / tot_chg_denom) * 50.0))

        put_conviction = min(99.0, max(20.0, round(0.55 * s_pos + 0.45 * s_flow, 1)))
        call_conviction = min(99.0, max(20.0, round(0.55 * (100.0 - s_pos) + 0.45 * (100.0 - s_flow), 1)))

        # 3. Call Wall & Put Wall
        from app.analytics.wall_engine import wall_engine
        wall_res = wall_engine.compute_walls(snapshot)
        call_wall_strike = wall_res["call_wall_strike"]
        put_wall_strike = wall_res["put_wall_strike"]

        # 4. Top 5 Strikes by combined OI change
        sorted_by_chg = sorted(strikes, key=lambda s: abs(getattr(s, 'ce_oi_change', getattr(getattr(s, 'ce_tick', None), 'oi_change', 0))) + abs(getattr(s, 'pe_oi_change', getattr(getattr(s, 'pe_tick', None), 'oi_change', 0))), reverse=True)[:5]
        top_oi_distribution = []
        for s in sorted_by_chg:
            top_oi_distribution.append({
                "strike": int(s.strike_price),
                "ce_oi_change": float(getattr(s, 'ce_oi_change', getattr(getattr(s, 'ce_tick', None), 'oi_change', 0))),
                "pe_oi_change": float(getattr(s, 'pe_oi_change', getattr(getattr(s, 'pe_tick', None), 'oi_change', 0))),
                "is_atm": s.strike_price == chain.atm_strike
            })

        # Expected decay by EOD
        atm_rows = [s for s in strikes if s.strike_price == chain.atm_strike]
        if atm_rows:
            ce_ltp = float(getattr(atm_rows[0], 'ce_ltp', getattr(getattr(atm_rows[0], 'ce_tick', None), 'ltp', 50)))
            pe_ltp = float(getattr(atm_rows[0], 'pe_ltp', getattr(getattr(atm_rows[0], 'pe_tick', None), 'ltp', 50)))
            atm_ltp = ce_ltp + pe_ltp
        else:
            atm_ltp = 100.0
        expected_decay = round(atm_ltp * 0.45, 2)

        # Net Institutional Bias
        if total_pe_chg > total_ce_chg * 1.2:
            net_bias = "BULLISH FLOOR BUILDING"
        elif total_ce_chg > total_pe_chg * 1.2:
            net_bias = "BEARISH CEILING BUILDING"
        else:
            net_bias = "RANGE-BOUND ACCUMULATION"

        # 5. ATM ± 5 Strike Band Analysis (sm_bias_5 & Market Direction)
        s5_idx = max(0, atm_idx - 5)
        e5_idx = min(len(all_strikes_sorted), atm_idx + 6)
        band_5_strikes = all_strikes_sorted[s5_idx:e5_idx]

        pe_chg_5 = sum(float(getattr(s, 'pe_oi_change', getattr(getattr(s, 'pe_tick', None), 'oi_change', 0))) for s in band_5_strikes)
        ce_chg_5 = sum(float(getattr(s, 'ce_oi_change', getattr(getattr(s, 'ce_tick', None), 'oi_change', 0))) for s in band_5_strikes)
        pcr_val = float(chain.pcr) if (chain and chain.pcr is not None) else None

        flow_denom_5 = max(10000.0, abs(pe_chg_5) + abs(ce_chg_5))
        flow_ratio_5 = (pe_chg_5 - ce_chg_5) / flow_denom_5

        if flow_ratio_5 >= 0.25:
            sm_bias_5 = "BULLISH"
            sm_desc = f"Smart Money PE Writing +{(pe_chg_5/100000.0):.1f}L vs +{(ce_chg_5/100000.0):.1f}L CE (ATM ± 5)"
        elif flow_ratio_5 <= -0.25:
            sm_bias_5 = "BEARISH"
            sm_desc = f"Smart Money CE Writing +{(ce_chg_5/100000.0):.1f}L vs +{(pe_chg_5/100000.0):.1f}L PE (ATM ± 5)"
        else:
            sm_bias_5 = "NEUTRAL"
            sm_desc = "Balanced OI accumulation around ATM ± 5 strikes"

        score = 50
        if sm_bias_5 == "BULLISH":
            score += 25
        elif sm_bias_5 == "BEARISH":
            score -= 25

        if pcr_val is not None:
            if pcr_val >= 1.15:
                score += 15
            elif pcr_val <= 0.85:
                score -= 15

        spot_price = float(snapshot.spot.spot_price)
        if spot_price >= chain.atm_strike:
            score += 10
        else:
            score -= 10

        score = min(99, max(5, score))

        cw_str = str(int(call_wall_strike)) if call_wall_strike is not None else "UNAVAILABLE"
        pw_str = str(int(put_wall_strike)) if put_wall_strike is not None else "UNAVAILABLE"

        if score >= 65:
            status = "BULLISH"
            label = "🟢 BULLISH TREND (BUY DIPS / SELL PE)"
            action = f"Institutional floor solid at {pw_str} PE. Favor selling Put Options near {pw_str} PE or buying CE on dips."
        elif score <= 35:
            status = "BEARISH"
            label = "🔴 BEARISH TREND (SELL RALLIES / SELL CE)"
            action = f"Call resistance wall firm at {cw_str} CE. Favor selling Call Options near {cw_str} CE or buying PE on rallies."
        else:
            status = "NEUTRAL"
            label = "🟡 SIDEWAYS / RANGEBOUND (STRADDLE DECAY)"
            action = f"Market range-bound between {pw_str} PE & {cw_str} CE. Short Straddle / Strangle for EOD decay."

        # Duration Tracker
        now_dt = datetime.now()
        tracker = self._direction_tracker.get(sym)
        if not tracker or tracker.get("status") != status:
            tracker = {
                "status": status,
                "established_at": now_dt,
                "last_evaluated": now_dt
            }
            self._direction_tracker[sym] = tracker
        else:
            tracker["last_evaluated"] = now_dt

        est_dt = tracker["established_at"]
        elapsed_sec = int((now_dt - est_dt).total_seconds())
        mins = elapsed_sec // 60
        hrs = mins // 60
        rem_mins = mins % 60

        duration_str = f"{hrs}h {rem_mins}m" if hrs > 0 else (f"{mins}m" if mins > 0 else f"{max(0, elapsed_sec)}s")
        since_time_str = est_dt.strftime("%H:%M:%S IST")
        last_eval_str = now_dt.strftime("%H:%M:%S IST")

        market_direction = {
            "status": status,
            "label": label,
            "score": score,
            "action": action,
            "sm_bias_5": sm_bias_5,
            "sm_bias_desc": sm_desc,
            "pe_chg_5": pe_chg_5,
            "ce_chg_5": ce_chg_5,
            "pcr": round(pcr_val, 2) if pcr_val is not None else None,
            "since_time": since_time_str,
            "duration": duration_str,
            "last_eval": last_eval_str,
            "established_iso": est_dt.isoformat()
        }

        # High-Conviction Smart Money Score
        pe_ce_chg_denom = max(1.0, abs(pe_chg_5) + abs(ce_chg_5))
        ratio_5 = (pe_chg_5 - ce_chg_5) / pe_ce_chg_denom

        if ratio_5 >= 0.15:
            smart_money_score = min(98, max(75, int(50 + (ratio_5 * 48))))
            net_bias = "BULLISH FLOOR BUILDING"
        elif ratio_5 <= -0.15:
            smart_money_score = min(98, max(75, int(50 + (abs(ratio_5) * 48))))
            net_bias = "BEARISH CEILING BUILDING"
        else:
            smart_money_score = max(50, min(65, int(50 + (abs(ratio_5) * 35))))
            net_bias = "NEUTRAL / STRADDLE ZONE"

        # OI Chart Data for ATM ± 10 Strikes
        start_chart_idx = max(0, atm_idx - 10)
        end_chart_idx = min(len(all_strikes_sorted), atm_idx + 11)
        chart_rows = all_strikes_sorted[start_chart_idx:end_chart_idx]
        oi_chart_data = []
        for s in chart_rows:
            ce_oi = _get_raw_val(s, 'ce_oi', 'ce_tick', 'oi') or 0.0
            pe_oi = _get_raw_val(s, 'pe_oi', 'pe_tick', 'oi') or 0.0
            ce_oi_chg = _get_raw_val(s, 'ce_oi_change', 'ce_tick', 'oi_change') or 0.0
            pe_oi_chg = _get_raw_val(s, 'pe_oi_change', 'pe_tick', 'oi_change') or 0.0
            oi_chart_data.append({
                "strike": int(s.strike_price),
                "ce_oi": ce_oi,
                "ce_oi_change": ce_oi_chg,
                "pe_oi": pe_oi,
                "pe_oi_change": pe_oi_chg,
                "prev_ce_oi": max(0.0, ce_oi - ce_oi_chg),
                "prev_pe_oi": max(0.0, pe_oi - pe_oi_chg),
                "ce_day_diff": ce_oi_chg,
                "pe_day_diff": pe_oi_chg,
            })

        return {
            "call_conviction": call_conviction,
            "put_conviction": put_conviction,
            "call_wall_strike": call_wall_strike,
            "put_wall_strike": put_wall_strike,
            "expected_decay": expected_decay,
            "net_bias": net_bias,
            "smart_money_score": smart_money_score,
            "top_oi_distribution": top_oi_distribution,
            "market_direction": market_direction,
            "oi_chart_data": oi_chart_data
        }

    def _get_fallback_scoring(self, symbol: str) -> Dict[str, Any]:
        return {
            "call_conviction": 0.0,
            "put_conviction": 0.0,
            "call_wall_strike": None,
            "put_wall_strike": None,
            "expected_decay": 0.0,
            "net_bias": "DATA_UNAVAILABLE",
            "smart_money_score": 0.0,
            "top_oi_distribution": [],
            "market_direction": {
                "status": "UNAVAILABLE",
                "label": "DATA UNAVAILABLE",
                "score": 0.0,
                "action": "Insufficient market data.",
                "sm_bias_5": "NEUTRAL",
                "sm_bias_desc": "Data unavailable",
                "pe_chg_5": 0,
                "ce_chg_5": 0,
                "pcr": 0.0
            },
            "oi_chart_data": []
        }


smart_money_scorer = SmartMoneyScorer()
