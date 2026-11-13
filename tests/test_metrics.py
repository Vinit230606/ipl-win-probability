"""Brier / log loss against scikit-learn, BSS sign, ECE on a perfectly calibrated toy."""
from __future__ import annotations

import numpy as np
import pytest
from sklearn.metrics import brier_score_loss
from sklearn.metrics import log_loss as sk_log_loss

from iplwp.metrics import brier, bss, calibration_bins, ece, log_loss


@pytest.fixture
def data():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 5000)
    y = (rng.uniform(0, 1, 5000) < p).astype(int)
    return p, y


def test_brier_and_log_loss_match_sklearn(data):
    p, y = data
    assert brier(p, y) == pytest.approx(brier_score_loss(y, p))
    assert log_loss(p, y) == pytest.approx(sk_log_loss(y, np.clip(p, 1e-6, 1 - 1e-6)))


def test_log_loss_clips_extremes():
    assert np.isfinite(log_loss([0.0, 1.0], [1, 0]))
    assert log_loss([0.0], [1]) == pytest.approx(-np.log(1e-6))


def test_bss_sign():
    assert bss(0.10, 0.20) == pytest.approx(0.5)
    assert bss(0.25, 0.20) < 0
    assert bss(0.2, 0.2) == 0


def test_ece_perfect_calibration():
    # in every bin, the observed rate equals the (constant) predicted value
    p = np.repeat([0.05, 0.25, 0.55, 0.95], 20)
    y = np.concatenate([[1] + [0] * 19, [1] * 5 + [0] * 15, [1] * 11 + [0] * 9, [1] * 19 + [0]])
    assert ece(p, y) == pytest.approx(0.0, abs=1e-12)


def test_calibration_bins_edges():
    t = calibration_bins([0.0, 0.1, 0.99, 1.0], [0, 0, 1, 1], 10)
    assert len(t) == 10
    assert t.loc[0, "n"] == 1 and t.loc[1, "n"] == 1 and t.loc[9, "n"] == 2
    assert t["n"].sum() == 4
