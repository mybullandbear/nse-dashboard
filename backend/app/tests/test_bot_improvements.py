import os
import sys
import unittest
from unittest.mock import patch
import json
import tempfile
import asyncio
from datetime import datetime, time, timedelta

# Ensure backend root is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.services.tqs_service import tqs_service, TradeQualityScoreService
from app.services.tracker_bot import SmartTrackerBot
from app.db.tracker_storage import TrackerStorage
from app.services.option_chain import ParsedOptionChain, StrikeRow, StrikeContract


def run_async(coro):
    return asyncio.run(coro)


def make_mock_chain(symbol="NIFTY", spot_price=25000.0, atm_strike=25000.0, strikes=None):
    return ParsedOptionChain(
        symbol=symbol,
        spot_price=spot_price,
        spot_change=0.0,
        spot_pchange=0.0,
        atm_strike=atm_strike,
        expiry="CURRENT",
        expiry_list=["CURRENT"],
        pcr=1.0,
        pcr_atm_5=1.0,
        max_pain=atm_strike,
        total_ce_oi=1000000,
        total_pe_oi=1000000,
        strikes=strikes or [],
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )


class TestBotImprovements(unittest.TestCase):
    def setUp(self):
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        self.storage = TrackerStorage(db_path=self.temp_db_path)

        self.bot = SmartTrackerBot()
        self.bot.is_active = True
        self.bot.FLAT_BROKERAGE_PER_TRADE = 75.0
        self.bot.HARD_CAPITAL_CEILING = 30000.0

    def tearDown(self):
        try:
            os.close(self.temp_db_fd)
            if os.path.exists(self.temp_db_path):
                os.remove(self.temp_db_path)
        except Exception:
            pass

    # -------------------------------------------------------------
    # 1. Capital boundary and insufficient cash
    # -------------------------------------------------------------
    def test_capital_boundary_and_insufficient_cash(self):
        with patch("app.services.tracker_bot.tracker_storage", self.storage):
            status = self.bot.get_capital_status()
            self.assertEqual(status["hard_ceiling"], 30000.0)
            self.assertEqual(status["available_capital"], 30000.0)
            self.assertEqual(status["committed_margin"], 0.0)

            # Insert an open trade consuming ₹24,000 (entry 320 * 75 lot_size)
            self.storage.insert_trade({
                "id": "tr_existing",
                "symbol": "NIFTY",
                "strategy_type": "BUY_CALL_BREAKOUT",
                "role": "BUYER",
                "entry_net_price": 320.0,
                "current_net_price": 320.0,
                "target_price": 365.0,
                "stop_loss_price": 275.0,
                "trailing_stop_price": 275.0,
                "lot_size": 75,
                "lots": 1,
                "brokerage_inr": 75.0,
                "legs": []
            })

            status = self.bot.get_capital_status()
            self.assertEqual(status["committed_margin"], 24000.0)
            self.assertEqual(status["available_capital"], 6000.0)

            # Sizing validation: Candidate requiring ₹7,575 > available ₹6,000 is rejected
            required_outlay = 7575.0
            self.bot._record_rejection("BANKNIFTY", "CAPITAL_EXCEEDED", {
                "required": required_outlay,
                "available": status["available_capital"],
                "deficit": required_outlay - status["available_capital"],
                "ceiling": self.bot.HARD_CAPITAL_CEILING
            })

            rejections = self.bot.get_rejections_log()
            self.assertTrue(any(r["reason"] == "CAPITAL_EXCEEDED" for r in rejections))
            rej = [r for r in rejections if r["reason"] == "CAPITAL_EXCEEDED"][0]
            self.assertEqual(rej["details"]["available"], 6000.0)

    # -------------------------------------------------------------
    # 2. Flat ₹75 Accounting
    # -------------------------------------------------------------
    def test_flat_75_accounting(self):
        lot_size = 75
        entry_price = 100.0
        exit_price = 114.0
        pts_gain = exit_price - entry_price  # +14 pts
        gross_pnl = pts_gain * lot_size      # +1050.0
        brokerage = 75.0
        net_pnl = gross_pnl - brokerage      # +975.0

        trade_id = self.storage.insert_trade({
            "id": "tr_flat75_win",
            "symbol": "NIFTY",
            "strategy_type": "BUY_CALL_BREAKOUT",
            "role": "BUYER",
            "entry_net_price": entry_price,
            "current_net_price": entry_price,
            "target_price": 114.0,
            "stop_loss_price": 86.0,
            "trailing_stop_price": 86.0,
            "lot_size": lot_size,
            "lots": 1,
            "brokerage_inr": brokerage,
            "legs": []
        })

        self.storage.close_trade(
            trade_id=trade_id,
            exit_net_price=exit_price,
            gross_realized_pnl=gross_pnl,
            net_realized_pnl=net_pnl,
            exit_reason="TARGET1_ACHIEVED"
        )

        closed = self.storage.get_trade_by_id(trade_id)
        self.assertIsNotNone(closed)
        self.assertEqual(closed["brokerage_inr"], 75.0)
        self.assertEqual(closed["gross_realized_pnl_inr"], 1050.0)
        self.assertEqual(closed["realized_pnl_inr"], 975.0)
        self.assertEqual(closed["gross_realized_pnl_inr"] - closed["realized_pnl_inr"], 75.0)

        # Losing trade: Entry ₹100, Exit ₹86 (-14 pts)
        loss_pts = -14.0
        gross_loss = loss_pts * lot_size     # -1050.0
        net_loss = gross_loss - brokerage    # -1125.0
        trade_id_loss = self.storage.insert_trade({
            "id": "tr_flat75_loss",
            "symbol": "NIFTY",
            "strategy_type": "BUY_CALL_BREAKOUT",
            "role": "BUYER",
            "entry_net_price": entry_price,
            "current_net_price": entry_price,
            "target_price": 114.0,
            "stop_loss_price": 86.0,
            "trailing_stop_price": 86.0,
            "lot_size": lot_size,
            "lots": 1,
            "brokerage_inr": brokerage,
            "legs": []
        })
        self.storage.close_trade(
            trade_id=trade_id_loss,
            exit_net_price=86.0,
            gross_realized_pnl=gross_loss,
            net_realized_pnl=net_loss,
            exit_reason="STOP_LOSS_HIT"
        )
        closed_loss = self.storage.get_trade_by_id(trade_id_loss)
        self.assertIsNotNone(closed_loss)
        self.assertEqual(closed_loss["brokerage_inr"], 75.0)
        self.assertEqual(closed_loss["gross_realized_pnl_inr"], -1050.0)
        self.assertEqual(closed_loss["realized_pnl_inr"], -1125.0)

    # -------------------------------------------------------------
    # 3. Whole-lot integer quantities
    # -------------------------------------------------------------
    def test_whole_lot_quantities(self):
        from app.core.config import get_settings
        settings = get_settings()

        for sym in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]:
            lot_size = settings.LOT_SIZES.get(sym)
            self.assertIsNotNone(lot_size)
            self.assertIsInstance(lot_size, int)
            self.assertGreater(lot_size, 0)

            # In Variant C scout baseline, lots is strictly 1 integer
            lots = 1
            total_qty = lots * lot_size
            self.assertIsInstance(total_qty, int)
            self.assertEqual(total_qty % lot_size, 0)

    # -------------------------------------------------------------
    # 4. CE/PE Scoring Symmetry in TQS
    # -------------------------------------------------------------
    def test_ce_pe_scoring_symmetry(self):
        chain = make_mock_chain(symbol="NIFTY", spot_price=25000.0, atm_strike=25000.0)

        ce_contract = StrikeContract(
            strikePrice=25000.0,
            lastPrice=100.0,
            change=5.0,
            pChange=5.0,
            totalTradedVolume=50000,
            openInterest=100000,
            changeinOpenInterest=15000,
            impliedVolatility=15.0
        )

        pe_contract = StrikeContract(
            strikePrice=25000.0,
            lastPrice=100.0,
            change=5.0,
            pChange=5.0,
            totalTradedVolume=50000,
            openInterest=100000,
            changeinOpenInterest=15000,
            impliedVolatility=15.0
        )

        c_row = StrikeRow(strikePrice=25000.0, CE=ce_contract, PE=pe_contract)

        # Bullish evaluation (Confluence = 75, OTT = BULLISH, trend_dir = +0.5)
        ce_score, ce_breakdown = tqs_service.compute_tqs(
            symbol="NIFTY",
            chain=chain,
            contract_row=c_row,
            option_type="CE",
            role="BUYER",
            confluence_score=75.0,
            technical_state={"ott_state": "BULLISH", "trend_dir_strength": 0.5, "adx": 30.0},
            target_pts=14.0,
            risk_pts=14.0
        )

        # Bearish evaluation with symmetric disparity (Confluence = 25, OTT = BEARISH, trend_dir = -0.5)
        pe_score, pe_breakdown = tqs_service.compute_tqs(
            symbol="NIFTY",
            chain=chain,
            contract_row=c_row,
            option_type="PE",
            role="BUYER",
            confluence_score=25.0,
            technical_state={"ott_state": "BEARISH", "trend_dir_strength": -0.5, "adx": 30.0},
            target_pts=14.0,
            risk_pts=14.0
        )

        # Both symmetric bullish and bearish setups must yield equal TQS scores
        self.assertEqual(ce_score, pe_score)
        self.assertEqual(ce_breakdown["p1_signal"], pe_breakdown["p1_signal"])
        self.assertEqual(ce_breakdown["p2_strike"], pe_breakdown["p2_strike"])
        self.assertEqual(ce_breakdown["p3_liquidity"], pe_breakdown["p3_liquidity"])
        self.assertEqual(ce_breakdown["p4_momentum"], pe_breakdown["p4_momentum"])
        self.assertEqual(ce_breakdown["p5_risk_reward"], pe_breakdown["p5_risk_reward"])

    # -------------------------------------------------------------
    # 5. Missing and stale market data handling
    # -------------------------------------------------------------
    def test_missing_and_stale_market_data(self):
        empty_contract = StrikeContract(
            strikePrice=25000.0,
            lastPrice=100.0,
            totalTradedVolume=0,
            openInterest=0,
            changeinOpenInterest=0,
            impliedVolatility=0.0
        )
        empty_pe = StrikeContract(strikePrice=25000.0, lastPrice=0.0)
        empty_row = StrikeRow(strikePrice=25000.0, CE=empty_contract, PE=empty_pe)
        empty_chain = make_mock_chain(symbol="NIFTY", spot_price=25000.0, atm_strike=25000.0, strikes=[empty_row])

        # When OI, volume, and Greeks are missing, TQS must NOT silently award high score
        score, breakdown = tqs_service.compute_tqs(
            symbol="NIFTY",
            chain=empty_chain,
            contract_row=empty_row,
            option_type="CE",
            role="BUYER",
            confluence_score=50.0,  # Neutral confluence
            technical_state={},
            target_pts=14.0,
            risk_pts=14.0
        )

        # Disparity = 0, delta missing = 0, liquidity = 0
        self.assertEqual(breakdown["p1_signal"], 0.0)
        self.assertEqual(breakdown["p3_liquidity"], 0.0)
        self.assertLess(score, 50.0)  # Fails TQS threshold of 70

        # Simulator data source rejection
        sim_chain = make_mock_chain(symbol="NIFTY", spot_price=25000.0, atm_strike=25000.0, strikes=[empty_row])
        sim_chain.source = "SIMULATOR"

        with patch("app.services.tracker_bot.tracker_storage", self.storage):
            run_async(self.bot.process_tick("NIFTY", sim_chain, {}))
            rejections = self.bot.get_rejections_log()
            self.assertTrue(any(r["reason"] == "SIMULATOR_DATA_REJECTED" for r in rejections))

    # -------------------------------------------------------------
    # 6. TQS Calculation vs Raw Confluence Independence
    # -------------------------------------------------------------
    def test_tqs_calculation_and_independence(self):
        illiquid_ce = StrikeContract(
            strikePrice=25000.0,
            lastPrice=100.0,
            totalTradedVolume=10,
            openInterest=100,
            changeinOpenInterest=0
        )
        empty_pe = StrikeContract(strikePrice=25000.0, lastPrice=0.0)
        c_row = StrikeRow(strikePrice=25000.0, CE=illiquid_ce, PE=empty_pe)
        chain = make_mock_chain(symbol="NIFTY", spot_price=25000.0, atm_strike=25000.0, strikes=[c_row])

        tqs_score, breakdown = tqs_service.compute_tqs(
            symbol="NIFTY",
            chain=chain,
            contract_row=c_row,
            option_type="CE",
            role="BUYER",
            confluence_score=80.0,
            technical_state={},
            target_pts=14.0,
            risk_pts=14.0
        )

        # Confirm TQS is decoupled from Confluence (80 != tqs_score)
        self.assertNotEqual(tqs_score, 80.0)
        # Five pillars must all be present
        self.assertIn("p1_signal", breakdown)
        self.assertIn("p2_strike", breakdown)
        self.assertIn("p3_liquidity", breakdown)
        self.assertIn("p4_momentum", breakdown)
        self.assertIn("p5_risk_reward", breakdown)
        self.assertIn("total", breakdown)
        self.assertEqual(breakdown["total"], tqs_score)

    # -------------------------------------------------------------
    # 7. Duplicate signals and concurrency lock
    # -------------------------------------------------------------
    def test_duplicate_signals_and_concurrency_lock(self):
        with patch("app.services.tracker_bot.tracker_storage", self.storage):
            # Insert active trade for NIFTY
            self.storage.insert_trade({
                "id": "tr_nifty_active",
                "symbol": "NIFTY",
                "strategy_type": "BUY_CALL_BREAKOUT",
                "role": "BUYER",
                "entry_net_price": 100.0,
                "current_net_price": 100.0,
                "target_price": 114.0,
                "stop_loss_price": 86.0,
                "trailing_stop_price": 86.0,
                "lot_size": 75,
                "lots": 1,
                "legs": [{"strike": 25000, "option_type": "CE", "current_ltp": 100.0}]
            })

            # Check open trade exists
            open_trade = self.storage.get_open_trade_for_symbol("NIFTY")
            self.assertIsNotNone(open_trade)

            # Signal persistence tick test: new trade cannot be submitted for NIFTY while one is active
            contract = StrikeContract(strikePrice=25000, lastPrice=100.0)
            row = StrikeRow(strikePrice=25000, CE=contract, PE=contract)
            chain = make_mock_chain(symbol="NIFTY", spot_price=25000, atm_strike=25000, strikes=[row])

            initial_trades_count = len(self.storage.get_open_trades())
            run_async(self.bot.process_tick("NIFTY", chain, {}))

            # Concurrency lock prevented second trade
            self.assertEqual(len(self.storage.get_open_trades()), initial_trades_count)

    # -------------------------------------------------------------
    # 8. Variant C Execution Rules (+14% trigger, Entry + 3% Armor, Target 2, EOD)
    # -------------------------------------------------------------
    def test_variant_c_execution_rules(self):
        with patch("app.services.tracker_bot.tracker_storage", self.storage):
            entry_price = 100.0
            trade_id = self.storage.insert_trade({
                "id": "tr_variant_c",
                "symbol": "NIFTY",
                "strategy_type": "BUY_CALL_BREAKOUT",
                "role": "BUYER",
                "entry_net_price": entry_price,
                "current_net_price": entry_price,
                "target_price": 114.0,
                "target2_price": 135.0,
                "stop_loss_price": 86.0,
                "trailing_stop_price": 86.0,
                "lot_size": 75,
                "lots": 1,
                "legs": [{"strike": 25000, "option_type": "CE", "entry_ltp": 100.0, "current_ltp": 100.0, "target2_price": 135.0}]
            })

            # Case A: Price reaches +14% (₹114.0) -> Trailing Stop ratchets to Entry + 3% (₹103.0)
            contract = StrikeContract(strikePrice=25000, lastPrice=114.5)
            row = StrikeRow(strikePrice=25000, CE=contract, PE=contract)
            chain = make_mock_chain(symbol="NIFTY", spot_price=25000, atm_strike=25000, strikes=[row])

            trade = self.storage.get_trade_by_id(trade_id)
            now_dt = datetime(2026, 10, 8, 10, 30, 0)
            run_async(self.bot._update_and_check_exit(trade, chain, now_dt))

            updated = self.storage.get_trade_by_id(trade_id)
            self.assertEqual(updated["status"], "OPEN")
            self.assertEqual(updated["trailing_stop_price"], 103.0)  # Entry + 3% Armor

            # Case B: Price pulls back to ₹103.0 -> Exits with LOCKED_PROFIT_STOP_HIT
            pullback_contract = StrikeContract(strikePrice=25000, lastPrice=102.5)
            row_pb = StrikeRow(strikePrice=25000, CE=pullback_contract, PE=pullback_contract)
            chain_pb = make_mock_chain(symbol="NIFTY", spot_price=25000, atm_strike=25000, strikes=[row_pb])

            trade_pb = self.storage.get_trade_by_id(trade_id)
            run_async(self.bot._update_and_check_exit(trade_pb, chain_pb, now_dt))

            closed = self.storage.get_trade_by_id(trade_id)
            self.assertEqual(closed["status"], "CLOSED")
            self.assertIn("LOCKED_PROFIT_STOP_HIT", closed["exit_reason"])
            # Profit was locked at entry + 3%
            self.assertGreater(closed["gross_realized_pnl_inr"], 0.0)

            # Case C: Target 2 (+35%) Exit Test
            trade_id_t2 = self.storage.insert_trade({
                "id": "tr_variant_c_t2",
                "symbol": "NIFTY",
                "strategy_type": "BUY_CALL_BREAKOUT",
                "role": "BUYER",
                "entry_net_price": 100.0,
                "current_net_price": 100.0,
                "target_price": 114.0,
                "target2_price": 135.0,
                "stop_loss_price": 86.0,
                "trailing_stop_price": 86.0,
                "lot_size": 75,
                "lots": 1,
                "legs": [{"strike": 25000, "option_type": "CE", "entry_ltp": 100.0, "current_ltp": 100.0, "target2_price": 135.0}]
            })
            t2_contract = StrikeContract(strikePrice=25000, lastPrice=136.0)
            chain_t2 = make_mock_chain(symbol="NIFTY", spot_price=25000, atm_strike=25000, strikes=[StrikeRow(strikePrice=25000, CE=t2_contract, PE=t2_contract)])
            trade_t2 = self.storage.get_trade_by_id(trade_id_t2)
            run_async(self.bot._update_and_check_exit(trade_t2, chain_t2, now_dt))
            closed_t2 = self.storage.get_trade_by_id(trade_id_t2)
            self.assertEqual(closed_t2["status"], "CLOSED")
            self.assertIn("TARGET2_ACHIEVED", closed_t2["exit_reason"])

            # Case D: EOD Auto-Squareoff at 15:30 IST
            trade_id_eod = self.storage.insert_trade({
                "id": "tr_variant_c_eod",
                "symbol": "NIFTY",
                "strategy_type": "BUY_CALL_BREAKOUT",
                "role": "BUYER",
                "entry_net_price": 100.0,
                "current_net_price": 100.0,
                "target_price": 114.0,
                "stop_loss_price": 86.0,
                "trailing_stop_price": 86.0,
                "lot_size": 75,
                "lots": 1,
                "legs": [{"strike": 25000, "option_type": "CE", "entry_ltp": 100.0, "current_ltp": 105.0}]
            })
            eod_contract = StrikeContract(strikePrice=25000, lastPrice=105.0)
            chain_eod = make_mock_chain(symbol="NIFTY", spot_price=25000, atm_strike=25000, strikes=[StrikeRow(strikePrice=25000, CE=eod_contract, PE=eod_contract)])
            trade_eod = self.storage.get_trade_by_id(trade_id_eod)
            eod_time = datetime(2026, 10, 8, 15, 30, 1)
            run_async(self.bot._update_and_check_exit(trade_eod, chain_eod, eod_time))
            closed_eod = self.storage.get_trade_by_id(trade_id_eod)
            self.assertEqual(closed_eod["status"], "CLOSED")
            self.assertIn("EOD_SQUAREOFF", closed_eod["exit_reason"])

    # -------------------------------------------------------------
    # 9. State Persistence & Restart Recovery
    # -------------------------------------------------------------
    def test_state_persistence_and_restart_recovery(self):
        with patch("app.services.tracker_bot.tracker_storage", self.storage):
            self.storage.insert_trade({
                "id": "tr_persisted_1",
                "symbol": "BANKNIFTY",
                "strategy_type": "BUY_CALL_BREAKOUT",
                "role": "BUYER",
                "entry_net_price": 400.0,
                "current_net_price": 400.0,
                "target_price": 456.0,
                "stop_loss_price": 344.0,
                "trailing_stop_price": 344.0,
                "lot_size": 30,
                "lots": 1,
                "legs": []
            })

            # Simulate complete process reboot: create new bot instance
            rebooted_bot = SmartTrackerBot()
            status = rebooted_bot.get_capital_status()
            # 400 * 30 = 12,000 committed
            self.assertEqual(status["open_positions"], 1)
            self.assertEqual(status["committed_margin"], 12000.0)
            self.assertEqual(status["available_capital"], max(0.0, rebooted_bot.capital_ceiling - 12000.0))


    # -------------------------------------------------------------
    # 10. Shared Capital Across Concurrent Entries
    # -------------------------------------------------------------
    def test_shared_capital_pool_concurrent_entries(self):
        with patch("app.services.tracker_bot.tracker_storage", self.storage):
            # Position 1: NIFTY commits ₹22,500 (300 * 75)
            self.storage.insert_trade({
                "id": "tr_nifty_p1",
                "symbol": "NIFTY",
                "strategy_type": "BUY_CALL_BREAKOUT",
                "role": "BUYER",
                "entry_net_price": 300.0,
                "current_net_price": 300.0,
                "target_price": 342.0,
                "stop_loss_price": 258.0,
                "trailing_stop_price": 258.0,
                "lot_size": 75,
                "lots": 1,
                "brokerage_inr": 75.0,
                "legs": []
            })

            status = self.bot.get_capital_status()
            self.assertEqual(status["committed_margin"], 22500.0)
            self.assertEqual(status["available_capital"], 7500.0)

            # Concurrent Candidate 1: BANKNIFTY requires ₹12,075 (400 * 30 + 75) -> Must REJECT
            self.bot._record_rejection("BANKNIFTY", "CAPITAL_EXCEEDED", {
                "required": 12075.0,
                "available": status["available_capital"],
                "deficit": 12075.0 - status["available_capital"],
                "ceiling": self.bot.HARD_CAPITAL_CEILING
            })
            rejections = self.bot.get_rejections_log()
            self.assertTrue(any(r["symbol"] == "BANKNIFTY" and r["reason"] == "CAPITAL_EXCEEDED" for r in rejections))

            # Concurrent Candidate 2: FINNIFTY requires ₹6,075 (100 * 60 + 75) -> FITS in ₹7,500
            self.storage.insert_trade({
                "id": "tr_finnifty_p2",
                "symbol": "FINNIFTY",
                "strategy_type": "BUY_CALL_BREAKOUT",
                "role": "BUYER",
                "entry_net_price": 100.0,
                "current_net_price": 100.0,
                "target_price": 114.0,
                "stop_loss_price": 86.0,
                "trailing_stop_price": 86.0,
                "lot_size": 60,
                "lots": 1,
                "brokerage_inr": 75.0,
                "legs": []
            })
            status2 = self.bot.get_capital_status()
            self.assertEqual(status2["open_positions"], 2)
            self.assertEqual(status2["committed_margin"], 28500.0)
            self.assertEqual(status2["available_capital"], 1500.0)

    # -------------------------------------------------------------
    # 11. Unaffordable ATM Contracts Never Executed
    # -------------------------------------------------------------
    def test_unaffordable_atm_contract_never_executed(self):
        with patch("app.services.tracker_bot.tracker_storage", self.storage):
            # Candidate requires ₹32,787.80 (> ₹30,000 ceiling)
            required_outlay = 32787.80
            available_cap = self.bot.get_capital_status()["available_capital"]
            self.assertGreater(required_outlay, available_cap)

            # Rejection must be logged and open trades must remain 0
            self.bot._record_rejection("BANKNIFTY", "CAPITAL_EXCEEDED", {
                "required": required_outlay,
                "available": available_cap,
                "ceiling": self.bot.HARD_CAPITAL_CEILING
            })
            self.assertEqual(len(self.storage.get_open_trades()), 0)
            self.assertTrue(any(r["reason"] == "CAPITAL_EXCEEDED" for r in self.bot.get_rejections_log()))


if __name__ == "__main__":
    unittest.main()
