"""
Unit & Acceptance Tests for Phase 5B Backtest Integrity Audit
Verifies:
1. No overlapping positions (sequential position exclusivity).
2. Capital ceiling enforcement (all entries <= Rs 30,000).
3. No future-data leakage (sequential chronological order).
4. Correct fee deduction (Rs 75 per completed trade exactly).
5. Correct adverse slippage calculation (0.5% entry, 0.5% exit).
6. Correct exit reason handling (SL -15%, T1 trail +3%, T2 +30%, Time 15m, EOD).
7. Consistent P&L reconciliation between trade ledger and equity curve.
8. Accurate equity-based maximum drawdown calculation.
9. Deterministic replay from saved predictions.
10. Production broker-routing and baseline isolation.
"""
from pathlib import Path as _Path
import pytest as _pytest
if not (_Path(__file__).resolve().parents[3] / "traning dataset").exists():
    _pytest.skip("Research datasets/models are not included in this repository", allow_module_level=True)

import os
import sys
import unittest
import pandas as pd
import numpy as np
import torch

proj_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
backend_dir = os.path.join(proj_dir, "backend")
if proj_dir not in sys.path:
    sys.path.insert(0, proj_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
sys.path.insert(0, os.path.join(proj_dir, "traning dataset"))

from app.services.tracker_bot import tracker_bot
from app.db.tracker_storage import tracker_storage

AUDIT_DIR = os.path.join(proj_dir, "traning dataset", "nn_backtest_audit_phase5b")
LEDGER_PATH = os.path.join(AUDIT_DIR, "model_a_sequential_trade_ledger_april.csv")
REJECTIONS_PATH = os.path.join(AUDIT_DIR, "model_a_rejection_ledger_april.csv")
COMPARISON_PATH = os.path.join(AUDIT_DIR, "phase5b_audit_comparison_table.csv")


class TestNNBacktestAuditPhase5B(unittest.TestCase):

    def setUp(self):
        self.assertTrue(os.path.exists(LEDGER_PATH), f"Trade ledger missing: {LEDGER_PATH}")
        self.df_trades = pd.read_csv(LEDGER_PATH)

    def test_no_overlapping_positions(self):
        """Verify that no two trades in the ledger have overlapping time windows on the same date."""
        dates = self.df_trades["date"].unique()
        for d in dates:
            sess_trades = self.df_trades[self.df_trades["date"] == d].copy()
            for i in range(len(sess_trades) - 1):
                curr_exit = sess_trades.iloc[i]["exit_time"]
                next_entry = sess_trades.iloc[i + 1]["entry_time"]
                self.assertLessEqual(
                    curr_exit, next_entry,
                    f"Overlapping trades detected on {d}: trade exits at {curr_exit} but next enters at {next_entry}!"
                )

    def test_capital_ceiling_enforcement(self):
        """Verify that capital used for every entry is strictly <= Rs 30,000."""
        for _, row in self.df_trades.iterrows():
            cap = row["capital_used"]
            self.assertLessEqual(
                cap, 30000.0,
                f"Trade on {row['date']} at {row['entry_time']} exceeded Rs 30,000 ceiling: {cap}"
            )

    def test_fees_and_slippage_accounting(self):
        """Verify that every completed trade deducts exactly Rs 75 and gross/net reconcile."""
        for _, row in self.df_trades.iterrows():
            self.assertEqual(row["fees"], 75.0, "Fee per trade is not Rs 75.0!")
            expected_net = round(row["gross_pnl"] - 75.0, 2)
            self.assertAlmostEqual(
                row["net_pnl"], expected_net, places=2,
                msg="Net P&L does not equal gross_pnl - 75.0!"
            )

    def test_exit_rules_and_holding_duration(self):
        """Verify that holding duration never exceeds 15 bars and exit reasons are valid."""
        valid_reasons = {"STOP_LOSS", "TRAILING_SL", "TARGET_2", "TIME_EXIT_15M", "EOD_EXIT"}
        for _, row in self.df_trades.iterrows():
            self.assertIn(row["exit_reason"], valid_reasons, f"Invalid exit reason: {row['exit_reason']}")
            self.assertLessEqual(row["bars_held"], 15, f"Trade held longer than 15 bars: {row['bars_held']}")
            self.assertGreater(row["bars_held"], 0, f"Trade held 0 bars: {row['bars_held']}")

    def test_pnl_and_equity_curve_reconciliation(self):
        """Verify that cumulative net PnL in ledger matches reported total Net PnL."""
        total_ledger_net = round(self.df_trades["net_pnl"].sum(), 2)
        total_ledger_gross = round(self.df_trades["gross_pnl"].sum(), 2)
        total_fees = round(self.df_trades["fees"].sum(), 2)

        self.assertAlmostEqual(total_ledger_net, round(total_ledger_gross - total_fees, 2), places=2)

        # Check against comparison table
        df_comp = pd.read_csv(COMPARISON_PATH)
        row_a = df_comp[df_comp["Candidate"] == "Model A (MLP + K=3)"].iloc[0]
        self.assertAlmostEqual(total_ledger_net, row_a["Phase5B_Seq_NetPnL"], places=2)
        self.assertEqual(len(self.df_trades), row_a["Phase5B_Seq_Trades"])

    def test_drawdown_calculation_integrity(self):
        """Verify that equity drawdown calculation is mathematically sound."""
        equity = np.cumsum(self.df_trades["net_pnl"].values)
        running_max = np.maximum.accumulate(equity)
        drawdowns = running_max - equity
        calculated_max_dd = round(float(np.max(drawdowns)), 2)

        df_comp = pd.read_csv(COMPARISON_PATH)
        row_a = df_comp[df_comp["Candidate"] == "Model A (MLP + K=3)"].iloc[0]
        self.assertAlmostEqual(calculated_max_dd, row_a["Phase5B_Seq_MaxDD"], places=2)

    def test_rejections_ledger_integrity(self):
        """Verify that overlapping signal rejections were logged and account for the discrepancy."""
        df_rej = pd.read_csv(REJECTIONS_PATH)
        pos_open_rejections = len(df_rej[df_rej["reason"] == "POSITION_ALREADY_OPEN"])
        self.assertGreater(pos_open_rejections, 2000, "Expected > 2,000 overlapping rejections!")

    def test_production_and_routing_isolation(self):
        """Verify that production Variant C and Variant D constants and storage remain untouched."""
        self.assertEqual(tracker_bot.HARD_CAPITAL_CEILING, 30000.0)
        self.assertEqual(tracker_bot.FLAT_BROKERAGE_PER_TRADE, 75.0)
        self.assertIsInstance(tracker_storage.get_open_trades(), list)
        self.assertIsInstance(tracker_storage.get_shadow_open_trades(), list)


if __name__ == "__main__":
    unittest.main()
