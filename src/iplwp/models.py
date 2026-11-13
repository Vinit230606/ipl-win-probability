"""Model definitions (design section 10) and recency sample weights (refinement D8).

LR-full / LR-core: StandardScaler + LogisticRegression in one Pipeline, so the scaler is fit on the
fitting rows only. GBM: HistGradientBoostingClassifier with optional monotonic constraints.
Recency weights depend only on a row's season and the latest season used for fitting, never on
the validation or test seasons.
"""
from __future__ import annotations

import itertools
import time
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .config import Config
from .features import BASE7

# Monotonic constraints in BASE7 order (design 10.2 / requirement 8.3)
MONO_BY_FEATURE = {"runs_needed": -1, "balls_left": 1, "wickets_left": 1, "target": 0, "rrr": -1,
                   "runs_last18": 0, "wkts_last18": 0}
MONO = [MONO_BY_FEATURE[f] for f in BASE7]


def recency_weights(seasons, ref_season: int, half_life: float | None) -> np.ndarray:
    """Weight 0.5 ** ((ref_season - season) / half_life), normalised to mean 1.

    `ref_season` is the latest season among the fitting rows. half_life None -> all ones.
    """
    s = np.asarray(seasons, float)
    if half_life is None:
        return np.ones(len(s))
    w = 0.5 ** ((ref_season - s) / half_life)
    return w / w.mean()


def make_lr(C: float, max_iter: int) -> Pipeline:
    return Pipeline([("scale", StandardScaler()),
                     ("lr", LogisticRegression(C=C, solver="lbfgs", max_iter=max_iter))])


def make_gbm(params: dict[str, Any], seed: int) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        loss="log_loss",
        learning_rate=params["learning_rate"],
        max_leaf_nodes=params["max_leaf_nodes"],
        min_samples_leaf=params["min_samples_leaf"],
        l2_regularization=params["l2_regularization"],
        max_iter=params["max_iter"],
        early_stopping=False,
        monotonic_cst=MONO if params["monotonic"] else None,
        random_state=seed,
    )


def fit_lr(X, y, w, C: float, max_iter: int) -> Pipeline:
    model = make_lr(C, max_iter)
    model.fit(X, y, lr__sample_weight=w)
    return model


def fit_gbm(X, y, w, params: dict[str, Any], seed: int) -> HistGradientBoostingClassifier:
    model = make_gbm(params, seed)
    model.fit(X, y, sample_weight=w)
    return model


def predict_p(model, X) -> np.ndarray:
    return model.predict_proba(X)[:, 1]


def gbm_grid(cfg: Config, max_iter: tuple[int, ...] | None = None) -> list[dict[str, Any]]:
    g = cfg.gbm
    keys = ["learning_rate", "max_leaf_nodes", "min_samples_leaf", "l2_regularization",
            "max_iter", "monotonic"]
    vals = [g.learning_rate, g.max_leaf_nodes, g.min_samples_leaf, g.l2_regularization,
            max_iter if max_iter is not None else g.max_iter, g.monotonic]
    return [dict(zip(keys, v)) for v in itertools.product(*vals)]


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.seconds = time.perf_counter() - self.t0


# --------------------------------------------------------------------------------------------
# Tuning on validation (design 10.1-10.3). Pure functions: frames in, tables out.
# --------------------------------------------------------------------------------------------
def _xy(rows, cols):
    return rows[cols].to_numpy(float), rows["y"].to_numpy().astype(int)


def tune_lr(train, val, feature_sets: dict[str, list[str]], cfg: Config, log=print):
    """Grid over feature set x C x half-life. Returns (log DataFrame, best row dict).

    Selection: lowest validation Brier; ties -> lower log loss -> smaller C -> uniform weights first.
    """
    import pandas as pd

    from .metrics import brier, log_loss

    ref = int(train["season"].max())
    rows = []
    for (fs_name, cols), hl, C in itertools.product(feature_sets.items(), cfg.recency.half_life_grid,
                                                    cfg.lr.C_grid):
        Xt, yt = _xy(train, cols)
        Xv, yv = _xy(val, cols)
        w = recency_weights(train["season"], ref, hl)
        with Timer() as t:
            m = fit_lr(Xt, yt, w, C, cfg.lr.max_iter)
        p = predict_p(m, Xv)
        rows.append({"feature_set": fs_name, "C": C, "half_life": hl,
                     "val_brier": brier(p, yv), "val_log_loss": log_loss(p, yv, cfg.eval.logloss_eps),
                     "n_iter": int(m.named_steps["lr"].n_iter_[0]), "fit_seconds": round(t.seconds, 2)})
    df = pd.DataFrame(rows)
    df["_hl"] = df["half_life"].fillna(np.inf)
    best = df.sort_values(["val_brier", "val_log_loss", "C", "_hl"],
                          ascending=[True, True, True, False]).iloc[0]
    df = df.drop(columns="_hl")
    # wall-clock timings stay in the tuning log only, so chosen settings are reproducible
    b = best.drop(labels=["_hl", "fit_seconds", "n_iter"]).to_dict()
    b["half_life"] = None if pd.isna(b["half_life"]) else float(b["half_life"])
    b["features"] = feature_sets[b["feature_set"]]
    log(f"  best: {b['feature_set']} C={b['C']} half_life={b['half_life']} "
        f"val Brier {b['val_brier']:.5f}")
    return df, b


def tune_gbm(train, val, cfg: Config, log=print, budget_seconds: float = 30 * 60):
    """GBM tuning (design 10.2 + D8).

    Pass 1: the full grid with uniform weights. If the projected time exceeds `budget_seconds`
    after the first configs, the design fallback is used (max_iter=300 grid, then the top 10 with
    max_iter=600). Pass 2: the top `gbm_top_k` configs re-fit with every non-uniform half-life.
    Returns (log DataFrame, best row dict, notes list).
    """
    import pandas as pd

    from .metrics import brier, log_loss

    Xt, yt = _xy(train, BASE7)
    Xv, yv = _xy(val, BASE7)
    ref = int(train["season"].max())
    rows, notes = [], []

    def run(params, hl, stage):
        w = None if hl is None else recency_weights(train["season"], ref, hl)
        with Timer() as t:
            m = fit_gbm(Xt, yt, w, params, cfg.seed)
        p = predict_p(m, Xv)
        r = {**params, "half_life": hl, "stage": stage, "val_brier": brier(p, yv),
             "val_log_loss": log_loss(p, yv, cfg.eval.logloss_eps), "fit_seconds": round(t.seconds, 2)}
        rows.append(r)
        return r

    grid = gbm_grid(cfg)
    t0 = time.perf_counter()
    fallback = False
    for i, params in enumerate(grid):
        run(params, None, "grid")
        if i == 19:
            projected = (time.perf_counter() - t0) / 20 * len(grid)
            if projected > budget_seconds:
                fallback = True
                break
        if (i + 1) % 24 == 0:
            log(f"  GBM grid {i + 1}/{len(grid)} ({time.perf_counter() - t0:.0f}s)")
    if fallback:
        notes.append(f"Full grid projected at {projected / 60:.0f} min > {budget_seconds / 60:.0f}; "
                     "used the design fallback (max_iter=300 grid, top 10 at max_iter=600).")
        rows.clear()
        for params in gbm_grid(cfg, max_iter=(300,)):
            run(params, None, "grid300")
        top = pd.DataFrame(rows).sort_values(["val_brier", "val_log_loss"]).head(10)
        for _, r in top.iterrows():
            p = {k: r[k] for k in ("learning_rate", "max_leaf_nodes", "min_samples_leaf",
                                   "l2_regularization", "monotonic")}
            run({**p, "max_iter": 600}, None, "top10_600")
    else:
        notes.append(f"Full grid of {len(grid)} configs with uniform weights "
                     f"({time.perf_counter() - t0:.0f}s).")

    base = pd.DataFrame(rows).sort_values(["val_brier", "val_log_loss"]).head(cfg.recency.gbm_top_k)
    other_hl = [h for h in cfg.recency.half_life_grid if h is not None]
    for _, r in base.iterrows():
        params = {k: (bool(r[k]) if k == "monotonic" else r[k]) for k in
                  ("learning_rate", "max_leaf_nodes", "min_samples_leaf", "l2_regularization",
                   "max_iter", "monotonic")}
        params["max_leaf_nodes"] = int(params["max_leaf_nodes"])
        params["min_samples_leaf"] = int(params["min_samples_leaf"])
        params["max_iter"] = int(params["max_iter"])
        for hl in other_hl:
            run(params, hl, "recency")
    notes.append(f"Recency pass: top {cfg.recency.gbm_top_k} uniform-weight configs x half-lives "
                 f"{other_hl} ({len(base) * len(other_hl)} fits).")

    df = pd.DataFrame(rows)
    df["_hl"] = df["half_life"].fillna(np.inf)
    best = df.sort_values(["val_brier", "val_log_loss", "_hl"], ascending=[True, True, False]).iloc[0]
    df = df.drop(columns="_hl")
    b = {k: best[k] for k in ("learning_rate", "max_leaf_nodes", "min_samples_leaf",
                              "l2_regularization", "max_iter", "monotonic", "half_life",
                              "val_brier", "val_log_loss")}
    b = {k: (v.item() if hasattr(v, "item") else v) for k, v in b.items()}
    b["monotonic"] = bool(b["monotonic"])
    b["half_life"] = None if pd.isna(b["half_life"]) else float(b["half_life"])
    b["features"] = BASE7
    log(f"  best GBM: {b}")
    return df, b, notes


def fit_chosen(kind: str, params: dict, rows, cfg: Config):
    """Fit model `kind` ("lr_full" | "lr_core" | "gbm") with chosen `params` on `rows`
    (recency weights relative to the latest season in `rows`)."""
    w = recency_weights(rows["season"], int(rows["season"].max()), params["half_life"])
    X, y = _xy(rows, params["features"])
    if kind == "gbm":
        return fit_gbm(X, y, None if params["half_life"] is None else w, params, cfg.seed)
    return fit_lr(X, y, w, params["C"], cfg.lr.max_iter)
