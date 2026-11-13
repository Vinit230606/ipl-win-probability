"""Resampling is by whole match; same seed gives the same interval (design 11.2)."""
from __future__ import annotations

import numpy as np
import pytest

from iplwp.bootstrap import bootstrap_bss, match_sse, verdict


@pytest.fixture
def toy():
    rng = np.random.default_rng(1)
    sizes = rng.integers(80, 130, 40)
    mid = np.repeat([f"m{i}" for i in range(40)], sizes)
    y = np.repeat(rng.integers(0, 2, 40), sizes)
    p_ref = np.full(len(y), 0.5)
    p_mod = np.clip(0.5 + (y - 0.5) * 0.4 + rng.normal(0, 0.1, len(y)), 0, 1)
    return mid, y, p_mod, p_ref, sizes


def test_draws_are_sums_of_whole_matches(toy):
    mid, y, p_mod, p_ref, sizes = toy
    g = match_sse(mid, y, p_mod, p_ref)
    assert g["n"].sum() == len(y)
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(g), size=(200, len(g)))
    n = g["n"].to_numpy()[idx].sum(1)
    possible = set(g["n"])
    # every per-draw row count decomposes into whole-match sizes
    assert all(set(g["n"].to_numpy()[i]) <= possible for i in idx)
    assert (n >= g["n"].min() * len(g)).all() and (n <= g["n"].max() * len(g)).all()


def test_same_seed_same_interval(toy):
    mid, y, p_mod, p_ref, _ = toy
    a = bootstrap_bss(mid, y, p_mod, p_ref, 500, 42)
    b = bootstrap_bss(mid, y, p_mod, p_ref, 500, 42)
    c = bootstrap_bss(mid, y, p_mod, p_ref, 500, 7)
    assert a == b
    assert a["ci"] != c["ci"]
    assert a["ci"][0] <= a["bss"] <= a["ci"][1]
    assert a["bss"] > 0


def test_verdicts():
    assert verdict("GBM", 0.1, [0.05, 0.15]).startswith("GBM beats the baseline")
    assert verdict("GBM", 0.01, [-0.02, 0.04]).startswith("We cannot say GBM beats")
    assert verdict("GBM", -0.1, [-0.2, -0.05]).startswith("GBM is worse than")
