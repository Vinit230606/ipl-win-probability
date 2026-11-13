"""Report figures (design 11.7). Each function takes plain data and an output path."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .evaluate import METHOD_LABELS  # noqa: E402

COLORS = {"baseline": "#5E6D66", "lr_full": "#1E4636", "lr_core": "#6FA287", "gbm": "#C98A00"}


def _save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=150, metadata={"Software": None})
    plt.close(fig)


def calibration_plot(calib: dict[str, list[dict]], path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(5.5, 5))
    ax.plot([0, 1], [0, 1], color="#999", lw=1, ls=":", label="perfect calibration")
    for k, bins in calib.items():
        b = [x for x in bins if x["n"]]
        ax.plot([x["mean_p"] for x in b], [x["observed_rate"] for x in b], marker="o", ms=4,
                color=COLORS[k], label=METHOD_LABELS[k], ls="--" if k == "baseline" else "-")
    ax.set(xlabel="Mean predicted win probability", ylabel="Observed chase win rate",
           xlim=(0, 1), ylim=(0, 1), title=title)
    ax.legend(frameon=False, fontsize=9)
    _save(fig, path)


def bss_interval_plot(entries: list[tuple[str, float, list[float]]], path: Path, title: str) -> None:
    """entries: (label, bss, [lo, hi])."""
    fig, ax = plt.subplots(figsize=(6.5, 0.6 * len(entries) + 1.2))
    for i, (lab, b, (lo, hi)) in enumerate(entries):
        color = "#1E4636" if lo > 0 else ("#B3261E" if hi < 0 else "#C98A00")
        ax.plot([lo, hi], [i, i], color=color, lw=3)
        ax.plot([b], [i], "o", color=color)
        ax.text(hi, i + 0.18, f" {b:.3f} [{lo:.3f}, {hi:.3f}]", fontsize=8, va="bottom")
    ax.axvline(0, color="#999", lw=1)
    ax.set_yticks(range(len(entries)), [e[0] for e in entries])
    ax.set_ylim(-0.6, len(entries) - 0.2)
    ax.set_xlabel("Brier skill score (95% match-bootstrap interval)")
    ax.set_title(title)
    _save(fig, path)


def phase_brier_plot(phase: list[dict], methods: list[str], path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(6.5, 4))
    x = np.arange(len(phase))
    w = 0.8 / len(methods)
    for j, k in enumerate(methods):
        ax.bar(x + (j - (len(methods) - 1) / 2) * w, [e[f"brier_{k}"] for e in phase], w,
               color=COLORS[k], label=METHOD_LABELS[k])
    ax.set_xticks(x, [f"{e['phase']}\n({e['n_rows']:,} rows)" for e in phase])
    ax.set_ylabel("Brier score (lower is better)")
    ax.set_title(title)
    ax.legend(frameon=False, fontsize=9)
    _save(fig, path)


def drift_plot(drift: list[dict], path: Path, model_label: str) -> None:
    d = pd.DataFrame(drift)
    fig, ax = plt.subplots(figsize=(6, 4))
    x = np.arange(len(d))
    ax.bar(x - 0.2, d["chase_win_rate"], 0.4, color="#5E6D66", label="Observed chase win rate")
    ax.bar(x + 0.2, d["start_mean_p"], 0.4, color="#C98A00",
           label=f"{model_label}: mean start-of-chase prediction")
    ax.set_xticks(x, [f"{s}\n({r})" for s, r in zip(d["season"], d["role"])])
    ax.set_ylim(0, 1)
    ax.set_ylabel("Probability")
    ax.set_title("Scoring drift check")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    _save(fig, path)


def replay_plot(balls: pd.DataFrame, path: Path, title: str, model_label: str) -> None:
    """balls: i, p_base, p_model, wicket (bool), over_idx."""
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(balls["i"], 100 * balls["p_base"], color="#5E6D66", ls="--", lw=1.5, label="Baseline")
    ax.plot(balls["i"], 100 * balls["p_model"], color="#C98A00", lw=2.5, label=model_label)
    w = balls[balls["wicket"]]
    ax.scatter(w["i"], 100 * w["p_model"], color="#B3261E", zorder=3, s=25, label="Wicket")
    firsts = balls.groupby("over_idx")["i"].min()
    ax.set_xticks(firsts.values[::2], [str(o + 1) for o in firsts.index[::2]])
    ax.set(xlabel="Over", ylabel="Chasing team win probability (%)", ylim=(0, 100), title=title)
    ax.legend(frameon=False, fontsize=9, loc="best")
    _save(fig, path)
