"""
Unified Dashboard Replay Engine (Zero Repetition)
Provides centralized historical time-travel for the ENTIRE dashboard:
- Multi-Index Institutional Command Radar
- Top Ticker Cards (5 Indices)
- Directional Weightage Bar
- ATM +- 2 Option Confluence Corridor
- Option Chain Matrix Table
- Strike Buildup Lab
- Price vs OI Matrix
"""
import sqlite3
import os
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class UnifiedReplayService:
    def __init__(self):
        vm_db = "/home/ubuntu/nse-dashboard/backend/app/db/terminal_snapshots.db"
        if os.path.exists(vm_db):
            self.db_path = vm_db
        else:
            self.db_path = os.path.join(os.path.dirname(__file__), "..", "db", "terminal_snapshots.db")

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def get_available_sessions(self) -> List[str]:
        """Returns sorted list of all recorded trading session dates."""
        dates = []
        if os.path.exists(self.db_path):
            try:
                conn = self._get_conn()
                cur = conn.cursor()
                cur.execute("SELECT DISTINCT trade_date FROM intraday_snapshots ORDER BY trade_date DESC")
                dates = [r[0] for r in cur.fetchall() if r[0]]
                conn.close()
            except Exception as e:
                logger.error(f"Error fetching replay sessions: {e}")
        return dates or ["2026-10-12"]

    def get_session_timeline(self, trade_date: str) -> List[str]:
        """Returns ordered list of distinct minute timestamps for the session."""
        try:
            conn = self._get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT time_str
                FROM intraday_snapshots
                WHERE trade_date = ? AND time_str >= '09:15' AND time_str <= '15:35'
                ORDER BY time_str ASC
            """, (trade_date,))
            times = [r[0] for r in cur.fetchall() if r[0]]
            conn.close()
            return times
        except Exception as e:
            logger.error(f"Error fetching session timeline for {trade_date}: {e}")
            return []

    def get_unified_snapshot(
        self,
        trade_date: Optional[str] = None,
        time_str: Optional[str] = None,
        symbol: str = "NIFTY"
    ) -> Dict[str, Any]:
        """
        Retrieves complete synchronized state for the entire terminal at the specified date and minute.
        """
        sessions = self.get_available_sessions()
        if not sessions:
            return {"success": False, "error": "No historical recorded sessions available"}

        selected_date = trade_date if (trade_date and trade_date in sessions) else sessions[0]
        timeline = self.get_session_timeline(selected_date)
        if not timeline:
            return {"success": False, "error": f"No timeline data for {selected_date}"}

        # Resolve closest time <= target time
        selected_time = timeline[-1]
        if time_str:
            for t in timeline:
                if t <= time_str:
                    selected_time = t
                else:
                    break

        sym_upper = symbol.upper()
        conn = self._get_conn()
        cur = conn.cursor()

        # 1. Fetch index snapshot for all 4 symbols at this exact time
        cur.execute("""
            SELECT time_str, symbol, spot, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, pcr, confluence
            FROM intraday_snapshots
            WHERE trade_date = ? AND time_str = ?
        """, (selected_date, selected_time))
        snap_rows = {r["symbol"]: dict(r) for r in cur.fetchall()}

        # If any symbol missing at exact time, find its closest previous
        all_syms = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
        for s in all_syms:
            if s not in snap_rows:
                cur.execute("""
                    SELECT time_str, symbol, spot, ce_oi, pe_oi, ce_oi_chg, pe_oi_chg, pcr, confluence
                    FROM intraday_snapshots
                    WHERE trade_date = ? AND symbol = ? AND time_str <= ?
                    ORDER BY time_str DESC LIMIT 1
                """, (selected_date, s, selected_time))
                row = cur.fetchone()
                if row:
                    snap_rows[s] = dict(row)

        # 2. Get session opening reference spot for each index (at 09:15)
        cur.execute("""
            SELECT symbol, spot
            FROM intraday_snapshots
            WHERE trade_date = ? AND time_str >= '09:15'
            GROUP BY symbol
            ORDER BY time_str ASC
        """, (selected_date,))
        open_spots = {r["symbol"]: float(r["spot"]) for r in cur.fetchall() if r["spot"]}

        # 3. Build Multi-Index Radar rows & Top Ticker Cards
        radar_indices = []
        ticker_cards = {}
        dirs = []

        for sym in all_syms:
            item = snap_rows.get(sym, {})
            spot = float(item.get("spot") or 0.0)
            open_spot = open_spots.get(sym, spot)
            spot_pchange = round(((spot - open_spot) / max(1.0, open_spot)) * 100.0, 2) if open_spot > 0 else 0.0
            point_change = round(spot - open_spot, 2)

            step = 100.0 if "BANK" in sym else (25.0 if "MID" in sym else 50.0)
            atm = round(spot / step) * step if step > 0 else spot

            # Hull proxy & trend
            if spot_pchange >= 0.15:
                hull_state = "BULLISH"
                trend_dir = "UP"
            elif spot_pchange <= -0.15:
                hull_state = "BEARISH"
                trend_dir = "DOWN"
            else:
                hull_state = "NEUTRAL"
                trend_dir = "SIDEWAYS"

            tot_ce = int(item.get("ce_oi") or 1)
            tot_pe = int(item.get("pe_oi") or 1)
            if tot_pe > tot_ce * 1.08:
                tot_bias = "PE_DOMINANT"
            elif tot_ce > tot_pe * 1.08:
                tot_bias = "CE_DOMINANT"
            else:
                tot_bias = "BALANCED"

            ce_chg = int(item.get("ce_oi_chg") or 0)
            pe_chg = int(item.get("pe_oi_chg") or 0)
            if pe_chg > ce_chg * 1.15:
                oi_bias = "PUT_SUPPORT"
            elif ce_chg > pe_chg * 1.15:
                oi_bias = "CALL_RESISTANCE"
            else:
                oi_bias = "BALANCED"

            pcr = float(item.get("pcr") or 1.0)
            pcr_adj = (min(1.6, max(0.6, pcr)) - 1.0) * 35.0
            mom_adj = min(25.0, max(-25.0, spot_pchange * 30.0))
            oi_adj = 8.0 if tot_bias == "PE_DOMINANT" else (-8.0 if tot_bias == "CE_DOMINANT" else 0.0)
            flow_adj = 8.0 if oi_bias == "PUT_SUPPORT" else (-8.0 if oi_bias == "CALL_RESISTANCE" else 0.0)
            conf = round(min(98.0, max(5.0, 50.0 + pcr_adj + mom_adj + oi_adj + flow_adj)), 1)

            if conf >= 60.0 or spot_pchange >= 0.25:
                alphatrend = "BULLISH"
            elif conf <= 40.0 or spot_pchange <= -0.25:
                alphatrend = "BEARISH"
            else:
                alphatrend = "NEUTRAL"

            if conf >= 68.0:
                directive = "BUY_CALL"
            elif conf <= 34.0:
                directive = "BUY_PUT"
            else:
                directive = "STANDBY"
            dirs.append(directive)

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

            radar_indices.append({
                "symbol": sym,
                "name": f"{sym} 50" if sym == "NIFTY" else sym,
                "spot_price": spot,
                "spot_pchange": spot_pchange,
                "atm_strike": atm,
                "hull_state": hull_state,
                "trend_direction": trend_dir,
                "total_oi_bias": tot_bias,
                "intraday_flow": oi_bias,
                "alphatrend": alphatrend,
                "action_directive": directive,
                "regime_name": regime_name,
                "confluence_score": conf,
                "pcr": pcr,
                "total_ce_oi": tot_ce,
                "total_pe_oi": tot_pe
            })

            ticker_cards[sym] = {
                "symbol": sym,
                "name": f"{sym} 50" if sym == "NIFTY" else sym,
                "ltp": spot,
                "change": point_change,
                "pChange": spot_pchange,
                "atm": atm,
                "high": round(spot * 1.003, 2),
                "low": round(spot * 0.997, 2),
                "open": open_spot
            }

        # Add SENSEX proxy for top ticker bar
        nifty_card = ticker_cards.get("NIFTY", {})
        ticker_cards["SENSEX"] = {
            "symbol": "SENSEX",
            "name": "BSE SENSEX",
            "ltp": round((nifty_card.get("ltp", 25000) * 3.32), 2),
            "change": round((nifty_card.get("change", 0.0) * 3.32), 2),
            "pChange": nifty_card.get("pChange", 0.0),
            "atm": round((nifty_card.get("atm", 25000) * 3.32) / 100) * 100,
            "open": round((nifty_card.get("open", 25000) * 3.32), 2)
        }

        # Overall market regime
        buy_ce = sum(1 for d in dirs if d == "BUY_CALL")
        buy_pe = sum(1 for d in dirs if d == "BUY_PUT")
        if buy_ce >= 2 and buy_pe == 0:
            regime = "FULL_BULLISH_UNISON" if buy_ce == len(dirs) else "MODERATE_BULLISH"
        elif buy_pe >= 2 and buy_ce == 0:
            regime = "FULL_BEARISH_UNISON" if buy_pe == len(dirs) else "MODERATE_BEARISH"
        elif buy_ce >= 1 and buy_pe >= 1:
            regime = "DIVERGENCE_CHOP"
        else:
            regime = "NEUTRAL_STANDBY"

        # 4. Fetch Strikes for selected symbol (or closest available)
        cur.execute("""
            SELECT strike, option_type, ltp, price_pchange, oi, oi_chg, volume, is_atm
            FROM intraday_strike_snapshots
            WHERE trade_date = ? AND symbol = ? AND time_str = ?
            ORDER BY strike ASC
        """, (selected_date, sym_upper, selected_time))
        strike_rows = cur.fetchall()

        # If not at exact minute, fetch closest <= time
        if not strike_rows:
            cur.execute("""
                SELECT DISTINCT time_str
                FROM intraday_strike_snapshots
                WHERE trade_date = ? AND symbol = ? AND time_str <= ?
                ORDER BY time_str DESC LIMIT 1
            """, (selected_date, sym_upper, selected_time))
            sub_t = cur.fetchone()
            if sub_t:
                cur.execute("""
                    SELECT strike, option_type, ltp, price_pchange, oi, oi_chg, volume, is_atm
                    FROM intraday_strike_snapshots
                    WHERE trade_date = ? AND symbol = ? AND time_str = ?
                    ORDER BY strike ASC
                """, (selected_date, sym_upper, sub_t[0]))
                strike_rows = cur.fetchall()

        # Group strikes into CE & PE
        strikes_map = {}
        for r in strike_rows:
            stk = float(r["strike"])
            if stk not in strikes_map:
                strikes_map[stk] = {
                    "strikePrice": stk,
                    "is_atm": bool(r["is_atm"]),
                    "CE": None,
                    "PE": None
                }
            opt = r["option_type"].upper()
            strikes_map[stk][opt] = {
                "ltp": float(r["ltp"] or 0.0),
                "pChange": float(r["price_pchange"] or 0.0),
                "oi": int(r["oi"] or 0),
                "changeinOpenInterest": int(r["oi_chg"] or 0),
                "totalTradedVolume": int(r["volume"] or 0)
            }

        sorted_strikes = [strikes_map[k] for k in sorted(strikes_map.keys())]

        # Determine ATM strike
        current_spot = ticker_cards.get(sym_upper, {}).get("ltp", 0.0)
        step = 100.0 if "BANK" in sym_upper else (25.0 if "MID" in sym_upper else 50.0)
        calc_atm = round(current_spot / step) * step if step > 0 else current_spot

        atm_stk = next((s["strikePrice"] for s in sorted_strikes if s["is_atm"]), calc_atm)

        # 5. Build ATM +- 2 Confluence Corridor
        corridor_strikes = []
        if sorted_strikes:
            # Find index of ATM
            atm_idx = min(range(len(sorted_strikes)), key=lambda i: abs(sorted_strikes[i]["strikePrice"] - atm_stk))
            start_idx = max(0, atm_idx - 2)
            end_idx = min(len(sorted_strikes), atm_idx + 3)
            corridor_strikes = sorted_strikes[start_idx:end_idx]

        # 6. Strike Buildup Classification & Counts
        counts = {"LONG_BUILDUP": 0, "SHORT_BUILDUP": 0, "SHORT_COVERING": 0, "LONG_UNWINDING": 0}
        buildup_rows = []

        for stk_obj in sorted_strikes:
            for opt_type in ["CE", "PE"]:
                opt_data = stk_obj.get(opt_type)
                if not opt_data:
                    continue
                p_chg = opt_data.get("pChange", 0.0)
                oi_chg = opt_data.get("changeinOpenInterest", 0)

                if p_chg > 0 and oi_chg > 0:
                    b_type = "LONG_BUILDUP"
                elif p_chg < 0 and oi_chg > 0:
                    b_type = "SHORT_BUILDUP"
                elif p_chg > 0 and oi_chg <= 0:
                    b_type = "SHORT_COVERING"
                else:
                    b_type = "LONG_UNWINDING"

                counts[b_type] += 1
                buildup_rows.append({
                    "strike": stk_obj["strikePrice"],
                    "option_type": opt_type,
                    "ltp": opt_data["ltp"],
                    "pChange": p_chg,
                    "oi": opt_data["oi"],
                    "oi_chg": oi_chg,
                    "buildup_type": b_type,
                    "is_atm": stk_obj["strikePrice"] == atm_stk
                })

        conn.close()

        # 5. Build full option chain structure compatible with chain_table.js
        formatted_chain = {
            "symbol": sym_upper,
            "spotPrice": current_spot,
            "timestamp": f"{selected_date} {selected_time}",
            "source": f"REPLAY_SNAPSHOT ({selected_date})",
            "strikes": sorted_strikes
        }

        # 6. Compute exact ATM +- 2 Option Confluence Matrix using quantitative engine
        confluence_data = None
        try:
            from app.services.option_chain import parse_option_chain
            from app.services.option_confluence_service import option_confluence_service

            raw_chain_dict = {
                "records": {
                    "underlyingValue": current_spot,
                    "data": [
                        {
                            "strikePrice": s["strikePrice"],
                            "CE": {
                                "lastPrice": (s.get("CE") or {}).get("ltp", 0.0),
                                "pChange": (s.get("CE") or {}).get("pChange", 0.0),
                                "openInterest": (s.get("CE") or {}).get("oi", 0),
                                "changeinOpenInterest": (s.get("CE") or {}).get("changeinOpenInterest", 0),
                                "totalTradedVolume": (s.get("CE") or {}).get("totalTradedVolume", 0)
                            },
                            "PE": {
                                "lastPrice": (s.get("PE") or {}).get("ltp", 0.0),
                                "pChange": (s.get("PE") or {}).get("pChange", 0.0),
                                "openInterest": (s.get("PE") or {}).get("oi", 0),
                                "changeinOpenInterest": (s.get("PE") or {}).get("changeinOpenInterest", 0),
                                "totalTradedVolume": (s.get("PE") or {}).get("totalTradedVolume", 0)
                            }
                        }
                        for s in sorted_strikes
                    ]
                }
            }
            parsed_chain_obj = parse_option_chain(raw_chain_dict, sym_upper)
            if parsed_chain_obj:
                import asyncio
                # Use current running loop or new loop to run async analyze_confluence
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        import concurrent.futures
                        with concurrent.futures.ThreadPoolExecutor() as pool:
                            confluence_data = pool.submit(
                                asyncio.run, option_confluence_service.analyze_confluence(sym_upper, range_strikes=2, parsed_chain=parsed_chain_obj)
                            ).result()
                    else:
                        confluence_data = loop.run_until_complete(
                            option_confluence_service.analyze_confluence(sym_upper, range_strikes=2, parsed_chain=parsed_chain_obj)
                        )
                except Exception:
                    confluence_data = asyncio.run(
                        option_confluence_service.analyze_confluence(sym_upper, range_strikes=2, parsed_chain=parsed_chain_obj)
                    )
        except Exception as e_conf:
            logger.debug(f"Replay confluence calculation note: {e_conf}")

        time_idx = timeline.index(selected_time) if selected_time in timeline else 0

        return {
            "success": True,
            "trade_date": selected_date,
            "time_str": selected_time,
            "time_index": time_idx,
            "total_minutes": len(timeline),
            "timeline": timeline,
            "available_dates": sessions,
            "multi_index_radar": radar_indices,
            "ticker_cards": ticker_cards,
            "market_regime": regime,
            "corridor_strikes": corridor_strikes,
            "confluence_corridor": confluence_data,
            "option_chain": formatted_chain,
            "buildup_lab": {
                "counts": counts,
                "strikes": buildup_rows
            }
        }


unified_replay_service = UnifiedReplayService()
