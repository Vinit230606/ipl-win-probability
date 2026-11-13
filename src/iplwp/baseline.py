"""Historical lookup-table baseline with four fallback levels (design section 9).

The table stores, per bucket of (runs needed, balls left, wickets left), the number of training
rows and how many of them belonged to chases that were won. Prediction uses the first level whose
bucket has at least `min_count` training rows: A (runs x balls x wickets) -> B (runs x balls) ->
C (coarse runs x coarse balls) -> D (overall rate). It is fit on training rows only.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import BaselineConfig

LEVELS = ["A", "B", "C", "D"]


def runs_band(r, cfg: BaselineConfig) -> np.ndarray:
    """1-9 -> 0, 10-19 -> 1, ..., all runs_needed >= runs_cap share one band."""
    return np.minimum(np.asarray(r, int), cfg.runs_cap) // cfg.runs_band


def balls_band(b, cfg: BaselineConfig) -> np.ndarray:
    """1-12 -> 0, 13-24 -> 1, ..., 109-120 -> 9."""
    return (np.asarray(b, int) - 1) // cfg.balls_band


def wkt_group(w, cfg: BaselineConfig) -> np.ndarray:
    """Index of the wicket group (8-10, 5-7, 3-4, 1-2 by default) containing wickets_left."""
    w = np.asarray(w, int)
    out = np.full(w.shape, -1)
    for i, (lo, hi) in enumerate(cfg.wicket_groups):
        out[(w >= lo) & (w <= hi)] = i
    if (out < 0).any():
        raise ValueError(f"wickets_left outside every wicket group: {sorted(set(w[out < 0]))}")
    return out


def bucket_keys(rows: pd.DataFrame, cfg: BaselineConfig) -> dict[str, np.ndarray]:
    """String keys per level for each row, e.g. "A|4|2|1", "B|4|2", "C|1|0"."""
    r, b, w = rows["runs_needed"].to_numpy(), rows["balls_left"].to_numpy(), rows["wickets_left"].to_numpy()
    rb, bb, wg = runs_band(r, cfg).astype(str), balls_band(b, cfg).astype(str), wkt_group(w, cfg).astype(str)
    rc = (np.minimum(np.asarray(r, int), cfg.runs_cap) // cfg.level_c.runs_band).astype(str)
    bc = ((np.asarray(b, int) - 1) // cfg.level_c.balls_band).astype(str)
    sep = np.array("|")
    return {
        "A": np.char.add(np.char.add(np.char.add(np.char.add(np.char.add("A|", rb), sep), bb), sep), wg),
        "B": np.char.add(np.char.add(np.char.add("B|", rb), sep), bb),
        "C": np.char.add(np.char.add(np.char.add("C|", rc), sep), bc),
    }


class LookupBaseline:
    """Bucketed historical win rate. `table` maps key -> (wins, count); key "D" is the overall rate."""

    def __init__(self, cfg: BaselineConfig, table: dict[str, tuple[int, int]] | None = None,
                 fitted_on: dict | None = None):
        self.cfg = cfg
        self.table = table or {}
        self.fitted_on = fitted_on or {}

    def fit(self, rows: pd.DataFrame) -> "LookupBaseline":
        """Count wins per bucket on `rows` (model rows of the fitting seasons; needs `y`)."""
        if "is_model_row" in rows and not rows["is_model_row"].all():
            raise ValueError("baseline must be fit on model rows only")
        keys = bucket_keys(rows, self.cfg)
        y = rows["y"].to_numpy().astype(int)
        table: dict[str, tuple[int, int]] = {}
        for lvl in ("A", "B", "C"):
            g = pd.DataFrame({"k": keys[lvl], "y": y}).groupby("k")["y"].agg(["sum", "size"])
            table.update({k: (int(s), int(n)) for k, (s, n) in zip(g.index, g.to_numpy())})
        table["D"] = (int(y.sum()), int(len(y)))
        self.table = dict(sorted(table.items()))
        self.fitted_on = {"rows": int(len(rows)), "matches": int(rows["match_id"].nunique()),
                          "seasons": sorted(int(s) for s in rows["season"].unique())}
        return self

    def predict(self, rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        """Return (p, level_used) per row using the A -> B -> C -> D fallback."""
        keys = bucket_keys(rows, self.cfg)
        n = len(rows)
        p = np.full(n, np.nan)
        level = np.full(n, "D", dtype=object)
        done = np.zeros(n, bool)
        mc = self.cfg.min_count
        for lvl in ("A", "B", "C"):
            wins = np.array([self.table.get(k, (0, 0))[0] for k in keys[lvl]], float)
            cnt = np.array([self.table.get(k, (0, 0))[1] for k in keys[lvl]], float)
            use = ~done & (cnt >= mc)
            p[use] = wins[use] / cnt[use]
            level[use] = lvl
            done |= use
        w, c = self.table["D"]
        p[~done] = w / c
        return p, level.astype(str)

    def to_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "config": {"runs_band": self.cfg.runs_band, "runs_cap": self.cfg.runs_cap,
                       "balls_band": self.cfg.balls_band,
                       "wicket_groups": [list(g) for g in self.cfg.wicket_groups],
                       "min_count": self.cfg.min_count,
                       "level_c": {"runs_band": self.cfg.level_c.runs_band,
                                   "balls_band": self.cfg.level_c.balls_band}},
            "fitted_on": self.fitted_on,
            "table": {k: list(v) for k, v in self.table.items()},
        }
        path.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path, cfg: BaselineConfig) -> "LookupBaseline":
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(cfg, {k: (int(v[0]), int(v[1])) for k, v in d["table"].items()}, d["fitted_on"])


def level_shares(levels: np.ndarray) -> dict[str, float]:
    """Share of rows served by each level A-D."""
    s = pd.Series(levels).value_counts(normalize=True)
    return {lvl: float(s.get(lvl, 0.0)) for lvl in LEVELS}
