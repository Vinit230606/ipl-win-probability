"""Rare and extreme scoreboard states (post-test addition, `edgecases` stage).

Problem: LR-core is a straight line in log-odds. In states the data never reached (for example
42 needed from 42 balls with 1 wicket left) it extrapolates to probabilities like 0.1%, which the
calculator rounded to "0%". The fix has three parts:

1. Data support. For every state, count the fitting chases that passed through a small cell
   around it (`support_bucket` runs x balls, same wickets left).
2. A second model that does not need to have seen the state: the ball-by-ball simulation
   (simulate.py), recalibrated with Platt scaling on the fitting rows.
3. The calculator blends them, trusting LR-core in proportion to the data:
       p = a * p_LR-core + (1 - a) * p_simulation,   a = n / (n + k),
   then a monotone envelope makes the whole table obey cricket logic (one more run needed, one
   ball fewer or one wicket fewer never raises the chance).

The simulation shrinkage and k are chosen on validation log loss (log loss punishes the
over-confidence being fixed; Brier barely notices it). Fitting uses train for choosing and
train + validation for the website, like every other model. The test seasons had already been
scored when this was added, so test numbers here are a post-test check, not a clean test.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config
from .features import CORE, core_terms
from .metrics import brier, ece, log_loss
from .simulate import SimSpec, calibrate, delivery_table, fit_calibration, fit_outcomes, lookup, solve

SCENARIOS = [
    # (runs needed, balls left, wickets left, why it is interesting)
    (42, 42, 1, "The case that showed the problem: a run a ball, last pair at the crease."),
    (42, 42, 2, "The same chase with one more wicket."),
    (42, 42, 6, "The same chase with a normal number of wickets."),
    (60, 42, 1, "Harder, last wicket."),
    (10, 12, 1, "Last wicket, close to the line."),
    (1, 1, 1, "One run off the last ball, last wicket."),
    (6, 1, 10, "A six needed off the last ball."),
    (20, 6, 10, "Twenty off the last over."),
    (36, 6, 10, "Six sixes needed off the last over."),
    (100, 30, 10, "A big target late, all wickets in hand."),
    (300, 120, 10, "The largest input the calculator allows."),
    (1, 120, 10, "One run needed with the whole innings left."),
]


# ---------------------------------------------------------------------------------------------
# data support
# ---------------------------------------------------------------------------------------------
def support_shape(cfg: Config) -> tuple[int, int, int]:
    s = cfg.simulation
    return (cfg.rules.wickets + 1, cfg.export.calculator_max_runs // s.support_runs + 1,
            (cfg.rules.balls_per_innings - 1) // s.support_balls + 1)


def support_cells(r, b, w, cfg: Config):
    """Cell index (wickets left, runs // support_runs, (balls - 1) // support_balls)."""
    s = cfg.simulation
    rr = np.minimum(np.asarray(r, int), cfg.export.calculator_max_runs) // s.support_runs
    bb = (np.asarray(b, int) - 1) // s.support_balls
    return np.asarray(w, int), rr, bb


def support_grid(rows: pd.DataFrame, cfg: Config) -> tuple[np.ndarray, np.ndarray]:
    """Distinct chases (and how many of them were won) per support cell.

    `rows` are open-state rows of the fitting seasons. A chase counts once per cell.
    """
    w, r, b = support_cells(rows["runs_needed"], rows["balls_left"], rows["wickets_left"], cfg)
    cells = pd.DataFrame({"w": w, "r": r, "b": b, "m": rows["match_id"].to_numpy(),
                          "y": rows["y"].to_numpy(int)}).drop_duplicates(["w", "r", "b", "m"])
    n = np.zeros(support_shape(cfg), int)
    won = np.zeros_like(n)
    np.add.at(n, (cells["w"], cells["r"], cells["b"]), 1)
    np.add.at(won, (cells["w"], cells["r"], cells["b"]), cells["y"])
    return n, won


def support_of(grid: np.ndarray, r, b, w, cfg: Config) -> np.ndarray:
    return grid[support_cells(r, b, w, cfg)]


# ---------------------------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------------------------
def lr_core_p(model, r, b, w, clip: float) -> np.ndarray:
    t = core_terms(r, b, w, clip)
    return model.predict_proba(np.column_stack([t[c] for c in CORE]))[:, 1]


class Simulation:
    """Fitted ball-by-ball model: outcome table P, solved table V, Platt coefficients (a, c)."""

    def __init__(self, P: np.ndarray, V: np.ndarray, a: float, c: float, shrinkage: float):
        self.P, self.V, self.a, self.c, self.shrinkage = P, V, a, c, shrinkage

    @classmethod
    def fit(cls, all_rows: pd.DataFrame, model_rows: pd.DataFrame, spec: SimSpec,
            shrinkage: float) -> "Simulation":
        """`all_rows`: every chase state row of the fitting seasons (one per delivery);
        `model_rows`: the open-state rows, used to fit the Platt calibration."""
        P = fit_outcomes(delivery_table(all_rows, spec), spec, shrinkage)
        V = solve(P, spec)
        raw = lookup(V, model_rows["runs_needed"], model_rows["balls_left"], model_rows["wickets_left"])
        a, c = fit_calibration(raw, model_rows["y"])
        return cls(P, V, a, c, shrinkage)

    def raw(self, r, b, w) -> np.ndarray:
        return lookup(self.V, r, b, w)

    def p(self, r, b, w) -> np.ndarray:
        return calibrate(self.raw(r, b, w), self.a, self.c)


def blend_weight(support, k: float) -> np.ndarray:
    """Weight on LR-core: n / (n + k). No data -> 0 (pure simulation)."""
    n = np.asarray(support, float)
    return n / (n + k)


def monotone_envelope(H: np.ndarray) -> np.ndarray:
    """Make a table H[r, b, w] (r 0..R, b 0..B, w 0..W) obey cricket logic: never higher with
    more runs needed, never lower with more balls or wickets left.

    Upper envelope U, the smallest such table >= H (r descending, b and w ascending):
        U[r,b,w] = max(H[r,b,w], U[r+1,b,w], U[r,b-1,w], U[r,b,w-1]).
    Lower envelope L, the largest such table <= H (r ascending, b and w descending):
        L[r,b,w] = min(H[r,b,w], L[r-1,b,w], L[r,b+1,w], L[r,b,w+1]).
    Result (U + L) / 2: monotone because both are, and it moves H up and down evenly.
    Fixed cells: r = 0 -> 1; b = 0 or w = 0 (with r >= 1) -> 0. docs/assets/js/simulation.js
    runs the same loops.
    """
    R, B, W = H.shape[0] - 1, H.shape[1] - 1, H.shape[2] - 1
    h = H.tolist()
    U = [[[0.0] * (W + 1) for _ in range(B + 1)] for _ in range(R + 2)]
    for r in range(R, 0, -1):
        ur, un, hr = U[r], U[r + 1], h[r]
        for b in range(1, B + 1):
            row, prev_b, nxt, hrow = ur[b], ur[b - 1], un[b], hr[b]
            for w in range(1, W + 1):
                v = hrow[w]
                if nxt[w] > v:
                    v = nxt[w]
                if prev_b[w] > v:
                    v = prev_b[w]
                if row[w - 1] > v:
                    v = row[w - 1]
                row[w] = v
    L = [[[1.0] * (W + 2) for _ in range(B + 2)] for _ in range(R + 1)]
    for r in range(1, R + 1):
        lr_, lp, hr = L[r], L[r - 1], h[r]
        for b in range(B, 0, -1):
            row, nxt_b, up, hrow = lr_[b], lr_[b + 1], lp[b], hr[b]
            for w in range(W, 0, -1):
                v = hrow[w]
                if up[w] < v:
                    v = up[w]
                if nxt_b[w] < v:
                    v = nxt_b[w]
                if row[w + 1] < v:
                    v = row[w + 1]
                row[w] = v
    G = np.zeros_like(H)
    G[0] = 1.0
    for r in range(1, R + 1):
        for b in range(1, B + 1):
            ub, lb = U[r][b], L[r][b]
            G[r, b, 1:] = [0.5 * (ub[w] + lb[w]) for w in range(1, W + 1)]
    return G


def calculator_table(lr_model, sim: Simulation, grid: np.ndarray, k: float,
                     cfg: Config) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Full calculator table over r 0..max_runs, b 0..120, w 0..10.

    Returns (G final, H blend before the envelope, A weight on LR-core). Index 0 rows hold the
    rule outcomes (r = 0 -> 1; b = 0 or w = 0 -> 0).
    """
    R, B, W = cfg.export.calculator_max_runs, cfg.rules.balls_per_innings, cfg.rules.wickets
    r, b, w = (a.ravel() for a in np.meshgrid(np.arange(1, R + 1), np.arange(1, B + 1),
                                              np.arange(1, W + 1), indexing="ij"))
    a = blend_weight(support_of(grid, r, b, w, cfg), k)
    H = np.zeros((R + 1, B + 1, W + 1))
    H[0] = 1.0
    H[r, b, w] = a * lr_core_p(lr_model, r, b, w, cfg.rules.rrr_clip) + (1 - a) * sim.p(r, b, w)
    A = np.zeros(H.shape)
    A[r, b, w] = a
    return monotone_envelope(H), H, A


def table_lookup(G: np.ndarray, r, b, w) -> np.ndarray:
    R = G.shape[0] - 1
    return G[np.clip(np.asarray(r, int), 0, R), np.asarray(b, int), np.asarray(w, int)]


def tune(train_all, train_model, val, lr_train, spec: SimSpec, cfg: Config):
    """Grid over shrinkage x k for the full calculator (blend + envelope), on validation.

    Selection: lowest validation log loss; ties -> larger shrinkage, then larger k (smoother).
    Returns (log rows, best row).
    """
    grid, _ = support_grid(train_model, cfg)
    r, b, w, y = val["runs_needed"], val["balls_left"], val["wickets_left"], val["y"]
    sup = support_of(grid, r, b, w, cfg)
    p_lr = lr_core_p(lr_train, r, b, w, cfg.rules.rrr_clip)
    eps = cfg.eval.logloss_eps
    rows = []
    for s in cfg.simulation.shrinkage_grid:
        sim = Simulation.fit(train_all, train_model, spec, s)
        p_sim, p_raw = sim.p(r, b, w), sim.raw(r, b, w)
        for k in cfg.simulation.blend_k_grid:
            G, _, _ = calculator_table(lr_train, sim, grid, k, cfg)
            pc = table_lookup(G, r, b, w)
            rows.append({"shrinkage": s, "k": k,
                         "val_log_loss": log_loss(pc, y, eps), "val_brier": brier(pc, y),
                         "mean_lr_weight": float(blend_weight(sup, k).mean()),
                         "share_without_data": float((sup == 0).mean()),
                         "val_log_loss_lr_core": log_loss(p_lr, y, eps), "val_brier_lr_core": brier(p_lr, y),
                         "val_log_loss_simulation": log_loss(p_sim, y, eps), "val_brier_simulation": brier(p_sim, y),
                         "val_brier_simulation_uncalibrated": brier(p_raw, y),
                         "platt_slope": sim.a, "platt_intercept": sim.c})
    best = sorted(rows, key=lambda e: (round(e["val_log_loss"], 10), -e["shrinkage"], -e["k"]))[0]
    return rows, best


def subset_metrics(p: dict[str, np.ndarray], y, mask=None) -> dict[str, dict]:
    y = np.asarray(y)
    m = np.ones(len(y), bool) if mask is None else np.asarray(mask)
    out = {}
    for k, v in p.items():
        out[k] = ({"brier": brier(v[m], y[m]), "log_loss": log_loss(v[m], y[m]),
                   "ece": ece(v[m], y[m]), "n_rows": int(m.sum())} if m.any()
                  else {"brier": None, "log_loss": None, "ece": None, "n_rows": 0})
    return out


def monotonic_violations(fn, cfg: Config, tol: float = 1e-9) -> dict[str, int]:
    """Count grid neighbours where one more run needed, one ball fewer or one wicket fewer RAISES p."""
    R = cfg.export.calculator_max_runs
    r, b, w = (a.ravel() for a in np.meshgrid(np.arange(1, R), np.arange(1, cfg.rules.balls_per_innings + 1),
                                               np.arange(1, cfg.rules.wickets + 1), indexing="ij"))
    p = fn(r, b, w)
    kw, kb = w > 1, b > 1
    return {"states_checked": int(len(r)),
            "more_runs_raises_p": int((fn(r + 1, b, w) > p + tol).sum()),
            "fewer_balls_raises_p": int((fn(r[kb], b[kb] - 1, w[kb]) > p[kb] + tol).sum()),
            "fewer_wickets_raises_p": int((fn(r[kw], b[kw], w[kw] - 1) > p[kw] + tol).sum())}


def reach_stats(rows: pd.DataFrame) -> list[dict]:
    """Per wickets-left value: chases that reached it at an open state, and how many won."""
    g = rows.groupby(["wickets_left", "match_id"])["y"].first().reset_index()
    t = g.groupby("wickets_left")["y"].agg(["size", "sum"]).reset_index()
    return [{"wickets_left": int(w), "chases": int(n), "won": int(s)} for w, n, s in t.to_numpy()]


def parity_vectors(cfg: Config, sim: Simulation, G: np.ndarray, n: int) -> list[dict]:
    """Random states (plus edge cases) with the raw simulation, calibrated simulation and final
    calculator values at full precision, for the JavaScript parity test."""
    rng = np.random.default_rng(cfg.seed + 1)
    edge = [(1, 1, 1), (300, 120, 10), (42, 42, 1), (300, 1, 1), (6, 1, 10), (1, 120, 10)]
    r = np.concatenate([[e[0] for e in edge], rng.integers(1, cfg.export.calculator_max_runs + 1, n - len(edge))])
    b = np.concatenate([[e[1] for e in edge], rng.integers(1, cfg.rules.balls_per_innings + 1, n - len(edge))])
    w = np.concatenate([[e[2] for e in edge], rng.integers(1, cfg.rules.wickets + 1, n - len(edge))])
    raw, cal, fin = sim.raw(r, b, w), sim.p(r, b, w), table_lookup(G, r, b, w)
    return [{"runs_needed": int(x), "balls_left": int(y_), "wickets_left": int(z), "raw": float(p0),
             "sim": float(p1), "p": float(p2)} for x, y_, z, p0, p1, p2 in zip(r, b, w, raw, cal, fin)]


# ---------------------------------------------------------------------------------------------
# the `edgecases` stage
# ---------------------------------------------------------------------------------------------
def run_stage(cfg: Config) -> dict:
    """Tune on validation, refit on train + validation, check scenarios, write outputs.

    Writes reports/{edge_cases.json, edge_cases.md, tuning_edge_cases.csv} and
    models/simulation_final.json (read by `make export`). Returns the edge_cases.json contents.
    """
    import json

    import joblib

    from .evaluate import round_floats
    from .io_tables import read_dev_features, read_table
    from .models import fit_chosen
    from .report_utils import md_table
    from .simulate import spec_from_config

    spec = spec_from_config(cfg)
    clip = cfg.rules.rrr_clip
    selection = json.loads((cfg.io.models_dir / "selection.json").read_text(encoding="utf-8"))
    lr_params = {k: v for k, v in selection["chosen_params"]["lr_core"].items()
                 if k not in ("fit_seconds", "n_iter")}

    # 1. choose settings on validation; test rows are not read here
    dev = read_dev_features(cfg)
    train_all = dev[dev["split"] == "train"]
    train_m = train_all[train_all["is_model_row"]]
    val = dev[(dev["split"] == "val") & dev["is_model_row"]]
    lr_train = fit_chosen("lr_core", lr_params, train_m, cfg)
    log, best = tune(train_all, train_m, val, lr_train, spec, cfg)
    pd.DataFrame(log).to_csv(cfg.io.reports_dir / "tuning_edge_cases.csv", index=False)
    k = float(best["k"])
    print(f"Chosen on validation: shrinkage {best['shrinkage']:g}, k {k:g} "
          f"(val log loss {best['val_log_loss']:.5f}, LR-core {best['val_log_loss_lr_core']:.5f})")

    # 2. refit on train + validation for the website (same data as the other final models)
    fit_m = dev[dev["is_model_row"]]
    sim = Simulation.fit(dev, fit_m, spec, best["shrinkage"])
    grid, won = support_grid(fit_m, cfg)
    lr_final = joblib.load(cfg.io.models_dir / "lr_core_final.joblib")
    G, H, A = calculator_table(lr_final, sim, grid, k, cfg)

    def calc(r, b, w):
        return table_lookup(G, r, b, w)

    def before(r, b, w):
        return table_lookup(H, r, b, w)

    # 3. scenarios, monotonicity, coverage
    scen = []
    for r, b, w, why in SCENARIOS:
        cell = tuple(x[0] for x in support_cells([r], [b], [w], cfg))
        scen.append({"runs_needed": r, "balls_left": b, "wickets_left": w, "why": why,
                     "support_chases": int(grid[cell]), "support_won": int(won[cell]),
                     "lr_weight": float(A[r, b, w]),
                     "p_lr_core": float(lr_core_p(lr_final, [r], [b], [w], clip)[0]),
                     "p_simulation_raw": float(sim.raw(r, b, w)),
                     "p_simulation": float(sim.p([r], [b], [w])[0]),
                     "p_blend": float(H[r, b, w]),
                     "p_calculator": float(G[r, b, w])})
    mono = {"lr_core": monotonic_violations(lambda r, b, w: lr_core_p(lr_final, r, b, w, clip), cfg),
            "simulation": monotonic_violations(sim.p, cfg),
            "blend_before_envelope": monotonic_violations(before, cfg),
            "calculator": monotonic_violations(calc, cfg)}
    inner = (slice(1, None),) * 3
    floor = cfg.simulation.display_floor
    rr, bb, ww = (a.ravel() for a in np.meshgrid(np.arange(1, G.shape[0]), np.arange(1, G.shape[1]),
                                                  np.arange(1, G.shape[2]), indexing="ij"))
    p_lr_all = lr_core_p(lr_final, rr, bb, ww, clip)
    no_data = (A[inner].ravel() == 0)
    near = (p_lr_all < floor) | (p_lr_all > 1 - floor)
    gflat = G[inner].ravel()
    coverage = {"calculator_states": int(len(rr)), "states_without_data": int(no_data.sum()),
                "share_without_data": float(no_data.mean()),
                "lr_core_near_certain": int(near.sum()),
                "lr_core_near_certain_without_data": int((near & no_data).sum()),
                "calculator_near_certain": int(((gflat < floor) | (gflat > 1 - floor)).sum()),
                "mean_change_by_envelope": float(np.abs(G - H)[inner].mean()),
                "max_change_by_envelope": float(np.abs(G - H)[inner].max())}

    # 4. post-test check on the test seasons (scored once already by `final`)
    full = read_table(cfg, cfg.io.processed_dir, "chase_features")
    test = full[(full["split"] == "test") & full["is_model_row"]]
    r, b, w, y = test["runs_needed"], test["balls_left"], test["wickets_left"], test["y"]
    nd = support_of(grid, r, b, w, cfg) == 0
    p = {"lr_core": lr_core_p(lr_final, r, b, w, clip), "simulation": sim.p(r, b, w), "calculator": calc(r, b, w)}
    yy = y.to_numpy()

    def certain_wrong(v):
        return int((((v < floor) & (yy == 1)) | ((v > 1 - floor) & (yy == 0))).sum())

    post = {"all_rows": subset_metrics(p, y), "rows_without_data": subset_metrics(p, y, nd),
            "share_rows_without_data": float(nd.mean()), "n_rows": int(len(yy)),
            "near_certain_rows": {m_: int(((v < floor) | (v > 1 - floor)).sum()) for m_, v in p.items()},
            "near_certain_wrong": {m_: certain_wrong(v) for m_, v in p.items()}}

    out = round_floats({
        "chosen": {"shrinkage": best["shrinkage"], "k": k,
                   "support_bucket": {"runs": cfg.simulation.support_runs, "balls": cfg.simulation.support_balls},
                   "platt_slope": sim.a, "platt_intercept": sim.c, "selection_metric": "validation log loss"},
        "validation": {kk: best[kk] for kk in ("val_log_loss", "val_brier", "val_log_loss_lr_core",
                                               "val_brier_lr_core", "val_log_loss_simulation",
                                               "val_brier_simulation", "val_brier_simulation_uncalibrated",
                                               "share_without_data", "mean_lr_weight")},
        "tuning": log, "post_test": post, "scenarios": scen, "monotonicity": mono,
        "coverage": coverage, "reach": reach_stats(fit_m), "display_floor": floor,
        "fit": {"seasons": sorted(int(s) for s in fit_m["season"].unique()),
                "chases": int(fit_m["match_id"].nunique()), "deliveries": int(len(dev)),
                "contexts": spec.n_contexts, "outcome_classes": len(spec.classes),
                "rrr_bands": list(spec.rrr_bands), "wicket_groups": [list(g) for g in spec.wicket_groups]},
    }, 10)
    rep = cfg.io.reports_dir
    (rep / "edge_cases.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    model = {"classes": [list(c) for c in spec.classes], "rrr_bands": list(spec.rrr_bands),
             "wicket_groups": [list(g) for g in spec.wicket_groups], "balls": spec.balls,
             "wickets": spec.wickets, "max_runs": spec.max_runs,
             "outcome_probs": sim.P.tolist(), "platt": [sim.a, sim.c], "blend_k": k,
             "support_bucket": [cfg.simulation.support_runs, cfg.simulation.support_balls],
             "support": grid.tolist(), "display_floor": floor,
             "parity_vectors": parity_vectors(cfg, sim, G, cfg.simulation.n_parity_vectors)}
    (cfg.io.models_dir / "simulation_final.json").write_text(json.dumps(model), encoding="utf-8")

    def pc(v):
        return f"{100 * v:.1f}%"

    st = pd.DataFrame([{"state": f"{s['runs_needed']} off {s['balls_left']}, {s['wickets_left']} wkt",
                        "chases in cell": s["support_chases"], "LR-core": pc(s["p_lr_core"]),
                        "simulation": pc(s["p_simulation"]), "LR weight": f"{s['lr_weight']:.2f}",
                        "calculator": pc(s["p_calculator"])} for s in scen])
    mt = pd.DataFrame([{"model": m_, "test Brier": f"{post['all_rows'][m_]['brier']:.4f}",
                        "test log loss": f"{post['all_rows'][m_]['log_loss']:.4f}",
                        "rows without data, Brier": (f"{post['rows_without_data'][m_]['brier']:.4f}"
                                                     if post["rows_without_data"][m_]["brier"] is not None else ""),
                        "near-certain and wrong": post["near_certain_wrong"][m_]} for m_ in p])
    mo = pd.DataFrame([{"model": m_, **v} for m_, v in mono.items()])
    text = "\n".join([
        "# Edge cases (post-test addition)", "",
        "Added after the test seasons were scored, to fix near-certain calculator outputs in states the "
        "data never reached. Settings were chosen on validation; test numbers are a post-test check, "
        "not a clean test. Code: `src/iplwp/simulate.py`, `src/iplwp/edge_cases.py`.", "",
        f"Chosen on validation log loss: simulation shrinkage {best['shrinkage']:g}, blend k {k:g} "
        f"(LR-core weight n/(n+k), n = fitting chases in the {cfg.simulation.support_runs}-run x "
        f"{cfg.simulation.support_balls}-ball cell). Validation log loss {best['val_log_loss']:.5f} vs "
        f"LR-core {best['val_log_loss_lr_core']:.5f}; Brier {best['val_brier']:.5f} vs "
        f"{best['val_brier_lr_core']:.5f}.", "",
        f"Calculator states with no fitting chase in their cell: {coverage['states_without_data']:,} of "
        f"{coverage['calculator_states']:,}. LR-core gives under 1% or over 99% on "
        f"{coverage['lr_core_near_certain']:,} states, {coverage['lr_core_near_certain_without_data']:,} of "
        "them without data.", "",
        md_table(st), "", md_table(mt), "", "Monotonicity violations on the calculator grid:", "",
        md_table(mo), "", "Tuning log: `reports/tuning_edge_cases.csv`.", ""])
    (rep / "edge_cases.md").write_text(text, encoding="utf-8")
    print(md_table(st))
    print(md_table(mt))
    print(md_table(mo))
    print(coverage)
    return out
