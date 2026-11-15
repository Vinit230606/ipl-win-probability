# Edge cases (post-test addition)

Added after the test seasons were scored, to fix near-certain calculator outputs in states the data never reached. Settings were chosen on validation; test numbers are a post-test check, not a clean test. Code: `src/iplwp/simulate.py`, `src/iplwp/edge_cases.py`.

Chosen on validation log loss: simulation shrinkage 5, blend k 1 (LR-core weight n/(n+k), n = fitting chases in the 5-run x 6-ball cell). Validation log loss 0.38288 vs LR-core 0.38131; Brier 0.12169 vs 0.12110.

Calculator states with no fitting chase in their cell: 256,554 of 360,000. LR-core gives under 1% or over 99% on 231,060 states, 198,622 of them without data.

| state | chases in cell | LR-core | simulation | LR weight | calculator |
|---|---|---|---|---|---|
| 42 off 42, 1 wkt | 0 | 0.1% | 15.8% | 0.00 | 15.8% |
| 42 off 42, 2 wkt | 0 | 17.0% | 34.1% | 0.00 | 34.1% |
| 42 off 42, 6 wkt | 16 | 91.8% | 90.7% | 0.94 | 91.7% |
| 60 off 42, 1 wkt | 1 | 0.0% | 0.9% | 0.50 | 0.4% |
| 10 off 12, 1 wkt | 3 | 75.5% | 65.4% | 0.75 | 66.6% |
| 1 off 1, 1 wkt | 8 | 89.8% | 76.1% | 0.89 | 82.0% |
| 6 off 1, 10 wkt | 0 | 17.0% | 23.5% | 0.00 | 23.5% |
| 20 off 6, 10 wkt | 0 | 37.3% | 13.7% | 0.00 | 20.1% |
| 36 off 6, 10 wkt | 0 | 5.9% | 0.0% | 0.00 | 1.2% |
| 100 off 30, 10 wkt | 0 | 19.0% | 0.1% | 0.00 | 1.7% |
| 300 off 120, 10 wkt | 0 | 3.1% | 0.1% | 0.00 | 0.1% |
| 1 off 120, 10 wkt | 0 | 100.0% | 100.0% | 0.00 | 100.0% |

| model | test Brier | test log loss | rows without data, Brier | near-certain and wrong |
|---|---|---|---|---|
| lr_core | 0.1272 | 0.4008 | 0.0581 | 0 |
| simulation | 0.1388 | 0.4289 | 0.0446 | 32 |
| calculator | 0.1265 | 0.3979 | 0.0450 | 11 |

Monotonicity violations on the calculator grid:

| model | states_checked | more_runs_raises_p | fewer_balls_raises_p | fewer_wickets_raises_p |
|---|---|---|---|---|
| lr_core | 358800 | 0 | 0 | 0 |
| simulation | 358800 | 368 | 14772 | 10920 |
| blend_before_envelope | 358800 | 3207 | 16038 | 25276 |
| calculator | 358800 | 0 | 0 | 0 |

Tuning log: `reports/tuning_edge_cases.csv`.
