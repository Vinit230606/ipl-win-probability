// Results page (design 13.2): every number comes from data/results.json.
import {
  CHART_MISSING, chartAvailable, chartFonts, ciText, cssVar, el, fix, highlightNav, int, loadJSON,
  onThemeChange, pct, showError, table,
} from "./common.js";
import { lineFor, teamFromName } from "./teams.js";

const $ = (id) => document.getElementById(id);
const ORDER = ["baseline", "lr_full", "lr_core", "gbm"];
let R = null;
let CHASER = new Map();   // match id -> chasing team name (from data/matches.json)
const charts = [];

init();

async function init() {
  highlightNav();
  try {
    let idx;
    [R, idx] = await Promise.all([loadJSON("data/results.json"), loadJSON("data/matches.json")]);
    CHASER = new Map(idx.matches.map((m) => [m.match_id, m.batting_team]));
  } catch {
    return;
  }
  render();
  if (!chartAvailable()) showError(CHART_MISSING);
  else drawCharts();
  onThemeChange(() => { charts.splice(0).forEach((c) => c.destroy()); if (chartAvailable()) drawCharts(); });
}

const label = (k) => R.methods[k].label;

function render() {
  const s = R.splits.seasons, c = R.counts, ev = R.evaluation;
  const best = R.best_model, other = R.other_model;
  $("intro").textContent =
    `Every method was scored once on the ${s.test.join(" and ")} seasons: ${int(c.test_matches)} chases, ` +
    `${int(c.test_model_rows)} balls. Models were fit on ${s.train[0]}–${s.val[s.val.length - 1]} ` +
    `(${int(c.fit_matches)} chases) with settings chosen on ${s.val.join(", ")}. The ` +
    `${int(c.test_terminal_rows)} balls where the result was already settled are left out of the scores.`;

  $("verdicts").replaceChildren(
    ...["lr_full", "lr_core", "gbm"].map((k) => el("li", { text: R.test[k].verdict })),
    el("li", { text: `${label("gbm")} against ${label("lr_full")}: ${R.test_gbm_vs_lr_full.verdict}` }));
  $("selection").textContent =
    `${label(best)} was chosen as the replay's main model because it had the lower validation Brier ` +
    `score (${fix(R.validation[best].brier, 4)} against ${fix(R.validation[other].brier, 4)} for ` +
    `${label(other)}). That choice was fixed before the test run and was not changed after it, so ` +
    `the replay draws ${label(best)} as the main line with ${label(other)} next to it.`;

  $("metrics-intro").textContent =
    "Brier score is the mean squared gap between the probability and the result (1 for a win, 0 for " +
    "a loss); lower is better. Skill (BSS) is the share of the baseline's Brier score a model " +
    `removes; above 0 is better than the baseline. Intervals come from resampling whole test matches ` +
    `${int(ev.n_bootstrap)} times (${pct(ev.ci)} percentile interval). A model is called better only ` +
    "when the whole interval is above 0.";
  $("metrics").replaceChildren(table(
    ["Method", "Brier", "Log loss", "ECE", `BSS [${pct(ev.ci)} interval]`],
    ORDER.map((k) => {
      const m = R.test[k];
      return [label(k), fix(m.brier, 4), fix(m.log_loss, 4), fix(m.ece, 4), k === "baseline" ? "reference" : ciText(m.bss, m.bss_ci)];
    }),
    { caption: "Test seasons, balls where the result was still open", numeric: [1, 2, 3] }));
  $("all-rows").textContent = "Including the settled balls (scored with their known 100% or 0%), Brier is " +
    ORDER.map((k) => `${fix(R.test_all_rows_brier[k], 4)} for ${label(k)}`).join(", ") + ".";

  const tb = R.diagnostics.target_bins;
  $("target-intro").textContent =
    `${R.diagnostics.note} Tree models such as ${label("gbm")} cannot extrapolate: they predict ` +
    "for a high target what they saw for the highest targets in training. Logistic regression " +
    "changes smoothly with the target, so it copes better when scoring rises.";
  $("target-bins").replaceChildren(table(
    ["Target", "Train+val chases", "Train+val win rate", "Test chases", "Test win rate",
      ...ORDER.map((k) => `Mean ${label(k)}`), ...ORDER.map((k) => `Brier ${label(k)}`)],
    tb.map((b) => [b.target_band, int(b.fit_matches), pct(b.fit_chase_win_rate), int(b.n_matches), pct(b.chase_win_rate),
      ...ORDER.map((k) => pct(b[`mean_p_${k}`])), ...ORDER.map((k) => fix(b[`brier_${k}`], 3))]),
    { caption: "By target score: how many chases the models learned from, how often chases were won, and each method's average test prediction",
      numeric: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] }));

  const bd = (rows, key, keyLabel) => table(
    [keyLabel, "Balls", ...ORDER.map((k) => `Brier ${label(k)}`), ...ORDER.slice(1).map((k) => `BSS ${label(k)}`)],
    rows.map((e) => [String(e[key]), int(e.n_rows), ...ORDER.map((k) => fix(e[`brier_${k}`], 4)),
      ...ORDER.slice(1).map((k) => ciText(e[`bss_${k}`], e[`bss_ci_${k}`]))]),
    { numeric: [1, 2, 3, 4, 5] });
  const phaseName = { powerplay: "Powerplay (overs 1–6)", middle: "Middle (overs 7–15)", death: "Death (overs 16–20)" };
  $("phase").replaceChildren(bd(R.phase.map((e) => ({ ...e, phase: phaseName[e.phase] ?? e.phase })), "phase", "Phase"));
  $("season").replaceChildren(bd(R.season, "season", "Season"));
  $("drift").replaceChildren(table(
    ["Season", "Role", "Chases", "Mean start prediction", "Chase win rate", "Gap (points)", "Mean prediction, all balls", "Observed, all balls"],
    R.drift.map((d) => [String(d.season), d.role, int(d.n_matches), pct(d.start_mean_p, 1), pct(d.chase_win_rate, 1),
      `${d.gap_start > 0 ? "+" : ""}${fix(100 * d.gap_start, 1)}`, pct(d.mean_p, 1), pct(d.observed_rows, 1)]),
    { caption: `${label(best)}; a negative gap means it under-predicted chases`, numeric: [2, 3, 4, 5, 6, 7] }));

  const caseRows = (list, caption) => table(["Chase", "What happened", ""],
    list.map((e) => [e.match_id, e.explanation,
      el("a", { href: `index.html?match=${encodeURIComponent(e.match_id)}`, text: "Open replay" })]),
    { caption, rowLines: list.map((e) => (CHASER.has(e.match_id) ? lineFor(teamFromName(CHASER.get(e.match_id))) : null)) });
  $("worst").replaceChildren(caseRows(R.failure_cases.worst_vs_baseline, "Test chases where the main model did worst against the baseline"));
  $("upsets").replaceChildren(caseRows(R.failure_cases.biggest_upsets, "Biggest upsets: lowest probability given to the eventual winner"));

  $("validation").replaceChildren(table(
    ["Method", "Brier", "Log loss", "ECE", `BSS [${pct(ev.ci)} interval]`],
    ORDER.map((k) => {
      const m = R.validation[k];
      return [label(k), fix(m.brier, 4), fix(m.log_loss, 4), fix(m.ece, 4), k === "baseline" ? "reference" : ciText(m.bss, m.bss_ci)];
    }),
    { caption: `Validation season ${s.val.join(", ")}, models fit on ${s.train[0]}–${s.train[s.train.length - 1]}`, numeric: [1, 2, 3] }));

  const lv = R.baseline_levels;
  $("levels").replaceChildren(table(["Level", "Bucket used", "Share of test balls"], [
    ["A", "Runs band × balls band × wickets group", pct(lv.A, 1)],
    ["B", "Runs band × balls band", pct(lv.B, 1)],
    ["C", "Coarse runs band × coarse balls band", pct(lv.C, 1)],
    ["D", "Overall training win rate", pct(lv.D, 1)],
  ], { caption: `A bucket is used when it has at least ${R.evaluation.baseline_min_count} training balls`, numeric: [2] }));
}

function drawCharts() {
  const color = { baseline: cssVar("--chalk-dim"), lr_full: cssVar("--chalk"), lr_core: cssVar("--chalk-dim"), gbm: cssVar("--chalk") };
  Chart.defaults.font = chartFonts();
  Chart.defaults.color = cssVar("--chalk-dim");
  const grid = cssVar("--rope");

  const entries = [
    ...["lr_core", "lr_full", "gbm"].map((k) => [`${label(k)} vs baseline`, R.test[k].bss, R.test[k].bss_ci]),
    [`${label("gbm")} vs ${label("lr_full")}`, R.test_gbm_vs_lr_full.bss, R.test_gbm_vs_lr_full.ci],
  ];
  const tone = ([, , ci]) => (ci[0] > 0 ? cssVar("--turf-line") : ci[1] < 0 ? cssVar("--chalk-dim") : cssVar("--rope"));
  const zeroLine = {
    id: "zero",
    afterDatasetsDraw(ch) {
      const { ctx, chartArea: a, scales: { x } } = ch;
      ctx.save(); ctx.strokeStyle = cssVar("--chalk"); ctx.globalAlpha = 0.6;
      ctx.beginPath(); ctx.moveTo(x.getPixelForValue(0), a.top); ctx.lineTo(x.getPixelForValue(0), a.bottom); ctx.stroke();
      ctx.restore();
    },
  };
  charts.push(new Chart($("bss-chart"), {
    type: "bar",
    data: {
      labels: entries.map((e) => e[0]),
      datasets: [
        { data: entries.map((e) => e[2]), backgroundColor: entries.map(tone), barThickness: 10, borderSkipped: false },
        { type: "scatter", data: entries.map((e) => ({ x: e[1], y: e[0] })), backgroundColor: cssVar("--chalk"), pointRadius: 4 },
      ],
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false, animation: false, events: [],
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { title: { display: true, text: "Brier skill score (dot) and 95% interval (bar)" }, grid: { color: grid } },
                y: { type: "category", grid: { display: false } } },
    },
    plugins: [zeroLine],
  }));

  const datasets = [{ label: "Perfect calibration", data: [{ x: 0, y: 0 }, { x: 100, y: 100 }],
    borderColor: grid, borderDash: [2, 4], borderWidth: 1.5, pointRadius: 0 }];
  for (const k of ORDER) {
    datasets.push({
      label: label(k),
      data: R.calibration.test[k].filter((b) => b.n > 0).map((b) => ({ x: 100 * b.mean_p, y: 100 * b.observed_rate })),
      // neutral lines, told apart by line style and marker (main model solid, baseline dashed)
      borderColor: color[k], backgroundColor: color[k], borderWidth: k === R.best_model ? 2.5 : 1.5,
      borderDash: k === R.best_model ? undefined : { baseline: [7, 5], lr_full: [2, 4], lr_core: [9, 3, 2, 3], gbm: [2, 4] }[k],
      pointStyle: { baseline: "rect", lr_full: "circle", lr_core: "triangle", gbm: "rectRot" }[k], pointRadius: 4,
    });
  }
  charts.push(new Chart($("calib-chart"), {
    type: "line",
    data: { datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, events: [],
      plugins: { legend: { position: "bottom" }, tooltip: { enabled: false } },
      scales: {
        x: { type: "linear", min: 0, max: 100, title: { display: true, text: "Mean predicted probability" }, ticks: { callback: (v) => `${v}%` }, grid: { color: grid } },
        y: { min: 0, max: 100, title: { display: true, text: "Observed chase win rate" }, ticks: { callback: (v) => `${v}%` }, grid: { color: grid } },
      },
    },
  }));
}
