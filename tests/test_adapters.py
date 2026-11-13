"""The K, C and J adapters must map the same toy match to identical canonical rows."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from iplwp.config import DEFAULT_CONFIG_PATH, load_config
from iplwp.io_adapters import (SchemaNotRecognised, adapt_cricsheet_csv, adapt_cricsheet_json,
                               adapt_kaggle, detect_format, require_format)
from iplwp.schema import CANONICAL_DELIVERIES, CANONICAL_MATCHES, DataQualityError

FIX = Path(__file__).parent / "fixtures"
TARGET_COLS = ["target_runs_provided", "target_overs_provided"]


@pytest.fixture(scope="module")
def adapted():
    k = adapt_kaggle(FIX / "toy_k" / "deliveries.csv", FIX / "toy_k" / "matches.csv")
    c = adapt_cricsheet_csv([FIX / "toy_c" / "999001.csv"], [FIX / "toy_c" / "999001_info.csv"])
    j = adapt_cricsheet_json([FIX / "toy_j" / "999001.json"])
    return {"K": k, "C": c, "J": j}


def test_detection():
    assert detect_format(FIX / "toy_k").format == "K"
    assert detect_format(FIX / "toy_c").format == "C"
    assert detect_format(FIX / "toy_j").format == "J"


def test_canonical_columns_only(adapted):
    for m, d in adapted.values():
        assert list(m.columns) == CANONICAL_MATCHES
        assert list(d.columns) == CANONICAL_DELIVERIES


def test_same_deliveries(adapted):
    _, dk = adapted["K"]
    for name in ("C", "J"):
        pd.testing.assert_frame_equal(dk, adapted[name][1], obj=f"K vs {name} deliveries")


def test_same_matches(adapted):
    mk = adapted["K"][0]
    pd.testing.assert_frame_equal(mk.drop(columns=TARGET_COLS),
                                  adapted["C"][0].drop(columns=TARGET_COLS))
    pd.testing.assert_frame_equal(mk, adapted["J"][0])
    assert adapted["C"][0][TARGET_COLS].isna().all().all()


def test_season_from_date_not_label(adapted):
    for m, _ in adapted.values():
        assert m.loc[0, "season"] == 2020          # label is "2020/21"
        assert m.loc[0, "date"] == pd.Timestamp("2020-09-20")


def test_values(adapted):
    m, d = adapted["J"]
    assert m.loc[0, "outcome_type"] == "normal" and m.loc[0, "winner"] == "Mumbai Indians"
    i2 = d[d.innings == 2].reset_index(drop=True)
    assert i2["seq"].tolist() == [0, 1, 2, 3]
    assert i2["runs_total"].tolist() == [1, 0, 2, 5]
    assert i2["is_legbye"].tolist() == [False, False, True, False]
    assert i2["is_noball"].tolist() == [False, False, False, True]
    assert i2["dismissal_kind"].tolist()[1] == "caught"
    assert i2["n_dismissals"].tolist() == [0, 1, 0, 0]
    assert (i2["bowling_team"] == "Kings XI Punjab").all()
    i1 = d[d.innings == 1].reset_index(drop=True)
    assert i1["is_wide"].tolist() == [False, True, False]
    assert i1["dismissal_kind"].tolist()[2] == "bowled"  # Kaggle "Bowled" lower-cased


def test_kaggle_aliases(tmp_path, adapted):
    d = pd.read_csv(FIX / "toy_k" / "deliveries.csv")
    d = d.rename(columns={"match_id": "id", "batter": "batsman", "inning": "innings"})
    d.to_csv(tmp_path / "deliveries.csv", index=False)
    m = pd.read_csv(FIX / "toy_k" / "matches.csv")
    m.to_csv(tmp_path / "matches.csv", index=False)
    assert detect_format(tmp_path).format == "K"
    mk, dk = adapt_kaggle(tmp_path / "deliveries.csv", tmp_path / "matches.csv")
    pd.testing.assert_frame_equal(dk, adapted["K"][1])


def test_runs_total_assertion(tmp_path):
    d = pd.read_csv(FIX / "toy_k" / "deliveries.csv")
    d.loc[0, "total_runs"] = 99
    d.to_csv(tmp_path / "deliveries.csv", index=False)
    with pytest.raises(DataQualityError):
        adapt_kaggle(tmp_path / "deliveries.csv", FIX / "toy_k" / "matches.csv")


def test_unknown_layout_raises_and_writes_template(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    pd.DataFrame({"a": [1], "b": [2]}).to_csv(raw / "x.csv", index=False)
    cfg_dict = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text())
    cfg_dict["io"]["raw_dir"] = str(raw)
    (tmp_path / "config").mkdir()
    cfg_file = tmp_path / "config" / "config.yaml"
    cfg_file.write_text(yaml.safe_dump(cfg_dict))
    cfg = load_config(cfg_file)
    with pytest.raises(SchemaNotRecognised, match="column_map.yaml"):
        require_format(cfg)
    assert (tmp_path / "config" / "column_map.yaml").exists()
