"""Website data export (design section 12).

Reads only outputs of earlier stages: chase_features, chases, the stored test predictions written
by `make final`, reports/metrics.json and the final LR-core model. No model is fit here. Every file
is validated against its JSON schema in `json_schemas/` before the stage reports success.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from jsonschema import Draft202012Validator

from .config import Config
from .evaluate import METHOD_LABELS, round_floats
from .features import CORE, core_terms
from .io_tables import read_table
from .metrics import brier
from .schema import normalise_team

SCHEMA_DIR = Path(__file__).parent / "json_schemas"
METHODS = ["baseline", "lr_full", "lr_core", "gbm"]
EDGE_VECTORS = [(1, 1, 1), (300, 120, 10), (1, 120, 10), (300, 1, 1)]


class ExportValidationError(Exception):
    """A website JSON file does not match its schema, contains NaN, or the data is too large."""


def validate(obj: dict, schema_name: str, label: str) -> None:
    """Raise ExportValidationError naming `label` and the JSON path of the first schema error."""
    schema = json.loads((SCHEMA_DIR / f"{schema_name}.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(obj), key=lambda e: list(map(str, e.absolute_path)))
    if errors:
        e = errors[0]
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        raise ExportValidationError(f"{label}: {e.message} at {where} ({len(errors)} error(s))")


def _write(obj: dict, path: Path, compact: bool) -> None:
    text = json.dumps(obj, ensure_ascii=False, allow_nan=False,
                      **({"separators": (",", ":")} if compact else {"indent": 1}))
    path.write_text(text + "\n", encoding="utf-8")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def result_text(c: pd.Series, wickets: int) -> str:
    """'<team> won by N wickets' for a successful chase, '<team> won by N runs' otherwise."""
    if int(c["chase_won"]):
        return (f"{normalise_team(c['batting_team'])} won by "
                f"{_plural(wickets - int(c['final_wickets']), 'wicket')}")
    return (f"{normalise_team(c['bowling_team'])} won by "
            f"{_plural(int(c['target']) - 1 - int(c['final_runs']), 'run')}")


def _venue(v) -> str | None:
    return None if v is None or pd.isna(v) else str(v)


def _method_descriptions(chosen: dict) -> dict[str, dict[str, str]]:
    def weighting(k):
        hl = chosen[k]["half_life"]
        return ("All training seasons weighted equally." if hl is None else
                f"Recent seasons weighted more (weight halves every {hl:g} seasons back).")

    lr_feats = ("the seven scoreboard features" if chosen["lr_full"]["feature_set"] == "BASE7" else
                "the seven scoreboard features plus four terms derived from them (log runs "
                "needed, log balls left, required rate times wickets, runs per wicket)")
    return {
        "baseline": {"label": METHOD_LABELS["baseline"], "description":
                     "Historical lookup table: the share of training chases that were won from the "
                     "same band of runs needed, balls left and wickets left, with coarser "
                     "fallbacks for rare states. No machine learning."},
        "lr_full": {"label": METHOD_LABELS["lr_full"], "description":
                    f"Logistic regression on {lr_feats}. {weighting('lr_full')}"},
        "lr_core": {"label": METHOD_LABELS["lr_core"], "description":
                    "Logistic regression on runs needed, balls left and wickets left only (plus "
                    f"terms computed from those three). Used by the what-if calculator. "
                    f"{weighting('lr_core')}"},
        "gbm": {"label": METHOD_LABELS["gbm"], "description":
                "Gradient-boosted decision trees (scikit-learn HistGradientBoostingClassifier) on "
                f"the seven scoreboard features. {weighting('gbm')}"},
    }


def target_bins(rows: pd.DataFrame, edges: tuple[int, ...]) -> list[dict]:
    """Post-test diagnosis: chase win rate and each method's mean prediction and Brier by target."""
    labels = ([f"up to {edges[0]}"] + [f"{a + 1}–{b}" for a, b in zip(edges[:-1], edges[1:])]
              + [f"over {edges[-1]}"])
    b = np.digitize(rows["target"].to_numpy(), np.asarray(edges), right=True)
    out = []
    for k, lab in enumerate(labels):
        m = b == k
        if not m.any():
            continue
        sub = rows[m]
        e = {"target_band": lab, "n_rows": int(m.sum()), "n_matches": int(sub["match_id"].nunique()),
             "chase_win_rate": float(sub.groupby("match_id")["y"].first().mean())}
        for meth in METHODS:
            e[f"mean_p_{meth}"] = float(sub[f"p_{meth}"].mean())
            e[f"brier_{meth}"] = brier(sub[f"p_{meth}"], sub["y"])
        out.append(e)
    return out


def build_lr_core(cfg: Config, metrics: dict) -> dict:
    """Coefficients of the final LR-core pipeline plus parity vectors computed by scikit-learn."""
    feats = metrics["chosen_params"]["lr_core"]["features"]
    if list(feats) != CORE:
        raise ExportValidationError(f"LR-core features {feats} differ from CORE {CORE}")
    model = joblib.load(cfg.io.models_dir / "lr_core_final.joblib")
    sc, lr = model.named_steps["scale"], model.named_steps["lr"]
    rng = np.random.default_rng(cfg.seed)
    n_rand = cfg.export.n_parity_vectors - len(EDGE_VECTORS)
    max_r, max_b, max_w = cfg.export.calculator_max_runs, cfg.rules.balls_per_innings, cfg.rules.wickets
    r = np.concatenate([[e[0] for e in EDGE_VECTORS], rng.integers(1, max_r + 1, n_rand)])
    b = np.concatenate([[e[1] for e in EDGE_VECTORS], rng.integers(1, max_b + 1, n_rand)])
    w = np.concatenate([[e[2] for e in EDGE_VECTORS], rng.integers(1, max_w + 1, n_rand)])
    terms = core_terms(r, b, w, cfg.rules.rrr_clip)
    X = np.column_stack([terms[c] for c in CORE])
    p = model.predict_proba(X)[:, 1]
    z = lr.intercept_[0] + ((X - sc.mean_) / sc.scale_) @ lr.coef_[0]
    if np.max(np.abs(1 / (1 + np.exp(-z)) - p)) > 1e-12:
        raise ExportValidationError("exported LR-core coefficients do not reproduce predict_proba")
    t = metrics["test"]["lr_core"]
    return {
        "feature_order": CORE,
        "rrr_clip": cfg.rules.rrr_clip,
        "scaler_mean": [float(v) for v in sc.mean_],
        "scaler_scale": [float(v) for v in sc.scale_],
        "coef": [float(v) for v in lr.coef_[0]],
        "intercept": float(lr.intercept_[0]),
        "half_life": metrics["chosen_params"]["lr_core"]["half_life"],
        "input_ranges": {"runs_needed": [1, max_r], "balls_left": [1, max_b],
                         "wickets_left": [1, max_w]},
        "test_metrics": {"brier": t["brier"], "bss": t["bss"], "bss_ci": t["bss_ci"]},
        "test_vectors": [{"runs_needed": int(a), "balls_left": int(bb), "wickets_left": int(c),
                          "p": float(pp)} for a, bb, c, pp in zip(r, b, w, p)],
    }


def export_site(cfg: Config) -> dict:
    """Write and validate docs/data/{matches.json, matches/<id>.json, results.json, lr_core.json}."""
    out_dir = cfg.io.site_data_dir
    match_dir = out_dir / "matches"
    match_dir.mkdir(parents=True, exist_ok=True)
    nd = cfg.export.prob_decimals
    metrics = json.loads((cfg.io.reports_dir / "metrics.json").read_text(encoding="utf-8"))
    best, other = metrics["best_model"], metrics["other_model"]

    feats = read_table(cfg, cfg.io.processed_dir, "chase_features")
    preds = read_table(cfg, cfg.io.processed_dir, "test_predictions")
    starts = read_table(cfg, cfg.io.processed_dir, "test_start_predictions").set_index("match_id")
    chases = read_table(cfg, cfg.io.processed_dir, "chases").set_index("match_id")
    test = feats[feats["split"] == "test"]
    t = test.merge(preds, on=["match_id", "seq"], how="left", validate="one_to_one")
    pcols = [f"p_{m}" for m in METHODS]
    if t[pcols].isna().any().any():
        raise ExportValidationError("test rows without stored predictions; rerun `make final`")
    t = t.sort_values(["match_id", "seq"]).reset_index(drop=True)
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for old in match_dir.glob("*.json"):
        old.unlink()
    index = []
    for mid, g in t.groupby("match_id", sort=True):
        c = chases.loc[mid]
        y = int(c["chase_won"])
        mrow = g["is_model_row"].to_numpy()
        pb, pm, po = (g[f"p_{k}"].to_numpy() for k in ("baseline", best, other))
        summary = {"brier_baseline": brier(pb[mrow], g["y"][mrow]),
                   "brier_model": brier(pm[mrow], g["y"][mrow]),
                   "brier_other": brier(po[mrow], g["y"][mrow]),
                   "model_closer_share": float(np.mean(np.abs(pm[mrow] - y) < np.abs(pb[mrow] - y)))}
        i = np.arange(1, len(g) + 1)
        ov = pd.DataFrame({"over": g["over_idx"].to_numpy(), "runs": g["runs_total"].to_numpy(), "i": i})
        agg = ov.groupby("over").agg(runs=("runs", "sum"), i_from=("i", "min"), i_to=("i", "max"))
        big = [{"over": int(o) + 1, "runs": int(a.runs), "i_from": int(a.i_from), "i_to": int(a.i_to)}
               for o, a in agg[agg["runs"] >= cfg.rules.big_over_runs].iterrows()]
        balls = [{
            "i": int(k), "label": r.label, "event": r.event,
            "score": f"{int(r.runs_scored)}/{int(r.wickets_fallen)}",
            "runs_needed": max(int(r.runs_needed), 0), "balls_left": int(r.balls_left),
            "wickets_left": int(r.wickets_left), "rrr": round(float(r.rrr), 2),
            "r18": int(r.runs_last18), "w18": int(r.wkts_last18), "phase": r.phase,
            "wicket": bool(r.is_wicket_ball), "terminal": bool(r.is_terminal),
            "p_base": round(float(getattr(r, "p_baseline")), nd),
            "p_model": round(float(getattr(r, f"p_{best}")), nd),
            "p_other": round(float(getattr(r, f"p_{other}")), nd),
        } for k, r in zip(i, g.itertuples(index=False))]
        s = starts.loc[mid]
        head = {"match_id": str(mid), "season": int(c["season"]),
                "date": pd.Timestamp(c["date"]).strftime("%Y-%m-%d"), "venue": _venue(c["venue"]),
                "batting_team": normalise_team(c["batting_team"]),
                "bowling_team": normalise_team(c["bowling_team"]),
                "target": int(c["target"]), "chase_won": y,
                "result_text": result_text(c, cfg.rules.wickets)}
        doc = {**head, "best_model": best, "other_model": other,
               "summary": round_floats(summary, nd),
               "start": {"p_base": round(float(s["p_baseline"]), nd),
                         "p_model": round(float(s[f"p_{best}"]), nd),
                         "p_other": round(float(s[f"p_{other}"]), nd)},
               "big_overs": big, "balls": balls}
        validate(doc, "match", f"matches/{mid}.json")
        _write(doc, match_dir / f"{mid}.json", compact=True)
        index.append({**head, "swing": round(float(pm[mrow].max() - pm[mrow].min()), nd),
                      **{k: round(v, nd) for k, v in summary.items() if k != "model_closer_share"}})

    index.sort(key=lambda e: (e["date"], e["match_id"]), reverse=True)
    matches_doc = {"generated_at": generated, "best_model": best, "other_model": other,
                   "featured_match_id": metrics["featured_match_id"], "matches": index}
    if matches_doc["featured_match_id"] not in {e["match_id"] for e in index}:
        raise ExportValidationError("featured match is not among the exported chases")
    validate(matches_doc, "matches", "matches.json")
    _write(matches_doc, out_dir / "matches.json", compact=False)

    split_rows = metrics["splits"]["table"]
    kept = int(sum(r["matches"] for r in split_rows))
    excluded = int(sum(metrics["exclusions"].values()))
    model_rows = t[t["is_model_row"]]
    results = round_floats({
        "generated_at": generated,
        "best_model": best,
        "other_model": other,
        "featured_match_id": metrics["featured_match_id"],
        "splits": metrics["splits"],
        "exclusions": metrics["exclusions"],
        "cleaning": {"raw_matches": kept + excluded, "kept": kept, "excluded": excluded},
        "methods": _method_descriptions(metrics["chosen_params"]),
        "chosen_params": metrics["chosen_params"],
        "test": metrics["test"],
        "validation": metrics["validation"],
        "test_gbm_vs_lr_full": metrics["test_gbm_vs_lr_full"],
        "validation_gbm_vs_lr_full": metrics["validation_gbm_vs_lr_full"],
        "test_all_rows_brier": metrics["test_all_rows_brier"],
        "calibration": metrics["calibration"],
        "phase": metrics["phase"],
        "season": metrics["season"],
        "drift": metrics["drift"],
        "failure_cases": metrics["failure_cases"],
        "baseline_levels": metrics["baseline_levels"],
        "counts": metrics["counts"],
        "evaluation": {"n_bootstrap": cfg.eval.n_bootstrap, "ci": cfg.eval.ci,
                       "calibration_bins": cfg.eval.calibration_bins,
                       "big_over_runs": cfg.rules.big_over_runs,
                       "momentum_window": cfg.rules.momentum_window_legal_balls,
                       "baseline_min_count": cfg.baseline.min_count},
        "diagnostics": {
            "target_bins": target_bins(model_rows, cfg.export.diagnostic_target_bins),
            "note": "Computed by `make export` from the stored test predictions after the single "
                    "test run, to explain the results. No model was refit or changed.",
        },
    }, 6)
    validate(results, "results", "results.json")
    _write(results, out_dir / "results.json", compact=False)

    lr_core = build_lr_core(cfg, metrics)
    validate(lr_core, "lr_core", "lr_core.json")
    _write(lr_core, out_dir / "lr_core.json", compact=False)

    size = sum(p.stat().st_size for p in out_dir.rglob("*.json"))
    if size > cfg.export.max_site_data_mb * 1024 * 1024:
        raise ExportValidationError(f"docs/data is {size / 1e6:.1f} MB, over the "
                                    f"{cfg.export.max_site_data_mb} MB limit")
    return {"matches": len(index), "bytes": size, "featured": metrics["featured_match_id"]}
