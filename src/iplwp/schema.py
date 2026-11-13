"""Canonical column names, dtypes and team-name normalisation (design sections 4.1 and 4.4).

Column names are defined once here. Team names are normalised for display and for comparing the
winner with the chasing team only; they are never model features.
"""
from __future__ import annotations

import pandas as pd


class DataQualityError(Exception):
    """An invariant broke in data that the pipeline intended to keep."""


# column -> pandas dtype
MATCHES_DTYPES: dict[str, str] = {
    "match_id": "string",
    "date": "datetime64[ns]",
    "season": "int64",
    "venue": "string",
    "city": "string",
    "team1": "string",
    "team2": "string",
    "winner": "string",
    "outcome_type": "string",          # normal | tie | no_result
    "method": "string",
    "target_runs_provided": "Int64",
    "target_overs_provided": "Float64",
}

DELIVERIES_DTYPES: dict[str, str] = {
    "match_id": "string",
    "innings": "int64",
    "seq": "int64",
    "batting_team": "string",
    "bowling_team": "string",
    "batter": "string",
    "bowler": "string",
    "runs_batter": "int64",
    "runs_extras": "int64",
    "runs_total": "int64",
    "is_wide": "bool",
    "is_noball": "bool",
    "is_bye": "bool",
    "is_legbye": "bool",
    "is_penalty": "bool",
    "dismissal_kind": "string",
    # Refinement of design 4.1: the kind of the second dismissal on the same delivery (Cricsheet
    # "other_wicket"), needed so states.py can apply "count both unless a kind is non-wicket".
    "dismissal_kind_2": "string",
    "n_dismissals": "int64",
}

CANONICAL_MATCHES = list(MATCHES_DTYPES)
CANONICAL_DELIVERIES = list(DELIVERIES_DTYPES)

OUTCOME_TYPES = ("normal", "tie", "no_result")

TEAM_DISPLAY: dict[str, str] = {
    "Delhi Daredevils": "Delhi Capitals",
    "Kings XI Punjab": "Punjab Kings",
    "Royal Challengers Bangalore": "Royal Challengers Bengaluru",
    "Rising Pune Supergiants": "Rising Pune Supergiant",
}


def normalise_team(name: str | None) -> str | None:
    """Map a historical team name to its current name; unknown names are returned unchanged."""
    if name is None or (isinstance(name, float) and pd.isna(name)) or name is pd.NA:
        return None
    return TEAM_DISPLAY.get(name, name)


def normalise_team_series(s: pd.Series) -> pd.Series:
    return s.astype("string").replace(TEAM_DISPLAY)


def enforce_schema(df: pd.DataFrame, dtypes: dict[str, str], table: str) -> pd.DataFrame:
    """Return `df` with exactly the canonical columns, in order, cast to canonical dtypes.

    Raises DataQualityError naming any missing column.
    """
    missing = [c for c in dtypes if c not in df.columns]
    if missing:
        raise DataQualityError(f"{table}: missing canonical columns {missing}")
    out = df[list(dtypes)].copy()
    for c, t in dtypes.items():
        if t == "string":
            out[c] = out[c].astype("string")
        elif t == "datetime64[ns]":
            out[c] = pd.to_datetime(out[c]).astype("datetime64[ns]")
        else:
            out[c] = out[c].astype(t)
    return out.reset_index(drop=True)
