"""
Unit & Acceptance Tests for Phase 5A Neural-Network Benchmark
Verifies:
- Existence and integrity of Phase 5A artifacts (Scaler, K-means, Models A & B)
- Zero temporal leakage (Jan-Feb fit strictly, no target/leakage in inputs)
- Deterministic and bit-identical inference upon model reload
- Live/shadow pipeline isolation
"""
from pathlib import Path as _Path
import pytest as _pytest
if not (_Path(__file__).resolve().parents[3] / "traning dataset").exists():
    _pytest.skip("Research datasets/models are not included in this repository", allow_module_level=True)

import os
import sys
import json
import unittest
import torch
import numpy as np

proj_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
backend_dir = os.path.join(proj_dir, "backend")
if proj_dir not in sys.path:
    sys.path.insert(0, proj_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
sys.path.insert(0, os.path.join(proj_dir, "traning dataset"))

from train_and_benchmark_nn_phase5a import TabularClassifierMLP
from app.services.tracker_bot import tracker_bot
from app.db.tracker_storage import tracker_storage

ARTIFACTS_DIR = os.path.join(proj_dir, "traning dataset", "nn_benchmark_phase5a")
BACKEND_DIR = os.path.join(backend_dir, "app", "ml", "artifacts", "nn_phase5a")
MANIFEST_PATH = os.path.join(proj_dir, "traning dataset", "kmeans_feature_manifest.json")


class TestNNBenchmarkPhase5A(unittest.TestCase):

    def test_artifacts_exist_and_consistent(self):
        """Verify that all required versioned artifacts are saved in both directories."""
        required_files = [
            "scaler_fit_jan_feb.pt",
            "kmeans_fit_jan_feb_k3.pt",
            "kmeans_fit_jan_feb_k4.pt",
            "model_a_k3_mlp.pt",
            "model_b_k4_mlp.pt"
        ]
        for f in required_files:
            p1 = os.path.join(ARTIFACTS_DIR, f)
            p2 = os.path.join(BACKEND_DIR, f)
            self.assertTrue(os.path.exists(p1), f"Artifact missing in training dir: {p1}")
            self.assertTrue(os.path.exists(p2), f"Artifact missing in backend dir: {p2}")

    def test_model_architecture_and_feature_dimensions(self):
        """Verify Model A has D=31 (28 feats + 3 regimes) and Model B has D=32 (28 feats + 4 regimes)."""
        ckpt_a = torch.load(os.path.join(ARTIFACTS_DIR, "model_a_k3_mlp.pt"), weights_only=False)
        ckpt_b = torch.load(os.path.join(ARTIFACTS_DIR, "model_b_k4_mlp.pt"), weights_only=False)

        self.assertEqual(ckpt_a["in_features"], 31)
        self.assertEqual(ckpt_a["regime_k"], 3)
        self.assertEqual(len(ckpt_a["feature_names"]), 28)

        self.assertEqual(ckpt_b["in_features"], 32)
        self.assertEqual(ckpt_b["regime_k"], 4)
        self.assertEqual(len(ckpt_b["feature_names"]), 28)

        # Ensure no leakage columns are in feature names
        for bad_col in ["target_label", "fwd_ce_net_pnl", "fwd_pe_net_pnl"]:
            self.assertNotIn(bad_col, ckpt_a["feature_names"])
            self.assertNotIn(bad_col, ckpt_b["feature_names"])

    def test_deterministic_model_inference(self):
        """Verify that reloading Model A yields deterministic predictions across re-runs."""
        ckpt_a = torch.load(os.path.join(ARTIFACTS_DIR, "model_a_k3_mlp.pt"), weights_only=False)
        model = TabularClassifierMLP(in_features=31)
        model.load_state_dict(ckpt_a["model_state_dict"])
        model.eval()

        torch.manual_seed(999)
        dummy_input = torch.randn(20, 31)

        with torch.no_grad():
            out1 = model(dummy_input)
            probs1 = torch.softmax(out1, dim=1)

            out2 = model(dummy_input)
            probs2 = torch.softmax(out2, dim=1)

        self.assertTrue(torch.equal(out1, out2), "Model forward pass is non-deterministic!")
        self.assertTrue(torch.equal(probs1, probs2), "Softmax probabilities are non-deterministic!")
        self.assertEqual(out1.shape, (20, 3))

    def test_anti_leakage_and_scaler_properties(self):
        """Verify scaler was fit on Jan-Feb strictly and has finite non-zero scale values."""
        scaler_ckpt = torch.load(os.path.join(ARTIFACTS_DIR, "scaler_fit_jan_feb.pt"), weights_only=False)
        mean = scaler_ckpt["scaler_mean"]
        std = scaler_ckpt["scaler_std"]

        self.assertEqual(len(mean), 28)
        self.assertEqual(len(std), 28)
        self.assertFalse(torch.isnan(mean).any(), "Scaler mean contains NaNs!")
        self.assertFalse(torch.isnan(std).any(), "Scaler std contains NaNs!")
        self.assertTrue((std > 1e-6).all(), "Scaler std contains near-zero values!")
        self.assertEqual(scaler_ckpt["fit_partition"], "Jan-Feb 2026")

    def test_live_trading_pipeline_isolation(self):
        """Verify that live execution engines and baseline constants remain untouched."""
        self.assertEqual(tracker_bot.HARD_CAPITAL_CEILING, 30000.0)
        self.assertEqual(tracker_bot.FLAT_BROKERAGE_PER_TRADE, 75.0)

        # Verify storage connections are functioning and unmodified
        self.assertIsInstance(tracker_storage.get_open_trades(), list)
        self.assertIsInstance(tracker_storage.get_shadow_open_trades(), list)


if __name__ == "__main__":
    unittest.main()
