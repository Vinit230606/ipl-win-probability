"""Load `config/config.yaml` into frozen dataclasses.

Every constant used by the pipeline (paths, seed, bucket widths, grids) lives in the YAML file;
code reads it through `load_config()` so no magic numbers are scattered across modules.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "config.yaml"


@dataclass(frozen=True)
class IoConfig:
    raw_dir: Path
    interim_dir: Path
    processed_dir: Path
    models_dir: Path
    reports_dir: Path
    site_data_dir: Path
    format: str


@dataclass(frozen=True)
class RulesConfig:
    overs: int
    balls_per_innings: int
    wickets: int
    non_wicket_dismissals: tuple[str, ...]
    rrr_clip: float
    momentum_window_legal_balls: int
    big_over_runs: int


@dataclass(frozen=True)
class SplitConfig:
    n_test_seasons: int
    n_val_seasons: int


@dataclass(frozen=True)
class LevelCConfig:
    runs_band: int
    balls_band: int


@dataclass(frozen=True)
class BaselineConfig:
    runs_band: int
    runs_cap: int
    balls_band: int
    wicket_groups: tuple[tuple[int, int], ...]
    min_count: int
    level_c: LevelCConfig


@dataclass(frozen=True)
class LrConfig:
    C_grid: tuple[float, ...]
    max_iter: int


@dataclass(frozen=True)
class GbmConfig:
    learning_rate: tuple[float, ...]
    max_leaf_nodes: tuple[int, ...]
    min_samples_leaf: tuple[int, ...]
    l2_regularization: tuple[float, ...]
    max_iter: tuple[int, ...]
    monotonic: tuple[bool, ...]


@dataclass(frozen=True)
class RecencyConfig:
    half_life_grid: tuple[float | None, ...]
    gbm_top_k: int


@dataclass(frozen=True)
class SimulationConfig:
    rrr_bands: tuple[float, ...]
    wicket_groups: tuple[tuple[int, int], ...]
    legal_max_runs: int
    extra_max_runs: int
    max_runs: int
    shrinkage_grid: tuple[float, ...]
    support_runs: int
    support_balls: int
    blend_k_grid: tuple[float, ...]
    n_parity_vectors: int
    display_floor: float


@dataclass(frozen=True)
class EvalConfig:
    n_bootstrap: int
    ci: float
    calibration_bins: int
    logloss_eps: float
    n_failure_cases: int


@dataclass(frozen=True)
class ExportConfig:
    prob_decimals: int
    n_parity_vectors: int
    calculator_max_runs: int
    diagnostic_target_bins: tuple[int, ...]
    max_site_data_mb: float


@dataclass(frozen=True)
class Config:
    seed: int
    io: IoConfig
    rules: RulesConfig
    split: SplitConfig
    baseline: BaselineConfig
    lr: LrConfig
    gbm: GbmConfig
    recency: RecencyConfig
    simulation: SimulationConfig
    eval: EvalConfig
    export: ExportConfig
    path: Path
    sha256: str


def _tuple(values: Any) -> tuple:
    return tuple(values)


def load_config(path: str | Path | None = None) -> Config:
    """Read the YAML config at `path` (default `config/config.yaml`) and return a frozen Config.

    Relative paths in the `io` section are resolved against the repository root, so stages work
    no matter which directory the CLI is started from. `sha256` is the hash of the file bytes and
    is recorded in the test lock.
    """
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    raw_bytes = cfg_path.read_bytes()
    d = yaml.safe_load(raw_bytes)

    io = d["io"]
    io_cfg = IoConfig(
        **{k: (REPO_ROOT / v) for k, v in io.items() if k != "format"},
        format=str(io["format"]),
    )
    if io_cfg.format not in ("parquet", "csv"):
        raise ValueError(f"io.format must be 'parquet' or 'csv', got {io_cfg.format!r}")

    r = d["rules"]
    rules = RulesConfig(**{**r, "non_wicket_dismissals": _tuple(r["non_wicket_dismissals"])})
    b = d["baseline"]
    baseline = BaselineConfig(
        runs_band=b["runs_band"],
        runs_cap=b["runs_cap"],
        balls_band=b["balls_band"],
        wicket_groups=tuple(tuple(g) for g in b["wicket_groups"]),
        min_count=b["min_count"],
        level_c=LevelCConfig(**b["level_c"]),
    )
    lr = LrConfig(C_grid=_tuple(d["lr"]["C_grid"]), max_iter=d["lr"]["max_iter"])
    gbm = GbmConfig(**{k: _tuple(v) for k, v in d["gbm"].items()})

    return Config(
        seed=int(d["seed"]),
        io=io_cfg,
        rules=rules,
        split=SplitConfig(**d["split"]),
        baseline=baseline,
        lr=lr,
        gbm=gbm,
        recency=RecencyConfig(
            half_life_grid=tuple(None if h is None else float(h)
                                 for h in d["recency"]["half_life_grid"]),
            gbm_top_k=int(d["recency"]["gbm_top_k"]),
        ),
        simulation=SimulationConfig(
            rrr_bands=tuple(float(x) for x in d["simulation"]["rrr_bands"]),
            wicket_groups=tuple(tuple(g) for g in d["simulation"]["wicket_groups"]),
            legal_max_runs=int(d["simulation"]["legal_max_runs"]),
            extra_max_runs=int(d["simulation"]["extra_max_runs"]),
            max_runs=int(d["simulation"]["max_runs"]),
            shrinkage_grid=tuple(float(x) for x in d["simulation"]["shrinkage_grid"]),
            support_runs=int(d["simulation"]["support_bucket"]["runs"]),
            support_balls=int(d["simulation"]["support_bucket"]["balls"]),
            blend_k_grid=tuple(float(x) for x in d["simulation"]["blend_k_grid"]),
            n_parity_vectors=int(d["simulation"]["n_parity_vectors"]),
            display_floor=float(d["simulation"]["display_floor"]),
        ),
        eval=EvalConfig(**d["eval"]),
        export=ExportConfig(**{**d["export"], "diagnostic_target_bins":
                               tuple(int(x) for x in d["export"]["diagnostic_target_bins"])}),
        path=cfg_path,
        sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )
