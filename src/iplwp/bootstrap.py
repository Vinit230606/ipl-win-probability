"""Match-level bootstrap for Brier skill score intervals (design section 11.2).

Whole matches are resampled with replacement, because the ~115 rows of one chase are strongly
correlated. The model and the reference are scored on the SAME resampled matches in every draw.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def match_sse(match_id, y, p_model, p_ref) -> pd.DataFrame:
    """Per match: row count and sums of squared errors for the model and the reference."""
    y = np.asarray(y, float)
    df = pd.DataFrame({"match_id": np.asarray(match_id), "y": y,
                       "se_model": (np.asarray(p_model, float) - y) ** 2,
                       "se_base": (np.asarray(p_ref, float) - y) ** 2})
    return df.groupby("match_id", sort=True).agg(n=("y", "size"), sse_m=("se_model", "sum"),
                                                 sse_b=("se_base", "sum"))


def bootstrap_bss(match_id, y, p_model, p_ref, n_boot: int, seed: int,
                  ci: float = 0.95) -> dict[str, float | list[float]]:
    """BSS of `p_model` against `p_ref` with a percentile interval from `n_boot` match resamples.

    Returns {"bss": point estimate on all rows, "ci": [lo, hi], "n_matches": ...}.
    """
    g = match_sse(match_id, y, p_model, p_ref)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n_boot, len(g)))
    n = g["n"].to_numpy()[idx].sum(1)
    bm = g["sse_m"].to_numpy()[idx].sum(1) / n
    bb = g["sse_b"].to_numpy()[idx].sum(1) / n
    draws = 1.0 - bm / bb
    a = (1.0 - ci) / 2.0
    lo, hi = np.percentile(draws, [100 * a, 100 * (1 - a)])
    point = 1.0 - g["sse_m"].sum() / g["sse_b"].sum()
    return {"bss": float(point), "ci": [float(lo), float(hi)], "n_matches": int(len(g))}


def verdict(name: str, bss: float, ci: list[float], reference: str = "the baseline") -> str:
    """Verdict sentence (design 11.2): better only if the whole interval is above 0."""
    lo, hi = ci
    if lo > 0:
        return f"{name} beats {reference} (BSS {bss:.3f}, 95% interval [{lo:.3f}, {hi:.3f}])."
    if hi < 0:
        return (f"{name} is worse than {reference} (BSS {bss:.3f}, 95% interval "
                f"[{lo:.3f}, {hi:.3f}]).")
    return (f"We cannot say {name} beats {reference}: the 95% interval [{lo:.3f}, {hi:.3f}] "
            f"includes 0 (BSS {bss:.3f}).")
