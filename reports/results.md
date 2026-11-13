# Results (test seasons, scored once)

Models were refit on train + validation (2008–2024, 1039 chases, 120,079 model rows) with the settings chosen on validation, then scored once on the test seasons 2025, 2026 (138 chases, 15,776 model rows; 138 terminal rows excluded from the main metrics). See `reports/TEST_LOCK.json`.

Best model for the website (chosen on validation before this run): **GBM**.

## Verdicts

- LR-full beats the baseline (BSS 0.177, 95% interval [0.119, 0.230]).
- LR-core beats the baseline (BSS 0.161, 95% interval [0.118, 0.203]).
- We cannot say GBM beats the baseline: the 95% interval [-0.320, 0.009] includes 0 (BSS -0.148).
- GBM vs LR-full: GBM is worse than LR-full (BSS -0.395, 95% interval [-0.641, -0.182]).

## Test metrics

Model rows only. BSS intervals: 1000 bootstrap resamples of whole test matches, the same resamples for every method. `brier_all_rows` adds the terminal rows, scored with their rule-based outcome, for comparison with sources that include them.

| method | brier | log_loss | ece | bss_vs_baseline [95% CI] | brier_all_rows |
|---|---|---|---|---|---|
| Baseline | 0.1516 | 0.5117 | 0.1323 |  | 0.1503 |
| LR-full | 0.1248 | 0.3908 | 0.0817 | 0.177 [0.119, 0.230] | 0.1237 |
| LR-core | 0.1272 | 0.4008 | 0.0936 | 0.161 [0.118, 0.203] | 0.1261 |
| GBM | 0.1740 | 0.5652 | 0.1372 | -0.148 [-0.320, 0.009] | 0.1725 |

Validation vs test:

| method | val brier | test brier | val ece | test ece |
|---|---|---|---|---|
| Baseline | 0.1353 | 0.1516 | 0.0764 | 0.1323 |
| LR-full | 0.1205 | 0.1248 | 0.0533 | 0.0817 |
| LR-core | 0.1211 | 0.1272 | 0.0585 | 0.0936 |
| GBM | 0.1161 | 0.1740 | 0.0630 | 0.1372 |

## By phase

| phase | rows | chases | brier Baseline | brier LR-full | brier LR-core | brier GBM | BSS LR-full | BSS LR-core | BSS GBM |
|---|---|---|---|---|---|---|---|---|---|
| powerplay | 5199 | 138 | 0.2075 | 0.1740 | 0.1789 | 0.2199 | 0.162 [0.109, 0.208] | 0.138 [0.091, 0.181] | -0.060 [-0.171, 0.056] |
| middle | 7596 | 138 | 0.1380 | 0.1146 | 0.1170 | 0.1719 | 0.170 [0.089, 0.249] | 0.152 [0.095, 0.210] | -0.245 [-0.481, -0.058] |
| death | 2981 | 128 | 0.0886 | 0.0648 | 0.0629 | 0.0994 | 0.269 [0.163, 0.382] | 0.290 [0.205, 0.388] | -0.122 [-0.426, 0.160] |

## By test season

| season | rows | chases | brier Baseline | brier LR-full | brier LR-core | brier GBM | BSS LR-full | BSS LR-core | BSS GBM |
|---|---|---|---|---|---|---|---|---|---|
| 2025 | 7765 | 68 | 0.1510 | 0.1333 | 0.1310 | 0.1601 | 0.117 [0.041, 0.196] | 0.132 [0.075, 0.190] | -0.060 [-0.251, 0.142] |
| 2026 | 8011 | 70 | 0.1522 | 0.1165 | 0.1235 | 0.1875 | 0.234 [0.164, 0.299] | 0.189 [0.133, 0.239] | -0.232 [-0.495, 0.007] |

## Drift check

Validation uses the train-only model from the tune stage; test seasons use the final model.

- (validation) In 2024 the GBM under-predicted chases by 9.2 points at the start of the chase (mean 0.422 vs observed 0.514 over 70 chases); over all model rows the mean prediction was 0.420 vs observed 0.483.
- (test) In 2025 the GBM under-predicted chases by 12.2 points at the start of the chase (mean 0.393 vs observed 0.515 over 68 chases); over all model rows the mean prediction was 0.429 vs observed 0.486.
- (test) In 2026 the GBM under-predicted chases by 27.5 points at the start of the chase (mean 0.367 vs observed 0.643 over 70 chases); over all model rows the mean prediction was 0.437 vs observed 0.631.

## Failure cases

Test chases where GBM's match-level Brier most exceeds the baseline's:

- `1473466`: Delhi Capitals chasing 206 against Mumbai Indians (2025-04-13), lost. GBM match Brier 0.681 vs baseline 0.217 (+0.464).
- `1529279`: Sunrisers Hyderabad chasing 229 against Rajasthan Royals (2026-04-25), won. GBM match Brier 0.748 vs baseline 0.287 (+0.460).
- `1473479`: Rajasthan Royals chasing 206 against Royal Challengers Bengaluru (2025-04-24), lost. GBM match Brier 0.655 vs baseline 0.197 (+0.459).
- `1529286`: Delhi Capitals chasing 226 against Rajasthan Royals (2026-05-01), won. GBM match Brier 0.815 vs baseline 0.366 (+0.450).
- `1529290`: Mumbai Indians chasing 229 against Lucknow Super Giants (2026-05-04), won. GBM match Brier 0.771 vs baseline 0.343 (+0.428).

Biggest upsets (lowest probability GBM gave the eventual winner at any model row):

- `1473468`: Kolkata Knight Riders chasing 112 against Punjab Kings (2025-04-15), lost. GBM gave the defending team only 0.1% after ball 8.6 (needed 41 from 66 balls with 7 wickets left).
- `1527687`: Delhi Capitals chasing 211 against Gujarat Titans (2026-04-08), lost. GBM gave the defending team only 0.9% after ball 19.4 (needed 2 from 2 balls with 3 wickets left).
- `1473507`: Royal Challengers Bengaluru chasing 228 against Lucknow Super Giants (2025-05-27), won. GBM gave the chasing team only 1.0% after ball 11.2 (needed 105 from 52 balls with 6 wickets left).
- `1473464`: Sunrisers Hyderabad chasing 246 against Punjab Kings (2025-04-12), won. GBM gave the chasing team only 1.2% after ball 0.1 (needed 246 from 119 balls with 10 wickets left).
- `1529284`: Sunrisers Hyderabad chasing 244 against Mumbai Indians (2026-04-29), won. GBM gave the chasing team only 1.2% after ball 0.1 (needed 244 from 119 balls with 10 wickets left).

Featured match for the website (largest swing in GBM's probability): `1527688` (swing 0.952).

## Baseline level usage on test

| level | share of test rows |
|---|---|
| A | 96.5% |
| B | 2.7% |
| C | 0.8% |
| D | 0.0% |

## Exclusions

| reason | matches |
|---|---|
| DLS | 23 |
| TIE | 16 |
| REDUCED_OVERS | 12 |
| NO_RESULT | 9 |
| CHASE_INCOMPLETE | 6 |

## Limitations

The estimates describe historical IPL chases with a full 20-over target only: not first innings, not DLS or shortened matches, not ties or no-results. Inputs are the scoreboard state only (runs needed, balls left, wickets left, target, required rate, last-18-ball runs and wickets); team strength, venue, players and conditions are ignored, so the probabilities are league-average and say nothing about why teams win. Validation is a single season of about 70 chases, so tuning choices are noisy. The validation and test seasons fall in the Impact Player era, which is barely represented in training; recency weighting (D8) reduces but does not remove the drift reported above. This is not a betting tool.

Figures: `reports/figures/`.
