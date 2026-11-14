# IPL Win Probability

ES 335 course project by Vinit Parmar (24110239) and Dutt Parmar (24110115).

After every delivery of the second innings of a completed, full 20-over IPL chase, we estimate the
probability that the chasing team wins, using only the match state known at that moment. We compare
a historical lookup-table baseline against logistic regression and gradient-boosted trees, and
publish the results as a static website in `docs/`.

## Results in brief
Test seasons 2025–2026 (138 chases, 15,776 balls), scored once. Full report: `reports/results.md`.

| Method | Test Brier | Skill vs baseline [95% interval] |
|---|---|---|
| Baseline (lookup table) | 0.1516 | |
| LR-full | 0.1248 | 0.177 [0.119, 0.230]: beats the baseline |
| LR-core (calculator) | 0.1272 | 0.161 [0.118, 0.203]: beats the baseline |
| GBM | 0.1740 | −0.148 [−0.320, 0.009]: not shown to beat it |

GBM had the best validation score (2024) but failed on test. Tree models cannot extrapolate, and
targets above 220 were rare and almost always defended in 2008–2024 but are often chased in
2025–2026. Logistic regression changes smoothly with the target and handled the shift.

Live site: https://vinit230606.github.io/ipl-win-probability/
(repository: https://github.com/Vinit230606/ipl-win-probability).

## Data
Ball-by-ball data from [Cricsheet](https://cricsheet.org/) (`ipl_json.zip`, 1,243 IPL matches,
JSON format 1.2.0/1.3.0), licensed under the Open Data Commons Attribution License (ODC-By).
The pipeline reads them from `data/raw/cricsheet_json/` and never modifies them. That folder is
not in git (100 MB); on a fresh clone, unzip the committed `ipl_json.zip` (identical files) there:
```
Expand-Archive ipl_json.zip -DestinationPath data/raw/cricsheet_json
```

## Setup (Windows PowerShell)
```
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```
On macOS/Linux use `python3 -m venv .venv && source .venv/bin/activate`.

The website needs Chart.js 4.4.1, vendored at `docs/assets/vendor/chart.umd.min.js`. Download it
once and commit it:
```
Invoke-WebRequest https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.js -OutFile docs/assets/vendor/chart.umd.min.js
```
Without it the pages still load their numbers and tables and show a notice instead of charts.

## Commands
Every stage runs as `python -m iplwp.cli <stage>`; with `make` installed, `make <stage>` does the same.

| Stage | What it does | Time |
|---|---|---|
| `profile` | inspect raw files, write `reports/data_profile.md` | 30 s |
| `data` | adapt + clean + reconstruct chase states | 10 s |
| `features` | leakage-safe features and the season split | 5 s |
| `baseline` | lookup table fit on train, scored on validation | 5 s |
| `tune` | tune LR and GBM on validation only | ~13 min |
| `final` | refit on train + validation, evaluate the test seasons once | 1 min |
| `export` | write and validate the website JSON in `docs/data/` | 20 s |
| `all` | every stage above in order | ~15 min |

`final` refuses to run again once `reports/TEST_LOCK.json` exists. A rerun needs
`final --force --reason "<why>"` and is recorded in the lock file.

Tests: `python -m pytest -q` then `node docs/tests/parity.test.mjs` (both are in `make test`).
Preview the site: `python -m http.server -d docs 8000`, then open http://localhost:8000.

## Deploying the website
GitHub Pages serves the `docs/` folder of `main` (Settings → Pages → Deploy from a branch →
`main` / `docs`). Every push to `main` redeploys the site within a minute or two. `docs/data/` is
committed; `.venv`, `data/interim`, `data/processed` and `models/` are not. All asset paths are
relative, so the site works under `https://<user>.github.io/<repo>/`.

## Reproducibility
`config/config.yaml` holds every constant; all randomness uses `seed: 42`. The whole pipeline was
rerun from scratch in a separate folder (its own `models/` and `reports/`, so the real test lock
was not touched). It reproduced every setting and metric. Two consecutive `final` runs there wrote
byte-identical `metrics.json`. Timing values (`fit_seconds`) were dropped from the chosen settings
after this check. The real `reports/metrics.json`, written before that fix, still contains two
such timing fields; the metrics themselves are unaffected.

## Changes to the design plan
- **D7 (approved):** the data is Cricsheet JSON, so `io_adapters.py` has a third adapter, "J",
  next to the planned Kaggle ("K") and Cricsheet CSV ("C") adapters. It follows the C mapping rules.
- The canonical deliveries table has one extra column, `dismissal_kind_2`, holding the kind of a
  second dismissal on the same ball. It is needed for the rule "count both unless a kind is
  non-wicket". The current data has no double dismissals.
- **D8 (approved): recency weighting for the Impact Player era.** LR-full, LR-core and GBM
  weight each training row by `0.5 ** ((latest fitting season − season) / half_life)`,
  normalised to mean 1. The half-life is a tuning choice from {uniform, 8, 4, 2} seasons, picked
  on validation Brier like every other setting. The inputs and prediction rules are unchanged, and
  the baseline stays unweighted. GBM tries the half-lives on its 10 best uniform-weight configs
  rather than on all 216 (`config.yaml: recency`). The drift check (design 11.5) reports whether
  predictions are biased in the Impact Player seasons.
- **Replay shows two models (decided after the test run).** `models/selection.json` names GBM
  as the website's main model, and that was not changed. Because GBM lost to LR-full on test, the
  replay also draws LR-full as a second line (the `p_other` field, already in the design). The
  results page explains the choice.
- **Post-test diagnosis table.** `make export` adds a "by target score" table to `results.json`,
  computed from the stored test predictions. No model is refit or changed.
- The website is mostly plain HTML/CSS/JS as designed. There is also an `about.js` that fills the
  About page numbers from `results.json`, a shared `lr_core.js` used by both the calculator and
  the Node parity test, and `docs/package.json` (marks the JS as ES modules for Node).
- Python 3.13 with the nearest package versions that install on it (see `requirements.txt`),
  because no working Python 3.11 is installed on the development machine.
