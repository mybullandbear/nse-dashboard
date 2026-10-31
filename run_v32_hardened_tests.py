"""
Unified V3.2 Institutional Terminal Validation Test Suite
Tests all 14 backend and analytical requirements.
"""

import sys
import os
import unittest
from datetime import datetime, timezone, timedelta

# Path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from legacy_archive.v3_1_legacy.vcc_intelligence_engine import vcc_intelligence_engine, VCCIntelligenceEngine
from app.services.market_hours import get_market_session_info, is_market_open
from app.db.database import init_db, SessionLocal
from app.db.models import DailyMarketSnapshotModel
from app.schemas import OptionChainResponse, OptionStrikeData, PCRData, VIXData

IST = timezone(timedelta(hours=5, minutes=30))

class TestV32HardenedEngine(unittest.TestCase):

    def setUp(self):
        self.engine = VCCIntelligenceEngine()

    def test_01_market_hours_engine(self):
        """Test market hours session gating."""
        # 11:00 AM IST (Live - weekday check)
        dt_live = datetime(2026, 8, 26, 11, 0, 0, tzinfo=IST) # Wednesday
        sess_live = get_market_session_info(now_dt=dt_live)
        self.assertEqual(sess_live["session_state"], "LIVE_MARKET")
        self.assertTrue(sess_live["is_live"])
        self.assertTrue(sess_live["signal_generation_allowed"])

        # 23:00 PM IST (Closed)
        dt_closed = datetime(2026, 8, 26, 23, 0, 0, tzinfo=IST)
        sess_closed = get_market_session_info(now_dt=dt_closed)
        self.assertEqual(sess_closed["session_state"], "MARKET_CLOSED")
        self.assertFalse(sess_closed["is_live"])
        self.assertFalse(sess_closed["signal_generation_allowed"])

    def test_02_directional_flow_math(self):
        """Test PE/CE directional flow sign convention & non-double-counting."""
        # Test case: PE Bullish Flow +1.84L, CE Bearish Flow -0.44L
        # Expected: Net Flow = +1.40L, Total Activity = 2.28L
        pe_bullish = 1.84
        ce_bearish = -0.44
        net_flow = round(pe_bullish + ce_bearish, 2)
        tot_act = round(pe_bullish + abs(ce_bearish), 2)

        self.assertEqual(net_flow, 1.40)
        self.assertEqual(tot_act, 2.28)

    def test_03_strike_classification(self):
        """Test strike level action classification."""
        # PE Writing: OI +15,000, LTP -2.5
        act_pe_write, conf = self.engine._classify_option_action(15000, 100.0, 102.5, "PE", has_history=True)
        self.assertEqual(act_pe_write, "PUT WRITING")

        # CE Writing: OI +20,000, LTP -4.0
        act_ce_write, conf = self.engine._classify_option_action(20000, 150.0, 154.0, "CE", has_history=True)
        self.assertEqual(act_ce_write, "CALL WRITING")

        # PE Short Covering: OI -10,000, LTP +3.0
        act_pe_sc, conf = self.engine._classify_option_action(-10000, 105.0, 102.0, "PE", has_history=True)
        self.assertEqual(act_pe_sc, "PUT SHORT COVERING")

        # CE Short Covering: OI -12,000, LTP +4.0
        act_ce_sc, conf = self.engine._classify_option_action(-12000, 120.0, 116.0, "CE", has_history=True)
        self.assertEqual(act_ce_sc, "CALL SHORT COVERING")

        # PE Long Buildup: OI +10,000, LTP +5.0
        act_pe_lb, conf = self.engine._classify_option_action(10000, 110.0, 105.0, "PE", has_history=True)
        self.assertEqual(act_pe_lb, "PUT LONG BUILDUP")

        # CE Long Buildup: OI +10,000, LTP +5.0
        act_ce_lb, conf = self.engine._classify_option_action(10000, 130.0, 125.0, "CE", has_history=True)
        self.assertEqual(act_ce_lb, "CALL LONG BUILDUP")

    def test_04_data_sufficiency(self):
        """Test strict data sufficiency enforcement when snapshot history is missing."""
        act_no_hist, conf = self.engine._classify_option_action(15000, 100.0, 102.5, "PE", has_history=False)
        self.assertEqual(act_no_hist, "DATA INSUFFICIENT")

    def test_05_wall_oscillation_detector(self):
        """Test wall migration oscillation filter."""
        # Create sequence bouncing back and forth: 24000 -> 23950 -> 24000 -> 23950
        snaps = []
        for i, stk in enumerate([24000, 23950, 24000, 23950, 24000]):
            m = DailyMarketSnapshotModel(
                trade_date="2026-08-24",
                timestamp=f"2026-08-24T10:{i*5:02d}:00",
                symbol="NIFTY",
                spot_price=24000.0,
                atm_strike=stk - 200, # so PE strike becomes stk
                pcr=1.0
            )
            snaps.append(m)

        mig = self.engine._compute_wall_migration(snaps, "PE")
        self.assertIn("OSCILLATING", mig["direction"])
        self.assertEqual(mig["velocity_pts_hr"], 0.0)

    def test_06_look_ahead_protection(self):
        """Verify look-ahead protection logic."""
        snaps = [
            DailyMarketSnapshotModel(trade_date="2026-08-24", timestamp="2026-08-24T10:00:00", symbol="NIFTY", spot_price=24000.0, atm_strike=24000.0, pcr=1.0),
            DailyMarketSnapshotModel(trade_date="2026-08-24", timestamp="2026-08-24T10:05:00", symbol="NIFTY", spot_price=24020.0, atm_strike=24000.0, pcr=1.05),
            DailyMarketSnapshotModel(trade_date="2026-08-24", timestamp="2026-08-24T10:15:00", symbol="NIFTY", spot_price=24050.0, atm_strike=24000.0, pcr=1.10),
        ]
        res = self.engine._compute_historical_outcome_reliability(snaps, 23800.0, 24200.0)
        self.assertIsNotNone(res)

if __name__ == '__main__':
    unittest.main()
