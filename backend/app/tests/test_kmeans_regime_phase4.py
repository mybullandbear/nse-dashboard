"""
Regression & Acceptance Tests for Phase 4 K-Means Market Regime Model
Runs via standard python unittest module.
"""
from pathlib import Path as _Path
import pytest as _pytest
if not (_Path(__file__).resolve().parents[3] / "traning dataset").exists():
    _pytest.skip("Research datasets/models are not included in this repository", allow_module_level=True)

import os
import sys
import json
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

from app.ml.kmeans_regime import TorchStandardScaler, TorchKMeans
from app.db.tracker_storage import tracker_storage
from app.services.tracker_bot import tracker_bot


MANIFEST_PATH = os.path.join(proj_dir, "traning dataset", "kmeans_feature_manifest.json")
DATASET_PATH = os.path.join(proj_dir, "traning dataset", "jan_apr_features_and_labels.csv")
MODEL_PATH = os.path.join(proj_dir, "traning dataset", "kmeans_regime_phase4", "selected_kmeans_regime_model.pt")


class TestKMeansRegimePhase4(unittest.TestCase):

    def test_feature_manifest_completeness_and_order(self):
        """Verify feature manifest matches the 28 input features in exact order."""
        self.assertTrue(os.path.exists(MANIFEST_PATH), "Feature manifest JSON does not exist!")
        with open(MANIFEST_PATH, "r") as f:
            manifest = json.load(f)

        feature_order = manifest["feature_order"]
        self.assertEqual(len(feature_order), 28, f"Expected 28 features, got {len(feature_order)}")
        self.assertNotIn("target_label", feature_order, "Target label MUST be excluded from features!")
        self.assertNotIn("fwd_ce_net_pnl", feature_order, "Forward PnL MUST be excluded from features!")
        self.assertNotIn("fwd_pe_net_pnl", feature_order, "Forward PnL MUST be excluded from features!")

        df_sample = pd.read_csv(DATASET_PATH, nrows=10)
        for feat in feature_order:
            self.assertIn(feat, df_sample.columns, f"Feature {feat} missing in dataset!")

    def test_no_missing_or_infinite_values(self):
        """Verify zero NaN or Inf values in the dataset."""
        with open(MANIFEST_PATH, "r") as f:
            manifest = json.load(f)
        feature_order = manifest["feature_order"]

        df = pd.read_csv(DATASET_PATH)
        X = df[feature_order]
        self.assertEqual(X.isnull().sum().sum(), 0, "Dataset contains NaN values!")
        self.assertEqual(np.isinf(X.values).sum(), 0, "Dataset contains Infinite values!")

    def test_temporal_leakage_prevention(self):
        """Verify that model checkpoint metadata records Jan-Mar training dates strictly."""
        self.assertTrue(os.path.exists(MODEL_PATH), "Model checkpoint does not exist!")
        ckpt = torch.load(MODEL_PATH, weights_only=False)
        train_range = ckpt.get("train_date_range", [])
        self.assertEqual(len(train_range), 2)
        self.assertGreaterEqual(train_range[0], "2026-01-01")
        self.assertLessEqual(train_range[1], "2026-03-31", f"Training range leaked beyond March: {train_range[1]}")

    def test_model_reload_and_prediction_repeatability(self):
        """Verify that loading the checkpoint produces identical predictions across multiple runs."""
        ckpt = torch.load(MODEL_PATH, weights_only=False)
        scaler = TorchStandardScaler()
        scaler.mean = ckpt["scaler_mean"]
        scaler.std = ckpt["scaler_std"]

        model = TorchKMeans(n_clusters=ckpt["k"])
        model.centroids = ckpt["centroids"]

        dummy_input = torch.randn(50, len(ckpt["feature_names"]))
        scaled_1 = scaler.transform(dummy_input)
        preds_1 = model.predict(scaled_1)

        scaled_2 = scaler.transform(dummy_input)
        preds_2 = model.predict(scaled_2)

        self.assertTrue(torch.equal(preds_1, preds_2), "Predictions are not deterministic across re-runs!")
        self.assertEqual(len(preds_1), 50)
        self.assertTrue((preds_1 >= 0).all() and (preds_1 < ckpt["k"]).all())

    def test_live_trading_pipeline_isolation(self):
        """Verify that live baseline and shadow trading paths in tracker_bot remain untouched."""
        self.assertEqual(tracker_bot.HARD_CAPITAL_CEILING, 30000.0)
        self.assertEqual(tracker_bot.FLAT_BROKERAGE_PER_TRADE, 75.0)

        live_trades = tracker_storage.get_open_trades()
        self.assertIsInstance(live_trades, list)

        shadow_trades = tracker_storage.get_shadow_open_trades()
        self.assertIsInstance(shadow_trades, list)


if __name__ == "__main__":
    unittest.main()
