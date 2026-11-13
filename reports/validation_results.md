# Validation results

Everything here uses training and validation seasons only; test seasons are never read by `make baseline` or `make tune`.

## Baseline (lookup table fit on train)

Fit on 112,041 train model rows (969 chases, 2008–2023). Buckets with at least 30 rows: level A 283, B 151, C 25. The train row is in-sample and shown only for reference.

| split | rows | brier | log_loss | ece | level_A | level_B | level_C | level_D |
|---|---|---|---|---|---|---|---|---|
| train | 112041 | 0.1535 | 0.4571 | 0.0014 | 98.3% | 1.2% | 0.5% | 0.0% |
| val | 8038 | 0.1353 | 0.4518 | 0.0764 | 97.0% | 2.3% | 0.8% | 0.0% |

<!-- tuning section: written by the tune stage -->

## Recency weighting (decision D8)

Training rows are weighted 0.5 ** ((latest train season − season) / half-life), normalised to mean 1, to let the models lean towards the Impact Player era (2023 on). Half-lives tried: ['uniform', 8.0, 4.0, 2.0]. Lowest validation Brier per model:

- LR-full: best uniform 0.12234; best weighted 0.12054 (half-life 2). Chosen: half-life 2.
- LR-core: best uniform 0.12418; best weighted 0.12110 (half-life 2). Chosen: half-life 2.
- GBM: best uniform 0.11657; best weighted 0.11614 (half-life 8). Chosen: half-life 8.

## Chosen settings

- LR-full: feature set BASE7_E, C 0.03, half-life 2 seasons.
- LR-core: feature set CORE, C 0.3, half-life 2 seasons.
- GBM: learning_rate 0.03, max_leaf_nodes 15, min_samples_leaf 200, l2 0.0, max_iter 300, monotonic True, half-life 8 seasons.

## Validation metrics (fit on train, scored on validation model rows)

8,038 rows from 70 chases. BSS intervals: 1000 bootstrap resamples of whole matches.

| method | brier | log_loss | ece | bss_vs_baseline |
|---|---|---|---|---|
| Baseline | 0.1353 | 0.4518 | 0.0764 |  |
| LR-full | 0.1205 | 0.3781 | 0.0533 | 0.109 [0.044, 0.169] |
| LR-core | 0.1211 | 0.3813 | 0.0585 | 0.105 [0.051, 0.156] |
| GBM | 0.1161 | 0.3778 | 0.0630 | 0.142 [-0.007, 0.266] |

- LR-full beats the baseline (BSS 0.109, 95% interval [0.044, 0.169]).
- LR-core beats the baseline (BSS 0.105, 95% interval [0.051, 0.156]).
- We cannot say GBM beats the baseline: the 95% interval [-0.007, 0.266] includes 0 (BSS 0.142).
- GBM vs LR-full: We cannot say GBM beats LR-full: the 95% interval [-0.156, 0.191] includes 0 (BSS 0.037).

**Best model for the website: GBM** (lower validation Brier of LR-full and GBM). Written to `models/selection.json` before any test scoring.

## By phase (validation)

| phase | rows | brier Baseline | brier LR-full | brier LR-core | brier GBM | BSS LR-full | BSS LR-core | BSS GBM |
|---|---|---|---|---|---|---|---|---|
| powerplay | 2630 | 0.1658 | 0.1495 | 0.1518 | 0.1395 | 0.098 [0.024, 0.163] | 0.084 [0.014, 0.149] | 0.158 [0.028, 0.280] |
| middle | 3806 | 0.1308 | 0.1182 | 0.1177 | 0.1179 | 0.096 [0.003, 0.185] | 0.100 [0.021, 0.181] | 0.099 [-0.068, 0.254] |
| death | 1602 | 0.0961 | 0.0785 | 0.0789 | 0.0736 | 0.183 [0.030, 0.318] | 0.180 [0.075, 0.328] | 0.234 [-0.050, 0.448] |

## Drift check (validation season, best model)

- In 2024 the GBM under-predicted chases by 9.2 points at the start of the chase (mean 0.422 vs observed 0.514 over 70 chases); over all model rows the mean prediction was 0.420 vs observed 0.483.

## Calibration (validation, 10 equal-width bins)

| method | bin | n | mean_p | observed |
|---|---|---|---|---|
| Baseline | 0.0–0.1 | 2015 | 0.028 | 0.072 |
| Baseline | 0.1–0.2 | 1049 | 0.146 | 0.196 |
| Baseline | 0.2–0.3 | 647 | 0.260 | 0.277 |
| Baseline | 0.3–0.4 | 576 | 0.356 | 0.455 |
| Baseline | 0.4–0.5 | 666 | 0.447 | 0.613 |
| Baseline | 0.5–0.6 | 647 | 0.560 | 0.620 |
| Baseline | 0.6–0.7 | 615 | 0.649 | 0.826 |
| Baseline | 0.7–0.8 | 340 | 0.742 | 0.912 |
| Baseline | 0.8–0.9 | 548 | 0.849 | 0.971 |
| Baseline | 0.9–1.0 | 935 | 0.975 | 0.998 |
| LR-full | 0.0–0.1 | 1850 | 0.039 | 0.027 |
| LR-full | 0.1–0.2 | 987 | 0.146 | 0.187 |
| LR-full | 0.2–0.3 | 699 | 0.248 | 0.296 |
| LR-full | 0.3–0.4 | 525 | 0.345 | 0.410 |
| LR-full | 0.4–0.5 | 451 | 0.452 | 0.483 |
| LR-full | 0.5–0.6 | 640 | 0.552 | 0.541 |
| LR-full | 0.6–0.7 | 583 | 0.649 | 0.808 |
| LR-full | 0.7–0.8 | 616 | 0.749 | 0.877 |
| LR-full | 0.8–0.9 | 626 | 0.847 | 0.950 |
| LR-full | 0.9–1.0 | 1061 | 0.958 | 0.996 |
| LR-core | 0.0–0.1 | 1957 | 0.037 | 0.036 |
| LR-core | 0.1–0.2 | 1002 | 0.146 | 0.187 |
| LR-core | 0.2–0.3 | 681 | 0.251 | 0.339 |
| LR-core | 0.3–0.4 | 510 | 0.351 | 0.408 |
| LR-core | 0.4–0.5 | 478 | 0.452 | 0.441 |
| LR-core | 0.5–0.6 | 640 | 0.552 | 0.608 |
| LR-core | 0.6–0.7 | 579 | 0.649 | 0.839 |
| LR-core | 0.7–0.8 | 595 | 0.750 | 0.891 |
| LR-core | 0.8–0.9 | 584 | 0.849 | 0.959 |
| LR-core | 0.9–1.0 | 1012 | 0.961 | 1.000 |
| GBM | 0.0–0.1 | 2438 | 0.022 | 0.046 |
| GBM | 0.1–0.2 | 770 | 0.146 | 0.177 |
| GBM | 0.2–0.3 | 480 | 0.246 | 0.358 |
| GBM | 0.3–0.4 | 467 | 0.350 | 0.522 |
| GBM | 0.4–0.5 | 563 | 0.455 | 0.581 |
| GBM | 0.5–0.6 | 495 | 0.552 | 0.582 |
| GBM | 0.6–0.7 | 537 | 0.653 | 0.790 |
| GBM | 0.7–0.8 | 478 | 0.747 | 0.824 |
| GBM | 0.8–0.9 | 554 | 0.849 | 0.964 |
| GBM | 0.9–1.0 | 1256 | 0.975 | 0.998 |

## Tuning summaries

LR-full, best C per feature set and half-life:

| feature_set | half_life | val_brier | val_log_loss |
|---|---|---|---|
| BASE7 | 2 | 0.12254 | 0.38339 |
| BASE7 | 4 | 0.12288 | 0.38375 |
| BASE7 | 8 | 0.12348 | 0.38540 |
| BASE7 | uniform | 0.12442 | 0.38757 |
| BASE7_E | 2 | 0.12054 | 0.37813 |
| BASE7_E | 4 | 0.12081 | 0.37767 |
| BASE7_E | 8 | 0.12140 | 0.37859 |
| BASE7_E | uniform | 0.12234 | 0.38061 |

LR-core, best C per half-life:

| half_life | val_brier | val_log_loss |
|---|---|---|
| 2 | 0.12110 | 0.38131 |
| 4 | 0.12168 | 0.38165 |
| 8 | 0.12266 | 0.38378 |
| uniform | 0.12418 | 0.38752 |

GBM:

- Full grid of 216 configs with uniform weights (641s).
- Recency pass: top 10 uniform-weight configs x half-lives [8.0, 4.0, 2.0] (30 fits).

Top 10 GBM fits by validation Brier:

| learning_rate | max_leaf_nodes | min_samples_leaf | l2_regularization | max_iter | monotonic | half_life | stage | val_brier | val_log_loss | fit_seconds |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.03 | 15 | 200 | 0.0 | 300 | True | 8 | recency | 0.11614 | 0.37779 | 2.56 |
| 0.03 | 15 | 50 | 0.0 | 300 | True | uniform | grid | 0.11657 | 0.37761 | 1.21 |
| 0.03 | 15 | 200 | 1.0 | 300 | True | 8 | recency | 0.11697 | 0.37977 | 2.5 |
| 0.03 | 15 | 50 | 1.0 | 300 | True | 8 | recency | 0.11714 | 0.38040 | 2.51 |
| 0.03 | 15 | 50 | 0.0 | 300 | True | 8 | recency | 0.11718 | 0.38143 | 2.59 |
| 0.03 | 15 | 800 | 1.0 | 300 | True | 8 | recency | 0.11742 | 0.38650 | 2.47 |
| 0.03 | 15 | 800 | 1.0 | 300 | True | 4 | recency | 0.11743 | 0.38421 | 2.46 |
| 0.03 | 15 | 200 | 1.0 | 300 | True | uniform | grid | 0.11751 | 0.37984 | 1.7 |
| 0.03 | 15 | 50 | 1.0 | 300 | True | uniform | grid | 0.11754 | 0.38108 | 1.25 |
| 0.03 | 15 | 200 | 0.0 | 300 | True | uniform | grid | 0.11831 | 0.38322 | 0.99 |

Full logs: `reports/tuning_lr_full.csv`, `reports/tuning_lr_core.csv`, `reports/tuning_gbm.csv`.
