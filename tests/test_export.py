"""Website JSON: schema validity, size limit, no NaN, parity vectors reproduce scikit-learn."""
from __future__ import annotations

import json

import joblib
import numpy as np
import pytest

from iplwp.config import load_config
from iplwp.export import validate
from iplwp.features import CORE, core_terms

CFG = load_config()
DATA = CFG.io.site_data_dir


def _load(path):
    def bad(c):
        raise ValueError(f"{path.name}: non-finite number {c}")
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=bad)


@pytest.fixture(scope="module")
def site():
    if not (DATA / "matches.json").exists():
        pytest.skip("run `make export` first")
    return {"matches": _load(DATA / "matches.json"), "results": _load(DATA / "results.json"),
            "lr_core": _load(DATA / "lr_core.json")}


def test_top_level_schemas(site):
    validate(site["matches"], "matches", "matches.json")
    validate(site["results"], "results", "results.json")
    validate(site["lr_core"], "lr_core", "lr_core.json")


def test_every_match_file_valid(site):
    ids = {m["match_id"] for m in site["matches"]["matches"]}
    files = {p.stem for p in (DATA / "matches").glob("*.json")}
    assert ids == files
    assert site["matches"]["featured_match_id"] in ids
    for p in sorted((DATA / "matches").glob("*.json")):
        doc = _load(p)
        validate(doc, "match", p.name)
        assert [b["i"] for b in doc["balls"]] == list(range(1, len(doc["balls"]) + 1))
        last = doc["balls"][-1]
        assert last["terminal"] and last["p_model"] == float(doc["chase_won"])


def test_size_under_limit():
    if not DATA.exists():
        pytest.skip("run `make export` first")
    size = sum(p.stat().st_size for p in DATA.rglob("*.json"))
    assert size < CFG.export.max_site_data_mb * 1024 * 1024


def test_parity_vectors_match_sklearn(site):
    lc = site["lr_core"]
    assert len(lc["test_vectors"]) >= 200 and lc["feature_order"] == CORE
    model = joblib.load(CFG.io.models_dir / "lr_core_final.joblib")
    v = lc["test_vectors"]
    t = core_terms([x["runs_needed"] for x in v], [x["balls_left"] for x in v],
                   [x["wickets_left"] for x in v], lc["rrr_clip"])
    p = model.predict_proba(np.column_stack([t[c] for c in CORE]))[:, 1]
    assert np.max(np.abs(p - np.array([x["p"] for x in v]))) < 1e-12
    edges = {(x["runs_needed"], x["balls_left"], x["wickets_left"]) for x in v}
    assert {(1, 1, 1), (300, 120, 10), (1, 120, 10), (300, 1, 1)} <= edges
