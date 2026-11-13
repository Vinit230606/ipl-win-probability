"""Probability metrics (design section 11.1): Brier, log loss, BSS, calibration bins, ECE.

All functions take arrays of predicted probabilities `p` and 0/1 outcomes `y` and are pure.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def brier(p, y) -> float:
    """Mean squared difference between probability and outcome."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def log_loss(p, y, eps: float = 1e-6) -> float:
    """Mean negative log-likelihood with p clipped to [eps, 1 - eps]."""
    pc = np.clip(np.asarray(p, float), eps, 1 - eps)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc)))


def bss(brier_model: float, brier_reference: float) -> float:
    """Brier skill score: 1 - Brier_model / Brier_reference (> 0 means better than reference)."""
    return float(1.0 - brier_model / brier_reference)


def calibration_bins(p, y, n_bins: int = 10) -> pd.DataFrame:
    """Equal-width bins on p: bin index, edges, count, mean predicted, observed rate.

    p = 1.0 falls in the last bin. Empty bins are kept with n = 0 and NaN means.
    """
    p, y = np.asarray(p, float), np.asarray(y, float)
    idx = np.minimum((p * n_bins).astype(int), n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        n = int(m.sum())
        rows.append({"bin": b, "lo": b / n_bins, "hi": (b + 1) / n_bins, "n": n,
                     "mean_p": float(p[m].mean()) if n else np.nan,
                     "observed_rate": float(y[m].mean()) if n else np.nan})
    return pd.DataFrame(rows)


def ece(p, y, n_bins: int = 10) -> float:
    """Expected calibration error: sum over bins of (n_b / N) * |observed_b - mean_p_b|."""
    t = calibration_bins(p, y, n_bins)
    t = t[t["n"] > 0]
    return float((t["n"] / t["n"].sum() * (t["observed_rate"] - t["mean_p"]).abs()).sum())
