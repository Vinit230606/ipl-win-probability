"""Ball-by-ball chase state reconstruction (design section 6).

Input: canonical innings-2 deliveries of kept chases plus each chase's target and result.
Output: one row per delivery with the scoreboard AFTER that delivery. Every quantity on row i is a
cumulative sum over deliveries 1..i of the same innings, so nothing uses later deliveries; the label
`y` (did the chase win) is the only per-match value and is never a feature.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import RulesConfig
from .schema import DataQualityError

STATE_COLUMNS = [
    "match_id", "season", "seq", "batting_team", "bowling_team", "batter", "bowler", "target",
    "runs_total", "legal", "wkts_this_ball", "legal_before", "legal_after", "runs_scored",
    "wickets_fallen", "runs_needed", "balls_left", "wickets_left", "over_idx", "phase", "label",
    "event", "is_wicket_ball", "is_terminal", "terminal_p", "y",
]


def wickets_on_delivery(d: pd.DataFrame, non_wicket: tuple[str, ...]) -> pd.Series:
    """Number of wickets that fall on each delivery.

    Each dismissal counts unless its kind is a non-wicket dismissal (retired hurt / retired not
    out). With two dismissals on one ball, both count unless one of the kinds is non-wicket.
    """
    nw = list(non_wicket)
    k1 = d["dismissal_kind"].isin(nw).fillna(False).astype(int)
    k2 = d["dismissal_kind_2"].isin(nw).fillna(False).astype(int)
    return (d["n_dismissals"] - k1 - k2).clip(lower=0).astype(int)


def _event_text(wide, noball, bye, legbye, penalty, rb, rx, rt, k1, k2, non_wicket) -> str:
    if wide:
        base = "wd" if rt - 1 == 0 else f"wd+{rt - 1}"
    elif noball:
        base = "nb" if rt - 1 == 0 else f"nb+{rt - 1}"
    elif bye:
        base = f"{rx}b"
    elif legbye:
        base = f"{rx}lb"
    elif penalty:
        base = f"{rx}pen"
    else:
        base = str(rb) if rb > 0 else "·"
    parts = [base]
    for k in (k1, k2):
        if k is None or k is pd.NA or (isinstance(k, float) and np.isnan(k)):
            continue
        parts.append(k if k in non_wicket else f"W {k}")
    if len(parts) > 1 and parts[0] == "·":
        parts = parts[1:]
    return " ".join(parts)


def event_texts(d: pd.DataFrame, non_wicket: tuple[str, ...]) -> list[str]:
    """Short event text per delivery: "4", "·", "W caught", "wd", "nb+4", "1lb", "wd W stumped"."""
    k1 = d["dismissal_kind"].astype(object).where(d["dismissal_kind"].notna(), None)
    k2 = d["dismissal_kind_2"].astype(object).where(d["dismissal_kind_2"].notna(), None)
    k1 = k1.where(d["n_dismissals"] > 0, None)
    return [
        _event_text(*args, non_wicket)
        for args in zip(d["is_wide"], d["is_noball"], d["is_bye"], d["is_legbye"],
                        d["is_penalty"], d["runs_batter"], d["runs_extras"], d["runs_total"],
                        k1, k2)
    ]


def build_states(deliveries: pd.DataFrame, chases: pd.DataFrame, rules: RulesConfig) -> pd.DataFrame:
    """Reconstruct the chase state after every innings-2 delivery.

    `deliveries`: canonical rows of innings 2 only, for the matches in `chases`.
    `chases`: one row per match with `match_id`, `season`, `target`, `chase_won`.
    Returns one row per delivery with STATE_COLUMNS, sorted by (match_id, seq).
    Raises DataQualityError if a delivery follows a terminal state or legal balls exceed the limit.
    """
    if (deliveries["innings"] != 2).any():
        raise ValueError("build_states expects innings-2 deliveries only")
    d = deliveries.sort_values(["match_id", "seq"], kind="stable").reset_index(drop=True)
    info = chases.set_index("match_id")
    d["season"] = d["match_id"].map(info["season"]).astype(int)
    d["target"] = d["match_id"].map(info["target"]).astype(int)
    d["y"] = d["match_id"].map(info["chase_won"]).astype(int)

    d["legal"] = ~(d["is_wide"] | d["is_noball"])
    d["wkts_this_ball"] = wickets_on_delivery(d, rules.non_wicket_dismissals)
    g = d.groupby("match_id", sort=False)
    d["legal_after"] = g["legal"].cumsum().astype(int)
    d["legal_before"] = d["legal_after"] - d["legal"].astype(int)
    d["runs_scored"] = g["runs_total"].cumsum().astype(int)
    d["wickets_fallen"] = g["wkts_this_ball"].cumsum().astype(int)

    d["runs_needed"] = d["target"] - d["runs_scored"]
    d["balls_left"] = rules.balls_per_innings - d["legal_after"]
    d["wickets_left"] = rules.wickets - d["wickets_fallen"]
    d["over_idx"] = d["legal_before"] // 6
    d["phase"] = np.select([d["over_idx"] <= 5, d["over_idx"] <= 14],
                           ["powerplay", "middle"], "death")
    d["label"] = (d["legal_before"] // 6).astype(str) + "." + (d["legal_before"] % 6 + 1).astype(str)
    d["event"] = event_texts(d, rules.non_wicket_dismissals)
    d["is_wicket_ball"] = d["wkts_this_ball"] > 0

    d["is_terminal"] = (d["runs_needed"] <= 0) | (d["wickets_left"] <= 0) | (d["balls_left"] <= 0)
    d["terminal_p"] = np.where(d["is_terminal"], np.where(d["runs_needed"] <= 0, 1.0, 0.0), np.nan)

    if (d["balls_left"] < 0).any():
        bad = d.loc[d["balls_left"] < 0, "match_id"].iloc[0]
        raise DataQualityError(f"match {bad}: more than {rules.balls_per_innings} legal balls in chase")
    if (d["wickets_left"] < 0).any():
        bad = d.loc[d["wickets_left"] < 0, "match_id"].iloc[0]
        raise DataQualityError(f"match {bad}: more than {rules.wickets} wickets in chase")
    after_terminal = d.groupby("match_id", sort=False)["is_terminal"].transform(
        lambda s: s.shift(1, fill_value=False).cummax())
    if after_terminal.any():
        bad = d.loc[after_terminal, "match_id"].iloc[0]
        raise DataQualityError(f"match {bad}: deliveries recorded after the chase was decided")
    return d[STATE_COLUMNS]


def running_total_check(states: pd.DataFrame, chases: pd.DataFrame) -> pd.DataFrame:
    """Compare the last row of every chase with the totals computed in cleaning.

    Returns one row per chase with `ok`; the caller raises if any is False (requirement 2.4).
    """
    last = states.groupby("match_id", sort=False).tail(1).set_index("match_id")
    c = chases.set_index("match_id")
    out = pd.DataFrame({
        "runs_ok": last["runs_scored"] == c.loc[last.index, "final_runs"],
        "wickets_ok": last["wickets_fallen"] == c.loc[last.index, "final_wickets"],
        "legal_ok": last["legal_after"] == c.loc[last.index, "final_legal_balls"],
    })
    out["ok"] = out.all(axis=1)
    missing = set(c.index) - set(last.index)
    if missing:
        raise DataQualityError(f"chases without state rows: {sorted(missing)[:5]}")
    return out.reset_index()
