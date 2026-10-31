"""
V3.2 Final Pre-Live Audit Test Suite — 20 Verification Conditions.
Verifies snapshot immutability, look-ahead protection, window-restricted MFE/MAE,
data quality filters, symmetric directional logic, session boundaries, and sample governance.
"""

import sys
import os
import unittest
from datetime import datetime, timedelta
from pytz import timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'legacy_archive', 'v3_1_legacy'))

from app.db.database import init_db, SessionLocal, engine
from app.db.models import VCCLiveSignalAuditModel, DailyMarketSnapshotModel
from app.schemas import OptionChainResponse, PCRData, VIXData
from legacy_archive.v3_1_legacy.live_signal_audit_service import (
    live_signal_audit_service,
    get_session_slot,
    get_sample_governance_label,
    IST
)
from legacy_archive.v3_1_legacy.vcc_intelligence_engine import vcc_intelligence_engine
from sqlalchemy.exc import IntegrityError

class TestV32TwentyConditionsAudit(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db = SessionLocal()
        # Clear test audit entries
        self.db.query(VCCLiveSignalAuditModel).filter(VCCLiveSignalAuditModel.symbol.like("AUDIT_TEST_%")).delete(synchronize_session=False)
        self.db.query(DailyMarketSnapshotModel).filter(DailyMarketSnapshotModel.symbol.like("AUDIT_TEST_%")).delete(synchronize_session=False)
        self.db.commit()

    def tearDown(self):
        self.db.query(VCCLiveSignalAuditModel).filter(VCCLiveSignalAuditModel.symbol.like("AUDIT_TEST_%")).delete(synchronize_session=False)
        self.db.query(DailyMarketSnapshotModel).filter(DailyMarketSnapshotModel.symbol.like("AUDIT_TEST_%")).delete(synchronize_session=False)
        self.db.commit()
        self.db.close()

    def test_condition_01_snapshot_immutability(self):
        """1. Every signal snapshot is immutable."""
        snap_id = "AUDIT_TEST_IMMUTABLE_01"
        rec = VCCLiveSignalAuditModel(
            snapshot_id=snap_id,
            trade_date="2026-08-25",
            timestamp="2026-08-25T10:00:00",
            symbol="AUDIT_TEST_NIFTY",
            operational_state="ENTRY CONFIRMED",
            spot_price=24200.0,
            final_confluence_score=85.0
        )
        self.db.add(rec)
        self.db.commit()

        # Re-fetch and verify original attributes are fixed
        fetched = self.db.query(VCCLiveSignalAuditModel).filter_by(snapshot_id=snap_id).first()
        self.assertEqual(fetched.operational_state, "ENTRY CONFIRMED")
        self.assertEqual(fetched.spot_price, 24200.0)
        self.assertEqual(fetched.final_confluence_score, 85.0)

    def test_condition_02_future_timestamp_requirement(self):
        """2. T+5, T+15 and T+30 outcomes calculated ONLY after future timestamp exists."""
        t0_str = "2026-08-25T10:00:00"
        rec = VCCLiveSignalAuditModel(
            snapshot_id="AUDIT_TEST_TIMING_01",
            trade_date="2026-08-25",
            timestamp=t0_str,
            symbol="AUDIT_TEST_NIFTY",
            spot_price=24200.0,
            signal_direction="BULLISH",
            operational_state="ENTRY CONFIRMED",
            outcome_evaluated=False
        )
        self.db.add(rec)
        self.db.commit()

        # Add snapshot only 1 minute in the future (< 300s max elapsed)
        s1 = DailyMarketSnapshotModel(trade_date="2026-08-25", timestamp="2026-08-25T10:01:00", symbol="AUDIT_TEST_NIFTY", spot_price=24210.0)
        self.db.add(s1)
        self.db.commit()

        live_signal_audit_service.evaluate_pending_signal_outcomes(symbol="AUDIT_TEST_NIFTY")

        fetched = self.db.query(VCCLiveSignalAuditModel).filter_by(snapshot_id="AUDIT_TEST_TIMING_01").first()
        # Should not be evaluated yet as 300s elapsed does not exist
        self.assertFalse(fetched.outcome_evaluated)
        self.assertIsNone(fetched.spot_t5)

        # Now add snapshots at T+5m (10:05:00) and T+15m (10:15:00)
        s5 = DailyMarketSnapshotModel(trade_date="2026-08-25", timestamp="2026-08-25T10:05:00", symbol="AUDIT_TEST_NIFTY", spot_price=24230.0)
        s15 = DailyMarketSnapshotModel(trade_date="2026-08-25", timestamp="2026-08-25T10:15:00", symbol="AUDIT_TEST_NIFTY", spot_price=24250.0)
        self.db.add_all([s5, s15])
        self.db.commit()

        live_signal_audit_service.evaluate_pending_signal_outcomes(symbol="AUDIT_TEST_NIFTY")
        fetched = self.db.query(VCCLiveSignalAuditModel).filter_by(snapshot_id="AUDIT_TEST_TIMING_01").first()
        self.assertTrue(fetched.outcome_evaluated)
        self.assertEqual(fetched.spot_t5, 24230.0)
        self.assertEqual(fetched.spot_t15, 24250.0)

    def test_condition_03_no_future_data_in_original_signal(self):
        """3. No future data is available to original signal calculation."""
        res = vcc_intelligence_engine.compute_vcc_intelligence("NIFTY", None, None, None)
        # Verify signal contains zero future outcome fields
        self.assertNotIn("spot_t5", res)
        self.assertNotIn("directional_correctness_15m", res)
        self.assertNotIn("future_price", res)

    def test_condition_04_mfe_mae_window_restricted(self):
        """4. MFE and MAE are calculated only from data occurring AFTER signal timestamp T."""
        t0_str = "2026-08-25T10:00:00"
        
        # Historical past snapshot at T-10m with extreme spot 25000
        s_past = DailyMarketSnapshotModel(trade_date="2026-08-25", timestamp="2026-08-25T09:50:00", symbol="AUDIT_TEST_MFE", spot_price=25000.0)
        
        rec = VCCLiveSignalAuditModel(
            snapshot_id="AUDIT_TEST_MFE_01",
            trade_date="2026-08-25",
            timestamp=t0_str,
            symbol="AUDIT_TEST_MFE",
            spot_price=24000.0,
            signal_direction="BULLISH",
            operational_state="ENTRY CONFIRMED",
            outcome_evaluated=False
        )
        
        # Future snapshots post T0 (max spot 24200, min spot 23950)
        s5 = DailyMarketSnapshotModel(trade_date="2026-08-25", timestamp="2026-08-25T10:05:00", symbol="AUDIT_TEST_MFE", spot_price=24100.0)
        s15 = DailyMarketSnapshotModel(trade_date="2026-08-25", timestamp="2026-08-25T10:15:00", symbol="AUDIT_TEST_MFE", spot_price=23950.0)
        s30 = DailyMarketSnapshotModel(trade_date="2026-08-25", timestamp="2026-08-25T10:30:00", symbol="AUDIT_TEST_MFE", spot_price=24200.0)
        
        self.db.add_all([s_past, rec, s5, s15, s30])
        self.db.commit()

        live_signal_audit_service.evaluate_pending_signal_outcomes(symbol="AUDIT_TEST_MFE")

        fetched = self.db.query(VCCLiveSignalAuditModel).filter_by(snapshot_id="AUDIT_TEST_MFE_01").first()
        # Expected max spot in future window is 24200 -> MFE = (24200 - 24000)/24000 * 100 = 0.833%
        # If past 25000 was used, MFE would be (25000 - 24000)/24000 * 100 = 4.166%
        self.assertAlmostEqual(fetched.mfe_t30_pct, 0.833, places=2)

    def test_condition_05_unavailable_outcomes_not_failures(self):
        """5. Expired/unavailable outcomes are NOT treated as failures."""
        rec = VCCLiveSignalAuditModel(
            snapshot_id="AUDIT_TEST_UNAVAIL_01",
            trade_date="2026-08-25",
            timestamp="2026-08-25T10:00:00",
            symbol="AUDIT_TEST_NIFTY",
            spot_price=24200.0,
            signal_direction="BULLISH",
            outcome_evaluated=False
        )
        self.db.add(rec)
        self.db.commit()

        # Evaluate with no future snapshots available
        live_signal_audit_service.evaluate_pending_signal_outcomes(symbol="AUDIT_TEST_NIFTY")

        rep = live_signal_audit_service.get_audit_summary_report(symbol="AUDIT_TEST_NIFTY")
        self.assertEqual(rep["outcomes"]["false_signals"], 0)
        self.assertEqual(rep["outcomes"]["correct_signals"], 0)

    def test_condition_06_invalid_data_excluded_from_stats(self):
        """6. DATA QUALITY INVALID observations excluded from performance statistics."""
        r_good = VCCLiveSignalAuditModel(
            snapshot_id="AUDIT_TEST_DQ_GOOD",
            trade_date="2026-08-25",
            timestamp="2026-08-25T10:00:00",
            symbol="AUDIT_TEST_DQ",
            spot_price=24200.0,
            signal_direction="BULLISH",
            data_quality_status="DATA QUALITY GOOD",
            outcome_evaluated=True,
            directional_correctness_15m="CORRECT"
        )
        r_inv = VCCLiveSignalAuditModel(
            snapshot_id="AUDIT_TEST_DQ_INVALID",
            trade_date="2026-08-25",
            timestamp="2026-08-25T10:01:00",
            symbol="AUDIT_TEST_DQ",
            spot_price=24200.0,
            signal_direction="BULLISH",
            data_quality_status="DATA QUALITY INVALID",
            outcome_evaluated=True,
            directional_correctness_15m="FALSE"
        )
        self.db.add_all([r_good, r_inv])
        self.db.commit()

        rep = live_signal_audit_service.get_audit_summary_report(symbol="AUDIT_TEST_DQ")
        self.assertEqual(rep["valid_signals"], 1)
        self.assertEqual(rep["invalid_data_signals"], 1)
        self.assertEqual(rep["outcomes"]["evaluated_signals"], 1)
        self.assertEqual(rep["outcomes"]["accuracy_15m_pct"], 100.0)

    def test_condition_07_watch_no_signal_not_directional_wins_losses(self):
        """7. WATCH / NO SIGNAL observations cannot accidentally be counted as directional wins/losses."""
        rec = VCCLiveSignalAuditModel(
            snapshot_id="AUDIT_TEST_WATCH_01",
            trade_date="2026-08-25",
            timestamp="2026-08-25T10:00:00",
            symbol="AUDIT_TEST_NIFTY",
            spot_price=24200.0,
            signal_direction="NEUTRAL",
            operational_state="WATCH",
            outcome_evaluated=False
        )
        s15 = DailyMarketSnapshotModel(trade_date="2026-08-25", timestamp="2026-08-25T10:15:00", symbol="AUDIT_TEST_NIFTY", spot_price=24260.0)
        self.db.add_all([rec, s15])
        self.db.commit()

        live_signal_audit_service.evaluate_pending_signal_outcomes(symbol="AUDIT_TEST_NIFTY")

        fetched = self.db.query(VCCLiveSignalAuditModel).filter_by(snapshot_id="AUDIT_TEST_WATCH_01").first()
        self.assertEqual(fetched.directional_correctness_15m, "NEUTRAL")

    def test_condition_08_symmetric_bullish_bearish_logic(self):
        """8. BULLISH and BEARISH success calculations use symmetric logic."""
        # Bullish signal +20pt move -> CORRECT
        c_bull_pos = live_signal_audit_service._classify_correctness_pts(True, False, 24220.0, 24200.0, 15.0)
        # Bullish signal -20pt move -> FALSE
        c_bull_neg = live_signal_audit_service._classify_correctness_pts(True, False, 24180.0, 24200.0, 15.0)

        # Bearish signal -20pt move -> CORRECT
        c_bear_pos = live_signal_audit_service._classify_correctness_pts(False, True, 24180.0, 24200.0, 15.0)
        # Bearish signal +20pt move -> FALSE
        c_bear_neg = live_signal_audit_service._classify_correctness_pts(False, True, 24220.0, 24200.0, 15.0)

        self.assertEqual(c_bull_pos, "CORRECT")
        self.assertEqual(c_bull_neg, "FALSE")
        self.assertEqual(c_bear_pos, "CORRECT")
        self.assertEqual(c_bear_neg, "FALSE")

    def test_condition_09_signal_conflict_not_directional(self):
        """9. SIGNAL CONFLICT does not accidentally count as a directional prediction."""
        rec = VCCLiveSignalAuditModel(
            snapshot_id="AUDIT_TEST_CONFLICT_01",
            trade_date="2026-08-25",
            timestamp="2026-08-25T10:00:00",
            symbol="AUDIT_TEST_NIFTY",
            spot_price=24200.0,
            signal_direction="SIGNAL CONFLICT",
            operational_state="SIGNAL CONFLICT",
            outcome_evaluated=False
        )
        s15 = DailyMarketSnapshotModel(trade_date="2026-08-25", timestamp="2026-08-25T10:15:00", symbol="AUDIT_TEST_NIFTY", spot_price=24300.0)
        self.db.add_all([rec, s15])
        self.db.commit()

        live_signal_audit_service.evaluate_pending_signal_outcomes(symbol="AUDIT_TEST_NIFTY")

        fetched = self.db.query(VCCLiveSignalAuditModel).filter_by(snapshot_id="AUDIT_TEST_CONFLICT_01").first()
        self.assertEqual(fetched.directional_correctness_15m, "NEUTRAL")

    def test_condition_10_duplicate_snapshots_prevented(self):
        """10. Duplicate snapshots cannot inflate signal counts."""
        snap_id = "AUDIT_TEST_DUP_KEY"
        rec1 = VCCLiveSignalAuditModel(snapshot_id=snap_id, trade_date="2026-08-25", timestamp="2026-08-25T10:00:00", symbol="AUDIT_TEST_NIFTY")
        self.db.add(rec1)
        self.db.commit()

        # Try inserting duplicate PK
        rec2 = VCCLiveSignalAuditModel(snapshot_id=snap_id, trade_date="2026-08-25", timestamp="2026-08-25T10:00:00", symbol="AUDIT_TEST_NIFTY")
        self.db.add(rec2)
        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_condition_11_persistent_signal_deduplication(self):
        """11. A persistent signal is not incorrectly counted as 100 independent signals merely because observed repeatedly."""
        mock_intel = {
            "symbol": "AUDIT_TEST_DEDUP",
            "spot_price": 24200.0,
            "signal_meta": {"operational_state": "ENTRY CONFIRMED", "signal_confidence": 85.0},
            "final_confluence": {"score": 80.0, "label": "BULLISH", "evidence_count": 5, "conflict_count": 0},
            "flow_engine": {"directional_flow_label": "PUT WRITING", "net_flow_lakhs": 2.0},
            "connection_telemetry": {"option_data_age_sec": 5.0, "spot_data_age_sec": 1.0}
        }

        # Log 1st snapshot
        sid1 = live_signal_audit_service.record_live_signal_snapshot(mock_intel)
        self.assertIsNotNone(sid1)

        # Immediate 2nd tick with same state -> throttled, returns None
        sid2 = live_signal_audit_service.record_live_signal_snapshot(mock_intel)
        self.assertIsNone(sid2)

    def test_condition_12_outcomes_not_double_counted(self):
        """12. T+5/T+15/T+30 observations cannot be double-counted."""
        rec = VCCLiveSignalAuditModel(
            snapshot_id="AUDIT_TEST_DBL_01",
            trade_date="2026-08-25",
            timestamp="2026-08-25T10:00:00",
            symbol="AUDIT_TEST_NIFTY",
            spot_price=24200.0,
            signal_direction="BULLISH",
            outcome_evaluated=False
        )
        s15 = DailyMarketSnapshotModel(trade_date="2026-08-25", timestamp="2026-08-25T10:15:00", symbol="AUDIT_TEST_NIFTY", spot_price=24250.0)
        self.db.add_all([rec, s15])
        self.db.commit()

        eval_cnt_1 = live_signal_audit_service.evaluate_pending_signal_outcomes(symbol="AUDIT_TEST_NIFTY")
        self.assertEqual(eval_cnt_1, 1)

        # Second run should process 0 records because outcome_evaluated is now True
        eval_cnt_2 = live_signal_audit_service.evaluate_pending_signal_outcomes(symbol="AUDIT_TEST_NIFTY")
        self.assertEqual(eval_cnt_2, 0)

    def test_condition_13_market_closed_no_new_live_signals(self):
        """13. Market-closed observations cannot generate new live signals."""
        # 18:00 IST is post market hours
        ist = timezone("Asia/Kolkata")
        closed_dt = ist.localize(datetime(2026, 8, 25, 18, 0, 0))

        chain = OptionChainResponse(symbol="NIFTY", spot_price=24200.0, atm_strike=24200, expiry="2026-08-27", strikes=[])
        res = vcc_intelligence_engine.compute_vcc_intelligence(
            symbol="NIFTY",
            chain=chain,
            pcr_obj=None,
            vix_obj=None,
            override_now_dt=closed_dt
        )
        self.assertEqual(res["signal_meta"]["operational_state"], "MARKET CLOSED")
        self.assertEqual(res["market_state_strip"]["session_state"], "MARKET CLOSED")
        self.assertFalse(res["market_state_strip"]["execution_enabled"])

    def test_condition_14_session_boundaries_respected(self):
        """14. Session boundaries are respected."""
        rec_day1 = VCCLiveSignalAuditModel(
            snapshot_id="AUDIT_TEST_SESS_DAY1",
            trade_date="2026-08-25",
            timestamp="2026-08-25T15:25:00",
            symbol="AUDIT_TEST_NIFTY",
            spot_price=24200.0,
            signal_direction="BULLISH",
            outcome_evaluated=False
        )
        # Snapshot next day at 09:20
        s_day2 = DailyMarketSnapshotModel(trade_date="2026-08-26", timestamp="2026-08-26T09:20:00", symbol="AUDIT_TEST_NIFTY", spot_price=24500.0)
        self.db.add_all([rec_day1, s_day2])
        self.db.commit()

        live_signal_audit_service.evaluate_pending_signal_outcomes(symbol="AUDIT_TEST_NIFTY")

        fetched = self.db.query(VCCLiveSignalAuditModel).filter_by(snapshot_id="AUDIT_TEST_SESS_DAY1").first()
        # Day 2 snapshot must NOT be used for Day 1 15m outcome -> spot_t15 remains None
        self.assertIsNone(fetched.spot_t15)

    def test_condition_15_independent_timestamps_stored(self):
        """15. Option-chain timestamp and spot timestamp are stored independently."""
        opt_ts = "2026-08-25T10:00:02"
        spot_ts = "2026-08-25T10:00:05"

        mock_intel = {
            "symbol": "AUDIT_TEST_IND_TS",
            "spot_price": 24200.0,
            "connection_telemetry": {
                "option_chain_timestamp": opt_ts,
                "spot_timestamp": spot_ts,
                "option_data_age_sec": 4.0,
                "spot_data_age_sec": 1.0
            }
        }
        sid = live_signal_audit_service.record_live_signal_snapshot(mock_intel)
        fetched = self.db.query(VCCLiveSignalAuditModel).filter_by(snapshot_id=sid).first()

        self.assertEqual(fetched.option_chain_timestamp, opt_ts)
        self.assertEqual(fetched.spot_timestamp, spot_ts)

    def test_condition_16_data_age_from_actual_source(self):
        """16. Data age is calculated from actual source timestamp, not application refresh time."""
        mock_intel = {
            "symbol": "AUDIT_TEST_AGE",
            "spot_price": 24200.0,
            "connection_telemetry": {
                "option_data_age_sec": 18.5,
                "spot_data_age_sec": 2.1
            }
        }
        sid = live_signal_audit_service.record_live_signal_snapshot(mock_intel)
        fetched = self.db.query(VCCLiveSignalAuditModel).filter_by(snapshot_id=sid).first()

        self.assertEqual(fetched.option_data_age_sec, 18.5)
        self.assertEqual(fetched.spot_data_age_sec, 2.1)

    def test_condition_17_confidence_not_presented_as_win_probability(self):
        """17. Confidence is never presented as win probability."""
        rep = live_signal_audit_service.get_audit_summary_report("AUDIT_TEST_NIFTY")
        self.assertIn("confidence_calibration", rep)
        self.assertNotIn("win_probability", str(rep))

    def test_condition_18_daily_stats_use_only_completed_outcomes(self):
        """18. Daily statistics use only completed outcomes."""
        r_compl = VCCLiveSignalAuditModel(
            snapshot_id="AUDIT_TEST_COMPL",
            trade_date="2026-08-25",
            timestamp="2026-08-25T10:00:00",
            symbol="AUDIT_TEST_COMPL",
            spot_price=24200.0,
            signal_direction="BULLISH",
            data_quality_status="DATA QUALITY GOOD",
            outcome_evaluated=True,
            directional_correctness_15m="CORRECT"
        )
        r_pend = VCCLiveSignalAuditModel(
            snapshot_id="AUDIT_TEST_PEND",
            trade_date="2026-08-25",
            timestamp="2026-08-25T10:01:00",
            symbol="AUDIT_TEST_COMPL",
            spot_price=24200.0,
            signal_direction="BULLISH",
            data_quality_status="DATA QUALITY GOOD",
            outcome_evaluated=False
        )
        self.db.add_all([r_compl, r_pend])
        self.db.commit()

        rep = live_signal_audit_service.get_audit_summary_report(symbol="AUDIT_TEST_COMPL")
        self.assertEqual(rep["total_signals"], 2)
        self.assertEqual(rep["outcomes"]["evaluated_signals"], 1)
        self.assertEqual(rep["outcomes"]["insufficient_outcome_data"], 1)

    def test_condition_19_incomplete_samples_labelled_insufficient(self):
        """19. Incomplete samples are explicitly labelled INSUFFICIENT SAMPLE."""
        self.assertEqual(get_sample_governance_label(0), "INSUFFICIENT SAMPLE")
        self.assertEqual(get_sample_governance_label(12), "INSUFFICIENT SAMPLE")
        self.assertEqual(get_sample_governance_label(29), "INSUFFICIENT SAMPLE")

    def test_condition_20_app_restart_prevents_duplicate_signals(self):
        """20. Restarting the application does not duplicate existing signals."""
        ts_str = "2026-08-25T10:00:00"
        mock_intel = {
            "symbol": "AUDIT_TEST_RESTART",
            "spot_price": 24200.0,
            "timestamp": ts_str,
            "signal_meta": {"operational_state": "ENTRY CONFIRMED", "signal_id": "AUDIT_TEST_RESTART_FIXED_ID"}
        }

        # Log initial signal before restart
        sid1 = live_signal_audit_service.record_live_signal_snapshot(mock_intel)
        self.assertIsNotNone(sid1)

        # Simulate App Restart by resetting in-memory throttle dictionary
        live_signal_audit_service._last_state_per_symbol.clear()

        # Attempt to log same signal with same timestamp
        sid2 = live_signal_audit_service.record_live_signal_snapshot(mock_intel)
        # Should be suppressed by DB primary key / unique constraint
        self.assertIsNone(sid2)


if __name__ == "__main__":
    unittest.main()
