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
(repository: https://github.com/Vinit230606/ipl-win-probability). The site's
[write-up](https://vinit230606.github.io/ipl-win-probability/about.html) walks from the question
to the conclusions; this repository lets you check every step.

## Where to find what
| To check | Look at |
|---|---|
| Question, prediction rules, claim limits | `docs/about.html` (live write-up), `reports/results.md` |
| Raw data and its profile | `ipl_json.zip`, `reports/data_profile.md` |
| Every excluded match and why | `reports/exclusions.csv`, rules in `src/iplwp/clean.py` |
| Per-season counts, data checks | `reports/data_quality.md` |
| Exact split of every kept chase | `reports/splits.csv` (match id, season, split, teams, target, result) |
| Scoreboard rebuild and features | `src/iplwp/states.py`, `src/iplwp/features.py` |
| Baseline and models | `src/iplwp/baseline.py`, `src/iplwp/models.py` |
| Tuning (every fit, validation only) | `reports/tuning_lr_full.csv`, `reports/tuning_lr_core.csv`, `reports/tuning_gbm.csv`, `reports/validation_results.md` |
| Test results, error analysis, figures | `reports/results.md`, `reports/metrics.json`, `reports/figures/` |
| Post-test diagnosis by target score | `docs/data/results.json` → `diagnostics` (computed by `export.py`, no refit) |
| Proof the test set was scored once | `reports/TEST_LOCK.json`, `src/iplwp/io_lock.py` |
| Tests (leakage, states, metrics, bootstrap, lock, export) | `tests/`, `docs/tests/parity.test.mjs` |
| Edge cases and the calculator fix (post-test) | `reports/edge_cases.md`, `reports/edge_cases.json`, `reports/tuning_edge_cases.csv`, `src/iplwp/simulate.py`, `src/iplwp/edge_cases.py` |
| Every constant and the seed | `config/config.yaml` |
| AI use | `AI_USE.md` and the section below |

The analysis lives in Python modules and the generated reports rather than notebooks, so one
command reruns all of it.

## Data
Ball-by-ball data from [Cricsheet](https://cricsheet.org/) (`ipl_json.zip`, 1,243 IPL matches,
JSON format 1.2.0/1.3.0), licensed under the Open Data Commons Attribution License (ODC-By).
The pipeline reads them from `data/raw/cricsheet_json/` and never modifies them. That folder is
not in git (100 MB); on a fresh clone, unzip the committed `ipl_json.zip` (identical files) there:
```
Expand-Archive ipl_json.zip -DestinationPath data/raw/cricsheet_json   # Windows
unzip ipl_json.zip -d data/raw/cricsheet_json                         # macOS / Linux
```
The latest version of the archive is at https://cricsheet.org/downloads/ipl_json.zip. It grows
every season, so use the committed copy to reproduce these results.

## Setup (Windows PowerShell)
```
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
```
On macOS/Linux use `python3 -m venv .venv && source .venv/bin/activate`.

The website uses Chart.js 4.4.1, vendored at `docs/assets/vendor/chart.umd.min.js`, so it
never depends on a CDN.

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
| `edgecases` | post-test addition: ball-by-ball simulation and blended calculator for rare states | 30 s |
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

To reproduce on a fresh clone: unzip the data, then run `python -m iplwp.cli all --force --reason
"reproduction"`. The committed `reports/TEST_LOCK.json` makes `final` refuse to rescore the test
seasons without `--force`; the forced run is appended to the lock file, so it stays visible.
Tuning takes about 13 minutes on a 16-thread laptop. Compare the new `reports/metrics.json` with
the committed one (`git diff reports/metrics.json`); only the two timing fields should change.

`models/` is not committed (it can be rebuilt). The settings chosen on validation are in
`reports/validation_results.md`, `reports/metrics.json` (`chosen_params`) and the copy of
`models/selection.json` stored in `reports/TEST_LOCK.json`.

## Changes to the design plan
- **D9 (post-test): calculator fix for situations the data never reached.** LR-core extrapolated to
  near-certainties there, for example 0.06% (shown as 0%) for 42 needed off 42 balls with one wicket
  left. `make edgecases` adds a ball-by-ball simulation: delivery outcome chances per
  phase × wickets × required-rate context, shrunk towards coarser contexts, solved exactly by
  dynamic programming and Platt-recalibrated. The calculator then blends LR-core and the simulation
  with weight n / (n + k), where n is the number of fitting chases in a 5-run × 6-ball cell, and
  applies a monotone envelope so cricket logic holds. Shrinkage and k were chosen on validation log
  loss. Because the test seasons had already been scored, the test numbers for this fix are
  reported as a post-test check (`reports/edge_cases.md`), and the main results and the replay are
  unchanged. The fix costs a little validation accuracy on common states (log loss 0.3829 vs
  0.3813) and is sometimes confidently wrong where data is thin; both are reported on the site's
  Edge cases page. `docs/tests/parity.test.mjs` checks that the JavaScript calculator matches
  Python on 250 states and has no monotonicity violations.
- **Site theme ("Under the lights", `.kiro/steering/ipl-ui-theme.md`).** A floodlit night match
  (navy night theme by default, a day-match theme under `prefers-color-scheme: light`), Barlow
  Condensed and Barlow, and team colour as the one bold element. Opening a chase dresses the TV-style
  score strip, the win predictor bar and the two halves of the chart in the chasing and defending
  teams' colours. Team kits and the OKLCH clash rule live in `docs/assets/js/teams.js` (approximate
  kit colours, short codes on badges, no logos). Model lines stay neutral. Kept from the earlier
  designs: the hero search, the "go further" links, the result card, the numbered preprocessing
  steps and the accessible tables. This is a visual and copy pass only; no data file or number
  changed. `docs/tests/teams.test.mjs` checks every match-up of the ten current teams in both themes,
  and `docs/tests/result_text.test.mjs` checks the rebuilt result sentences against the data.
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
- **Write-up page.** The course asks for the full reasoning on the website, so `about.html` became a
  write-up in twelve sections (question to citations), filled from `results.json` by `about.js`.
  `make export` also adds data facts (sizes, quality checks, per-season targets) to
  `results.json` and copies the report figures to `docs/assets/figures/`. The Replay page opens
  with a short summary and links to the write-up, results and repository.
- The website is otherwise plain HTML/CSS/JS as designed, plus a shared `lr_core.js` used by both
  the calculator and the Node parity test, `repo.js` for repository links, and
  `docs/package.json` (marks the JS as ES modules for Node).
- `make features` also writes `reports/splits.csv`, the split of every kept chase.
- Python 3.13 with the nearest package versions that install on it (see `requirements.txt`),
  because no working Python 3.11 is installed on the development machine.

## AI use
We used Kiro, an AI coding assistant running Anthropic's Claude, throughout the build. We wrote
the project proposal, the design (`design.md`) and the task plan first. The assistant then wrote
most of the code, tests, reports and website, task by task. We made the decisions at fixed review
points: approving the Cricsheet JSON adapter, the exclusion rules, the recency weighting for the
Impact Player era, the model settings before the test run, and how to present GBM's test failure.
`AI_USE.md` logs each step, what the tool did and what we checked by hand.

## Citations
- Cricsheet. IPL ball-by-ball data, JSON format, https://cricsheet.org/ (accessed 2026).
  Open Data Commons Attribution License (ODC-By 1.0).
- Pedregosa, F. et al. (2011). Scikit-learn: Machine learning in Python. *Journal of Machine
  Learning Research* 12, 2825?2830. (`LogisticRegression`, `HistGradientBoostingClassifier`,
  `StandardScaler`.)
- Ke, G. et al. (2017). LightGBM: A highly efficient gradient boosting decision tree. *NeurIPS*.
  (The histogram method behind `HistGradientBoostingClassifier`.)
- Brier, G. W. (1950). Verification of forecasts expressed in terms of probability. *Monthly
  Weather Review* 78(1), 1?3.
- Efron, B. and Tibshirani, R. J. (1993). *An Introduction to the Bootstrap*. Chapman & Hall.
- Naeini, M. P., Cooper, G. and Hauskrecht, M. (2015). Obtaining well calibrated probabilities
  using Bayesian binning. *AAAI*. (Expected calibration error.)
- The pandas development team, pandas; Harris, C. R. et al. (2020), Array programming with
  NumPy, *Nature* 585; Hunter, J. D. (2007), Matplotlib: A 2D graphics environment, *Computing in
  Science & Engineering* 9(3); Chart.js 4.4.1, https://www.chartjs.org/ (MIT licence); Barlow
  typeface by Jeremy Tribby, Google Fonts (SIL Open Font License).
