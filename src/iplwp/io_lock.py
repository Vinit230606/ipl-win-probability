"""Test lock (design 11.6): the test seasons are scored once; reruns need --force and a reason."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


class LockError(Exception):
    """Raised when the test set was already scored and --force was not given."""


def git_commit(repo: Path) -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True,
                           timeout=10)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def acquire_test_lock(path: Path, config_sha256: str, selection: dict, repo: Path,
                      force: bool = False, reason: str | None = None) -> dict:
    """Create `TEST_LOCK.json`, or with force + reason append a forced-run entry.

    Raises LockError if the lock exists and `force` is False, ValueError if `force` is True
    without a non-empty `reason`. Returns the lock contents after the update.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = {"timestamp": now, "git_commit": git_commit(repo), "config_sha256": config_sha256}
    if path.exists():
        if not force:
            raise LockError(
                f"{path} exists: the test seasons were already scored on "
                f"{json.loads(path.read_text(encoding='utf-8'))['created_at']}. Rerunning would "
                "mean looking at test results twice. If you must, run "
                "`python -m iplwp.cli final --force --reason \"<why>\"`; the run is recorded.")
        if not reason or not reason.strip():
            raise ValueError("--force requires --reason \"<text>\"")
        lock = json.loads(path.read_text(encoding="utf-8"))
        lock.setdefault("forced_runs", []).append({**entry, "reason": reason.strip(),
                                                   "selection": selection})
    else:
        lock = {"created_at": now, **entry, "selection": selection, "forced_runs": []}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, indent=2), encoding="utf-8")
    return lock
