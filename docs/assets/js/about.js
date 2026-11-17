// Write-up page: every number and data-dependent sentence comes from data/results.json,
// data/lr_core.json and the featured match file, all written by `make export`.
import { ciText, el, fix, fmtDate, highlightNav, int, loadJSON, pct, plural, table, teamName } from "./common.js";
import { lineFor, teamFromName } from "./teams.js";

const $ = (id) => document.getElementById(id);
const ORDER = ["baseline", "lr_full", "lr_core", "gbm"];

const REASONS = {
  DUPLICATE: ["The same match appears twice", "Cannot tell which copy is right."],
  NO_RESULT: ["No result", "There is no winner to predict."],
  TIE: ["Tie, including matches decided by a super over", "The label is neither win nor loss."],
  DLS: ["Target revised by the DLS method", "Runs needed and balls left no longer mean the same thing."],
  NO_CHASE: ["No second innings recorded", "There is no chase to follow."],
  REDUCED_OVERS: ["Shortened match, or a first innings that stopped short of 120 balls without being bowled out",
    "The target was not set over a full 20 overs."],
  TARGET_MISMATCH: ["Rebuilt target disagrees with the recorded one", "The ball-by-ball record is incomplete."],
  CHASE_INCOMPLETE: ["Chase ended early without being bowled out or reaching the target",
    "The innings record stops before the result, so the last state is wrong."],
  LABEL_MISMATCH: ["Recorded winner disagrees with the runs scored", "Either the label or the record is wrong."],
};

highlightNav();
init();

async function init() {
  let R, core;
  try {
    [R, core] = await Promise.all([loadJSON("data/results.json"), loadJSON("data/lr_core.json")]);
  } catch {
    return;
  }
  const lab = (k) => R.methods[k].label;
  const D = R.data, S = R.splits.seasons, ev = R.evaluation, T = R.test;
  const beats = ["lr_full", "lr_core", "gbm"].filter((k) => T[k].bss_ci[0] > 0);
  const worse = ["lr_full", "lr_core", "gbm"].filter((k) => T[k].bss_ci[1] < 0);
  const unclear = ["lr_full", "lr_core", "gbm"].filter((k) => !beats.includes(k) && !worse.includes(k));
  const bestTest = ORDER.reduce((a, k) => (T[k].brier < T[a].brier ? k : a), "baseline");
  const testSeasons = S.test.join(" and ");

  // 1. answer
  const skill = (k) => `${lab(k)} removed ${pct(T[k].bss)} of the baseline's Brier score (95% interval ` +
    `${pct(T[k].bss_ci[0])} to ${pct(T[k].bss_ci[1])})`;
  let answer = beats.length
    ? `Yes, on the ${testSeasons} test seasons ${beats.length === 1 ? "one model" : "some models"} did. ` +
      `${beats.map(skill).join("; ")}. `
    : `No model was shown to beat the baseline on the ${testSeasons} test seasons. `;
  answer += `The most accurate method was ${lab(bestTest)}, with a Brier score of ${fix(T[bestTest].brier, 3)} ` +
    `against ${fix(T.baseline.brier, 3)} for the baseline. `;
  for (const k of unclear) answer += `For ${lab(k)} the interval includes zero, so we cannot say it beats the baseline. `;
  for (const k of worse) answer += `${lab(k)} was worse than the baseline. `;
  if (!beats.includes(R.best_model)) {
    answer += `${lab(R.best_model)} had the best validation score but did not hold up on test, because ` +
      "scoring in the test seasons went beyond what it had seen in training (section 8).";
  }
  $("answer").textContent = answer;

  // 2. example rows
  const fm = await loadJSON(`data/matches/${encodeURIComponent(R.featured_match_id)}.json`);
  const picks = [0, fm.balls.findIndex((b) => b.wicket), Math.floor(fm.balls.length * 0.6), fm.balls.length - 1]
    .filter((v, k, a) => v >= 0 && a.indexOf(v) === k).sort((a, b) => a - b);
  $("row-example-intro").textContent =
    `Four of the ${fm.balls.length} rows for ${teamName(fm.batting_team)} chasing ${fm.target} against ` +
    `${teamName(fm.bowling_team)} (${fmtDate(fm.date)}), which ${fm.chase_won ? "they won" : "they lost"}:`;
  $("row-example").replaceChildren(table(
    ["Ball", "Event", "Score", "Runs needed", "Balls left", "Wickets left", "Target", "Required rate",
      `Runs, last ${ev.momentum_window}`, `Wickets, last ${ev.momentum_window}`, "Settled?", "Label"],
    picks.map((k) => {
      const b = fm.balls[k];
      return [b.label, b.event === "·" ? "dot ball" : b.event, b.score, String(b.runs_needed), String(b.balls_left),
        String(b.wickets_left), String(fm.target), fix(b.rrr, 2), String(b.r18), String(b.w18),
        b.terminal ? "yes" : "no", String(fm.chase_won)];
    }),
    { caption: "One row per delivery; the label is the match result", numeric: [3, 4, 5, 6, 7, 8, 9] }));

  // 3. data
  $("data-source").textContent =
    `Source: Cricsheet's IPL download (ipl_json.zip), one JSON file per match with every delivery. ` +
    `It has ${int(D.raw_matches)} matches and ${int(D.raw_deliveries)} deliveries from ${D.first_season} ` +
    `to ${D.last_season}. After cleaning, ${int(D.kept_chases)} chases remain, giving ` +
    `${int(D.chase_deliveries)} rows.`;
  $("variables").replaceChildren(table(["Variable", "What it is", "Used as"], [
    ["Runs off the bat, extras, extras type", "Recorded per delivery; extras are wides, no-balls, byes, leg-byes or penalties", "Rebuilding the score"],
    ["Dismissal kind", "Recorded per delivery when a batter is out", "Rebuilding wickets"],
    ["Innings, batting team", "Which side batted", "Finding the chase"],
    ["Winner, result, method", "Match outcome; method marks DLS", "Label and cleaning"],
    ["Runs needed, balls left, wickets left", "The scoreboard after the delivery", "Model input"],
    ["Target", "First-innings total + 1", "Model input"],
    ["Required run rate", `6 × runs needed / balls left, capped at ${fix(core.rrr_clip, 0)}`, "Model input"],
    [`Runs and wickets in the last ${ev.momentum_window} legal balls`, "Recent momentum, from earlier balls only", "Model input"],
    ["Chase won", "1 if the chasing team won, else 0", "Label"],
  ]));
  const first = D.seasons[0], last = D.seasons[D.seasons.length - 1];
  $("quality").replaceChildren(...[
    D.season_label_note,
    `${int(D.wides_in_chases)} wides and ${int(D.noballs_in_chases)} no-balls in the kept chases do not use up a ` +
      "ball, so balls left cannot be read off the delivery count.",
    `${plural(D.retired_hurt_in_chases, "dismissal")} in the chases ${D.retired_hurt_in_chases === 1 ? "is" : "are"} ` +
      "\"retired hurt\" or \"retired not out\", which are not wickets.",
    `${int(R.cleaning.excluded)} matches cannot be used as full chases (no result, ties, DLS, shortened or incomplete ` +
      "innings); they are removed and logged with their reason.",
    `After rebuilding every chase ball by ball, the final score matches the innings total for ${int(D.running_total_ok)} ` +
      `of ${int(D.kept_chases)} chases.`,
    `Scoring rose: the average target was ${fix(first.mean_target, 0)} in ${first.season} and ` +
      `${fix(last.mean_target, 0)} in ${last.season}. This shift matters for the results (section 8).`,
  ].map((t) => el("li", { text: t })));

  // 4. preprocessing, step by step
  $("pp1").textContent =
    `Input: ${int(D.raw_matches)} match files. Output: a matches table (one row per match) and a deliveries ` +
    `table (${int(D.raw_deliveries)} rows, one per delivery of every innings).`;
  $("pp1-check").textContent =
    `On every one of the ${int(D.raw_deliveries)} deliveries, the total must equal runs off the bat plus ` +
    "extras, or the run stops.";
  $("pp2-check").textContent =
    `The run stops unless raw matches = kept + removed (${int(R.cleaning.raw_matches)} = ` +
    `${int(R.cleaning.kept)} + ${int(R.cleaning.excluded)}), every kept match has exactly innings 1 and 2, ` +
    "and the two batting sides are the match's two teams.";
  $("pp3-check").textContent =
    `The rebuilt final score matches the innings total from step 2 for ${int(D.running_total_ok)} of ` +
    `${int(D.kept_chases)} chases (the run stops on any mismatch).`;
  $("pp4-check").textContent = "";
  const sp = R.splits.table;
  $("pp6").textContent =
    "Whole seasons go to one split, so the models are always tested on seasons later than anything they " +
    "learned from: " + sp.map((r) => `${({ train: "training", val: "validation", test: "test" })[r.split]} ` +
    `${r.seasons} (${int(r.matches)} chases)`).join(", ") + ".";
  $("cleaning-summary").textContent =
    `Only completed chases of a full 20-over target fit the question. Of ${int(R.cleaning.raw_matches)} ` +
    `matches, ${int(R.cleaning.excluded)} were removed and ${int(R.cleaning.kept)} were kept; the table ` +
    "below gives every reason.";
  const ex = Object.entries(R.exclusions).sort((a, b) => b[1] - a[1]);
  $("exclusions").replaceChildren(table(["Reason", "Matches", "Why it is removed"],
    ex.map(([k, n]) => [REASONS[k]?.[0] ?? k, int(n), REASONS[k]?.[1] ?? ""]),
    { caption: "Matches removed", numeric: [1] }));
  const onePer = D.terminal_rows === D.kept_chases;
  $("terminal-text").textContent =
    `${int(D.terminal_rows)} rows${onePer ? " (one per chase, the ball that ended it)" : ""} come after the ` +
    "result is already fixed by the rules: the target is reached, the side is all out, or no balls are left. " +
    "Their answer is certain, so including them would make every method look better without telling us " +
    `anything. Models are trained and scored on the other ${int(D.model_rows)} rows. The Results page also ` +
    "gives scores with them included, for comparison.";
  const lrSet = R.chosen_params.lr_full.feature_set;
  $("features").replaceChildren(...[
    "Runs needed, balls left and wickets left: the scoreboard itself.",
    "Target: a side needing 60 from 36 balls is in a different match when chasing 150 than when chasing 220.",
    `Required run rate, capped at ${fix(core.rrr_clip, 0)} runs per over: the pressure in one number; the cap ` +
      "keeps values finite on the last balls.",
    `Runs and wickets in the last ${ev.momentum_window} legal balls (three overs), counting any wides and ` +
      "no-balls among them: whether the chase is gaining or losing ground.",
    `For logistic regression only, four terms computed from the same row (log runs needed, log balls left, ` +
      "required rate × wickets left, runs per wicket), because a linear model needs help to bend. " +
      `Validation ${lrSet === "BASE7" ? "did not keep them for LR-full" : "kept them for LR-full"}.`,
  ].map((t) => el("li", { text: t })));

  // 5. methods
  const hl = (k) => (R.chosen_params[k].half_life == null ? "equal weights for all seasons"
    : `recent seasons weighted more (weight halves every ${R.chosen_params[k].half_life} seasons back)`);
  const settings = {
    baseline: `buckets need at least ${ev.baseline_min_count} training rows`,
    lr_full: `features ${R.chosen_params.lr_full.feature_set}, C = ${R.chosen_params.lr_full.C}, ${hl("lr_full")}`,
    lr_core: `C = ${R.chosen_params.lr_core.C}, ${hl("lr_core")}`,
    gbm: `learning rate ${R.chosen_params.gbm.learning_rate}, ${R.chosen_params.gbm.max_leaf_nodes} leaves, ` +
      `${R.chosen_params.gbm.max_iter} trees, monotonic constraints ${R.chosen_params.gbm.monotonic ? "on" : "off"}, ${hl("gbm")}`,
  };
  $("methods").replaceChildren(table(["Method", "What it is", "Settings chosen on validation"],
    ORDER.map((k) => [lab(k), R.methods[k].description, settings[k]])));
  $("selection").textContent =
    `The replay's main line is ${lab(R.best_model)}, because it had the lower validation Brier score of the two ` +
    `full models (${fix(R.validation[R.best_model].brier, 4)} against ${fix(R.validation[R.other_model].brier, 4)}). ` +
    "Tuning grids and logs are in the repository.";

  // 6. evaluation
  const role = { train: "Training", val: "Validation", test: "Test" };
  $("splits").replaceChildren(table(["Split", "Seasons", "Chases", "Rows used", "Chase win rate"],
    R.splits.table.map((r) => [role[r.split] ?? r.split, r.seasons, int(r.matches), int(r.model_rows), r.chase_win_rate]),
    { caption: "Season split", numeric: [2, 3, 4] }));
  const ipTrain = S.train.filter((s) => s >= 2023).length;
  $("split-note").textContent =
    `The Impact Player rule, which lets each side add a substitute, started in 2023. Validation (${S.val.join(", ")}) ` +
    `and test (${testSeasons}) are entirely in that era, while ${plural(ipTrain, "training season")} of ` +
    `${S.train.length} ${ipTrain === 1 ? "is" : "are"}. This is the main risk to the models, and section 8 shows ` +
    "it mattered.";
  $("metrics-list").replaceChildren(...[
    "Brier score (main): the mean of (probability − result)², where the result is 1 or 0. Lower is better; " +
      "always guessing 50% scores 0.25.",
    "Log loss (secondary): punishes confident wrong answers harder.",
    `Brier skill score (BSS) = 1 − Brier(model) / Brier(baseline). Its ${pct(ev.ci)} interval comes from ` +
      `${int(ev.n_bootstrap)} resamples of whole test matches, because the balls of one chase are not independent.`,
    "Verdict rule, fixed in advance: a model beats the baseline only if the whole interval is above zero.",
    `Calibration: ${ev.calibration_bins} equal-width probability bins, with expected calibration error (ECE).`,
  ].map((t) => el("li", { text: t })));

  // 7. results
  $("verdicts").replaceChildren(
    ...["lr_full", "lr_core", "gbm"].map((k) => el("li", { text: T[k].verdict })),
    el("li", { text: `${lab("gbm")} against ${lab("lr_full")}: ${R.test_gbm_vs_lr_full.verdict}` }));
  $("test-metrics").replaceChildren(table(["Method", "Brier", "Log loss", "ECE", `BSS [${pct(ev.ci)} interval]`],
    ORDER.map((k) => [lab(k), fix(T[k].brier, 4), fix(T[k].log_loss, 4), fix(T[k].ece, 4),
      k === "baseline" ? "reference" : ciText(T[k].bss, T[k].bss_ci)]),
    { caption: `Test seasons ${testSeasons}: ${int(R.counts.test_matches)} chases, ${int(R.counts.test_model_rows)} rows`, numeric: [1, 2, 3] }));
  const lr = "lr_full";
  const allPhases = R.phase.every((e) => e[`bss_ci_${lr}`][0] > 0);
  const bestPhase = R.phase.reduce((a, e) => (e[`bss_${lr}`] > a[`bss_${lr}`] ? e : a));
  $("phase-text").textContent =
    `${lab(lr)} ${allPhases ? "beats the baseline in every phase" : "does not beat the baseline in every phase"}; ` +
    `its skill is highest in the ${bestPhase.phase} phase (BSS ${fix(bestPhase[`bss_${lr}`])}). ` +
    (R.phase.every((e) => e.brier_gbm > e[`brier_${lr}`])
      ? `${lab("gbm")} has a higher (worse) Brier score than ${lab(lr)} in every phase.` : "");

  // 8. error analysis
  const tb = R.diagnostics.target_bins;
  const top = tb.slice(-2);
  const lowEdge = Number((top[0].target_band.match(/\d+/) ?? ["0"])[0]) - 1;
  const sum = (a, f) => a.reduce((s, x) => s + f(x), 0);
  const fitN = sum(top, (b) => b.fit_matches);
  const fitWin = sum(top, (b) => b.fit_matches * (b.fit_chase_win_rate ?? 0)) / fitN;
  const testN = sum(top, (b) => b.n_matches);
  const testWin = sum(top, (b) => b.n_matches * b.chase_win_rate) / testN;
  const rows = sum(top, (b) => b.n_rows);
  const mean = (k) => sum(top, (b) => b.n_rows * b[`mean_p_${k}`]) / rows;
  $("target-text").textContent =
    `In the training and validation seasons only ${fitN} chases had a target above ${lowEdge}, and ` +
    `${pct(fitWin)} of them were won. In the test seasons there were ${testN} such chases and ${pct(testWin)} ` +
    `were won. On those chases ${lab("gbm")}'s average prediction was ${pct(mean("gbm"))}, against ` +
    `${pct(mean(lr))} for ${lab(lr)}. Decision trees cannot extrapolate: for a target beyond most of what ` +
    "they saw, they repeat what they learned for the highest targets in training. Logistic regression changes " +
    "smoothly with the target, so it was less wrong. This table was computed after the single test run from " +
    "the stored predictions; no model was changed.";
  $("target-table").replaceChildren(table(
    ["Target", "Train+val chases", "Train+val win rate", "Test chases", "Test win rate", `Mean ${lab("gbm")}`,
      `Mean ${lab(lr)}`, `Brier ${lab("gbm")}`, `Brier ${lab(lr)}`, "Brier baseline"],
    tb.map((b) => [b.target_band, int(b.fit_matches), pct(b.fit_chase_win_rate), int(b.n_matches), pct(b.chase_win_rate),
      pct(b.mean_p_gbm), pct(b[`mean_p_${lr}`]), fix(b.brier_gbm), fix(b[`brier_${lr}`]), fix(b.brier_baseline)]),
    { caption: "By target score", numeric: [1, 2, 3, 4, 5, 6, 7, 8, 9] }));

  const testDrift = R.drift.filter((d) => d.role === "test");
  const under = R.drift.every((d) => d.gap_start < 0);
  const minUnder = Math.min(...ORDER.map((k) => R.calibration.test[k]
    .filter((b) => b.n > 0 && b.observed_rate > b.mean_p).length));
  const nBins = Math.min(...ORDER.map((k) => R.calibration.test[k].filter((b) => b.n > 0).length));
  $("drift-text").textContent =
    `${under ? `In every validation and test season ${lab(R.best_model)} under-predicted chases` : `${lab(R.best_model)}'s bias changed sign across seasons`}: ` +
    testDrift.map((d) => `in ${d.season} its average start-of-chase prediction was ${pct(d.start_mean_p)} while ` +
      `${pct(d.chase_win_rate)} of chases were won`).join("; ") + ". " +
    `The bias is not only ${lab(R.best_model)}'s: for every method, chasing teams won more often than predicted in at ` +
    `least ${minUnder} of ${nBins} calibration bins. Weighting recent seasons more (chosen on validation) ` +
    "did not remove it: the test seasons were further from the training data than the validation season was.";
  $("season-table").replaceChildren(table(["Season", "Split", "Chases", "Average target", "Targets over 200", "Chase win rate"],
    D.seasons.slice(-6).map((s) => [String(s.season), role[s.split] ?? s.split, int(s.chases), fix(s.mean_target, 0),
      pct(s.share_target_over_200), pct(s.chase_win_rate)]),
    { caption: "The last six seasons (all seasons are in the repository's data_quality.md)", numeric: [2, 3, 4, 5] }));

  $("failure-text").textContent =
    `The chases where ${lab(R.best_model)} did worst against the baseline, and the biggest upsets (the lowest ` +
    "probability it gave the eventual winner). Each opens in the replay.";
  const fc = R.failure_cases;
  const fcRows = [...fc.worst_vs_baseline.slice(0, 3).map((e) => ["Worse than baseline", e]),
    ...fc.biggest_upsets.slice(0, 3).map((e) => ["Upset", e])];
  const idx = await loadJSON("data/matches.json");
  const chaser = new Map(idx.matches.map((m) => [m.match_id, m.batting_team]));
  $("failures").replaceChildren(table(["Type", "Chase", ""],
    fcRows.map(([t, e]) => [t, e.explanation,
      el("a", { href: `index.html?match=${encodeURIComponent(e.match_id)}`, text: "Open replay" })]),
    { rowLines: fcRows.map(([, e]) => (chaser.has(e.match_id) ? lineFor(teamFromName(chaser.get(e.match_id))) : null)) }));
  $("example-fig").src = `assets/figures/example_replay_${R.featured_match_id}.png`;
  $("example-caption").textContent =
    `The chase with the largest swing in ${lab(R.best_model)}'s probability: ${teamName(fm.batting_team)} chasing ` +
    `${fm.target} against ${teamName(fm.bowling_team)}, ${fmtDate(fm.date)}. ${fm.result_text}.`;

  // 9. limitations
  const valChases = R.splits.table.find((r) => r.split === "val").matches;
  const worstTest = ORDER.reduce((a, k) => (T[k].brier > T[a].brier ? k : a), "baseline");
  $("lim-val").textContent =
    `Validation is one season (${valChases} chases), so tuning choices are noisy. ${lab(R.best_model)} looked ` +
    `best on validation (Brier ${fix(R.validation[R.best_model].brier, 4)}) and ` +
    (worstTest === R.best_model ? "was the worst method on test." : `scored ${fix(T[R.best_model].brier, 4)} on test.`);
  const trainSeasons = D.seasons.filter((s) => s.split === "train");
  const maxTrain = trainSeasons.reduce((a, s) => (s.mean_target > a.mean_target ? s : a));
  const testS = D.seasons.filter((s) => s.split === "test");
  $("lim-drift").textContent =
    `The average target in the test seasons (${testS.map((s) => `${fix(s.mean_target, 0)} in ${s.season}`).join(", ")}) ` +
    `was above every training season (highest: ${fix(maxTrain.mean_target, 0)} in ${maxTrain.season}). The results ` +
    "show how the models cope with that shift; they may not hold for later seasons if scoring keeps rising.";

  $("selection-decision").textContent =
    `${lab(R.best_model)} was chosen on validation as the replay's main model and did worse than ` +
    `${lab(R.other_model)} on test. Changing the choice after seeing test results would break the test-once ` +
    `rule, so the replay keeps ${lab(R.best_model)} as the main line and draws ${lab(R.other_model)} beside it.`;
}
