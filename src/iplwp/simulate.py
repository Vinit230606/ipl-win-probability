"""Ball-by-ball simulation model for scoreboard states the data never reached (edge cases).

Idea: instead of learning P(win | state) directly, learn P(outcome of one delivery | context) and
solve the chase exactly with dynamic programming. An outcome is (legal or extra, runs, wicket).
The context of a delivery is the state BEFORE it: phase (from balls left), wickets-left group and
required-rate band. Probabilities are shrunk towards coarser contexts (phase x wickets, then phase,
then all deliveries) so rare contexts borrow strength.

V[b, w, r] = probability of winning when r runs are needed from b legal balls with w wickets left:
  r <= 0 -> 1;  otherwise w = 0 or b = 0 -> 0;  otherwise
  V = sum over legal outcomes p * V[b-1, w-wk, r-k] + sum over extras p * V[b, w-wk, r-k].
Extras always add at least one run, so every transition reaches a state computed earlier.
Assumptions (stated on the website): deliveries are independent given the context; free hits and
batter identity are ignored.

Leakage: fit only on the rows passed in (train, or train + validation for the final model).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import Config

N_PHASES = 3
LEGAL = "L"
EXTRA = "X"


@dataclass(frozen=True)
class SimSpec:
    rrr_bands: tuple[float, ...]
    wicket_groups: tuple[tuple[int, int], ...]
    legal_max_runs: int
    extra_max_runs: int
    max_runs: int
    balls: int
    wickets: int

    @property
    def classes(self) -> list[tuple[str, int, int]]:
        """(kind, runs, wicket) in a fixed order shared with the JavaScript solver."""
        out = [(LEGAL, k, wk) for wk in (0, 1) for k in range(self.legal_max_runs + 1)]
        out += [(EXTRA, k, wk) for wk in (0, 1) for k in range(1, self.extra_max_runs + 1)]
        return out

    @property
    def n_contexts(self) -> int:
        return N_PHASES * len(self.wicket_groups) * (len(self.rrr_bands) + 1)


def spec_from_config(cfg: Config) -> SimSpec:
    s = cfg.simulation
    return SimSpec(tuple(float(x) for x in s.rrr_bands), s.wicket_groups,
                   s.legal_max_runs, s.extra_max_runs, s.max_runs, cfg.rules.balls_per_innings,
                   cfg.rules.wickets)


def phase_of(balls_left, balls: int) -> np.ndarray:
    """0 powerplay (overs 1-6), 1 middle (7-15), 2 death (16-20), from balls left before the ball."""
    over_idx = (balls - np.asarray(balls_left, int)) // 6
    return np.where(over_idx <= 5, 0, np.where(over_idx <= 14, 1, 2))


def wkt_group_of(w, spec: SimSpec) -> np.ndarray:
    w = np.asarray(w, int)
    out = np.full(w.shape, len(spec.wicket_groups) - 1)
    for i, (lo, hi) in enumerate(spec.wicket_groups):
        out[(w >= lo) & (w <= hi)] = i
    return out


def context_index(r, b, w, spec: SimSpec) -> np.ndarray:
    """Context of a delivery bowled when r runs are needed from b balls with w wickets left."""
    r, b = np.asarray(r, float), np.asarray(b, float)
    band = np.digitize(6.0 * r / np.maximum(b, 1.0), np.asarray(spec.rrr_bands), right=False)
    nb = len(spec.rrr_bands) + 1
    return (phase_of(b, spec.balls) * len(spec.wicket_groups) + wkt_group_of(w, spec)) * nb + band


def delivery_table(states: pd.DataFrame, spec: SimSpec) -> pd.DataFrame:
    """One row per delivery: context (from the state before it), outcome class, season.

    `states` are chase state rows (all rows, including the final one: its delivery started from
    an open state).
    """
    legal = states["legal"].to_numpy(bool)
    wk = np.minimum(states["wkts_this_ball"].to_numpy(int), 1)
    runs = states["runs_total"].to_numpy(int)
    r0 = states["runs_needed"].to_numpy(int) + runs
    b0 = states["balls_left"].to_numpy(int) + legal.astype(int)
    w0 = states["wickets_left"].to_numpy(int) + states["wkts_this_ball"].to_numpy(int)
    k = np.where(legal, np.minimum(runs, spec.legal_max_runs),
                 np.clip(runs, 1, spec.extra_max_runs))
    lookup = {c: i for i, c in enumerate(spec.classes)}
    cls = np.array([lookup[(LEGAL if l else EXTRA, int(kk), int(ww))] for l, kk, ww in zip(legal, k, wk)])
    return pd.DataFrame({"ctx": context_index(r0, b0, w0, spec), "cls": cls,
                         "season": states["season"].to_numpy(int)})


def fit_outcomes(deliv: pd.DataFrame, spec: SimSpec, shrinkage: float,
                 weights: np.ndarray | None = None) -> np.ndarray:
    """Outcome probabilities per context, shape (n_contexts, n_classes), rows sum to 1.

    Hierarchical shrinkage: all deliveries -> phase -> phase x wicket group -> full context,
    each level pulled towards its parent with `shrinkage` pseudo-deliveries.
    """
    n_cls = len(spec.classes)
    w = np.ones(len(deliv)) if weights is None else np.asarray(weights, float)
    counts = np.zeros((spec.n_contexts, n_cls))
    np.add.at(counts, (deliv["ctx"].to_numpy(), deliv["cls"].to_numpy()), w)
    nb = len(spec.rrr_bands) + 1
    ng = len(spec.wicket_groups)
    c4 = counts.reshape(N_PHASES, ng, nb, n_cls)
    glob = counts.sum(0)
    p_glob = glob / glob.sum()

    def shrink(c, parent):
        n = c.sum(-1, keepdims=True)
        return (c + shrinkage * parent) / (n + shrinkage)

    p_phase = shrink(c4.sum((1, 2)), p_glob)                       # (3, cls)
    p_pw = shrink(c4.sum(2), p_phase[:, None, :])                  # (3, ng, cls)
    p_ctx = shrink(c4, p_pw[:, :, None, :])                        # (3, ng, nb, cls)
    return p_ctx.reshape(spec.n_contexts, n_cls)


def solve(P: np.ndarray, spec: SimSpec) -> np.ndarray:
    """Win probability table V[b, w, r] for b in 0..balls, w in 0..wickets, r in 0..max_runs.

    The summation order (legal classes, then extras, in `spec.classes` order) matches
    docs/assets/js/simulation.js exactly, so both give bit-for-bit comparable results.
    """
    B, W, R = spec.balls, spec.wickets, spec.max_runs
    V = np.zeros((B + 1, W + 1, R + 1))
    V[:, :, 0] = 1.0
    classes = spec.classes
    legal = [(j, k, wk) for j, (kind, k, wk) in enumerate(classes) if kind == LEGAL]
    extra = [(j, k, wk) for j, (kind, k, wk) in enumerate(classes) if kind == EXTRA]
    r = np.arange(1, R + 1)
    for b in range(1, B + 1):
        for w in range(1, W + 1):
            Pr = P[context_index(r, np.full(R, b), np.full(R, w), spec)]   # (R, cls)
            acc = np.zeros(R)
            for j, k, wk in legal:
                nr = r - k
                nxt = np.where(nr <= 0, 1.0, V[b - 1, w - wk, np.maximum(nr, 0)])
                acc = acc + Pr[:, j] * nxt
            row = V[b, w]
            for i in range(R):
                s = acc[i]
                ri = i + 1
                for j, k, wk in extra:
                    nr = ri - k
                    s = s + Pr[i, j] * (1.0 if nr <= 0 else row[nr] if wk == 0 else V[b, w - 1, nr])
                row[ri] = s
    return V


EPS = 1e-6


def _logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def fit_calibration(p_raw, y) -> tuple[float, float]:
    """Platt scaling: p = sigmoid(a * logit(p_raw) + c), fit by maximum likelihood on the
    fitting rows. Corrects the simulation's over-confidence (it treats balls as independent)."""
    from sklearn.linear_model import LogisticRegression

    m = LogisticRegression(C=1e6, max_iter=1000).fit(_logit(p_raw)[:, None], np.asarray(y, int))
    return float(m.coef_[0, 0]), float(m.intercept_[0])


def calibrate(p_raw, a: float, c: float) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-(a * _logit(p_raw) + c)))


def lookup(V: np.ndarray, r, b, w) -> np.ndarray:
    """V at states (runs needed r >= 1, balls left b, wickets left w); r beyond the table is capped."""
    r = np.clip(np.asarray(r, int), 0, V.shape[2] - 1)
    return V[np.asarray(b, int), np.asarray(w, int), r]
