"""A second test run without --force aborts; --force needs a reason and is recorded."""
from __future__ import annotations

import json

import pytest

from iplwp.io_lock import LockError, acquire_test_lock


def test_lock_lifecycle(tmp_path):
    p = tmp_path / "TEST_LOCK.json"
    sel = {"best_model": "gbm"}
    lock = acquire_test_lock(p, "abc", sel, tmp_path)
    assert p.exists() and lock["selection"] == sel and lock["forced_runs"] == []
    with pytest.raises(LockError):
        acquire_test_lock(p, "abc", sel, tmp_path)
    with pytest.raises(ValueError):
        acquire_test_lock(p, "abc", sel, tmp_path, force=True)
    with pytest.raises(ValueError):
        acquire_test_lock(p, "abc", sel, tmp_path, force=True, reason="  ")
    acquire_test_lock(p, "def", sel, tmp_path, force=True, reason="fixed plot bug")
    d = json.loads(p.read_text())
    assert len(d["forced_runs"]) == 1
    assert d["forced_runs"][0]["reason"] == "fixed plot bug"
    assert d["forced_runs"][0]["config_sha256"] == "def"
    assert d["config_sha256"] == "abc"
