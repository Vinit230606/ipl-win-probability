"""Leakage-safe feature matrix (design section 7).

Every feature on row i is a function of the state after delivery i and of deliveries 1..i of the
same innings (the last-18 window looks backwards only) plus the target. Terminal rows are kept but
flagged `is_model_row = False`; their engineered features may be undefined (NaN) and are never used.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import RulesConfig

BASE7 = ["runs_needed", "balls_left", "wickets_left", "target", "rrr", "runs_last18", "wkts_last18"]
ENGINEERED = ["log_runs_needed", "log_balls_left", "rrr_x_wkts", "runs_per_wicket"]
BASE7_E = BASE7 + ENGINEERED
CORE = ["runs_needed", "balls_left", "wickets_left", "rrr"] + ENGINEERED
FEATURE_SETS = {"BASE7": BASE7, "BASE7_E": BASE7_E, "CORE": CORE}


def rrr(runs_needed: pd.Series | np.ndarray, balls_left: pd.Series | np.ndarray,
        clip: float) -> np.ndarray:
    """Required run rate 6 * runs_needed / balls_left, clipped to [0, clip].

    balls_left = 0 (terminal only) gives `clip` if runs are still needed, else 0.
    """
    r = np.asarray(runs_needed, dtype=float)
    b = np.asarray(balls_left, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.where(b > 0, 6.0 * r / np.where(b > 0, b, 1.0), np.where(r > 0, clip, 0.0))
    return np.clip(v, 0.0, clip)


def core_terms(runs_needed, balls_left, wickets_left, clip: float) -> dict[str, np.ndarray]:
    """CORE features from the three calculator inputs (the JavaScript calculator mirrors this)."""
    r = np.asarray(runs_needed, dtype=float)
    b = np.asarray(balls_left, dtype=float)
    w = np.asarray(wickets_left, dtype=float)
    q = rrr(r, b, clip)
    with np.errstate(divide="ignore", invalid="ignore"):
        rpw = np.where(w > 0, r / np.where(w > 0, w, 1.0), np.nan)
    return {
        "runs_needed": r, "balls_left": b, "wickets_left": w, "rrr": q,
        "log_runs_needed": np.log1p(np.clip(r, 0, None)),
        "log_balls_left": np.log1p(np.clip(b, 0, None)),
        "rrr_x_wkts": q * w / 10.0,
        "runs_per_wicket": rpw,
    }


def last_window(states: pd.DataFrame, window: int) -> pd.DataFrame:
    """Runs and wickets in the last `window` legal balls (plus extras bowled among them).

    For the row with legal_after = L the window is every delivery of the innings up to this one
    with legal_after > L - window. R[k] is the cumulative total after the last delivery whose
    legal_after == k (R[k] = 0 for k < 0 or when no delivery has legal_after == k, which only
    happens for k = 0); then runs_last = runs_scored - R[L - window]. Same for wickets.
    """
    key = states[["match_id", "legal_after", "runs_scored", "wickets_fallen"]]
    r = (key.groupby(["match_id", "legal_after"], sort=False)
         .agg(R=("runs_scored", "last"), W=("wickets_fallen", "last")).reset_index())
    look = pd.DataFrame({"match_id": states["match_id"].values,
                         "legal_after": states["legal_after"].values - window})
    got = look.merge(r, on=["match_id", "legal_after"], how="left")
    R = got["R"].fillna(0).to_numpy()
    W = got["W"].fillna(0).to_numpy()
    return pd.DataFrame({"runs_last18": states["runs_scored"].to_numpy() - R,
                         "wkts_last18": states["wickets_fallen"].to_numpy() - W},
                        index=states.index).astype(int)


def start_state_rows(per_match: pd.DataFrame, rules: RulesConfig) -> pd.DataFrame:
    """Feature rows for the state BEFORE ball 1 of each chase (design 12.2 `start`).

    `per_match` needs match_id, season, target, y. runs_needed = target, balls_left = 120,
    wickets_left = 10, last-18 counts = 0.
    """
    out = per_match[["match_id", "season", "target", "y"]].copy().reset_index(drop=True)
    out["runs_needed"] = out["target"]
    out["balls_left"] = rules.balls_per_innings
    out["wickets_left"] = rules.wickets
    terms = core_terms(out["runs_needed"], out["balls_left"], out["wickets_left"], rules.rrr_clip)
    for c in ["rrr"] + ENGINEERED:
        out[c] = terms[c]
    out["runs_last18"] = 0
    out["wkts_last18"] = 0
    return out


def compute_features(states: pd.DataFrame, rules: RulesConfig) -> pd.DataFrame:
    """Return `states` plus BASE7 + engineered features and `is_model_row`.

    `states` must contain whole innings prefixes sorted by (match_id, seq), as built by
    `states.build_states`.
    """
    out = states.copy()
    terms = core_terms(out["runs_needed"], out["balls_left"], out["wickets_left"], rules.rrr_clip)
    out["rrr"] = terms["rrr"]
    out[["runs_last18", "wkts_last18"]] = last_window(out, rules.momentum_window_legal_balls)
    for c in ENGINEERED:
        out[c] = terms[c]
    out["is_model_row"] = ~out["is_terminal"]
    out.loc[~out["is_model_row"], ENGINEERED] = np.nan
    return out
