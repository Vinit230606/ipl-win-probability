"""Command-line entry point: `python -m iplwp.cli <stage>`.

One subcommand per pipeline stage, with the same names as the Makefile targets. Each stage reads
only the outputs of earlier stages from disk, so any stage can be rerun on its own.
"""
from __future__ import annotations

import argparse
import os
import sys
import warnings
from typing import Callable

# joblib's physical-core probe fails on this Windows setup; give it the logical count instead.
os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(os.cpu_count() or 1))
# scikit-learn 1.5 passes an option newer SciPy no longer knows; harmless.
warnings.filterwarnings("ignore", message="Unknown solver options: iprint")
warnings.filterwarnings("ignore", message="Could not find the number of physical cores")

from .config import load_config

STAGES = ["profile", "data", "features", "baseline", "tune", "final", "export"]


def _not_implemented(name: str) -> Callable[[argparse.Namespace], int]:
    def run(args: argparse.Namespace) -> int:
        print(f"{name}: not implemented")
        return 1
    return run


def run_profile(args: argparse.Namespace) -> int:
    from .io_adapters import profile

    cfg = load_config(args.config)
    det = profile(cfg)
    print(f"Detected format: {det.format}")
    for n in det.notes:
        print(f"  {n}")
    if det.missing:
        print(f"  Missing: {det.missing}")
    print(f"Wrote {cfg.io.reports_dir / 'data_profile.md'}")
    return 0 if det.format != "unknown" else 2


def run_data(args: argparse.Namespace) -> int:
    """adapt -> data/interim; clean -> exclusions + chases; states -> data/processed/chase_states."""
    from .clean import clean, data_quality_markdown
    from .io_adapters import adapt
    from .io_tables import write_table
    from .schema import DataQualityError
    from .states import build_states, running_total_check

    cfg = load_config(args.config)
    matches, deliveries, fmt = adapt(cfg)
    write_table(cfg, matches, cfg.io.interim_dir, "matches")
    write_table(cfg, deliveries, cfg.io.interim_dir, "deliveries")
    print(f"Adapted format {fmt}: {len(matches):,} matches, {len(deliveries):,} deliveries")

    chases, kept, exclusions = clean(matches, deliveries, cfg.rules)
    cfg.io.reports_dir.mkdir(parents=True, exist_ok=True)
    exclusions.to_csv(cfg.io.reports_dir / "exclusions.csv", index=False)
    print(f"Kept {len(chases):,} chases; excluded {len(exclusions):,} "
          f"({exclusions['reason'].value_counts().to_dict()})")

    states = build_states(kept[kept["innings"] == 2], chases, cfg.rules)
    check = running_total_check(states, chases)
    (cfg.io.reports_dir / "data_quality.md").write_text(
        data_quality_markdown(matches, exclusions, chases, kept, states, check, fmt),
        encoding="utf-8")
    if not check["ok"].all():
        bad = check[~check["ok"]].iloc[0]
        raise DataQualityError(f"running-total check failed for match {bad['match_id']}: {bad.to_dict()}")
    write_table(cfg, chases, cfg.io.processed_dir, "chases")
    write_table(cfg, states, cfg.io.processed_dir, "chase_states")
    print(f"States: {len(states):,} rows ({int((~states['is_terminal']).sum()):,} model rows). "
          f"Running-total check: {int(check['ok'].sum())}/{len(check)} ok.")
    return 0


IMPACT_PLAYER_FROM = 2023  # IPL Impact Player substitution rule introduced in the 2023 season


def run_features(args: argparse.Namespace) -> int:
    """chase_states -> chase_features (+ split, is_model_row), feature_manifest.json, split table."""
    import json

    from .clean import SPLIT_MARKER
    from .features import FEATURE_SETS, compute_features
    from .io_tables import read_table, write_table
    from .report_utils import md_table
    from .split import assign_split, check_disjoint, season_split, split_table

    cfg = load_config(args.config)
    states = read_table(cfg, cfg.io.processed_dir, "chase_states")
    feats = compute_features(states, cfg.rules)
    mapping = season_split(feats["season"].unique(), cfg.split)
    feats["split"] = assign_split(feats, mapping)
    check_disjoint(feats)
    write_table(cfg, feats, cfg.io.processed_dir, "chase_features")
    # exact split of every kept chase, committed with the reports so graders can check it
    chases = read_table(cfg, cfg.io.processed_dir, "chases")
    chases["split"] = assign_split(chases, mapping)
    chases[["match_id", "date", "season", "split", "batting_team", "bowling_team", "target",
            "final_runs", "final_wickets", "chase_won"]].assign(
        date=lambda d: d["date"].astype(str).str[:10]).to_csv(
        cfg.io.reports_dir / "splits.csv", index=False)
    manifest = {"feature_sets": FEATURE_SETS, "split_seasons": {
        sp: sorted(int(s) for s, v in mapping.items() if v == sp) for sp in ("train", "val", "test")}}
    (cfg.io.processed_dir / "feature_manifest.json").write_text(json.dumps(manifest, indent=2),
                                                                 encoding="utf-8")

    table = split_table(feats)
    sp = manifest["split_seasons"]
    ip_train = [s for s in sp["train"] if s >= IMPACT_PLAYER_FROM]
    note = (f"Validation = {', '.join(map(str, sp['val']))}; test = "
            f"{', '.join(map(str, sp['test']))}. The Impact Player rule applies from "
            f"{IMPACT_PLAYER_FROM}, so validation and test are entirely in that era, while training "
            + (f"includes only {len(ip_train)} such season(s) ({', '.join(map(str, ip_train))}) "
               f"out of {len(sp['train'])}." if ip_train else "has none.")
            + " Higher scoring in that era is the main drift risk; it is checked in the results "
              "(design 11.5).")
    section = "\n".join([SPLIT_MARKER, "", "## Season split", "", md_table(table), "", note,
                         "", "Match ids are disjoint across splits (asserted).", ""])
    dq = cfg.io.reports_dir / "data_quality.md"
    text = dq.read_text(encoding="utf-8")
    if SPLIT_MARKER not in text:
        raise RuntimeError(f"{dq} has no split marker; rerun `make data`")
    dq.write_text(text.split(SPLIT_MARKER)[0] + section, encoding="utf-8")
    print(md_table(table))
    print(note)
    return 0


VAL_MARKER = "<!-- tuning section: written by the tune stage -->"


def _fmt(v, nd=4):
    return f"{v:.{nd}f}"


def run_baseline(args: argparse.Namespace) -> int:
    """Fit the lookup table on train model rows, score validation; test rows are never read."""
    from .baseline import LookupBaseline, level_shares
    from .io_tables import read_dev_features
    from .metrics import brier, ece, log_loss
    from .report_utils import md_table

    import pandas as pd

    cfg = load_config(args.config)
    f = read_dev_features(cfg)
    train = f[(f["split"] == "train") & f["is_model_row"]]
    val = f[(f["split"] == "val") & f["is_model_row"]]
    assert (train["split"] != "test").all() and (val["split"] != "test").all()
    bl = LookupBaseline(cfg.baseline).fit(train)
    bl.to_json(cfg.io.models_dir / "baseline_trainonly.json")
    rows = []
    for name, part in (("train", train), ("val", val)):
        p, lvl = bl.predict(part)
        sh = level_shares(lvl)
        rows.append({"split": name, "rows": len(part), "brier": _fmt(brier(p, part["y"])),
                     "log_loss": _fmt(log_loss(p, part["y"], cfg.eval.logloss_eps)),
                     "ece": _fmt(ece(p, part["y"], cfg.eval.calibration_bins)),
                     **{f"level_{k}": f"{100 * v:.1f}%" for k, v in sh.items()}})
    t = pd.DataFrame(rows)
    n_buckets = {lvl: sum(1 for k, (_, n) in bl.table.items()
                          if k.startswith(lvl + "|") and n >= cfg.baseline.min_count)
                 for lvl in ("A", "B", "C")}
    text = "\n".join([
        "# Validation results",
        "",
        "Everything here uses training and validation seasons only; test seasons are never read "
        "by `make baseline` or `make tune`.",
        "",
        "## Baseline (lookup table fit on train)",
        "",
        f"Fit on {bl.fitted_on['rows']:,} train model rows ({bl.fitted_on['matches']} chases, "
        f"{bl.fitted_on['seasons'][0]}–{bl.fitted_on['seasons'][-1]}). Buckets with at least "
        f"{cfg.baseline.min_count} rows: level A {n_buckets['A']}, B {n_buckets['B']}, "
        f"C {n_buckets['C']}. The train row is in-sample and shown only for reference.",
        "",
        md_table(t),
        "",
        VAL_MARKER,
        "",
    ])
    cfg.io.reports_dir.mkdir(parents=True, exist_ok=True)
    (cfg.io.reports_dir / "validation_results.md").write_text(text, encoding="utf-8")
    print(md_table(t))
    return 0


def run_tune(args: argparse.Namespace) -> int:
    """Tune LR-full, LR-core and GBM on validation; write tuning logs, selection.json, report."""
    import json
    from datetime import datetime, timezone

    import numpy as np

    from .baseline import LookupBaseline
    from .evaluate import (METHOD_LABELS, PHASES, breakdown, calibration, drift, drift_sentence,
                           method_metrics, pairwise_bss)
    from .features import BASE7, BASE7_E, CORE, start_state_rows
    from .io_tables import read_dev_features
    from .models import fit_chosen, predict_p, tune_gbm, tune_lr
    from .report_utils import md_table

    import pandas as pd

    cfg = load_config(args.config)
    f = read_dev_features(cfg)
    train = f[(f["split"] == "train") & f["is_model_row"]].reset_index(drop=True)
    val = f[(f["split"] == "val") & f["is_model_row"]].reset_index(drop=True)
    assert not (set(train["split"]) | set(val["split"])) & {"test"}
    bl_path = cfg.io.models_dir / "baseline_trainonly.json"
    if not bl_path.exists():
        raise FileNotFoundError("run `make baseline` first")
    bl = LookupBaseline.from_json(bl_path, cfg.baseline)
    rep = cfg.io.reports_dir

    print("Tuning LR-full ...")
    lr_full_log, lr_full = tune_lr(train, val, {"BASE7": BASE7, "BASE7_E": BASE7_E}, cfg)
    print("Tuning LR-core ...")
    lr_core_log, lr_core = tune_lr(train, val, {"CORE": CORE}, cfg)
    print("Tuning GBM ...")
    gbm_log, gbm, gbm_notes = tune_gbm(train, val, cfg)
    lr_full_log.to_csv(rep / "tuning_lr_full.csv", index=False)
    lr_core_log.to_csv(rep / "tuning_lr_core.csv", index=False)
    gbm_log.to_csv(rep / "tuning_gbm.csv", index=False)

    chosen = {"lr_full": lr_full, "lr_core": lr_core, "gbm": gbm}
    for k, v in chosen.items():
        (cfg.io.models_dir / f"{k}_best_params.json").write_text(json.dumps(v, indent=2),
                                                                  encoding="utf-8")

    # Validation predictions with the chosen settings (fit on train only)
    models = {k: fit_chosen(k, v, train, cfg) for k, v in chosen.items()}
    preds = {"baseline": bl.predict(val)[0]}
    for k, m in models.items():
        preds[k] = predict_p(m, val[chosen[k]["features"]].to_numpy(float))
    met = method_metrics(val, preds, cfg)
    gbm_vs_lr = pairwise_bss(val, preds["gbm"], preds["lr_full"], "GBM", "LR-full", cfg)
    best_model = "gbm" if met["gbm"]["brier"] < met["lr_full"]["brier"] else "lr_full"
    phase = breakdown(val, preds, "phase", cfg, order=PHASES)
    calib = calibration(val, preds, cfg)

    per_match = val.groupby("match_id", sort=False).first().reset_index()
    start = start_state_rows(per_match, cfg.rules)
    p_start = predict_p(models[best_model], start[chosen[best_model]["features"]].to_numpy(float))
    dr = drift(val, preds[best_model], start, p_start)

    selection = {
        "best_model": best_model,
        "rule": "lower validation Brier of LR-full and GBM",
        "validation": {k: {kk: vv for kk, vv in v.items() if kk != "verdict"} for k, v in met.items()},
        "chosen_params": chosen,
        "train_seasons": sorted(int(s) for s in train["season"].unique()),
        "val_seasons": sorted(int(s) for s in val["season"].unique()),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (cfg.io.models_dir / "selection.json").write_text(json.dumps(selection, indent=2),
                                                       encoding="utf-8")
    (rep / "validation_metrics.json").write_text(json.dumps({
        "methods": met, "gbm_vs_lr_full": gbm_vs_lr, "phase": phase, "calibration": calib,
        "drift": dr, "best_model": best_model}, indent=2, default=float), encoding="utf-8")

    # ---- report ----
    def hl_table(log_df, keys):
        g = log_df.copy()
        g["half_life"] = g["half_life"].map(lambda h: "uniform" if pd.isna(h) else f"{h:g}")
        return (g.sort_values("val_brier").groupby(keys, sort=False).head(1)
                .sort_values(keys)[keys + ["val_brier", "val_log_loss"]]
                .assign(val_brier=lambda d: d.val_brier.map(lambda v: f"{v:.5f}"),
                        val_log_loss=lambda d: d.val_log_loss.map(lambda v: f"{v:.5f}")))

    def params_text(k):
        v = chosen[k]
        hl = "uniform weights" if v["half_life"] is None else f"half-life {v['half_life']:g} seasons"
        if k == "gbm":
            return (f"learning_rate {v['learning_rate']}, max_leaf_nodes {v['max_leaf_nodes']}, "
                    f"min_samples_leaf {v['min_samples_leaf']}, l2 {v['l2_regularization']}, "
                    f"max_iter {v['max_iter']}, monotonic {v['monotonic']}, {hl}")
        return f"feature set {v['feature_set']}, C {v['C']}, {hl}"

    mt = pd.DataFrame([{
        "method": METHOD_LABELS[k], "brier": _fmt(v["brier"]), "log_loss": _fmt(v["log_loss"]),
        "ece": _fmt(v["ece"]),
        "bss_vs_baseline": "" if k == "baseline" else
        f"{v['bss']:.3f} [{v['bss_ci'][0]:.3f}, {v['bss_ci'][1]:.3f}]"} for k, v in met.items()])
    ph = pd.DataFrame([{"phase": e["phase"], "rows": e["n_rows"],
                        **{f"brier {METHOD_LABELS[k]}": _fmt(e[f"brier_{k}"]) for k in preds},
                        **{f"BSS {METHOD_LABELS[k]}": f"{e[f'bss_{k}']:.3f} [{e[f'bss_ci_{k}'][0]:.3f}, "
                           f"{e[f'bss_ci_{k}'][1]:.3f}]" for k in preds if k != "baseline"}}
                       for e in phase])
    cal_rows = []
    for k, bins in calib.items():
        for b in bins:
            if b["n"]:
                cal_rows.append({"method": METHOD_LABELS[k], "bin": f"{b['lo']:.1f}–{b['hi']:.1f}",
                                 "n": b["n"], "mean_p": f"{b['mean_p']:.3f}",
                                 "observed": f"{b['observed_rate']:.3f}"})
    recency_lines = []
    for k, lg in (("lr_full", lr_full_log), ("lr_core", lr_core_log), ("gbm", gbm_log)):
        uni = lg[lg["half_life"].isna()]["val_brier"].min()
        best_w = lg[lg["half_life"].notna()].sort_values("val_brier").iloc[0]
        recency_lines.append(
            f"- {METHOD_LABELS[k]}: best uniform {uni:.5f}; best weighted {best_w['val_brier']:.5f} "
            f"(half-life {best_w['half_life']:g}). Chosen: "
            + ("uniform." if chosen[k]["half_life"] is None else
               f"half-life {chosen[k]['half_life']:g}."))

    section = "\n".join([
        VAL_MARKER, "",
        "## Recency weighting (decision D8)",
        "",
        "Training rows are weighted 0.5 ** ((latest train season − season) / half-life), "
        "normalised to mean 1, to let the models lean towards the Impact Player era (2023 on). "
        f"Half-lives tried: {['uniform' if h is None else h for h in cfg.recency.half_life_grid]}. "
        "Lowest validation Brier per model:",
        "",
        *recency_lines,
        "",
        "## Chosen settings",
        "",
        *[f"- {METHOD_LABELS[k]}: {params_text(k)}." for k in chosen],
        "",
        "## Validation metrics (fit on train, scored on validation model rows)",
        "",
        f"{len(val):,} rows from {val['match_id'].nunique()} chases. BSS intervals: "
        f"{cfg.eval.n_bootstrap} bootstrap resamples of whole matches.",
        "",
        md_table(mt),
        "",
        *[f"- {v['verdict']}" for k, v in met.items() if k != "baseline"],
        f"- GBM vs LR-full: {gbm_vs_lr['verdict']}",
        "",
        f"**Best model for the website: {METHOD_LABELS[best_model]}** (lower validation Brier of "
        "LR-full and GBM). Written to `models/selection.json` before any test scoring.",
        "",
        "## By phase (validation)",
        "",
        md_table(ph),
        "",
        "## Drift check (validation season, best model)",
        "",
        *[f"- {drift_sentence(d, METHOD_LABELS[best_model])}" for d in dr],
        "",
        "## Calibration (validation, 10 equal-width bins)",
        "",
        md_table(pd.DataFrame(cal_rows)),
        "",
        "## Tuning summaries",
        "",
        "LR-full, best C per feature set and half-life:",
        "",
        md_table(hl_table(lr_full_log, ["feature_set", "half_life"])),
        "",
        "LR-core, best C per half-life:",
        "",
        md_table(hl_table(lr_core_log, ["half_life"])),
        "",
        "GBM:",
        "",
        *[f"- {n}" for n in gbm_notes],
        "",
        "Top 10 GBM fits by validation Brier:",
        "",
        md_table(gbm_log.sort_values("val_brier").head(10)
                 .assign(half_life=lambda d: d.half_life.map(lambda h: "uniform" if pd.isna(h) else f"{h:g}"),
                         val_brier=lambda d: d.val_brier.map(lambda v: f"{v:.5f}"),
                         val_log_loss=lambda d: d.val_log_loss.map(lambda v: f"{v:.5f}"))),
        "",
        "Full logs: `reports/tuning_lr_full.csv`, `reports/tuning_lr_core.csv`, "
        "`reports/tuning_gbm.csv`.",
        "",
    ])
    vr = rep / "validation_results.md"
    text = vr.read_text(encoding="utf-8")
    if VAL_MARKER not in text:
        raise RuntimeError("validation_results.md has no tuning marker; rerun `make baseline`")
    vr.write_text(text.split(VAL_MARKER)[0] + section, encoding="utf-8")
    print(md_table(mt))
    print(f"Best model: {best_model}")
    return 0


def run_final(args: argparse.Namespace) -> int:
    """Refit on train + validation with the settings in selection.json, score test ONCE."""
    import json

    import joblib
    import numpy as np
    import pandas as pd

    from . import plots
    from .baseline import LookupBaseline, level_shares
    from .config import REPO_ROOT
    from .evaluate import (METHOD_LABELS, PHASES, breakdown, calibration, drift, drift_sentence,
                           failure_cases, match_swings, method_metrics, pairwise_bss, round_floats)
    from .features import start_state_rows
    from .io_lock import LockError, acquire_test_lock
    from .io_tables import read_table, write_table
    from .metrics import brier
    from .models import fit_chosen, predict_p
    from .report_utils import md_table
    from .split import split_table

    cfg = load_config(args.config)
    rep, mdir = cfg.io.reports_dir, cfg.io.models_dir
    sel_path = mdir / "selection.json"
    if not sel_path.exists():
        raise FileNotFoundError("models/selection.json missing; run `make tune` first")
    selection = json.loads(sel_path.read_text(encoding="utf-8"))
    best = selection["best_model"]          # read, never recomputed (design 10.3)
    other = "lr_full" if best == "gbm" else "gbm"
    timing_keys = {"fit_seconds", "n_iter"}   # run-dependent; never written to metrics.json
    chosen = {k: {kk: vv for kk, vv in v.items() if kk not in timing_keys}
              for k, v in selection["chosen_params"].items()}
    val_metrics = json.loads((rep / "validation_metrics.json").read_text(encoding="utf-8"))

    f = read_table(cfg, cfg.io.processed_dir, "chase_features")
    chases = read_table(cfg, cfg.io.processed_dir, "chases")
    dev = f[f["split"].isin(["train", "val"]) & f["is_model_row"]].reset_index(drop=True)

    # 1. refit everything on train + validation (no test rows involved)
    bl = LookupBaseline(cfg.baseline).fit(dev)
    bl.to_json(mdir / "baseline_final.json")
    models = {k: fit_chosen(k, chosen[k], dev, cfg) for k in ("lr_full", "lr_core", "gbm")}
    for k, m in models.items():
        joblib.dump(m, mdir / f"{k}_final.joblib")
    print(f"Refit on {len(dev):,} train+val model rows ({dev['match_id'].nunique()} chases).")

    # 2. test lock, then score test once
    try:
        acquire_test_lock(rep / "TEST_LOCK.json", cfg.sha256, selection, REPO_ROOT,
                          force=getattr(args, "force", False), reason=getattr(args, "reason", None))
    except LockError as e:
        print(f"ABORTED: {e}")
        return 3
    test_all = f[f["split"] == "test"].reset_index(drop=True)
    test = test_all[test_all["is_model_row"]].reset_index(drop=True)

    def predict_all(rows):
        out = {"baseline": bl.predict(rows)[0]}
        for k, m in models.items():
            out[k] = predict_p(m, rows[chosen[k]["features"]].to_numpy(float))
        return out

    preds = predict_all(test)
    levels = bl.predict(test)[1]
    met = method_metrics(test, preds, cfg)
    gbm_vs_lr = pairwise_bss(test, preds["gbm"], preds["lr_full"], "GBM", "LR-full", cfg)
    phase = breakdown(test, preds, "phase", cfg, order=PHASES)
    season = breakdown(test, preds, "season", cfg)
    calib = calibration(test, preds, cfg)

    # all rows (terminal rows use the rule-based outcome), secondary metric
    term = test_all[~test_all["is_model_row"]]
    all_rows_brier = {k: brier(np.concatenate([p, term["terminal_p"].to_numpy()]),
                               np.concatenate([test["y"].to_numpy(), term["y"].to_numpy()]))
                      for k, p in preds.items()}

    # drift: validation season from the tune stage (train-only model), test seasons here
    per_match = test.groupby("match_id", sort=False).first().reset_index()
    start = start_state_rows(per_match, cfg.rules)
    start_preds = predict_all(start)
    dr_test = drift(test, preds[best], start, start_preds[best])
    dr = ([{**d, "role": "validation"} for d in val_metrics["drift"]]
          + [{**d, "role": "test"} for d in dr_test])

    fails = failure_cases(test, preds, best, chases, cfg.eval.n_failure_cases)
    swings = match_swings(test, preds[best], chases)
    featured = str(swings.iloc[0]["match_id"])

    # per-row predictions for the export stage (terminal rows carry the rule outcome)
    out = test_all[["match_id", "seq"]].copy()
    tp = test_all["terminal_p"].to_numpy()
    mrow = test_all["is_model_row"].to_numpy()
    for k in preds:
        col = np.where(mrow, np.nan, tp)
        col[mrow] = preds[k]
        out[f"p_{k}"] = col
    lv = np.full(len(out), "terminal", dtype=object)
    lv[mrow] = levels
    out["baseline_level"] = lv
    write_table(cfg, out, cfg.io.processed_dir, "test_predictions")
    sp = start[["match_id"]].copy()
    for k in start_preds:
        sp[f"p_{k}"] = start_preds[k]
    write_table(cfg, sp, cfg.io.processed_dir, "test_start_predictions")

    # 3. metrics.json (no timestamps, floats rounded -> byte-stable)
    excl = pd.read_csv(rep / "exclusions.csv")
    manifest = json.loads((cfg.io.processed_dir / "feature_manifest.json").read_text(encoding="utf-8"))
    metrics = round_floats({
        "best_model": best,
        "other_model": other,
        "featured_match_id": featured,
        "splits": {"seasons": manifest["split_seasons"],
                   "table": split_table(f).to_dict("records")},
        "exclusions": excl["reason"].value_counts().sort_index().to_dict(),
        "methods": {k: {"label": METHOD_LABELS[k]} for k in preds},
        "chosen_params": chosen,
        "test": met,
        "test_all_rows_brier": all_rows_brier,
        "test_gbm_vs_lr_full": gbm_vs_lr,
        "validation": val_metrics["methods"],
        "validation_gbm_vs_lr_full": val_metrics["gbm_vs_lr_full"],
        "calibration": {"test": calib, "validation": val_metrics["calibration"]},
        "phase": phase,
        "season": season,
        "drift": dr,
        "failure_cases": fails,
        "baseline_levels": level_shares(levels),
        "counts": {"test_rows": int(len(test_all)), "test_model_rows": int(len(test)),
                   "test_terminal_rows": int(len(term)), "test_matches": int(test_all["match_id"].nunique()),
                   "fit_rows": int(len(dev)), "fit_matches": int(dev["match_id"].nunique())},
    })
    (rep / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=False) + "\n",
                                      encoding="utf-8")

    # 4. figures
    fig = rep / "figures"
    plots.calibration_plot(calib, fig / "calibration_test.png", "Calibration on test seasons")
    entries = [(f"{METHOD_LABELS[k]} vs baseline", met[k]["bss"], met[k]["bss_ci"])
               for k in ("lr_core", "lr_full", "gbm")]
    entries.append(("GBM vs LR-full", gbm_vs_lr["bss"], gbm_vs_lr["ci"]))
    plots.bss_interval_plot(entries, fig / "bss_intervals_test.png", "Skill on test seasons")
    plots.phase_brier_plot(phase, list(preds), fig / "phase_brier_test.png", "Brier by phase (test)")
    plots.drift_plot(dr, fig / "season_drift.png", METHOD_LABELS[best])
    fm = test_all[test_all["match_id"] == featured].reset_index(drop=True)
    fo = out[out["match_id"] == featured].reset_index(drop=True)
    balls = pd.DataFrame({"i": np.arange(1, len(fm) + 1), "p_base": fo["p_baseline"],
                          "p_model": fo[f"p_{best}"], "wicket": fm["is_wicket_ball"],
                          "over_idx": fm["over_idx"]})
    c = chases.set_index("match_id").loc[featured]
    plots.replay_plot(balls, fig / f"example_replay_{featured}.png",
                      f"{c['batting_team']} chasing {int(c['target'])} v {c['bowling_team']}, "
                      f"{pd.Timestamp(c['date']).date()}", METHOD_LABELS[best])

    # 5. results.md
    def ci(v):
        return f"{v['bss']:.3f} [{v['bss_ci'][0]:.3f}, {v['bss_ci'][1]:.3f}]"

    mt = pd.DataFrame([{"method": METHOD_LABELS[k], "brier": _fmt(v["brier"]),
                        "log_loss": _fmt(v["log_loss"]), "ece": _fmt(v["ece"]),
                        "bss_vs_baseline [95% CI]": "" if k == "baseline" else ci(v),
                        "brier_all_rows": _fmt(all_rows_brier[k])} for k, v in met.items()])

    def bd_table(entries_, key):
        return pd.DataFrame([{key: e[key], "rows": e["n_rows"], "chases": e["n_matches"],
                              **{f"brier {METHOD_LABELS[k]}": _fmt(e[f"brier_{k}"]) for k in preds},
                              **{f"BSS {METHOD_LABELS[k]}": f"{e[f'bss_{k}']:.3f} [{e[f'bss_ci_{k}'][0]:.3f}, "
                                 f"{e[f'bss_ci_{k}'][1]:.3f}]" for k in preds if k != "baseline"}}
                             for e in entries_])

    val_tbl = pd.DataFrame([{"method": METHOD_LABELS[k], "val brier": _fmt(v["brier"]),
                             "test brier": _fmt(met[k]["brier"]),
                             "val ece": _fmt(v["ece"]), "test ece": _fmt(met[k]["ece"])}
                            for k, v in val_metrics["methods"].items()])
    ex_tbl = excl["reason"].value_counts().rename_axis("reason").reset_index(name="matches")
    lv_tbl = pd.DataFrame([{"level": k, "share of test rows": f"{100 * v:.1f}%"}
                           for k, v in level_shares(levels).items()])
    sp = manifest["split_seasons"]
    text = "\n".join([
        "# Results (test seasons, scored once)",
        "",
        f"Models were refit on train + validation ({sp['train'][0]}–{sp['val'][-1]}, "
        f"{dev['match_id'].nunique()} chases, {len(dev):,} model rows) with the settings chosen on "
        f"validation, then scored once on the test seasons {', '.join(map(str, sp['test']))} "
        f"({test_all['match_id'].nunique()} chases, {len(test):,} model rows; {len(term)} terminal "
        "rows excluded from the main metrics). See `reports/TEST_LOCK.json`.",
        "",
        f"Best model for the website (chosen on validation before this run): "
        f"**{METHOD_LABELS[best]}**.",
        "",
        "## Verdicts",
        "",
        *[f"- {met[k]['verdict']}" for k in ("lr_full", "lr_core", "gbm")],
        f"- GBM vs LR-full: {gbm_vs_lr['verdict']}",
        "",
        "## Test metrics",
        "",
        f"Model rows only. BSS intervals: {cfg.eval.n_bootstrap} bootstrap resamples of whole test "
        "matches, the same resamples for every method. `brier_all_rows` adds the terminal rows, "
        "scored with their rule-based outcome, for comparison with sources that include them.",
        "",
        md_table(mt),
        "",
        "Validation vs test:",
        "",
        md_table(val_tbl),
        "",
        "## By phase",
        "",
        md_table(bd_table(phase, "phase")),
        "",
        "## By test season",
        "",
        md_table(bd_table(season, "season")),
        "",
        "## Drift check",
        "",
        "Validation uses the train-only model from the tune stage; test seasons use the final "
        "model.",
        "",
        *[f"- ({d['role']}) {drift_sentence(d, METHOD_LABELS[best])}" for d in dr],
        "",
        "## Failure cases",
        "",
        f"Test chases where {METHOD_LABELS[best]}'s match-level Brier most exceeds the baseline's:",
        "",
        *[f"- `{e['match_id']}`: {e['explanation']}" for e in fails["worst_vs_baseline"]],
        "",
        f"Biggest upsets (lowest probability {METHOD_LABELS[best]} gave the eventual winner at any "
        "model row):",
        "",
        *[f"- `{e['match_id']}`: {e['explanation']}" for e in fails["biggest_upsets"]],
        "",
        f"Featured match for the website (largest swing in {METHOD_LABELS[best]}'s probability): "
        f"`{featured}` (swing {swings.iloc[0]['swing']:.3f}).",
        "",
        "## Baseline level usage on test",
        "",
        md_table(lv_tbl),
        "",
        "## Exclusions",
        "",
        md_table(ex_tbl),
        "",
        "## Limitations",
        "",
        "The estimates describe historical IPL chases with a full 20-over target only: not first "
        "innings, not DLS or shortened matches, not ties or no-results. Inputs are the scoreboard "
        "state only (runs needed, balls left, wickets left, target, required rate, last-18-ball "
        "runs and wickets); team strength, venue, players and conditions are ignored, so the "
        "probabilities are league-average and say nothing about why teams win. Validation is a "
        "single season of about 70 chases, so tuning choices are noisy. The validation and test "
        "seasons fall in the Impact Player era, which is barely represented in training; recency "
        "weighting (D8) reduces but does not remove the drift reported above. This is not a "
        "betting tool.",
        "",
        "Figures: `reports/figures/`.",
        "",
    ])
    (rep / "results.md").write_text(text, encoding="utf-8")
    print(md_table(mt))
    for k in ("lr_full", "lr_core", "gbm"):
        print(met[k]["verdict"])
    print(f"GBM vs LR-full: {gbm_vs_lr['verdict']}")
    return 0


def run_export(args: argparse.Namespace) -> int:
    """Write and validate the website JSON in docs/data/ (no model fitting)."""
    from .export import export_site

    cfg = load_config(args.config)
    info = export_site(cfg)
    print(f"Exported {info['matches']} chases to {cfg.io.site_data_dir} "
          f"({info['bytes'] / 1e6:.2f} MB); featured {info['featured']}. All files validated.")
    return 0


HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {s: _not_implemented(s) for s in STAGES}
HANDLERS["features"] = run_features
HANDLERS["export"] = run_export
HANDLERS["final"] = run_final
HANDLERS["baseline"] = run_baseline
HANDLERS["tune"] = run_tune
HANDLERS["profile"] = run_profile
HANDLERS["data"] = run_data


def run_all(args: argparse.Namespace) -> int:
    for s in STAGES:
        print(f"== {s} ==")
        rc = HANDLERS[s](args)
        if rc != 0:
            return rc
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m iplwp.cli",
                                description="IPL win probability pipeline stages.")
    p.add_argument("--config", default=None, help="path to config.yaml (default config/config.yaml)")
    sub = p.add_subparsers(dest="stage", required=True, metavar="stage")
    helps = {
        "profile": "inspect raw files, write reports/data_profile.md",
        "data": "adapt + clean + reconstruct chase states",
        "features": "leakage-safe features and season split",
        "baseline": "lookup-table baseline on train, scored on validation",
        "tune": "tune LR and GBM on validation seasons only",
        "final": "refit on train+val, evaluate test once",
        "export": "write website JSON into docs/data/",
        "all": "run every stage above in order",
    }
    for s in STAGES + ["all"]:
        sp = sub.add_parser(s, help=helps[s])
        if s in ("final", "all"):
            sp.add_argument("--force", action="store_true", help="rerun test scoring despite lock")
            sp.add_argument("--reason", default=None, help="required with --force")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.stage == "all":
        return run_all(args)
    return HANDLERS[args.stage](args)


if __name__ == "__main__":
    sys.exit(main())
