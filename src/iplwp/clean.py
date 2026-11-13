"""Match filtering, exclusion log and post-clean invariants (design section 5).

Rules are applied in a fixed order and each excluded match gets the reason of the FIRST rule it
fails. Cleaning uses match results only to decide which matches are valid full chases and to set
the label; it creates no features.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import RulesConfig
from .schema import DataQualityError, normalise_team_series
from .states import wickets_on_delivery

REASONS = ["DUPLICATE", "NO_RESULT", "TIE", "DLS", "NO_CHASE", "REDUCED_OVERS",
           "TARGET_MISMATCH", "CHASE_INCOMPLETE", "LABEL_MISMATCH"]
EXCLUSION_COLUMNS = ["match_id", "season", "reason", "detail"]


def innings_summary(deliveries: pd.DataFrame, rules: RulesConfig) -> pd.DataFrame:
    """Per (match_id, innings) for innings 1 and 2: batting team, runs, legal balls, wickets."""
    d = deliveries[deliveries["innings"].isin([1, 2])].copy()
    d["legal"] = ~(d["is_wide"] | d["is_noball"])
    d["wkts"] = wickets_on_delivery(d, rules.non_wicket_dismissals)
    return (d.groupby(["match_id", "innings"])
            .agg(batting_team=("batting_team", "first"),
                 n_batting_teams=("batting_team", "nunique"),
                 runs=("runs_total", "sum"),
                 legal_balls=("legal", "sum"),
                 wickets=("wkts", "sum"),
                 deliveries=("seq", "size"))
            .reset_index())


def clean(matches: pd.DataFrame, deliveries: pd.DataFrame,
          rules: RulesConfig) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Apply exclusion rules 1-9 and return (chases, kept_deliveries, exclusions).

    `chases`: one row per kept match with target, first-innings total, final chase runs, wickets,
    legal balls and `chase_won`. `kept_deliveries`: innings 1 and 2 rows of kept matches (super
    overs dropped). `exclusions`: match_id, season, reason, detail for every excluded match.
    Raises DataQualityError if a post-clean invariant fails.
    """
    excl: list[pd.DataFrame] = []

    # 1. DUPLICATE: keep none, log all
    dup = matches["match_id"].duplicated(keep=False)
    if dup.any():
        excl.append(pd.DataFrame({"match_id": matches.loc[dup, "match_id"],
                                  "season": matches.loc[dup, "season"],
                                  "reason": "DUPLICATE",
                                  "detail": "match_id appears more than once"}))
    m = matches[~dup].set_index("match_id")
    dup_ids = set(matches.loc[dup, "match_id"])

    inn = innings_summary(deliveries[~deliveries["match_id"].isin(dup_ids)], rules)
    i1 = inn[inn["innings"] == 1].set_index("match_id").reindex(m.index)
    i2 = inn[inn["innings"] == 2].set_index("match_id").reindex(m.index)

    first_total = i1["runs"].fillna(0).astype(int)
    target = first_total + 1
    final_runs = i2["runs"].fillna(0).astype(int)
    norm_winner = normalise_team_series(m["winner"])
    norm_chaser = normalise_team_series(i2["batting_team"])
    chase_won = (norm_winner == norm_chaser).fillna(False).astype(bool)
    reached = final_runs >= target

    full_balls, full_wkts = rules.balls_per_innings, rules.wickets
    i1_short = (i1["legal_balls"].fillna(0) < full_balls) & (i1["wickets"].fillna(0) < full_wkts)
    overs_reduced = (m["target_overs_provided"].notna()
                     & (m["target_overs_provided"].astype(float) != float(rules.overs))).fillna(False)
    target_bad = (m["target_runs_provided"].notna()
                  & (m["target_runs_provided"].astype(float) != target.astype(float))).fillna(False)
    i2_short = ((i2["legal_balls"].fillna(0) < full_balls) & (i2["wickets"].fillna(0) < full_wkts)
                & (final_runs < target))

    conds = [
        ("NO_RESULT", m["outcome_type"] == "no_result",
         lambda: "outcome: no result"),
        ("TIE", m["outcome_type"] == "tie",
         lambda: "outcome: tie (incl. super over)"),
        ("DLS", m["method"].notna(),
         lambda: "method: " + m["method"].astype(str)),
        ("NO_CHASE", i2["deliveries"].isna(),
         lambda: "no innings-2 deliveries"),
        ("REDUCED_OVERS", overs_reduced | i1_short,
         lambda: ("target overs " + m["target_overs_provided"].astype(str)
                  + "; innings 1: " + i1["legal_balls"].fillna(0).astype(int).astype(str)
                  + " legal balls, " + i1["wickets"].fillna(0).astype(int).astype(str) + " wkts")),
        ("TARGET_MISMATCH", target_bad,
         lambda: ("provided " + m["target_runs_provided"].astype(str)
                  + " vs rebuilt " + target.astype(str))),
        ("CHASE_INCOMPLETE", i2_short,
         lambda: ("innings 2: " + i2["legal_balls"].fillna(0).astype(int).astype(str)
                  + " legal balls, " + i2["wickets"].fillna(0).astype(int).astype(str)
                  + " wkts, " + final_runs.astype(str) + "/" + target.astype(str))),
        ("LABEL_MISMATCH", chase_won != reached,
         lambda: ("winner " + m["winner"].astype(str) + "; chase " + final_runs.astype(str)
                  + " vs target " + target.astype(str))),
    ]
    remaining = pd.Series(True, index=m.index)
    for reason, cond, detail in conds:
        hit = remaining & cond.fillna(False).astype(bool)
        if hit.any():
            det = detail()
            det = det if isinstance(det, pd.Series) else pd.Series(det, index=m.index)
            excl.append(pd.DataFrame({"match_id": m.index[hit], "season": m.loc[hit, "season"].values,
                                      "reason": reason, "detail": det[hit].values}))
        remaining &= ~hit

    kept = m.index[remaining]
    chases = pd.DataFrame({
        "match_id": kept,
        "season": m.loc[kept, "season"].values,
        "date": m.loc[kept, "date"].values,
        "venue": m.loc[kept, "venue"].values,
        "city": m.loc[kept, "city"].values,
        "batting_team": i2.loc[kept, "batting_team"].values,
        "bowling_team": i1.loc[kept, "batting_team"].values,
        "winner": m.loc[kept, "winner"].values,
        "target": target[kept].values,
        "first_innings_total": first_total[kept].values,
        "final_runs": final_runs[kept].values,
        "final_wickets": i2.loc[kept, "wickets"].astype(int).values,
        "final_legal_balls": i2.loc[kept, "legal_balls"].astype(int).values,
        "chase_won": chase_won[kept].astype(int).values,
    })
    chases["match_id"] = chases["match_id"].astype("string")
    chases = chases.sort_values(["date", "match_id"], kind="stable").reset_index(drop=True)

    exclusions = (pd.concat(excl, ignore_index=True) if excl
                  else pd.DataFrame(columns=EXCLUSION_COLUMNS))[EXCLUSION_COLUMNS]
    exclusions["reason"] = pd.Categorical(exclusions["reason"], REASONS, ordered=True)
    exclusions = exclusions.sort_values(["reason", "season", "match_id"]).reset_index(drop=True)
    exclusions["reason"] = exclusions["reason"].astype(str)

    kept_deliv = deliveries[deliveries["match_id"].isin(set(kept))
                            & deliveries["innings"].isin([1, 2])].reset_index(drop=True)
    _post_clean_checks(m.loc[kept], chases, inn[inn["match_id"].isin(set(kept))],
                       len(matches), len(exclusions), rules)
    return chases, kept_deliv, exclusions


def _post_clean_checks(m: pd.DataFrame, chases: pd.DataFrame, inn: pd.DataFrame,
                       n_raw: int, n_excl: int, rules: RulesConfig) -> None:
    """Invariants on kept data (design section 5); raise DataQualityError on any failure."""
    if n_raw != len(chases) + n_excl:
        raise DataQualityError(f"raw matches {n_raw} != kept {len(chases)} + excluded {n_excl}")
    counts = inn.groupby("match_id")["innings"].agg(lambda s: tuple(sorted(s)))
    bad = counts[counts != (1, 2)]
    if len(bad):
        raise DataQualityError(f"match {bad.index[0]}: innings {bad.iloc[0]} instead of (1, 2)")
    multi = inn[inn["n_batting_teams"] != 1]
    if len(multi):
        raise DataQualityError(f"match {multi['match_id'].iloc[0]}: several batting teams in "
                               f"innings {multi['innings'].iloc[0]}")
    c = chases.set_index("match_id")
    if (c["batting_team"] == c["bowling_team"]).any():
        raise DataQualityError(f"match {c.index[c['batting_team'] == c['bowling_team']][0]}: "
                               "both innings batted by the same team")
    teams = pd.DataFrame({"a": normalise_team_series(m["team1"]),
                          "b": normalise_team_series(m["team2"])}).loc[c.index]
    bat = normalise_team_series(c["batting_team"])
    bowl = normalise_team_series(c["bowling_team"])
    ok = ((bat == teams["a"]) & (bowl == teams["b"])) | ((bat == teams["b"]) & (bowl == teams["a"]))
    if not ok.all():
        raise DataQualityError(f"match {ok.index[~ok][0]}: innings teams differ from team1/team2")
    if (c["final_legal_balls"] > rules.balls_per_innings).any():
        raise DataQualityError("a kept chase has more legal balls than balls_per_innings")


def season_table(matches: pd.DataFrame, exclusions: pd.DataFrame, chases: pd.DataFrame) -> pd.DataFrame:
    """Per season: raw matches, exclusions per reason, kept chases, chase win rate; plus totals."""
    raw = matches.groupby("season").size().rename("matches_raw")
    ex = (exclusions.groupby(["season", "reason"]).size().unstack(fill_value=0)
          .reindex(columns=[r for r in REASONS if r in set(exclusions["reason"])], fill_value=0))
    kept = chases.groupby("season").size().rename("kept")
    rate = chases.groupby("season")["chase_won"].mean().rename("chase_win_rate")
    t = pd.concat([raw, ex, kept, rate], axis=1).fillna(0)
    t.index.name = "season"
    for col in t.columns:
        if col != "chase_win_rate":
            t[col] = t[col].astype(int)
    total = t.drop(columns="chase_win_rate").sum()
    total["chase_win_rate"] = chases["chase_won"].mean() if len(chases) else np.nan
    t.loc["total"] = total
    t = t.reset_index()
    t["chase_win_rate"] = t["chase_win_rate"].map(lambda v: f"{v:.3f}")
    for col in t.columns:
        if col not in ("season", "chase_win_rate"):
            t[col] = t[col].astype(int)
    return t


SPLIT_MARKER = "<!-- split section: written by the features stage -->"


def data_quality_markdown(matches: pd.DataFrame, exclusions: pd.DataFrame, chases: pd.DataFrame,
                          kept_deliveries: pd.DataFrame, states: pd.DataFrame,
                          check: pd.DataFrame, raw_format: str) -> str:
    """Build `reports/data_quality.md` (everything except the split table, added by `features`)."""
    from .report_utils import md_table

    i2 = kept_deliveries[kept_deliveries["innings"] == 2]
    n_terminal = int(states["is_terminal"].sum())
    by_reason = (exclusions["reason"].value_counts()
                 .reindex([r for r in REASONS], fill_value=0).rename_axis("reason")
                 .reset_index(name="matches"))
    n_ok = int(check["ok"].sum())
    reduced_by_i1 = exclusions[(exclusions["reason"] == "REDUCED_OVERS")
                               & exclusions["detail"].str.startswith("target overs 20.0")]
    lines = [
        "# Data quality",
        "",
        f"Raw format: {raw_format}. Generated by `make data`.",
        "",
        "## Matches per season",
        "",
        "Season = calendar year of the match date. `chase_win_rate` is over kept chases.",
        "",
        md_table(season_table(matches, exclusions, chases)),
        "",
        "## Exclusions by reason",
        "",
        "Each excluded match gets the first rule it fails, in the order below. Every excluded match "
        "is listed with details in `reports/exclusions.csv`.",
        "",
        md_table(by_reason),
        "",
        f"REDUCED_OVERS matches whose target overs were 20 but whose first innings ended before "
        f"120 legal balls with fewer than 10 wickets (umpire miscounts, an absent batter, or "
        f"interruptions): {len(reduced_by_i1)}"
        + (f" ({', '.join(reduced_by_i1['match_id'].astype(str))})." if len(reduced_by_i1) else "."),
        "",
        "## Totals",
        "",
        f"- Raw matches: {len(matches):,}. Excluded: {len(exclusions):,}. Kept chases: {len(chases):,}.",
        f"- Chase deliveries (state rows): {len(states):,}; terminal rows: {n_terminal:,}; "
        f"model rows (non-terminal): {len(states) - n_terminal:,}.",
        f"- Wides in kept chases: {int(i2['is_wide'].sum()):,}; no-balls: "
        f"{int(i2['is_noball'].sum()):,} (all kept innings: {int(kept_deliveries['is_wide'].sum()):,}"
        f" wides, {int(kept_deliveries['is_noball'].sum()):,} no-balls).",
        f"- Overall chase win rate: {chases['chase_won'].mean():.3f}.",
        "",
        "## Running-total check",
        "",
        f"Rebuilt running totals (runs, wickets, legal balls on the last state row) equal the "
        f"innings totals from cleaning for {n_ok:,} of {len(check):,} kept chases "
        f"({100 * n_ok / max(len(check), 1):.1f}%).",
        "",
        SPLIT_MARKER,
        "",
    ]
    return "\n".join(lines)
