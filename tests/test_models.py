"""Recency weights (D8) and monotonic constraint order."""
from __future__ import annotations

import numpy as np
import pytest

from iplwp.features import BASE7
from iplwp.models import MONO, recency_weights


def test_uniform():
    assert recency_weights([2008, 2015, 2023], 2023, None).tolist() == [1.0, 1.0, 1.0]


def test_half_life_and_mean_one():
    w = recency_weights([2019, 2021, 2023, 2023], 2023, 2.0)
    assert w.mean() == pytest.approx(1.0)
    assert w[1] / w[2] == pytest.approx(0.5)
    assert w[0] / w[2] == pytest.approx(0.25)


def test_mono_order():
    assert dict(zip(BASE7, MONO)) == {"runs_needed": -1, "balls_left": 1, "wickets_left": 1,
                                      "target": 0, "rrr": -1, "runs_last18": 0, "wkts_last18": 0}
