"""Evaluation helpers shared by the tune (validation) and final (test) stages (design 11).

Every function receives rows of ONE split plus a dict of predicted probabilities per method, and
returns plain tables/dicts. Main metrics use model rows only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .bootstrap import bootstrap_bss, verdict
from .config import Config
from .metrics import brier, calibration_bins, ece, log_loss

METHOD_LABELS = {"baseline": "Baseline", "lr_full": "LR-full", "lr_core": "LR-core", "gbm": "GBM"}
PHASES = ["powerplay", "middle", "death"]


def method_metrics(rows: pd.DataFrame, preds: dict[str, np.ndarray], cfg: Config) -> dict[str, dict]:
    """Per method: Brier, log loss, ECE, and (models only) BSS vs baseline with bootstrap CI."""
    y = rows["y"].to_numpy()
    mid = rows["match_id"].to_numpy()
    e = cfg.eval
    out = {}
    for name, p in preds.items():
        d = {"brier": brier(p, y), "log_loss": log_loss(p, y, e.logloss_eps),
             "ece": ece(p, y, e.calibration_bins), "n_rows": int(len(y)),
             "n_matches": int(rows["match_id"].nunique())}
        if name != "baseline":
            b = bootstrap_bss(mid, y, p, preds["baseline"], e.n_bootstrap, cfg.seed, e.ci)
            d["bss"], d["bss_ci"] = b["bss"], b["ci"]
            d["verdict"] = verdict(METHOD_LABELS[name], b["bss"], b["ci"])
        out[name] = d
    return out


def pairwise_bss(rows: pd.DataFrame, p_model, p_ref, name: str, ref: str, cfg: Config) -> dict:
    b = bootstrap_bss(rows["match_id"].to_numpy(), rows["y"].to_numpy(), p_model, p_ref,
                      cfg.eval.n_bootstrap, cfg.seed, cfg.eval.ci)
    b["verdict"] = verdict(name, b["bss"], b["ci"], reference=ref)
    return b


def breakdown(rows: pd.DataFrame, preds: dict[str, np.ndarray], by: str, cfg: Config,
              order: list | None = None) -> list[dict]:
    """Brier per method and BSS (with CI) vs baseline, per value of column `by`."""
    out = []
    keys = order if order is not None else sorted(rows[by].unique())
    for k in keys:
        m = (rows[by] == k).to_numpy()
        if not m.any():
            continue
        sub = rows[m]
        entry = {by: k if not isinstance(k, np.integer) else int(k), "n_rows": int(m.sum()),
                 "n_matches": int(sub["match_id"].nunique())}
        for name, p in preds.items():
            entry[f"brier_{name}"] = brier(p[m], sub["y"])
        for name, p in preds.items():
            if name == "baseline":
                continue
            b = bootstrap_bss(sub["match_id"].to_numpy(), sub["y"].to_numpy(), p[m],
                              preds["baseline"][m], cfg.eval.n_bootstrap, cfg.seed, cfg.eval.ci)
            entry[f"bss_{name}"], entry[f"bss_ci_{name}"] = b["bss"], b["ci"]
        out.append(entry)
    return out


def calibration(rows: pd.DataFrame, preds: dict[str, np.ndarray], cfg: Config) -> dict[str, list]:
    y = rows["y"].to_numpy()
    return {name: calibration_bins(p, y, cfg.eval.calibration_bins)
            .replace({np.nan: None}).to_dict("records") for name, p in preds.items()}


def drift(rows: pd.DataFrame, p: np.ndarray, start_rows: pd.DataFrame, p_start: np.ndarray) -> list[dict]:
    """Per season (design 11.5): mean predicted vs observed win rate on model rows, and the
    start-of-chase prediction averaged over matches vs the observed chase win rate."""
    out = []
    for s in sorted(rows["season"].unique()):
        m = (rows["season"] == s).to_numpy()
        ms = (start_rows["season"] == s).to_numpy()
        e = {"season": int(s), "mean_p": float(p[m].mean()),
             "observed_rows": float(rows.loc[m, "y"].mean()),
             "start_mean_p": float(p_start[ms].mean()),
             "chase_win_rate": float(start_rows.loc[ms, "y"].mean()),
             "n_matches": int(ms.sum())}
        e["gap_rows"] = e["mean_p"] - e["observed_rows"]
        e["gap_start"] = e["start_mean_p"] - e["chase_win_rate"]
        out.append(e)
    return out


def drift_sentence(d: dict, model_label: str) -> str:
    gap = d["gap_start"] * 100
    word = "over-predicted" if gap > 0 else "under-predicted"
    return (f"In {d['season']} the {model_label} {word} chases by {abs(gap):.1f} points at the "
            f"start of the chase (mean {d['start_mean_p']:.3f} vs observed "
            f"{d['chase_win_rate']:.3f} over {d['n_matches']} chases); over all model rows the "
            f"mean prediction was {d['mean_p']:.3f} vs observed {d['observed_rows']:.3f}.")


def _state_text(r) -> str:
    return (f"needed {int(r.runs_needed)} from {int(r.balls_left)} balls with "
            f"{int(r.wickets_left)} wickets left")


def failure_cases(rows: pd.DataFrame, preds: dict[str, np.ndarray], best: str,
                  chases: pd.DataFrame, n: int) -> dict[str, list[dict]]:
    """Design 11.4. `rows` are test model rows (with label, runs_needed, ...), `chases` has team
    names. Returns {"worst_vs_baseline": [...], "biggest_upsets": [...]}, each entry with
    match_id and a one-line explanation."""
    label = METHOD_LABELS[best]
    df = rows[["match_id", "y", "label", "runs_needed", "balls_left", "wickets_left"]].copy()
    df["p"] = preds[best]
    df["se_m"] = (preds[best] - df["y"]) ** 2
    df["se_b"] = (preds["baseline"] - df["y"]) ** 2
    info = chases.set_index("match_id")

    def who(mid):
        c = info.loc[mid]
        res = "won" if c["chase_won"] else "lost"
        return (f"{c['batting_team']} chasing {int(c['target'])} against {c['bowling_team']} "
                f"({pd.Timestamp(c['date']).date()}), {res}")

    g = df.groupby("match_id").agg(bm=("se_m", "mean"), bb=("se_b", "mean"))
    g["diff"] = g["bm"] - g["bb"]
    worst = []
    for mid, r in g.sort_values(["diff"], ascending=False).head(n).iterrows():
        worst.append({"match_id": str(mid), "brier_model": float(r.bm), "brier_baseline": float(r.bb),
                      "explanation": f"{who(mid)}. {label} match Brier {r.bm:.3f} vs baseline "
                                     f"{r.bb:.3f} (+{r['diff']:.3f})."})

    df["p_winner"] = np.where(df["y"] == 1, df["p"], 1 - df["p"])
    idx = df.groupby("match_id")["p_winner"].idxmin()
    low = df.loc[idx].sort_values(["p_winner", "match_id"]).head(n)
    upsets = []
    for r in low.itertuples():
        side = "the chasing team" if r.y == 1 else "the defending team"
        upsets.append({"match_id": str(r.match_id), "min_p_winner": float(r.p_winner),
                       "label": r.label,
                       "explanation": f"{who(r.match_id)}. {label} gave {side} only "
                                      f"{100 * r.p_winner:.1f}% after ball {r.label} "
                                      f"({_state_text(r)})."})
    return {"worst_vs_baseline": worst, "biggest_upsets": upsets}


def match_swings(rows: pd.DataFrame, p: np.ndarray, chases: pd.DataFrame) -> pd.DataFrame:
    """Per match: max p - min p over model rows; featured match = largest swing, tie -> latest."""
    df = pd.DataFrame({"match_id": rows["match_id"].to_numpy(), "p": p})
    s = df.groupby("match_id")["p"].agg(lambda v: v.max() - v.min()).rename("swing").reset_index()
    s = s.merge(chases[["match_id", "date"]], on="match_id")
    return s.sort_values(["swing", "date"], ascending=[False, False]).reset_index(drop=True)


def round_floats(obj, nd: int = 10):
    """Recursively round floats (keeps metrics.json byte-stable across runs)."""
    if isinstance(obj, float):
        return None if np.isnan(obj) else round(obj, nd)
    if isinstance(obj, (np.floating,)):
        return round_floats(float(obj), nd)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, dict):
        return {k: round_floats(v, nd) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_floats(v, nd) for v in obj]
    return obj
