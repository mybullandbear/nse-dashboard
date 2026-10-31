"""
Model A: K-Means Market Regime Detector (PyTorch Native)
High-performance, vectorised unsupervised clustering into macro market regimes:
- Trending Bullish / Bearish
- Sideways Consolidation
- Volatility Expansion
- Conflicting Signals
Immune to external C-extension DLL policy blocks; uses PyTorch CPU tensors directly.
"""
import os
import json
from typing import Dict, Any, List, Tuple, Optional
import numpy as np
import pandas as pd
import torch

from app.ml.features import FEATURE_NAMES


class TorchStandardScaler:
    """Vectorised standard scaler using PyTorch tensors."""
    def __init__(self):
        self.mean: Optional[torch.Tensor] = None
        self.std: Optional[torch.Tensor] = None

    def fit(self, X: torch.Tensor):
        self.mean = torch.mean(X, dim=0)
        self.std = torch.std(X, dim=0)
        self.std = torch.where(self.std == 0.0, torch.ones_like(self.std), self.std)

    def transform(self, X: torch.Tensor) -> torch.Tensor:
        if self.mean is None or self.std is None:
            raise ValueError("Scaler not fitted.")
        return (X - self.mean) / self.std

    def fit_transform(self, X: torch.Tensor) -> torch.Tensor:
        self.fit(X)
        return self.transform(X)


class TorchKMeans:
    """K-Means implementation with k-means++ initialization in PyTorch."""
    def __init__(self, n_clusters: int = 5, max_iter: int = 300, tol: float = 1e-4, random_state: int = 42):
        self.n_clusters = n_clusters
        self.max_iter = max_iter
        self.tol = tol
        self.random_state = random_state
        self.centroids: Optional[torch.Tensor] = None
        self.inertia_: float = 0.0

    def _kmeans_plus_plus_init(self, X: torch.Tensor) -> torch.Tensor:
        torch.manual_seed(self.random_state)
        n_samples, n_features = X.shape
        centroids = torch.empty((self.n_clusters, n_features), dtype=X.dtype)

        # Pick first centroid uniformly at random
        first_idx = torch.randint(0, n_samples, (1,)).item()
        centroids[0] = X[first_idx]

        # Pick remaining centroids with probability proportional to D(x)^2
        for c in range(1, self.n_clusters):
            dists = torch.cdist(X, centroids[:c])
            min_dists, _ = torch.min(dists, dim=1)
            probs = min_dists ** 2
            probs_sum = probs.sum()
            if probs_sum > 0:
                probs = probs / probs_sum
                next_idx = torch.multinomial(probs, 1).item()
            else:
                next_idx = torch.randint(0, n_samples, (1,)).item()
            centroids[c] = X[next_idx]

        return centroids

    def fit_predict(self, X: torch.Tensor) -> torch.Tensor:
        self.centroids = self._kmeans_plus_plus_init(X)

        labels = torch.zeros(X.shape[0], dtype=torch.long)
        for it in range(self.max_iter):
            dists = torch.cdist(X, self.centroids)
            new_labels = torch.argmin(dists, dim=1)

            new_centroids = torch.zeros_like(self.centroids)
            for k in range(self.n_clusters):
                mask = (new_labels == k)
                if mask.any():
                    new_centroids[k] = X[mask].mean(dim=0)
                else:
                    new_centroids[k] = self.centroids[k]

            shift = torch.norm(self.centroids - new_centroids)
            self.centroids = new_centroids
            labels = new_labels

            if shift < self.tol:
                break

        # Compute inertia
        dists = torch.cdist(X, self.centroids)
        min_dists, _ = torch.min(dists, dim=1)
        self.inertia_ = float((min_dists ** 2).sum().item())
        return labels

    def predict(self, X: torch.Tensor) -> torch.Tensor:
        if self.centroids is None:
            raise ValueError("KMeans not fitted.")
        dists = torch.cdist(X, self.centroids)
        return torch.argmin(dists, dim=1)


def compute_ch_score(X: torch.Tensor, labels: torch.Tensor, centroids: torch.Tensor) -> float:
    """Computes Calinski-Harabasz score using PyTorch."""
    n_samples, n_features = X.shape
    k = centroids.shape[0]
    if k <= 1 or n_samples <= k:
        return 0.0

    global_mean = X.mean(dim=0)
    extra_disp = 0.0
    intra_disp = 0.0

    for i in range(k):
        mask = (labels == i)
        c_samples = X[mask]
        n_c = c_samples.shape[0]
        if n_c > 0:
            extra_disp += n_c * torch.sum((centroids[i] - global_mean) ** 2).item()
            intra_disp += torch.sum((c_samples - centroids[i]) ** 2).item()

    if intra_disp == 0.0:
        return 0.0
    return float((extra_disp / (k - 1)) / (intra_disp / (n_samples - k)))


def compute_silhouette_estimate(X: torch.Tensor, labels: torch.Tensor, max_samples: int = 1500) -> float:
    """Estimates silhouette score over a random subsample."""
    n_samples = X.shape[0]
    if n_samples > max_samples:
        indices = torch.randperm(n_samples)[:max_samples]
        X_sub = X[indices]
        labels_sub = labels[indices]
    else:
        X_sub = X
        labels_sub = labels

    unique_labels = torch.unique(labels_sub)
    if len(unique_labels) <= 1:
        return 0.0

    dists = torch.cdist(X_sub, X_sub)
    n_sub = X_sub.shape[0]
    sil_values = []

    for i in range(n_sub):
        lbl = labels_sub[i].item()
        same_mask = (labels_sub == lbl)
        same_mask[i] = False

        if same_mask.any():
            a_i = dists[i, same_mask].mean().item()
        else:
            a_i = 0.0

        b_i = float('inf')
        for other_lbl in unique_labels:
            if other_lbl.item() != lbl:
                other_mask = (labels_sub == other_lbl)
                if other_mask.any():
                    d_other = dists[i, other_mask].mean().item()
                    b_i = min(b_i, d_other)

        denom = max(a_i, b_i)
        if denom > 0:
            sil_values.append((b_i - a_i) / denom)
        else:
            sil_values.append(0.0)

    return float(np.mean(sil_values)) if sil_values else 0.0


class KMeansRegimeEngine:
    def __init__(self, n_clusters: int = 5, random_state: int = 42):
        self.n_clusters = n_clusters
        self.random_state = random_state
        self.scaler = TorchStandardScaler()
        self.model: Optional[TorchKMeans] = None
        self.regime_profiles: Dict[int, Dict[str, Any]] = {}
        self.feature_names = FEATURE_NAMES

    def fit(self, X_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Fits the scaler and TorchKMeans model on feature DataFrame.
        """
        X_np = X_df[self.feature_names].values.astype(np.float32)
        X_t = torch.from_numpy(X_np)

        X_scaled = self.scaler.fit_transform(X_t)

        self.model = TorchKMeans(
            n_clusters=self.n_clusters,
            random_state=self.random_state
        )
        labels_t = self.model.fit_predict(X_scaled)
        labels = labels_t.cpu().numpy()

        sil_score = compute_silhouette_estimate(X_scaled, labels_t, max_samples=1500)
        ch_score = compute_ch_score(X_scaled, labels_t, self.model.centroids)
        inertia = self.model.inertia_

        # Profile clusters using unscaled feature averages
        df_labeled = X_df.copy()
        df_labeled['cluster'] = labels

        self.regime_profiles = {}
        for c_id in range(self.n_clusters):
            c_data = df_labeled[df_labeled['cluster'] == c_id]
            size = len(c_data)
            pct = round(size / len(df_labeled) * 100.0, 2)

            mean_spot_ret_5m = float(c_data['spot_ret_5m'].mean())
            mean_opt_mom = float(c_data['option_rel_momentum_5m'].mean())
            mean_oi_imb = float(c_data['net_oi_imbalance'].mean())
            mean_vol = float(c_data['spot_volatility_5m'].mean())
            mean_agree = float(c_data['indicator_agreement'].mean())
            mean_conf = float(c_data['confluence_5m_norm'].mean())

            # Assign meaningful semantic label
            if mean_agree > 0.35 and mean_spot_ret_5m > 0.04:
                semantic_name = "BULLISH_EXPANSION"
                desc = "Strong bullish indicator alignment with upward momentum and Call dominance."
            elif mean_agree < -0.35 and mean_spot_ret_5m < -0.04:
                semantic_name = "BEARISH_EXPANSION"
                desc = "Strong bearish indicator alignment with downward pressure and Put dominance."
            elif mean_vol > 0.12 or abs(mean_opt_mom) > 15.0:
                semantic_name = "HIGH_VOLATILITY_EXPANSION"
                desc = "High realized volatility with wide price swings and potential whipsaws."
            elif abs(mean_agree) < 0.20 and abs(mean_spot_ret_5m) < 0.04:
                semantic_name = "SIDEWAYS_CHOP"
                desc = "Tight range-bound consolidation with low directional momentum."
            else:
                semantic_name = "CONFLICTING_SIGNALS"
                desc = "Divergence between OI flows, indicator direction, and spot momentum."

            self.regime_profiles[c_id] = {
                "cluster_id": c_id,
                "regime_name": semantic_name,
                "description": desc,
                "sample_count": size,
                "sample_pct": pct,
                "mean_spot_ret_5m": round(mean_spot_ret_5m, 4),
                "mean_opt_momentum_5m": round(mean_opt_mom, 2),
                "mean_oi_imbalance": round(mean_oi_imb, 4),
                "mean_volatility_5m": round(mean_vol, 4),
                "mean_indicator_agreement": round(mean_agree, 4),
                "mean_confluence_5m_norm": round(mean_conf, 4)
            }

        return {
            "n_clusters": self.n_clusters,
            "inertia": inertia,
            "silhouette_score": sil_score,
            "calinski_harabasz_score": ch_score,
            "total_samples": len(X_df),
            "regimes": self.regime_profiles
        }

    def predict(self, X_df: pd.DataFrame) -> np.ndarray:
        """Predicts cluster IDs for a feature DataFrame."""
        if self.model is None:
            raise ValueError("Model not fitted.")
        X_np = X_df[self.feature_names].values.astype(np.float32)
        X_t = torch.from_numpy(X_np)
        X_scaled = self.scaler.transform(X_t)
        labels_t = self.model.predict(X_scaled)
        return labels_t.cpu().numpy()

    def predict_single(self, feat_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Predicts regime for a single feature dictionary in real time."""
        if self.model is None:
            raise ValueError("Model not fitted.")
        x_vec = np.array([[feat_dict.get(k, 0.0) for k in self.feature_names]], dtype=np.float32)
        x_t = torch.from_numpy(x_vec)
        x_scaled = self.scaler.transform(x_t)
        c_id = int(self.model.predict(x_scaled)[0].item())
        prof = self.regime_profiles.get(c_id, {
            "cluster_id": c_id,
            "regime_name": "UNKNOWN",
            "description": "Unprofiled regime"
        })
        return prof

    def save(self, model_dir: str):
        """Saves model artifacts to disk using PyTorch serialization."""
        os.makedirs(model_dir, exist_ok=True)
        torch.save({
            "centroids": self.model.centroids,
            "inertia": self.model.inertia_,
            "n_clusters": self.n_clusters,
            "scaler_mean": self.scaler.mean,
            "scaler_std": self.scaler.std,
            "feature_names": self.feature_names
        }, os.path.join(model_dir, "kmeans_regime_model.pt"))

        with open(os.path.join(model_dir, "regime_profiles.json"), "w") as f:
            json.dump(self.regime_profiles, f, indent=2)

    def load(self, model_dir: str):
        """Loads model artifacts from disk."""
        ckpt = torch.load(os.path.join(model_dir, "kmeans_regime_model.pt"))
        self.n_clusters = ckpt["n_clusters"]
        self.feature_names = ckpt["feature_names"]

        self.scaler = TorchStandardScaler()
        self.scaler.mean = ckpt["scaler_mean"]
        self.scaler.std = ckpt["scaler_std"]

        self.model = TorchKMeans(n_clusters=self.n_clusters)
        self.model.centroids = ckpt["centroids"]
        self.model.inertia_ = ckpt["inertia"]

        with open(os.path.join(model_dir, "regime_profiles.json"), "r") as f:
            raw_prof = json.load(f)
            self.regime_profiles = {int(k): v for k, v in raw_prof.items()}
