"""Each exclusion reason triggers on a toy match, is logged, and rule order is respected."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from toy import frames, match, simple_innings  # noqa: E402

from iplwp.clean import clean  # noqa: E402
from iplwp.config import load_config  # noqa: E402

RULES = load_config().rules


def full(mid, i1_balls=120, i1_wkts=0, i2_balls=120, i2_rpb=1, i2_wkts=0, bat1="A", bat2="B"):
    """Innings 1: 120 runs (target 121) unless changed; innings 2 as given."""
    return [simple_innings(mid, 1, bat1, bat2, i1_balls, 1, i1_wkts),
            simple_innings(mid, 2, bat2, bat1, i2_balls, i2_rpb, i2_wkts)]


@pytest.fixture(scope="module")
def result():
    ms, ds = [], []

    def add(m, inns):
        ms.append(m)
        ds.extend(inns)

    add(match("kept_lost", winner="A"), full("kept_lost"))
    add(match("kept_won", winner="B"), full("kept_won", i2_balls=61, i2_rpb=2))
    # renamed franchise: winner given under the new name, innings under the old one
    add(match("kept_renamed", team1="A", team2="Delhi Daredevils", winner="Delhi Capitals"),
        full("kept_renamed", i2_balls=61, i2_rpb=2, bat2="Delhi Daredevils"))
    add(match("dup"), full("dup"))
    add(match("dup"), [])
    add(match("noresult", winner=None, outcome_type="no_result"), full("noresult"))
    add(match("tie_and_dls", outcome_type="tie", method="D/L"), full("tie_and_dls"))
    add(match("dls", method="D/L"), full("dls"))
    add(match("nochase"), full("nochase")[:1])
    add(match("reduced_target", target_overs=15.0), full("reduced_target"))
    add(match("reduced_inn1"), full("reduced_inn1", i1_balls=60, i1_wkts=3))
    add(match("target_bad", target_runs=150, target_overs=20.0), full("target_bad"))
    add(match("incomplete"), full("incomplete", i2_balls=100, i2_wkts=5))
    add(match("label_bad", winner="B"), full("label_bad"))
    m, d = frames(ms, ds)
    # super over innings on a kept match must be dropped
    so = simple_innings("kept_lost", 3, "B", "A", 6)
    from iplwp.schema import DELIVERIES_DTYPES, enforce_schema
    import pandas as pd
    d = enforce_schema(pd.concat([d, so], ignore_index=True), DELIVERIES_DTYPES, "deliveries")
    return m, clean(m, d, RULES)


def reasons(result) -> dict[str, list[str]]:
    _, (_, _, excl) = result
    return excl.groupby("reason")["match_id"].apply(sorted).to_dict()


@pytest.mark.parametrize("reason,mid", [
    ("NO_RESULT", "noresult"), ("TIE", "tie_and_dls"), ("DLS", "dls"), ("NO_CHASE", "nochase"),
    ("REDUCED_OVERS", "reduced_target"), ("REDUCED_OVERS", "reduced_inn1"),
    ("TARGET_MISMATCH", "target_bad"), ("CHASE_INCOMPLETE", "incomplete"),
    ("LABEL_MISMATCH", "label_bad"),
])
def test_reason(result, reason, mid):
    assert mid in reasons(result)[reason]


def test_duplicate_logs_all_rows(result):
    assert reasons(result)["DUPLICATE"] == ["dup", "dup"]


def test_first_rule_wins(result):
    _, (_, _, excl) = result
    assert excl.loc[excl.match_id == "tie_and_dls", "reason"].tolist() == ["TIE"]


def test_kept_and_counts(result):
    m, (chases, kept, excl) = result
    assert sorted(chases.match_id) == ["kept_lost", "kept_renamed", "kept_won"]
    assert len(m) == len(chases) + len(excl)
    c = chases.set_index("match_id")
    assert c.loc["kept_lost", "target"] == 121 and c.loc["kept_lost", "chase_won"] == 0
    assert c.loc["kept_won", "chase_won"] == 1 and c.loc["kept_won", "final_runs"] == 122
    assert c.loc["kept_renamed", "chase_won"] == 1
    assert set(kept.innings) == {1, 2}
    assert list(excl.columns) == ["match_id", "season", "reason", "detail"]
