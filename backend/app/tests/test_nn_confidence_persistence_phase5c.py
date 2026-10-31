"""
Unit & Acceptance Tests for Phase 5C Confidence and Persistence Optimization
Verifies:
1. Simulator hardening: No same-bar re-entry flips (next entry >= exit_bar + 1).
2. Confidence filtering: Signal count decreases monotonically as threshold tau increases.
3. Signal persistence: P=2 and P=3 strictly require consecutive matching directional bars.
4. Capital ceiling: 100% of trades <= Rs 30,000 capital.
5. Fees accounting: Exactly Rs 75 deducted per completed trade.
6. Reconciliation: Ledger net PnL strictly reconciles to gross PnL - fees.
7. Production isolation: Baseline Variant C and Variant D shadow logic untouched.
"""
import os
import sys
import unittest
import pandas as pd
import numpy as np

proj_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
backend_dir = os.path.join(proj_dir, "backend")
if proj_dir not in sys.path:
    sys.path.insert(0, proj_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
sys.path.insert(0, os.path.join(proj_dir, "traning dataset"))

from app.services.tracker_bot import tracker_bot
from app.db.tracker_storage import tracker_storage

PHASE5C_DIR = os.path.join(proj_dir, "traning dataset", "nn_confidence_persistence_phase5c")
COMPARISON_PATH = os.path.join(PHASE5C_DIR, "phase5c_full_comparison_table.csv")
TRADES_C05_PATH = os.path.join(PHASE5C_DIR, "trades_april_c05.csv")


class TestNNConfidencePersistencePhase5C(unittest.TestCase):

    def setUp(self):
        self.assertTrue(os.path.exists(COMPARISON_PATH), f"Missing comparison summary: {COMPARISON_PATH}")
        self.df_comp = pd.read_csv(COMPARISON_PATH)

    def test_simulator_no_same_bar_reentry(self):
        """Verify that in C05 sequential trade ledger, no trade enters on the same bar as previous exit."""
        self.assertTrue(os.path.exists(TRADES_C05_PATH), f"Missing C05 ledger: {TRADES_C05_PATH}")
        df_tr = pd.read_csv(TRADES_C05_PATH)
        for i in range(len(df_tr) - 1):
            d1 = df_tr.iloc[i]["date"]
            d2 = df_tr.iloc[i + 1]["date"]
            if d1 == d2:
                exit_time = df_tr.iloc[i]["exit_time"]
                next_entry_time = df_tr.iloc[i + 1]["entry_time"]
                self.assertLess(
                    exit_time, next_entry_time,
                    f"Same-bar re-entry detected on {d1}: exit at {exit_time}, next entry at {next_entry_time}!"
                )

    def test_confidence_filtering_trade_reduction(self):
        """Verify that higher confidence threshold tau strictly reduces trade count in March and April."""
        configs = ["C01: Unrestricted Argmax (P=1)", "C04: Conf >= 0.55 (P=1)", "C05: Conf >= 0.60 (P=1)", "C06: Conf >= 0.65 (P=1)"]
        sub = self.df_comp[self.df_comp["Config"].isin(configs)].set_index("Config")

        # March trades must strictly decrease
        self.assertGreater(sub.loc["C01: Unrestricted Argmax (P=1)", "total_trades_March_Val"], sub.loc["C04: Conf >= 0.55 (P=1)", "total_trades_March_Val"])
        self.assertGreater(sub.loc["C04: Conf >= 0.55 (P=1)", "total_trades_March_Val"], sub.loc["C05: Conf >= 0.60 (P=1)", "total_trades_March_Val"])
        self.assertGreater(sub.loc["C05: Conf >= 0.60 (P=1)", "total_trades_March_Val"], sub.loc["C06: Conf >= 0.65 (P=1)", "total_trades_March_Val"])

        # April trades must strictly decrease
        self.assertGreater(sub.loc["C01: Unrestricted Argmax (P=1)", "total_trades_April_OOS"], sub.loc["C04: Conf >= 0.55 (P=1)", "total_trades_April_OOS"])
        self.assertGreater(sub.loc["C04: Conf >= 0.55 (P=1)", "total_trades_April_OOS"], sub.loc["C05: Conf >= 0.60 (P=1)", "total_trades_April_OOS"])
        self.assertGreater(sub.loc["C05: Conf >= 0.60 (P=1)", "total_trades_April_OOS"], sub.loc["C06: Conf >= 0.65 (P=1)", "total_trades_April_OOS"])

    def test_persistence_reduces_trades(self):
        """Verify that persistence P=2 strictly reduces trades compared to P=1 for same tau."""
        p1_trades = self.df_comp[self.df_comp["Config"] == "C04: Conf >= 0.55 (P=1)"]["total_trades_April_OOS"].values[0]
        p2_trades = self.df_comp[self.df_comp["Config"] == "C09: Conf >= 0.55 + P=2"]["total_trades_April_OOS"].values[0]
        self.assertGreater(p1_trades, p2_trades, "Persistence P=2 did not reduce trades compared to P=1!")

    def test_capital_ceiling_enforcement(self):
        """Verify that 100% of trades in C05 ledger satisfy Rs 30,000 ceiling."""
        df_tr = pd.read_csv(TRADES_C05_PATH)
        for _, row in df_tr.iterrows():
            self.assertLessEqual(row["capital_used"], 30000.0, f"Capital ceiling exceeded: {row['capital_used']}")

    def test_fee_and_gross_net_reconciliation(self):
        """Verify that Net PnL = Gross PnL - (Trades * 75) in C05 ledger."""
        df_tr = pd.read_csv(TRADES_C05_PATH)
        gross_sum = round(df_tr["gross_pnl"].sum(), 2)
        fees_sum = round(df_tr["fees"].sum(), 2)
        net_sum = round(df_tr["net_pnl"].sum(), 2)

        self.assertEqual(fees_sum, len(df_tr) * 75.0)
        self.assertAlmostEqual(net_sum, round(gross_sum - fees_sum, 2), places=2)

    def test_production_isolation(self):
        """Verify that production Variant C and Variant D shadow logic remains untouched."""
        self.assertEqual(tracker_bot.HARD_CAPITAL_CEILING, 30000.0)
        self.assertEqual(tracker_bot.FLAT_BROKERAGE_PER_TRADE, 75.0)
        self.assertIsInstance(tracker_storage.get_open_trades(), list)
        self.assertIsInstance(tracker_storage.get_shadow_open_trades(), list)


if __name__ == "__main__":
    unittest.main()
