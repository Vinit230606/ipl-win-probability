"""Chase state reconstruction on hand-computed toy innings (design sections 6 and 15)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from toy import ball, frames, innings, match  # noqa: E402

from iplwp.config import load_config  # noqa: E402
from iplwp.schema import DataQualityError  # noqa: E402
from iplwp.states import build_states  # noqa: E402

CFG = load_config()
RULES = CFG.rules

TOY = [
    # (ball, legal_after, runs_scored, wickets_fallen, label, event)
    (ball(1), 1, 1, 0, "0.1", "1"),
    (ball(0, 1, wide=True), 1, 2, 0, "0.2", "wd"),
    (ball(0, 5, wide=True), 1, 7, 0, "0.2", "wd+4"),
    (ball(4, 1, noball=True), 1, 12, 0, "0.2", "nb+4"),
    (ball(0, 2, bye=True), 2, 14, 0, "0.2", "2b"),
    (ball(0, 1, legbye=True), 3, 15, 0, "0.3", "1lb"),
    (ball(0, 1, wide=True, kind="run out"), 3, 16, 1, "0.4", "wd W run out"),
    (ball(0, kind="retired hurt"), 4, 16, 1, "0.4", "retired hurt"),
    (ball(0, kind="run out", kind2="retired hurt"), 5, 16, 2, "0.5", "W run out retired hurt"),
    (ball(1, kind="run out", kind2="obstructing the field"), 6, 17, 4, "0.6",
     "1 W run out W obstructing the field"),
    (ball(4), 7, 21, 4, "1.1", "4"),
]


def chases_for(mid, target, won, season=2015):
    return pd.DataFrame({"match_id": [mid], "season": [season], "target": [target],
                         "chase_won": [won]})


def toy_deliveries(mid, balls):
    _, d = frames([match(mid)], [innings(mid, 2, "B", "A", balls)])
    return d


@pytest.fixture(scope="module")
def toy_states():
    d = toy_deliveries("t1", [b for b, *_ in TOY])
    return build_states(d, chases_for("t1", 21, 1), RULES)


def test_hand_computed_values(toy_states):
    s = toy_states
    assert s["legal_after"].tolist() == [r[1] for r in TOY]
    assert s["runs_scored"].tolist() == [r[2] for r in TOY]
    assert s["wickets_fallen"].tolist() == [r[3] for r in TOY]
    assert s["label"].tolist() == [r[4] for r in TOY]
    assert s["event"].tolist() == [r[5] for r in TOY]
    assert s["balls_left"].tolist() == [120 - r[1] for r in TOY]
    assert s["runs_needed"].tolist() == [21 - r[2] for r in TOY]
    assert s["wickets_left"].tolist() == [10 - r[3] for r in TOY]
    assert (s["phase"] == "powerplay").all()
    assert (s["y"] == 1).all()


def test_terminal_win(toy_states):
    s = toy_states
    assert s["is_terminal"].tolist() == [False] * 10 + [True]
    assert s["terminal_p"].iloc[-1] == 1.0
    assert s["terminal_p"].iloc[:-1].isna().all()


def test_all_out_and_last_ball_terminal():
    d = toy_deliveries("t2", [ball(kind="bowled") for _ in range(10)])
    s = build_states(d, chases_for("t2", 150, 0), RULES)
    assert s["is_terminal"].tolist() == [False] * 9 + [True]
    assert s["terminal_p"].iloc[-1] == 0.0

    d = toy_deliveries("t3", [ball(1) for _ in range(120)])
    s = build_states(d, chases_for("t3", 200, 0), RULES)
    assert s["is_terminal"].sum() == 1 and s["is_terminal"].iloc[-1]
    assert s["balls_left"].iloc[-1] == 0 and s["terminal_p"].iloc[-1] == 0.0
    # phases by the over in which the ball was bowled: overs 1-6, 7-15, 16-20
    assert s["phase"].value_counts().to_dict() == {"powerplay": 36, "middle": 54, "death": 30}
    assert s.loc[35, "label"] == "5.6" and s.loc[36, "label"] == "6.1"
    assert s.loc[119, "label"] == "19.6"


def test_delivery_after_terminal_raises():
    d = toy_deliveries("t4", [ball(6), ball(1)])
    with pytest.raises(DataQualityError):
        build_states(d, chases_for("t4", 5, 1), RULES)


def loop_reference(d: pd.DataFrame, target: int) -> pd.DataFrame:
    """Slow, obviously-correct version of the cumulative state columns."""
    legal = runs = wkts = 0
    rows = []
    for r in d.sort_values("seq").itertuples():
        is_legal = not (r.is_wide or r.is_noball)
        legal_before = legal
        legal += int(is_legal)
        runs += r.runs_total
        kinds = [k for k in (r.dismissal_kind, r.dismissal_kind_2) if isinstance(k, str)]
        nw = sum(k in RULES.non_wicket_dismissals for k in kinds)
        wkts += max(r.n_dismissals - nw, 0)
        rows.append((legal, runs, wkts, target - runs, 120 - legal, 10 - wkts,
                     f"{legal_before // 6}.{legal_before % 6 + 1}"))
    return pd.DataFrame(rows, columns=["legal_after", "runs_scored", "wickets_fallen",
                                       "runs_needed", "balls_left", "wickets_left", "label"])


def test_loop_reference_on_toy(toy_states):
    d = toy_deliveries("t1", [b for b, *_ in TOY])
    ref = loop_reference(d, 21)
    pd.testing.assert_frame_equal(toy_states[ref.columns].reset_index(drop=True), ref,
                                  check_dtype=False)


def test_loop_reference_on_real_chases():
    from iplwp.io_tables import read_table, table_path
    if not table_path(CFG, CFG.io.processed_dir, "chase_states").exists():
        pytest.skip("run `make data` first")
    states = read_table(CFG, CFG.io.processed_dir, "chase_states")
    chases = read_table(CFG, CFG.io.processed_dir, "chases").set_index("match_id")
    deliv = read_table(CFG, CFG.io.interim_dir, "deliveries")
    rng = np.random.default_rng(CFG.seed)
    for mid in rng.choice(chases.index.to_numpy(), size=30, replace=False):
        d = deliv[(deliv.match_id == mid) & (deliv.innings == 2)]
        ref = loop_reference(d, int(chases.loc[mid, "target"]))
        got = states[states.match_id == mid][ref.columns].reset_index(drop=True)
        pd.testing.assert_frame_equal(got, ref, check_dtype=False, obj=f"match {mid}")
