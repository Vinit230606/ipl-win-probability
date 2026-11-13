"""Raw-data access: format detection, profiling and (from task 3) adapters to the canonical schema.

This is the ONLY module that reads files in `data/raw/`. Three layouts are recognised:

- "K": Kaggle-style `matches.csv` + `deliveries.csv` (design section 4.2).
- "C": Cricsheet CSV v2, per-match `<id>.csv` + `<id>_info.csv` (design section 4.2).
- "J": Cricsheet JSON, one `<id>.json` per match (proposed design refinement D7; this is the
  layout of the data actually supplied, cricsheet.org `ipl_json.zip`).

Nothing here looks at match outcomes to build features; it only reshapes raw records.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import Config
from .report_utils import md_table
from .schema import (CANONICAL_DELIVERIES, CANONICAL_MATCHES, DELIVERIES_DTYPES, MATCHES_DTYPES,
                     OUTCOME_TYPES, DataQualityError, enforce_schema)

PROFILE_DISTINCT_KEYS = (
    "extras_type", "dismissal", "result", "method", "outcome", "season",
    # extra keys for the Cricsheet JSON layout, whose field names differ from the CSV layouts
    "wicket_kind", "data_version", "match_type", "overs", "balls_per_over", "super_over",
)


class SchemaNotRecognised(Exception):
    """Raised when the raw files match none of the known layouts."""


# --------------------------------------------------------------------------------------------
# Format detection
# --------------------------------------------------------------------------------------------
K_DELIVERY_REQUIRED = [("inning", "innings"), ("over",), ("ball",), ("batting_team",), ("total_runs",)]
K_ALIASES = {
    "match_id": ("match_id", "id"),
    "batter": ("batter", "batsman", "striker"),
    "runs_batter": ("batsman_runs", "runs_batter"),
    "runs_extras": ("extra_runs", "extras"),
    "extras_type": ("extras_type",),
    "is_wicket": ("is_wicket",),
    "dismissal_kind": ("dismissal_kind",),
}
C_DELIVERY_REQUIRED = ["match_id", "innings", "ball", "runs_off_bat", "extras", "wides", "noballs",
                       "byes", "legbyes", "penalty", "wicket_type", "other_wicket_type"]
J_REQUIRED_KEYS = ("meta", "info", "innings")


@dataclass
class Detection:
    format: str                      # "K", "C", "J" or "unknown"
    files: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def _csv_header(path: Path) -> list[str]:
    return [c.strip().lower() for c in pd.read_csv(path, nrows=0).columns]


def _is_cricsheet_json(path: Path) -> bool:
    try:
        with path.open(encoding="utf-8") as f:
            d = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return isinstance(d, dict) and all(k in d for k in J_REQUIRED_KEYS)


def detect_format(raw_dir: Path) -> Detection:
    """Inspect every file under `raw_dir` (recursively) and decide which adapter applies.

    Returns a Detection; it never raises. Use `require_format` to turn "unknown" into an error.
    """
    csvs = sorted(raw_dir.rglob("*.csv"))
    jsons = sorted(p for p in raw_dir.rglob("*.json"))
    notes: list[str] = []

    # J: Cricsheet JSON, checked on a sample of files then confirmed on all.
    if jsons:
        good = [p for p in jsons if _is_cricsheet_json(p)]
        if good:
            if len(good) != len(jsons):
                notes.append(f"{len(jsons) - len(good)} JSON files are not Cricsheet match files "
                             "and will be ignored.")
            notes.append(f"{len(good)} Cricsheet JSON match files found.")
            return Detection("J", good, notes)

    headers = {p: _csv_header(p) for p in csvs}

    # K: Kaggle style
    k_deliv = [p for p, h in headers.items()
               if all(any(a in h for a in alts) for alts in K_DELIVERY_REQUIRED)]
    k_match = [p for p, h in headers.items() if "winner" in h and p not in k_deliv]
    if k_deliv and k_match:
        notes.append(f"Kaggle deliveries file(s): {[p.name for p in k_deliv]}; "
                     f"matches file(s): {[p.name for p in k_match]}")
        return Detection("K", k_deliv + k_match, notes)

    # C: Cricsheet CSV v2
    c_deliv = [p for p, h in headers.items() if all(c in h for c in C_DELIVERY_REQUIRED)]
    c_info = [p for p in csvs if p.name.endswith("_info.csv")]
    if c_deliv and c_info:
        notes.append(f"{len(c_deliv)} Cricsheet CSV delivery files, {len(c_info)} info files.")
        return Detection("C", c_deliv + c_info, notes)

    missing: list[str] = []
    if csvs:
        all_cols = set().union(*headers.values())
        missing = [c for c in C_DELIVERY_REQUIRED if c not in all_cols]
    else:
        missing = ["no CSV or Cricsheet JSON files found"]
    return Detection("unknown", csvs + jsons, notes, missing)


def write_column_map_template(path: Path) -> None:
    """Write `config/column_map.yaml` with every canonical column and an empty source field."""
    lines = ["# Fill in the raw file names (relative to data/raw) and the raw column name for each",
             "# canonical column, then rerun. `season` is derived from `date` and needs no column.",
             'matches_file: ""',
             'deliveries_file: ""',
             "matches:"]
    lines += [f"  {c}: \"\"" for c in CANONICAL_MATCHES if c != "season"]
    lines += ["deliveries:"]
    lines += [f"  {c}: \"\"" for c in CANONICAL_DELIVERIES if c != "dismissal_kind_2"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def require_format(cfg: Config) -> Detection:
    """Detect the raw format; on "unknown" write the column-map template and raise."""
    det = detect_format(cfg.io.raw_dir)
    if det.format == "unknown":
        tmpl = cfg.path.parent / "column_map.yaml"
        if not tmpl.exists():
            write_column_map_template(tmpl)
        raise SchemaNotRecognised(
            f"Raw files in {cfg.io.raw_dir} match no known layout. Missing canonical source "
            f"columns: {det.missing}. Fill in {tmpl} to map columns manually."
        )
    return det


# --------------------------------------------------------------------------------------------
# Cricsheet JSON: flatten to raw tables (raw field names, no cleaning, no canonical mapping)
# --------------------------------------------------------------------------------------------
def read_cricsheet_json(files: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Flatten Cricsheet JSON match files into three raw tables: matches, innings, deliveries.

    Column names mirror the JSON paths (e.g. `outcome_method`, `extras_wides`). Deliveries keep the
    file order as `file_order` within each innings, which is the bowling order.
    """
    m_rows, i_rows, d_rows = [], [], []
    for path in files:
        with path.open(encoding="utf-8") as f:
            d = json.load(f)
        info, meta = d["info"], d.get("meta", {})
        mid = path.stem
        outcome = info.get("outcome", {})
        by = outcome.get("by", {})
        teams = info.get("teams", [None, None])
        event = info.get("event", {})
        innings = d.get("innings", [])
        m_rows.append({
            "file": path.name,
            "match_id": mid,
            "data_version": meta.get("data_version"),
            "date": (info.get("dates") or [None])[0],
            "n_dates": len(info.get("dates") or []),
            "season": str(info.get("season")),
            "city": info.get("city"),
            "venue": info.get("venue"),
            "team1": teams[0] if len(teams) > 0 else None,
            "team2": teams[1] if len(teams) > 1 else None,
            "match_type": info.get("match_type"),
            "gender": info.get("gender"),
            "overs": info.get("overs"),
            "balls_per_over": info.get("balls_per_over"),
            "event_name": event.get("name"),
            "event_stage": event.get("stage"),
            "outcome_winner": outcome.get("winner"),
            "outcome_result": outcome.get("result"),
            "outcome_method": outcome.get("method"),
            "outcome_eliminator": outcome.get("eliminator"),
            "outcome_by_runs": by.get("runs"),
            "outcome_by_wickets": by.get("wickets"),
            "n_innings": len(innings),
            "has_missing_info": "missing" in info,
        })
        for inn_no, inn in enumerate(innings, start=1):
            target = inn.get("target", {})
            pen = inn.get("penalty_runs", {})
            i_rows.append({
                "match_id": mid,
                "innings": inn_no,
                "team": inn.get("team"),
                "super_over": bool(inn.get("super_over", False)),
                "target_runs": target.get("runs"),
                "target_overs": target.get("overs"),
                "penalty_runs_pre": pen.get("pre"),
                "penalty_runs_post": pen.get("post"),
                "has_absent_hand": "absent_hand" in inn,
                "has_miscounted_overs": "miscounted_overs" in inn,
                "n_overs_listed": len(inn.get("overs", [])),
            })
            order = 0
            for ov in inn.get("overs", []):
                for k, dl in enumerate(ov.get("deliveries", [])):
                    runs = dl.get("runs", {})
                    ex = dl.get("extras", {})
                    wk = dl.get("wickets", [])
                    d_rows.append({
                        "match_id": mid,
                        "innings": inn_no,
                        "team": inn.get("team"),
                        "super_over": bool(inn.get("super_over", False)),
                        "over": ov.get("over"),
                        "ball_in_over": k,
                        "file_order": order,
                        "batter": dl.get("batter"),
                        "bowler": dl.get("bowler"),
                        "runs_batter": runs.get("batter"),
                        "runs_extras": runs.get("extras"),
                        "runs_total": runs.get("total"),
                        "extras_wides": ex.get("wides", 0),
                        "extras_noballs": ex.get("noballs", 0),
                        "extras_byes": ex.get("byes", 0),
                        "extras_legbyes": ex.get("legbyes", 0),
                        "extras_penalty": ex.get("penalty", 0),
                        "n_wickets": len(wk),
                        "wicket_kind_1": wk[0].get("kind") if len(wk) > 0 else None,
                        "wicket_kind_2": wk[1].get("kind") if len(wk) > 1 else None,
                    })
                    order += 1
    return pd.DataFrame(m_rows), pd.DataFrame(i_rows), pd.DataFrame(d_rows)


def _read_raw_tables(det: Detection) -> dict[str, pd.DataFrame]:
    """Return named raw tables for profiling, according to the detected format."""
    if det.format == "J":
        m, i, d = read_cricsheet_json(det.files)
        return {"matches (flattened info)": m, "innings (flattened)": i,
                "deliveries (flattened)": d}
    return {p.name: pd.read_csv(p, low_memory=False) for p in det.files if p.suffix == ".csv"}


# --------------------------------------------------------------------------------------------
# Profile stage
# --------------------------------------------------------------------------------------------
def _profile_table(name: str, df: pd.DataFrame) -> str:
    out = [f"## {name}", "", f"Rows: {len(df):,}. Columns: {df.shape[1]}.", ""]
    info = pd.DataFrame({
        "column": df.columns,
        "dtype": [str(t) for t in df.dtypes],
        "nulls": df.isna().sum().values,
        "distinct": [df[c].nunique(dropna=True) for c in df.columns],
    })
    out += [md_table(info), "", "Five sample rows:", "", md_table(df.head(5)), ""]
    for c in df.columns:
        if any(k in c.lower() for k in PROFILE_DISTINCT_KEYS):
            vc = df[c].value_counts(dropna=False).sort_index(key=lambda s: s.astype(str))
            if len(vc) > 40:
                out += [f"Distinct values of `{c}`: {len(vc)} (too many to list).", ""]
                continue
            t = pd.DataFrame({"value": [str(v) for v in vc.index], "count": vc.values})
            out += [f"Distinct values of `{c}`:", "", md_table(t), ""]
    return "\n".join(out)


def _display_path(p: Path) -> str:
    from .config import REPO_ROOT
    try:
        return p.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def profile(cfg: Config) -> Detection:
    """Write `reports/data_profile.md` describing every raw file and the detected format.

    For the Cricsheet JSON layout the 1,000+ per-match files are flattened into matches, innings
    and deliveries tables, which are profiled as tables; a per-file appendix lists every file with
    its delivery count.
    """
    raw = cfg.io.raw_dir
    det = detect_format(raw)
    all_files = sorted(p for p in raw.rglob("*") if p.is_file())
    lines = [
        "# Raw data profile",
        "",
        f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by `make profile`.",
        "",
        f"Raw directory: `{_display_path(raw)}`. "
        f"Files: {len(all_files)}.",
        "",
        f"**Detected format: {det.format}**",
        "",
    ]
    lines += [f"- {n}" for n in det.notes]
    if det.missing:
        lines += [f"- Missing: {det.missing}"]
    other = [p for p in all_files if p not in set(det.files)]
    if other:
        lines += ["", "Files not used as data: " + ", ".join(p.name for p in other)]
    lines.append("")

    if det.format == "unknown":
        lines += ["No known layout. Fill in `config/column_map.yaml`.", ""]
        for p in all_files:
            if p.suffix == ".csv":
                lines.append(_profile_table(p.name, pd.read_csv(p, low_memory=False)))
        (cfg.io.reports_dir / "data_profile.md").write_text("\n".join(lines), encoding="utf-8")
        return det

    tables = _read_raw_tables(det)
    for name, df in tables.items():
        lines.append(_profile_table(name, df))

    if det.format == "J":
        m = tables["matches (flattened info)"]
        d = tables["deliveries (flattened)"]
        i = tables["innings (flattened)"]
        lines += _json_summary(m, i, d)
        per_file = (d.groupby("match_id").agg(deliveries=("file_order", "size"),
                                              innings=("innings", "max"))
                    .reindex(m["match_id"]).fillna(0).astype(int).reset_index())
        per_file.insert(0, "file", m["file"].values)
        per_file.insert(2, "data_version", m["data_version"].values)
        lines += ["## Appendix: every file", "", md_table(per_file), ""]

    cfg.io.reports_dir.mkdir(parents=True, exist_ok=True)
    (cfg.io.reports_dir / "data_profile.md").write_text("\n".join(lines), encoding="utf-8")
    return det


def _json_summary(m: pd.DataFrame, i: pd.DataFrame, d: pd.DataFrame) -> list[str]:
    """Facts about the Cricsheet JSON data that matter for cleaning (design section 5)."""
    years = pd.to_datetime(m["date"]).dt.year
    by_year = (pd.DataFrame({"year": years, "label": m["season"]})
               .groupby("year").agg(matches=("label", "size"),
                                    season_labels=("label", lambda s: ", ".join(sorted(set(s)))))
               .reset_index())
    wk_kinds = Counter(pd.concat([d["wicket_kind_1"], d["wicket_kind_2"]]).dropna())
    multi = int((d["n_wickets"] > 1).sum())
    so = i[i["super_over"]]
    inn3 = i[i["innings"] >= 3]
    sums_ok = int((d["runs_total"] == d["runs_batter"] + d["runs_extras"]).sum())
    ex_sum = d[["extras_wides", "extras_noballs", "extras_byes", "extras_legbyes",
                "extras_penalty"]].sum(axis=1)
    ex_ok = int((ex_sum == d["runs_extras"]).sum())
    i2 = i[i["innings"] == 2]
    lines = [
        "## Summary for cleaning",
        "",
        "Matches per calendar year of the first match date, with the raw season labels. Season is "
        "taken from the date year (requirement 1.5) because labels like `2007/08` are ambiguous.",
        "",
        md_table(by_year),
        "",
        f"- Matches: {len(m):,}; deliveries (all innings): {len(d):,}.",
        f"- Matches with more than one date: {int((m['n_dates'] > 1).sum())}.",
        f"- Outcome results: {m['outcome_result'].value_counts(dropna=False).to_dict()}.",
        f"- Outcome methods: {m['outcome_method'].value_counts(dropna=False).to_dict()}.",
        f"- Matches with innings >= 3: {inn3['match_id'].nunique()} "
        f"(super-over flag set on {len(so)} innings).",
        f"- Innings-2 rows with a provided target: {int(i2['target_runs'].notna().sum())} of "
        f"{len(i2)}; target overs != 20: {int((i2['target_overs'].notna() & (i2['target_overs'] != 20)).sum())}.",
        f"- Innings with penalty runs (pre/post): "
        f"{int(i['penalty_runs_pre'].notna().sum())}/{int(i['penalty_runs_post'].notna().sum())}.",
        f"- Deliveries with 2 dismissals: {multi}.",
        f"- Dismissal kinds: {dict(sorted(wk_kinds.items()))}.",
        f"- runs_total == runs_batter + runs_extras on {sums_ok:,} of {len(d):,} deliveries.",
        f"- Sum of extras breakdown == runs_extras on {ex_ok:,} of {len(d):,} deliveries.",
        f"- Wides: {int((d['extras_wides'] > 0).sum()):,}; no-balls: "
        f"{int((d['extras_noballs'] > 0).sum()):,}.",
        f"- Non-standard `overs` / `balls_per_over`: "
        f"{int((m['overs'] != 20).sum())} / {int((m['balls_per_over'] != 6).sum())}.",
        "",
    ]
    return lines


# --------------------------------------------------------------------------------------------
# Adapters: raw -> canonical (design 4.3)
# --------------------------------------------------------------------------------------------
def _finalise(matches: pd.DataFrame, deliveries: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Common last step of every adapter: season from date year, dtypes, runs_total assertion."""
    matches = matches.copy()
    matches["date"] = pd.to_datetime(matches["date"], format="mixed")
    matches["season"] = matches["date"].dt.year
    deliveries = deliveries.copy()
    for c in ("dismissal_kind", "dismissal_kind_2"):
        deliveries[c] = deliveries[c].astype("string").str.strip().str.lower()
        deliveries.loc[deliveries[c] == "", c] = pd.NA
    m = enforce_schema(matches, MATCHES_DTYPES, "matches")
    d = enforce_schema(deliveries, DELIVERIES_DTYPES, "deliveries")
    bad = d["runs_total"] != d["runs_batter"] + d["runs_extras"]
    if bad.any():
        r = d[bad].iloc[0]
        raise DataQualityError(f"runs_total != runs_batter + runs_extras on {int(bad.sum())} "
                               f"deliveries, first: match {r.match_id} innings {r.innings} "
                               f"seq {r.seq}")
    if not set(m["outcome_type"]).issubset(OUTCOME_TYPES):
        raise DataQualityError(f"unexpected outcome_type values {set(m['outcome_type'])}")
    d = d.sort_values(["match_id", "innings", "seq"], kind="stable").reset_index(drop=True)
    return m, d


def _other_team(batting: pd.Series, team1: pd.Series, team2: pd.Series) -> pd.Series:
    return team2.where(batting == team1, team1)


def adapt_cricsheet_json(files: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """J adapter (design refinement D7): Cricsheet JSON files -> canonical tables.

    Mapping mirrors the C adapter: winner, result ("tie" / "no result") and method come from
    `info.outcome`; a super-over `eliminator` also marks a tie. The innings-2 `target` block gives
    `target_runs_provided` / `target_overs_provided`. `seq` is the file order within each innings,
    which is bowling order. Innings numbers are positions in the file (super overs are 3+).
    """
    rm, ri, rd = read_cricsheet_json(files)
    if (ri["super_over"] != (ri["innings"] >= 3)).any():
        raise DataQualityError("Cricsheet super_over flag does not match innings number >= 3")

    i2 = ri[ri["innings"] == 2].set_index("match_id")
    m = pd.DataFrame({
        "match_id": rm["match_id"],
        "date": rm["date"],
        "venue": rm["venue"],
        "city": rm["city"],
        "team1": rm["team1"],
        "team2": rm["team2"],
        "winner": rm["outcome_winner"],
        "method": rm["outcome_method"],
    })
    res = rm["outcome_result"]
    m["outcome_type"] = "normal"
    m.loc[m["winner"].isna(), "outcome_type"] = "no_result"
    m.loc[res.eq("no result"), "outcome_type"] = "no_result"
    m.loc[res.eq("tie") | rm["outcome_eliminator"].notna(), "outcome_type"] = "tie"
    m["target_runs_provided"] = rm["match_id"].map(i2["target_runs"]).astype("Int64")
    m["target_overs_provided"] = rm["match_id"].map(i2["target_overs"]).astype("Float64")

    teams = rm.set_index("match_id")[["team1", "team2"]]
    t1 = rd["match_id"].map(teams["team1"])
    t2 = rd["match_id"].map(teams["team2"])
    d = pd.DataFrame({
        "match_id": rd["match_id"],
        "innings": rd["innings"],
        "seq": rd["file_order"],
        "batting_team": rd["team"],
        "bowling_team": _other_team(rd["team"], t1, t2),
        "batter": rd["batter"],
        "bowler": rd["bowler"],
        "runs_batter": rd["runs_batter"],
        "runs_extras": rd["runs_extras"],
        "runs_total": rd["runs_total"],
        "is_wide": rd["extras_wides"].fillna(0) > 0,
        "is_noball": rd["extras_noballs"].fillna(0) > 0,
        "is_bye": rd["extras_byes"].fillna(0) > 0,
        "is_legbye": rd["extras_legbyes"].fillna(0) > 0,
        "is_penalty": rd["extras_penalty"].fillna(0) > 0,
        "dismissal_kind": rd["wicket_kind_1"],
        "dismissal_kind_2": rd["wicket_kind_2"],
        "n_dismissals": rd["n_wickets"],
    })
    return _finalise(m, d)


def _pick(df: pd.DataFrame, alts: tuple[str, ...], required: bool = True) -> pd.Series | None:
    for a in alts:
        if a in df.columns:
            return df[a]
    if required:
        raise SchemaNotRecognised(f"none of the columns {alts} found")
    return None


def adapt_kaggle(deliveries_csv: Path, matches_csv: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """K adapter: Kaggle-style `deliveries.csv` + `matches.csv` -> canonical tables (design 4.3)."""
    rd = pd.read_csv(deliveries_csv, low_memory=False)
    rm = pd.read_csv(matches_csv, low_memory=False)
    rd.columns = [c.strip().lower() for c in rd.columns]
    rm.columns = [c.strip().lower() for c in rm.columns]

    def col(df: pd.DataFrame, name: str, default=None) -> pd.Series:
        return df[name] if name in df.columns else pd.Series(default, index=df.index)

    m = pd.DataFrame({
        "match_id": _pick(rm, ("match_id", "id")).astype(str),
        "date": rm["date"],
        "venue": col(rm, "venue"),
        "city": col(rm, "city"),
        "team1": rm["team1"],
        "team2": rm["team2"],
        "winner": rm["winner"],
        "method": col(rm, "method"),
    })
    m.loc[m["method"].astype("string").str.upper().isin(["NA", ""]), "method"] = None
    result = col(rm, "result").astype("string").str.lower()
    super_over = col(rm, "super_over").astype("string").str.upper()
    m["outcome_type"] = "normal"
    m.loc[result.eq("no result").fillna(False) | m["winner"].isna(), "outcome_type"] = "no_result"
    m.loc[result.eq("tie").fillna(False) | super_over.eq("Y").fillna(False), "outcome_type"] = "tie"
    m["target_runs_provided"] = pd.to_numeric(col(rm, "target_runs"), errors="coerce")
    m["target_overs_provided"] = pd.to_numeric(col(rm, "target_overs"), errors="coerce")

    rd["_row"] = range(len(rd))
    rd["_mid"] = _pick(rd, ("match_id", "id")).astype(str)
    rd["_inn"] = _pick(rd, ("inning", "innings")).astype(int)
    # `over` may be 0-based; it is used for ordering only.
    rd = rd.sort_values(["_mid", "_inn", "over", "ball", "_row"], kind="stable")
    rd["_seq"] = rd.groupby(["_mid", "_inn"]).cumcount()
    teams = m.set_index("match_id")[["team1", "team2"]]
    bowling = col(rd, "bowling_team")
    if bowling.isna().all():
        bowling = _other_team(rd["batting_team"], rd["_mid"].map(teams["team1"]),
                              rd["_mid"].map(teams["team2"]))
    et = col(rd, "extras_type").astype("string").str.lower().fillna("")
    is_w = pd.to_numeric(col(rd, "is_wicket", 0), errors="coerce").fillna(0).astype(int)
    kind = col(rd, "dismissal_kind").astype("string")
    kind = kind.where(is_w > 0, pd.NA)
    d = pd.DataFrame({
        "match_id": rd["_mid"],
        "innings": rd["_inn"],
        "seq": rd["_seq"],
        "batting_team": rd["batting_team"],
        "bowling_team": bowling,
        "batter": _pick(rd, ("batter", "batsman", "striker")),
        "bowler": rd["bowler"],
        "runs_batter": _pick(rd, ("batsman_runs", "runs_batter")),
        "runs_extras": _pick(rd, ("extra_runs", "extras")),
        "runs_total": rd["total_runs"],
        "is_wide": et.eq("wides"),
        "is_noball": et.eq("noballs"),
        "is_bye": et.eq("byes"),
        "is_legbye": et.eq("legbyes"),
        "is_penalty": et.eq("penalty"),
        "dismissal_kind": kind,
        "dismissal_kind_2": pd.Series(pd.NA, index=rd.index, dtype="string"),
        "n_dismissals": is_w,
    })
    return _finalise(m, d)


def _read_info_csv(path: Path) -> dict[str, list[str]]:
    """Parse a Cricsheet `<id>_info.csv` (rows `info,<key>,<value>[,...]`) into key -> values."""
    import csv

    out: dict[str, list[str]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 3 and row[0] == "info":
                out.setdefault(row[1], []).append(row[2])
    return out


def adapt_cricsheet_csv(delivery_files: list[Path], info_files: list[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """C adapter: Cricsheet CSV v2 files -> canonical tables (design 4.3).

    `seq` is the row order inside each match's delivery file, which is bowling order.
    """
    m_rows = []
    for p in info_files:
        info = _read_info_csv(p)
        teams = info.get("team", [None, None]) + [None, None]
        outcome = (info.get("outcome") or [None])[0]
        winner = (info.get("winner") or [None])[0]
        m_rows.append({
            "match_id": p.name[: -len("_info.csv")],
            "date": min(info["date"]),
            "venue": (info.get("venue") or [None])[0],
            "city": (info.get("city") or [None])[0],
            "team1": teams[0],
            "team2": teams[1],
            "winner": winner,
            "method": (info.get("method") or [None])[0],
            "outcome_type": ("tie" if outcome == "tie" or info.get("eliminator")
                             else "no_result" if outcome == "no result" or winner is None
                             else "normal"),
            "target_runs_provided": None,
            "target_overs_provided": None,
        })
    m = pd.DataFrame(m_rows)

    frames = []
    for p in delivery_files:
        df = pd.read_csv(p, low_memory=False)
        df["_row"] = range(len(df))
        frames.append(df)
    rd = pd.concat(frames, ignore_index=True)
    rd["match_id"] = rd["match_id"].astype(str)
    rd = rd.sort_values(["match_id", "innings", "_row"], kind="stable")
    num = lambda c: pd.to_numeric(rd[c], errors="coerce").fillna(0)  # noqa: E731
    d = pd.DataFrame({
        "match_id": rd["match_id"],
        "innings": rd["innings"].astype(int),
        "seq": rd.groupby(["match_id", "innings"]).cumcount(),
        "batting_team": rd["batting_team"],
        "bowling_team": rd["bowling_team"],
        "batter": rd["striker"],
        "bowler": rd["bowler"],
        "runs_batter": num("runs_off_bat").astype(int),
        "runs_extras": num("extras").astype(int),
        "is_wide": num("wides") > 0,
        "is_noball": num("noballs") > 0,
        "is_bye": num("byes") > 0,
        "is_legbye": num("legbyes") > 0,
        "is_penalty": num("penalty") > 0,
        "dismissal_kind": rd["wicket_type"],
        "dismissal_kind_2": rd["other_wicket_type"],
        "n_dismissals": rd["wicket_type"].notna().astype(int) + rd["other_wicket_type"].notna().astype(int),
    })
    d["runs_total"] = d["runs_batter"] + d["runs_extras"]
    return _finalise(m, d)


def adapt_column_map(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Manual adapter driven by `config/column_map.yaml` (used only when detection fails).

    The YAML has `matches_file` / `deliveries_file` (paths relative to raw_dir) and, under
    `matches:` and `deliveries:`, the raw column name for each canonical column. Boolean extras
    columns must already be 0/1 or True/False in the raw file.
    """
    import yaml

    spec = yaml.safe_load((cfg.path.parent / "column_map.yaml").read_text(encoding="utf-8"))
    for key in ("matches_file", "deliveries_file"):
        if not spec.get(key):
            raise SchemaNotRecognised(f"column_map.yaml: `{key}` is empty")
    rm = pd.read_csv(cfg.io.raw_dir / spec["matches_file"], low_memory=False)
    rd = pd.read_csv(cfg.io.raw_dir / spec["deliveries_file"], low_memory=False)

    def mapped(df: pd.DataFrame, mapping: dict[str, str], cols: list[str]) -> pd.DataFrame:
        empty = [c for c in cols if not mapping.get(c)]
        if empty:
            raise SchemaNotRecognised(f"column_map.yaml: no source column for {empty}")
        return pd.DataFrame({c: df[mapping[c]] for c in cols})

    mcols = [c for c in CANONICAL_MATCHES if c != "season"]
    m = mapped(rm, spec["matches"], mcols)
    dcols = [c for c in CANONICAL_DELIVERIES if c != "dismissal_kind_2"]
    d = mapped(rd, spec["deliveries"], dcols)
    d["dismissal_kind_2"] = pd.NA
    return _finalise(m, d)


def adapt(cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Detect the raw layout and map it to canonical (matches, deliveries, format_code)."""
    det = detect_format(cfg.io.raw_dir)
    if det.format == "J":
        m, d = adapt_cricsheet_json(det.files)
    elif det.format == "K":
        hdr = {p: _csv_header(p) for p in det.files}
        deliv = [p for p, h in hdr.items() if "total_runs" in h]
        match = [p for p in det.files if p not in deliv]
        m, d = adapt_kaggle(deliv[0], match[0])
    elif det.format == "C":
        info = [p for p in det.files if p.name.endswith("_info.csv")]
        deliv = [p for p in det.files if p not in info]
        m, d = adapt_cricsheet_csv(deliv, info)
    elif (cfg.path.parent / "column_map.yaml").exists():
        m, d = adapt_column_map(cfg)
    else:
        require_format(cfg)  # raises SchemaNotRecognised with the template
        raise AssertionError("unreachable")
    return m, d, det.format
