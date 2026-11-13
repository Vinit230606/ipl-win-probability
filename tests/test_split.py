"""Season split assignment and disjointness (requirement 5)."""
from __future__ import annotations

import pandas as pd
import pytest

from iplwp.config import load_config
from iplwp.split import assign_split, check_disjoint, season_split

CFG = load_config()


def test_assignment():
    m = season_split([2010, 2008, 2009, 2011, 2012, 2012], CFG.split)
    assert m == {2008: "train", 2009: "train", 2010: "val", 2011: "test", 2012: "test"}


def test_too_few_seasons():
    with pytest.raises(ValueError, match="split impossible"):
        season_split([2020, 2021, 2022], CFG.split)


def test_disjoint_and_assign():
    rows = pd.DataFrame({"match_id": ["a", "a", "b", "c"], "season": [2008, 2008, 2010, 2012]})
    rows["split"] = assign_split(rows, season_split(range(2008, 2013), CFG.split))
    assert rows["split"].tolist() == ["train", "train", "val", "test"]
    check_disjoint(rows)
    rows.loc[1, "split"] = "val"
    with pytest.raises(AssertionError):
        check_disjoint(rows)


def test_real_split_disjoint():
    from iplwp.io_tables import read_table, table_path
    if not table_path(CFG, CFG.io.processed_dir, "chase_features").exists():
        pytest.skip("run `make features` first")
    f = read_table(CFG, CFG.io.processed_dir, "chase_features")
    check_disjoint(f)
    by = f.groupby("split")["season"].agg(["min", "max"])
    assert by.loc["train", "max"] < by.loc["val", "min"] <= by.loc["val", "max"] < by.loc["test", "min"]
