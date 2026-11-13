"""Read and write pipeline tables (interim/processed) in the format chosen in config `io.format`."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import Config


def table_path(cfg: Config, directory: Path, name: str) -> Path:
    return directory / f"{name}.{cfg.io.format}"


def write_table(cfg: Config, df: pd.DataFrame, directory: Path, name: str) -> Path:
    """Write `df` as `<directory>/<name>.<fmt>` and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = table_path(cfg, directory, name)
    if cfg.io.format == "parquet":
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path, index=False)
    return path


def read_table(cfg: Config, directory: Path, name: str) -> pd.DataFrame:
    """Read a table written by `write_table`. Fails loudly if an earlier stage has not run."""
    path = table_path(cfg, directory, name)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run the earlier pipeline stage first")
    if cfg.io.format == "parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, dtype={"match_id": "string"})


def read_dev_features(cfg: Config) -> pd.DataFrame:
    """Read chase_features WITHOUT test-season rows (for the baseline and tune stages).

    With parquet the test rows are filtered out while reading, so they are never in memory.
    Asserts that no returned row has split == "test".
    """
    path = table_path(cfg, cfg.io.processed_dir, "chase_features")
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `make features` first")
    if cfg.io.format == "parquet":
        df = pd.read_parquet(path, filters=[("split", "!=", "test")])
    else:
        df = pd.read_csv(path, dtype={"match_id": "string"})
        df = df[df["split"] != "test"].reset_index(drop=True)
    assert (df["split"] != "test").all(), "test rows leaked into a development stage"
    return df
