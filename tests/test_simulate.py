"""Ball-by-ball solver, outcome shrinkage, blend weight and monotone envelope (edge-case fix)."""
from __future__ import annotations

import numpy as np
import pytest

from iplwp.edge_cases import blend_weight, monotone_envelope
from iplwp.simulate import SimSpec, calibrate, fit_outcomes, solve

SPEC = SimSpec(rrr_bands=(6.0,), wicket_groups=((2, 2), (1, 1)), legal_max_runs=6, extra_max_runs=7,
               max_runs=12, balls=6, wickets=2)


def only(kind, runs, wk):
    """Outcome table where every delivery in every context is the same outcome."""
    P = np.zeros((SPEC.n_contexts, len(SPEC.classes)))
    P[:, SPEC.classes.index((kind, runs, wk))] = 1.0
    return P


def test_one_run_every_ball():
    V = solve(only("L", 1, 0), SPEC)
    for b in range(1, 7):
        for r in range(1, 13):
            assert V[b, 2, r] == (1.0 if r <= b else 0.0)


def test_wicket_every_ball_loses_unless_target_reached():
    V = solve(only("L", 0, 1), SPEC)
    assert (V[1:, 1:, 1:] == 0).all() and (V[:, :, 0] == 1).all()


def test_wide_keeps_the_ball():
    # half wides (1 run, ball not used), half dots: from 3 needed off 1 ball the chase can only
    # be won by three wides in a row before the legal ball: 0.5 ** 3
    P = np.zeros((SPEC.n_contexts, len(SPEC.classes)))
    P[:, SPEC.classes.index(("X", 1, 0))] = 0.5
    P[:, SPEC.classes.index(("L", 0, 0))] = 0.5
    V = solve(P, SPEC)
    assert V[1, 2, 3] == pytest.approx(0.5 ** 3)
    assert V[1, 2, 1] == pytest.approx(0.5)


def test_fit_outcomes_rows_sum_to_one_and_shrink():
    import pandas as pd

    deliv = pd.DataFrame({"ctx": [0, 0, 0, 5], "cls": [0, 1, 1, 3], "season": [2020] * 4})
    P = fit_outcomes(deliv, SPEC, shrinkage=10.0)
    assert np.allclose(P.sum(1), 1.0)
    empty = [c for c in range(SPEC.n_contexts) if c not in (0, 5)]
    assert (P[empty] > 0).any(axis=1).all()           # unseen contexts borrow from parents
    assert P[0, 1] > P[empty[0], 1] * 0.5


def test_calibrate_identity():
    p = np.array([0.1, 0.5, 0.9])
    assert np.allclose(calibrate(p, 1.0, 0.0), p)


def test_blend_weight():
    assert blend_weight([0, 1, 9], 1.0).tolist() == [0.0, 0.5, 0.9]


def is_monotone(G):
    R, B, W = G.shape[0] - 1, G.shape[1] - 1, G.shape[2] - 1
    i = (slice(1, R + 1), slice(1, B + 1), slice(1, W + 1))
    g = G[i]
    return (np.diff(g, axis=0) <= 1e-12).all() and (np.diff(g, axis=1) >= -1e-12).all() \
        and (np.diff(g, axis=2) >= -1e-12).all()


def test_envelope_makes_any_table_monotone():
    rng = np.random.default_rng(0)
    H = rng.uniform(0, 1, (9, 7, 4))
    H[0] = 1.0
    G = monotone_envelope(H)
    assert is_monotone(G)
    assert G.min() >= 0 and G.max() <= 1


def test_envelope_leaves_monotone_tables_alone():
    V = solve(only("L", 1, 0), SPEC)                   # V[b, w, r]
    H = np.transpose(V, (2, 0, 1)).copy()              # -> [r, b, w]
    H = 0.2 + 0.6 * H
    H[0] = 1.0
    G = monotone_envelope(H)
    assert np.allclose(G[1:, 1:, 1:], H[1:, 1:, 1:])
