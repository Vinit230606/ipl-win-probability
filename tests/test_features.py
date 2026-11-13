"""Last-18 window, rrr clip and truncation invariance (requirements 4.1-4.3)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from toy import ball, frames, innings, match  # noqa: E402

from iplwp.config import load_config  # noqa: E402
from iplwp.features import BASE7_E, CORE, compute_features, core_terms, rrr  # noqa: E402
from iplwp.states import build_states  # noqa: E402

CFG = load_config()
RULES = CFG.rules


def states_from(balls, target=300, won=0, mid="f1"):
    _, d = frames([match(mid)], [innings(mid, 2, "B", "A", balls)])
    ch = pd.DataFrame({"match_id": [mid], "season": [2015], "target": [target], "chase_won": [won]})
    return build_states(d, ch, RULES)


def brute_last18(s: pd.DataFrame) -> pd.DataFrame:
    """Direct definition: deliveries up to this one with legal_after > L - 18."""
    out = []
    for i in range(len(s)):
        L = s["legal_after"].iloc[i]
        w = s.iloc[: i + 1]
        w = w[w["legal_after"] > L - 18]
        out.append((int(w["runs_total"].sum()), int(w["wkts_this_ball"].sum())))
    return pd.DataFrame(out, columns=["runs_last18", "wkts_last18"])


@pytest.fixture(scope="module")
def window_innings():
    balls = [ball(1), ball(1), ball(0, 1, wide=True)]
    balls += [ball(kind="caught") if k == 5 else ball(1) for k in range(3, 31)]
    return compute_features(states_from(balls), RULES)


def test_last18_hand_values(window_innings):
    f = window_innings.set_index("legal_after")
    # L = 20: window is legal balls 3..20 (the wide has legal_after 2, so it is out); ball 5 is a
    # wicket for 0 runs -> 17 runs, 1 wicket
    assert f.loc[20, "runs_last18"] == 17 and f.loc[20, "wkts_last18"] == 1
    # L = 19: legal 2, the wide (legal_after 2 > 1) and legal 3..19 -> 1 + 1 + 16 = 18 runs
    assert f.loc[19, "runs_last18"] == 18
    # early in the chase the window is everything so far
    assert f.loc[10, "runs_last18"] == f.loc[10, "runs_scored"]
    # L = 25: legal 8..25 -> 18 runs, no wicket
    assert f.loc[25, "runs_last18"] == 18 and f.loc[25, "wkts_last18"] == 0


def test_last18_matches_brute_force(window_innings):
    pd.testing.assert_frame_equal(
        window_innings[["runs_last18", "wkts_last18"]].reset_index(drop=True),
        brute_last18(window_innings), check_dtype=False)


def test_leading_wide_leaves_window_at_l18():
    balls = [ball(0, 1, wide=True)] + [ball(2) for _ in range(20)]
    f = compute_features(states_from(balls), RULES)
    row = f[f.legal_after == 18].iloc[0]
    assert row["runs_last18"] == 36          # the wide (legal_after 0) is outside the window
    row17 = f[f.legal_after == 17].iloc[0]
    assert row17["runs_last18"] == 35        # L < 18: everything so far
    pd.testing.assert_frame_equal(f[["runs_last18", "wkts_last18"]].reset_index(drop=True),
                                  brute_last18(f), check_dtype=False)


def test_rrr_clip():
    v = rrr(np.array([300, 10, 0, -5, 30, 7]), np.array([1, 60, 30, 10, 0, 0]), 36.0)
    assert v.tolist() == [36.0, 1.0, 0.0, 0.0, 36.0, 36.0]
    t = core_terms([42], [25], [6], 36.0)
    assert t["rrr"][0] == pytest.approx(6 * 42 / 25)
    assert t["rrr_x_wkts"][0] == pytest.approx(6 * 42 / 25 * 0.6)
    assert t["runs_per_wicket"][0] == pytest.approx(7.0)
    assert t["log_balls_left"][0] == pytest.approx(np.log1p(25))


def test_model_rows_have_finite_features(window_innings):
    m = window_innings[window_innings.is_model_row]
    assert np.isfinite(m[sorted(set(BASE7_E) | set(CORE))].to_numpy(dtype=float)).all()


def test_truncation_invariance_real_chases():
    """Deleting all deliveries after i leaves the features of rows 1..i unchanged (50 chases)."""
    from iplwp.io_tables import read_table, table_path
    if not table_path(CFG, CFG.io.processed_dir, "chase_features").exists():
        pytest.skip("run `make data` and `make features` first")
    feats = read_table(CFG, CFG.io.processed_dir, "chase_features")
    chases = read_table(CFG, CFG.io.processed_dir, "chases")
    deliv = read_table(CFG, CFG.io.interim_dir, "deliveries")
    deliv = deliv[deliv.innings == 2]
    cols = sorted(set(BASE7_E) | set(CORE))
    rng = np.random.default_rng(CFG.seed)
    ids = rng.choice(chases["match_id"].to_numpy(), size=50, replace=False)
    for mid in ids:
        d = deliv[deliv.match_id == mid].sort_values("seq")
        cut = int(rng.integers(1, len(d)))          # keep deliveries 0..cut-1
        truncated = compute_features(
            build_states(d.iloc[:cut], chases[chases.match_id == mid], RULES), RULES)
        full = feats[feats.match_id == mid].sort_values("seq").iloc[:cut]
        pd.testing.assert_frame_equal(truncated[cols].reset_index(drop=True),
                                      full[cols].reset_index(drop=True),
                                      check_dtype=False, obj=f"match {mid} cut {cut}")
