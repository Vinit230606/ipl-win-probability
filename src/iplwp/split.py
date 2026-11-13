"""Season-based train / validation / test split (design section 8).

Whole seasons go to one split, so no match (and no ball of a match) is shared between splits and
the test seasons are strictly later than everything used for fitting or tuning.
"""
from __future__ import annotations

import pandas as pd

from .config import SplitConfig

SPLITS = ["train", "val", "test"]


def season_split(seasons, cfg: SplitConfig) -> dict[int, str]:
    """Map each season to "train", "val" or "test": last n_test seasons test, the n_val before
    them validation, everything earlier train. Raises ValueError if that leaves no train season."""
    s = sorted(set(int(x) for x in seasons))
    need = cfg.n_test_seasons + cfg.n_val_seasons + 1
    if len(s) < need:
        raise ValueError(f"split impossible: {len(s)} seasons after cleaning, need at least {need}")
    n_tv = cfg.n_test_seasons + cfg.n_val_seasons
    out = {x: "train" for x in s[:-n_tv]}
    out.update({x: "val" for x in s[-n_tv:-cfg.n_test_seasons]})
    out.update({x: "test" for x in s[-cfg.n_test_seasons:]})
    return out


def assign_split(rows: pd.DataFrame, mapping: dict[int, str]) -> pd.Series:
    return rows["season"].astype(int).map(mapping).astype("string")


def check_disjoint(rows: pd.DataFrame) -> None:
    """Assert every match_id appears in exactly one split."""
    n = rows.groupby("match_id")["split"].nunique()
    if (n > 1).any():
        raise AssertionError(f"match {n.index[n > 1][0]} appears in more than one split")


def split_table(features: pd.DataFrame) -> pd.DataFrame:
    """Per split: seasons, matches, all rows, model rows, terminal rows, chase win rate (matches)."""
    rows = []
    for sp in SPLITS:
        f = features[features["split"] == sp]
        seasons = sorted(f["season"].unique())
        per_match = f.groupby("match_id")["y"].first()
        rows.append({
            "split": sp,
            "seasons": f"{seasons[0]}–{seasons[-1]}" if len(seasons) > 1 else str(seasons[0]),
            "matches": f["match_id"].nunique(),
            "all_rows": len(f),
            "model_rows": int(f["is_model_row"].sum()),
            "terminal_rows": int((~f["is_model_row"]).sum()),
            "chase_win_rate": f"{per_match.mean():.3f}",
        })
    return pd.DataFrame(rows)
