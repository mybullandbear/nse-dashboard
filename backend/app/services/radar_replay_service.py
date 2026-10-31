"""
Radar Replay Service: Historical Intraday Time-Travel & Audit Engine
Powers the Visual 'Whole-Day Replay / Timeline' feature for the Multi-Index Institutional Command Radar.
Allows traders to scrub through past market sessions minute-by-minute.
"""
import sqlite3
import os
import glob
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger(__name__)

class RadarReplayService:
    def __init__(self):
        vm_db = "/home/ubuntu/nse-dashboard/backend/app/db/terminal_snapshots.db"
        if os.path.exists(vm_db):
            self.term_db = vm_db
        else:
            self.term_db = os.path.join(os.path.dirname(__file__), "..", "db", "terminal_snapshots.db")
        self.dhan_base = 'C:/Ritesh Workspace/Projects/DhanVarsha/data/normalized'

    def get_available_sessions(self) -> List[str]:
        dates = set()
        if os.path.exists(self.term_db):
            try:
                conn = sqlite3.connect(self.term_db, timeout=5)
                cur = conn.cursor()
                cur.execute("SELECT DISTINCT trade_date FROM intraday_snapshots")
                for r in cur.fetchall():
                    if r[0]:
                        dates.add(r[0])
                conn.close()
            except Exception as e:
                logger.error(f"Error checking terminal DB dates: {e}")

        if os.path.exists(self.dhan_base):
            for p in glob.glob(os.path.join(self.dhan_base, "*", "*.db")):
                d_str = os.path.basename(os.path.dirname(p))
                dates.add(d_str)

        return sorted(list(dates), reverse=True)

    def get_replay_frame(self, target_date: Optional[str] = None, target_time: Optional[str] = None) -> Dict[str, Any]:
        sessions = self.get_available_sessions()
        if not sessions:
            return {"success": False, "error": "No historical recorded sessions available"}

        selected_date = target_date if (target_date and target_date in sessions) else sessions[0]

        # Check source
        dhan_db = os.path.join(self.dhan_base, selected_date, f"normalized_options_{selected_date}.db")
        if os.path.exists(dhan_db):
            return self._load_dhanvarsha_session(dhan_db, selected_date, target_time, sessions)
        elif os.path.exists(self.term_db):
            return self._load_terminal_session(self.term_db, selected_date, target_time, sessions)
        else:
            return {"success": False, "error": f"Session database not found for {selected_date}"}

    def _load_dhanvarsha_session(self, db_path: str, date_str: str, target_time: Optional[str], sessions: List[str]) -> Dict[str, Any]:
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    substr(timestamp, 12, 5) as time_str,
                    underlying,
                    AVG(spot_price) as spot,
                    SUM(CASE WHEN option_type='CE' THEN oi ELSE 0 END) as ce_oi,
                    SUM(CASE WHEN option_type='PE' THEN oi ELSE 0 END) as pe_oi
                FROM normalized_option_chain
                WHERE underlying IN ('NIFTY', 'BANKNIFTY', 'FINNIFTY')
                GROUP BY time_str, underlying
                ORDER BY time_str ASC
            """)
            rows = cur.fetchall()
            conn.close()

            by_time = {}
            for t_str, und, spot, ce_oi, pe_oi in rows:
                if t_str not in by_time:
                    by_time[t_str] = {}
                by_time[t_str][und] = {
                    "spot": round(spot, 1),
                    "ce_oi": ce_oi or 1,
                    "pe_oi": pe_oi or 1
                }

            all_times = sorted(list(by_time.keys()))
            if not all_times:
                return {"success": False, "error": f"No timestamps found for {date_str}"}

            base_spots = {u: by_time[all_times[0]][u]["spot"] for u in by_time[all_times[0]]}
            timeline_steps = []

            for t_str in all_times:
                indices_data = []
                dirs = []
                for und in ['NIFTY', 'BANKNIFTY', 'FINNIFTY']:
                    if und not in by_time[t_str]:
                        continue
                    item = by_time[t_str][und]
                    spot = item["spot"]
                    base_s = base_spots.get(und, spot)
                    pchange = round(((spot - base_s) / base_s) * 100.0, 2)
                    pcr = round(item["pe_oi"] / max(1, item["ce_oi"]), 2)

                    pcr_score = min(35.0, max(0.0, (pcr - 0.7) * 50.0))
                    mom_score = min(35.0, max(0.0, 17.5 + pchange * 15.0))
                    tot_bias = "PE_DOMINANT" if item["pe_oi"] > item["ce_oi"] * 1.08 else ("CE_DOMINANT" if item["ce_oi"] > item["pe_oi"] * 1.08 else "BALANCED")
                    oi_score = 25.0 if tot_bias == "PE_DOMINANT" else (5.0 if tot_bias == "CE_DOMINANT" else 15.0)
                    conf = round(pcr_score + mom_score + oi_score, 1)

                    directive = "BUY_CALL" if conf >= 68.0 else ("BUY_PUT" if conf <= 38.0 else "STANDBY")
                    dirs.append(directive)

                    step = 100.0 if "BANK" in und else 50.0
                    atm = round(spot / step) * step

                    indices_data.append({
                        "symbol": und,
                        "name": f"{und} 50" if und == "NIFTY" else und,
                        "spot_price": spot,
                        "spot_pchange": pchange,
                        "atm_strike": atm,
                        "tot_ce_oi": item["ce_oi"],
                        "tot_pe_oi": item["pe_oi"],
                        "tot_ce_oi_lakhs": round(item["ce_oi"] / 100000, 2),
                        "tot_pe_oi_lakhs": round(item["pe_oi"] / 100000, 2),
                        "net_oi_diff_lakhs": round(abs(item["pe_oi"] - item["ce_oi"]) / 100000, 2),
                        "tot_oi_bias": tot_bias,
                        "ce_oi_change_k": round(item["ce_oi"] * 0.05 / 1000, 1),
                        "pe_oi_change_k": round(item["pe_oi"] * 0.05 / 1000, 1),
                        "net_oi_chg_k": 0.0,
                        "oi_bias": "PUT_SUPPORT" if pcr >= 1.10 else ("CALL_RESISTANCE" if pcr <= 0.85 else "BALANCED"),
                        "key_support": atm - step * 2,
                        "key_resistance": atm + step * 2,
                        "max_pain": atm,
                        "pcr": pcr,
                        "alphatrend": "BULLISH" if conf >= 60 else ("BEARISH" if conf <= 40 else "NEUTRAL"),
                        "trend_direction": "UP" if pchange >= 0.15 else ("DOWN" if pchange <= -0.15 else "SIDEWAYS"),
                        "hull_state": "BULLISH" if pchange >= 0.10 else ("BEARISH" if pchange <= -0.10 else "NEUTRAL"),
                        "confluence_score": conf,
                        "market_regime": "STRONG TREND" if conf >= 70 or conf <= 30 else "RANGE-BOUND",
                        "action": directive
                    })

                buy_ce = dirs.count("BUY_CALL")
                buy_pe = dirs.count("BUY_PUT")
                if buy_ce >= 2 and buy_pe == 0:
                    regime = "FULL_BULLISH_UNISON" if buy_ce == len(dirs) else "MODERATE_BULLISH"
                elif buy_pe >= 2 and buy_ce == 0:
                    regime = "FULL_BEARISH_UNISON" if buy_pe == len(dirs) else "MODERATE_BEARISH"
                elif buy_ce >= 1 and buy_pe >= 1:
                    regime = "DIVERGENCE_CHOP"
                else:
                    regime = "NEUTRAL_STANDBY"

                timeline_steps.append({
                    "time": t_str,
                    "regime": regime,
                    "nifty_spot": next((x["spot_price"] for x in indices_data if x["symbol"] == "NIFTY"), 0),
                    "nifty_conf": next((x["confluence_score"] for x in indices_data if x["symbol"] == "NIFTY"), 50),
                    "indices": indices_data
                })

            chosen_step = timeline_steps[-1]
            if target_time:
                for s in timeline_steps:
                    if s["time"] >= target_time:
                        chosen_step = s
                        break

            total_steps = len(timeline_steps)
            bull_cnt = sum(1 for s in timeline_steps if "BULLISH" in s["regime"])
            bear_cnt = sum(1 for s in timeline_steps if "BEARISH" in s["regime"])
            chop_cnt = sum(1 for s in timeline_steps if "DIVERGENCE" in s["regime"] or "STANDBY" in s["regime"])

            return {
                "success": True,
                "selected_date": date_str,
                "available_dates": sessions,
                "total_minutes": total_steps,
                "time_list": [s["time"] for s in timeline_steps],
                "ribbon_stats": {
                    "bullish_pct": round((bull_cnt / max(1, total_steps)) * 100, 1),
                    "bearish_pct": round((bear_cnt / max(1, total_steps)) * 100, 1),
                    "chop_pct": round((chop_cnt / max(1, total_steps)) * 100, 1)
                },
                "timeline_summary": [{
                    "time": s["time"],
                    "regime": s["regime"],
                    "nifty_spot": s["nifty_spot"],
                    "nifty_conf": s["nifty_conf"]
                } for s in timeline_steps],
                "timeline_steps": timeline_steps,
                "current_snapshot": chosen_step
            }
        except Exception as e:
            logger.error(f"Error loading DhanVarsha session {db_path}: {e}")
            return {"success": False, "error": str(e)}

    def _load_terminal_session(self, db_path: str, date_str: str, target_time: Optional[str], sessions: List[str]) -> Dict[str, Any]:
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            cur = conn.cursor()
            cur.execute("""
                SELECT time_str, symbol, spot, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, pcr, confluence
                FROM intraday_snapshots
                WHERE trade_date = ?
                GROUP BY time_str, symbol
                ORDER BY time_str ASC
            """, (date_str,))
            rows = cur.fetchall()
            conn.close()

            by_time = {}
            for t_str, sym, spot, ce_oi, pe_oi, ce_chg, pe_chg, pcr, conf in rows:
                if t_str not in by_time:
                    by_time[t_str] = {}
                by_time[t_str][sym] = {
                    "spot": spot, "ce_oi": ce_oi, "pe_oi": pe_oi,
                    "ce_chg": ce_chg, "pe_chg": pe_chg, "pcr": pcr, "conf": conf
                }

            all_times = sorted(list(by_time.keys()))
            if not all_times:
                return {"success": False, "error": f"No snapshots found for {date_str}"}

            # 1. Establish session opening reference spot for each index
            base_spots = {}
            for t in all_times:
                for sym in by_time[t]:
                    if sym not in base_spots and by_time[t][sym]["spot"] > 0:
                        base_spots[sym] = by_time[t][sym]["spot"]

            trailing_spots = {s: [] for s in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']}
            timeline_steps = []

            for t_str in all_times:
                indices_data = []
                dirs = []
                for sym in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']:
                    if sym not in by_time[t_str]:
                        continue
                    item = by_time[t_str][sym]
                    spot = item["spot"]
                    open_spot = base_spots.get(sym, spot)
                    spot_pchange = round(((spot - open_spot) / max(1.0, open_spot)) * 100.0, 2)

                    # Update trailing window for Hull Suite proxy
                    trailing_spots[sym].append(spot)
                    if len(trailing_spots[sym]) > 6:
                        trailing_spots[sym].pop(0)
                    hma_proxy = sum(trailing_spots[sym]) / len(trailing_spots[sym])

                    # Dynamic Hull Suite State
                    hull_band = open_spot * 0.0003
                    if spot > hma_proxy + hull_band:
                        hull_state = "BULLISH"
                    elif spot < hma_proxy - hull_band:
                        hull_state = "BEARISH"
                    else:
                        hull_state = "NEUTRAL"

                    # Dynamic Trend Direction
                    if spot_pchange >= 0.15:
                        trend_dir = "UP"
                    elif spot_pchange <= -0.15:
                        trend_dir = "DOWN"
                    else:
                        trend_dir = "SIDEWAYS"

                    # Dynamic Total OI Dominance
                    tot_ce = item["ce_oi"] or 1
                    tot_pe = item["pe_oi"] or 1
                    if tot_pe > tot_ce * 1.08:
                        tot_bias = "PE_DOMINANT"
                    elif tot_ce > tot_pe * 1.08:
                        tot_bias = "CE_DOMINANT"
                    else:
                        tot_bias = "BALANCED"

                    # Dynamic Intraday Flow
                    ce_chg = item["ce_chg"] or 0
                    pe_chg = item["pe_chg"] or 0
                    if pe_chg > ce_chg * 1.15:
                        oi_bias = "PUT_SUPPORT"
                    elif ce_chg > pe_chg * 1.15:
                        oi_bias = "CALL_RESISTANCE"
                    else:
                        oi_bias = "BALANCED"

                    # Dynamic Multi-Dimensional Confluence Score
                    pcr = item["pcr"] or 1.0
                    pcr_adj = (min(1.6, max(0.6, pcr)) - 1.0) * 35.0
                    mom_adj = min(25.0, max(-25.0, spot_pchange * 30.0))
                    oi_adj = 8.0 if tot_bias == "PE_DOMINANT" else (-8.0 if tot_bias == "CE_DOMINANT" else 0.0)
                    flow_adj = 8.0 if oi_bias == "PUT_SUPPORT" else (-8.0 if oi_bias == "CALL_RESISTANCE" else 0.0)

                    conf = round(min(98.0, max(5.0, 50.0 + pcr_adj + mom_adj + oi_adj + flow_adj)), 1)

                    # Dynamic AlphaTrend
                    if conf >= 60.0 or spot_pchange >= 0.25:
                        alphatrend = "BULLISH"
                    elif conf <= 40.0 or spot_pchange <= -0.25:
                        alphatrend = "BEARISH"
                    else:
                        alphatrend = "NEUTRAL"

                    # Dynamic Action Directive
                    if conf >= 68.0:
                        directive = "BUY_CALL"
                    elif conf <= 34.0:
                        directive = "BUY_PUT"
                    else:
                        directive = "STANDBY"
                    dirs.append(directive)

                    # Market Regime
                    if conf >= 70.0:
                        regime_name = "STRONG BULLISH"
                    elif conf >= 60.0:
                        regime_name = "BULLISH"
                    elif conf <= 30.0:
                        regime_name = "STRONG BEARISH"
                    elif conf <= 40.0:
                        regime_name = "BEARISH"
                    else:
                        regime_name = "RANGE-BOUND"

                    step = 100.0 if "BANK" in sym else (25.0 if "MID" in sym else 50.0)
                    atm = round(spot / step) * step

                    indices_data.append({
                        "symbol": sym,
                        "name": f"{sym} 50" if sym == "NIFTY" else sym,
                        "spot_price": spot,
                        "spot_pchange": spot_pchange,
                        "atm_strike": atm,
                        "tot_ce_oi": tot_ce,
                        "tot_pe_oi": tot_pe,
                        "tot_ce_oi_lakhs": round(tot_ce / 100000, 2),
                        "tot_pe_oi_lakhs": round(tot_pe / 100000, 2),
                        "net_oi_diff_lakhs": round(abs(tot_pe - tot_ce) / 100000, 2),
                        "tot_oi_bias": tot_bias,
                        "ce_oi_change_k": round(ce_chg / 1000, 1),
                        "pe_oi_change_k": round(pe_chg / 1000, 1),
                        "net_oi_chg_k": round((pe_chg - ce_chg) / 1000, 1),
                        "oi_bias": oi_bias,
                        "key_support": atm - step * 2,
                        "key_resistance": atm + step * 2,
                        "max_pain": atm,
                        "pcr": round(pcr, 2),
                        "alphatrend": alphatrend,
                        "trend_direction": trend_dir,
                        "hull_state": hull_state,
                        "confluence_score": conf,
                        "market_regime": regime_name,
                        "action": directive
                    })

                buy_ce = dirs.count("BUY_CALL")
                buy_pe = dirs.count("BUY_PUT")
                if buy_ce >= 3:
                    session_regime = "FULL_BULLISH_UNISON"
                elif buy_pe >= 3:
                    session_regime = "FULL_BEARISH_UNISON"
                elif buy_ce >= 1 and buy_pe >= 1:
                    session_regime = "DIVERGENCE_CHOP"
                elif buy_ce >= 2:
                    session_regime = "MODERATE_BULLISH"
                elif buy_pe >= 2:
                    session_regime = "MODERATE_BEARISH"
                else:
                    session_regime = "STANDBY / NEUTRAL"

                timeline_steps.append({
                    "time": t_str,
                    "regime": session_regime,
                    "nifty_spot": next((x["spot_price"] for x in indices_data if x["symbol"] == "NIFTY"), 0),
                    "nifty_conf": next((x["confluence_score"] for x in indices_data if x["symbol"] == "NIFTY"), 50),
                    "indices": indices_data
                })

            chosen_step = timeline_steps[-1]
            if target_time:
                for s in timeline_steps:
                    if s["time"] >= target_time:
                        chosen_step = s
                        break

            total_steps = len(timeline_steps)
            bull_cnt = sum(1 for s in timeline_steps if "BULLISH" in s["regime"])
            bear_cnt = sum(1 for s in timeline_steps if "BEARISH" in s["regime"])
            chop_cnt = sum(1 for s in timeline_steps if "DIVERGENCE" in s["regime"] or "STANDBY" in s["regime"])

            return {
                "success": True,
                "selected_date": date_str,
                "available_dates": sessions,
                "total_minutes": total_steps,
                "time_list": [s["time"] for s in timeline_steps],
                "ribbon_stats": {
                    "bullish_pct": round((bull_cnt / max(1, total_steps)) * 100, 1),
                    "bearish_pct": round((bear_cnt / max(1, total_steps)) * 100, 1),
                    "chop_pct": round((chop_cnt / max(1, total_steps)) * 100, 1)
                },
                "timeline_summary": [{
                    "time": s["time"],
                    "regime": s["regime"],
                    "nifty_spot": s["nifty_spot"],
                    "nifty_conf": s["nifty_conf"]
                } for s in timeline_steps],
                "timeline_steps": timeline_steps,
                "current_snapshot": chosen_step
            }
        except Exception as e:
            logger.error(f"Error loading Terminal session {db_path}: {e}")
            return {"success": False, "error": str(e)}

radar_replay_service = RadarReplayService()
