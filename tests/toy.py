"""Builders for tiny canonical matches/deliveries used by several test files."""
from __future__ import annotations

import pandas as pd

from iplwp.schema import DELIVERIES_DTYPES, MATCHES_DTYPES, enforce_schema


def ball(runs_batter=0, runs_extras=0, wide=False, noball=False, bye=False, legbye=False,
         penalty=False, kind=None, kind2=None, n_dismissals=None) -> dict:
    nd = n_dismissals if n_dismissals is not None else int(kind is not None) + int(kind2 is not None)
    return {"runs_batter": runs_batter, "runs_extras": runs_extras,
            "runs_total": runs_batter + runs_extras, "is_wide": wide, "is_noball": noball,
            "is_bye": bye, "is_legbye": legbye, "is_penalty": penalty, "dismissal_kind": kind,
            "dismissal_kind_2": kind2, "n_dismissals": nd}


def innings(match_id: str, inn: int, bat: str, bowl: str, balls: list[dict]) -> pd.DataFrame:
    rows = [{"match_id": match_id, "innings": inn, "seq": i, "batting_team": bat,
             "bowling_team": bowl, "batter": "x", "bowler": "y", **b} for i, b in enumerate(balls)]
    return pd.DataFrame(rows)


def simple_innings(match_id, inn, bat, bowl, n_legal, runs_per_ball=1, wickets=0):
    """`n_legal` legal balls of `runs_per_ball` runs; the first `wickets` balls are wickets (0 runs)."""
    balls = [ball(kind="caught") if i < wickets else ball(runs_batter=runs_per_ball)
             for i in range(n_legal)]
    return innings(match_id, inn, bat, bowl, balls)


def match(match_id, team1="A", team2="B", winner="A", outcome_type="normal", method=None,
          target_runs=None, target_overs=None, date="2015-04-10") -> dict:
    return {"match_id": match_id, "date": date, "season": pd.Timestamp(date).year,
            "venue": "V", "city": "C", "team1": team1, "team2": team2, "winner": winner,
            "outcome_type": outcome_type, "method": method, "target_runs_provided": target_runs,
            "target_overs_provided": target_overs}


def frames(match_rows: list[dict], innings_frames: list[pd.DataFrame]):
    m = enforce_schema(pd.DataFrame(match_rows), MATCHES_DTYPES, "matches")
    d = enforce_schema(pd.concat(innings_frames, ignore_index=True), DELIVERIES_DTYPES, "deliveries")
    return m, d
