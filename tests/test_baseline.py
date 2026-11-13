"""Band functions at their edges, fallback order A -> B -> C -> D, counts, JSON round trip."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from iplwp.baseline import LookupBaseline, balls_band, bucket_keys, level_shares, runs_band, wkt_group
from iplwp.config import load_config

CFG = load_config().baseline


def test_runs_band_edges():
    assert runs_band([1, 9, 10, 19, 199, 200, 250], CFG).tolist() == [0, 0, 1, 1, 19, 20, 20]


def test_balls_band_edges():
    assert balls_band([1, 12, 13, 24, 108, 109, 120], CFG).tolist() == [0, 0, 1, 1, 8, 9, 9]


def test_wicket_groups():
    assert wkt_group([10, 8, 7, 5, 4, 3, 2, 1], CFG).tolist() == [0, 0, 1, 1, 2, 2, 3, 3]
    with pytest.raises(ValueError):
        wkt_group([0], CFG)


def test_keys():
    k = bucket_keys(pd.DataFrame({"runs_needed": [45], "balls_left": [30], "wickets_left": [6]}), CFG)
    assert (k["A"][0], k["B"][0], k["C"][0]) == ("A|4|2|1", "B|4|2", "C|1|0")


def rows(r, b, w, y, n, mid="m"):
    return pd.DataFrame({"runs_needed": [r] * n, "balls_left": [b] * n, "wickets_left": [w] * n,
                         "y": [y] * n, "match_id": [f"{mid}{i}" for i in range(n)],
                         "season": [2015] * n})


def test_fallback_order_and_counts():
    train = pd.concat([
        rows(45, 30, 6, 1, 30),   # A|4|2|1 (30 rows, all won)          B|4|2  C|1|0
        rows(45, 30, 9, 0, 10),   # A|4|2|0 (10)                         B|4|2 -> 40 rows, 30 won
        rows(55, 30, 9, 0, 25),   # A|5|2|0 (25 < 30)                    B|5|2
        rows(52, 26, 6, 1, 10),   # A|5|2|1 (10)                         B|5|2 -> 35 rows, 10 won
        rows(65, 30, 9, 0, 20),   # A|6|2|0 (20), B|6|2 (20)             C|2|0
        rows(75, 20, 9, 1, 12),   # A|7|1|0 (12), B|7|1 (12)             C|2|0 -> 32 rows, 12 won
    ], ignore_index=True)
    bl = LookupBaseline(CFG).fit(train)
    assert bl.table["A|4|2|1"] == (30, 30)
    assert bl.table["B|4|2"] == (30, 40)
    assert bl.table["B|5|2"] == (10, 35)
    assert bl.table["C|2|0"] == (12, 32)
    assert bl.table["D"] == (int(train.y.sum()), len(train))
    q = pd.DataFrame({"runs_needed": [45, 45, 55, 65, 150], "balls_left": [30, 30, 30, 30, 100],
                      "wickets_left": [6, 9, 9, 9, 3]})
    p, lvl = bl.predict(q)
    assert lvl.tolist() == ["A", "B", "B", "C", "D"]
    assert p[0] == 1.0
    assert p[1] == pytest.approx(30 / 40)
    assert p[2] == pytest.approx(10 / 35)
    assert p[3] == pytest.approx(12 / 32)
    assert p[4] == pytest.approx(train.y.mean())
    assert level_shares(lvl) == {"A": 0.2, "B": 0.4, "C": 0.2, "D": 0.2}


def test_json_round_trip(tmp_path):
    train = pd.concat([rows(45, 30, 6, 1, 40), rows(100, 90, 9, 0, 40)], ignore_index=True)
    bl = LookupBaseline(CFG).fit(train)
    bl.to_json(tmp_path / "b.json")
    bl2 = LookupBaseline.from_json(tmp_path / "b.json", CFG)
    p1, l1 = bl.predict(train)
    p2, l2 = bl2.predict(train)
    assert np.array_equal(p1, p2) and np.array_equal(l1, l2)


def test_rejects_terminal_rows():
    t = rows(45, 30, 6, 1, 5)
    t["is_model_row"] = [True, True, False, True, True]
    with pytest.raises(ValueError):
        LookupBaseline(CFG).fit(t)
