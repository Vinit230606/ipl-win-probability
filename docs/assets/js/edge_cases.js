// Edge-cases page: every number comes from data/edge_cases.json, data/calculator.json and
// data/lr_core.json; the explorer recomputes all three answers in the browser.
import {
  CHART_MISSING, chartAvailable, chartFonts, cssVar, el, fix, highlightNav, int, loadJSON, pct,
  plural, setTeamTint, showError, table,
} from "./common.js";
import { parseField } from "./lr_core.js";
import { buildCalculator } from "./simulation.js";

const $ = (id) => document.getElementById(id);
let E, calc, model, chart = null;

highlightNav();
init();

async function init() {
  let sim;
  try {
    [E, sim, model] = await Promise.all([loadJSON("data/edge_cases.json"), loadJSON("data/calculator.json"),
      loadJSON("data/lr_core.json")]);
  } catch {
    return;
  }
  calc = buildCalculator(model, sim);
  render();
  if (!chartAvailable()) showError(CHART_MISSING);
  for (const id of ["ex-runs", "ex-balls", "ex-wkts"]) $(id).addEventListener("input", explore);
  $("ex-form").addEventListener("submit", (e) => e.preventDefault());
  explore();
}

const P = (v, d = 1) => {
  const f = E.display_floor;
  if (v < f) return v < 0.0005 ? "≈0%" : `${(100 * v).toFixed(d)}%`;
  return `${(100 * v).toFixed(d)}%`;
};

function render() {
  const s0 = E.scenarios[0], C = E.coverage, ch = E.chosen, V = E.validation;
  $("lede").textContent =
    `The calculator answers any situation from 1 to 300 runs needed, 1 to 120 balls and 1 to 10 wickets: ` +
    `${int(C.calculator_states)} combinations. Past chases only pass through some of them. This page shows ` +
    "what went wrong in the rest, and how we fixed it.";
  $("problem").textContent =
    `Asked about ${s0.runs_needed} needed from ${s0.balls_left} balls with ${s0.wickets_left} wicket left, the ` +
    `simple model (LR-core) said ${P(s0.p_lr_core, 2)}, which the calculator showed as 0%. A run a ball with ` +
    "the last pair in is hard, but teams do it, so 0% is not believable. The table compares the simple " +
    "model with the fixed calculator on this and other unusual situations.";
  $("scenarios").replaceChildren(table(
    ["Situation", "Why it is interesting", "Past chases nearby", "Simple model", "Simulation", "Calculator"],
    E.scenarios.map((s) => [`${s.runs_needed} off ${s.balls_left}, ${plural(s.wickets_left, "wicket")}`, s.why,
      int(s.support_chases), P(s.p_lr_core), P(s.p_simulation), P(s.p_calculator)]),
    { caption: "Unusual situations (models fit on all training and validation seasons)", numeric: [2, 3, 4, 5] }));

  const one = E.reach.find((r) => r.wickets_left === 1) ?? { chases: 0, won: 0 };
  const fs = E.fit.seasons;
  $("why").textContent =
    "The simple model is a logistic regression: its log-odds are a weighted sum of the inputs, so they keep " +
    "moving in a straight line however far you go from the data. One input is runs needed per wicket; with " +
    `one wicket left it is the whole target, a value the data rarely has. In ${fs[0]}–${fs[fs.length - 1]}, ` +
    `${int(one.chases)} chases were ever down to their last wicket with the game still open, and ${int(one.won)} ` +
    `of them were won. Across the calculator's range, ${pct(C.share_without_data)} of situations have no past ` +
    `chase in their neighbourhood, and the simple model gives under 1% or over 99% on ` +
    `${int(C.lr_core_near_certain_without_data)} of those.`;
  $("reach").replaceChildren(table(["Wickets left", "Chases that got there", "Of those, won"],
    E.reach.slice().sort((a, b) => a.wickets_left - b.wickets_left)
      .map((r) => [String(r.wickets_left), int(r.chases), `${int(r.won)} (${pct(r.won / Math.max(r.chases, 1))})`]),
    { caption: `Training and validation seasons: chases that reached each number of wickets left before the end`, numeric: [1, 2] }));

  const sb = ch.support_bucket;
  $("fix-support").textContent =
    `For every situation we count the past chases (training and validation seasons) that passed through a ` +
    `small cell around it: ${sb.runs} runs by ${sb.balls} balls with exactly the same wickets left. A chase counts ` +
    `once per cell. ${int(C.states_without_data)} of the ${int(C.calculator_states)} situations have zero.`;
  $("fix-sim").replaceChildren(...[
    `Each delivery has one of ${E.fit.outcome_classes} outcomes: a legal ball with 0–6 runs, or a wide or no-ball ` +
      "with 1–7 runs, each with or without a wicket.",
    `The outcome chances depend on the situation before the ball: phase (powerplay, middle, death), wickets ` +
      `left group and required-rate band: ${E.fit.contexts} situations in all, counted over ${int(E.fit.deliveries)} ` +
      "deliveries.",
    `Rare situations borrow from broader ones (all deliveries → phase → phase and wickets → full situation), ` +
      `each pulled towards its parent by ${fix(ch.shrinkage, 0)} pseudo-deliveries.`,
    "The chance of winning is then solved exactly backwards from the end of the innings: needing r runs off " +
      "b balls with w wickets, add up each outcome's chance times the chance of winning from where it leaves " +
      "you. Wides and no-balls keep the ball count; a wicket costs a wicket; reaching the target wins.",
    `Treating balls as independent makes the simulation over-confident, so its answers are recalibrated on the ` +
      `training rows (Platt scaling: slope ${fix(ch.platt_slope, 3)}, intercept ${fix(ch.platt_intercept, 3)}).`,
  ].map((t) => el("li", { text: t })));
  $("fix-blend").textContent =
    `The calculator uses weight n / (n + ${fix(ch.k, 0)}) on the simple model and the rest on the simulation, ` +
    "where n is the number of past chases in the cell. With no data it is the simulation alone; with plenty " +
    "it is almost entirely the simple model, which is the more accurate of the two where data exists.";
  const mb = E.monotonicity.blend_before_envelope, mc = E.monotonicity.calculator;
  const brk = (m) => m.more_runs_raises_p + m.fewer_balls_raises_p + m.fewer_wickets_raises_p;
  $("fix-env").textContent =
    `Before this step, ${int(brk(mb))} neighbouring pairs broke the rule; after it, ${int(brk(mc))}. The average ` +
    `change is ${fix(100 * C.mean_change_by_envelope, 2)} percentage points.`;
  $("fix-floor").textContent =
    `While a chase is open, the calculator shows values under ${pct(E.display_floor)} as "under ` +
    `${pct(E.display_floor)}" and above ${pct(1 - E.display_floor)} as "over ${pct(1 - E.display_floor)}". A ` +
    "true 0% or 100% only appears once the result is settled by the rules.";

  $("tune-text").textContent =
    "The two settings (the shrinkage and k) were chosen on the validation season, by log loss, which punishes " +
    `confident wrong answers. Chosen: shrinkage ${fix(ch.shrinkage, 0)}, k ${fix(ch.k, 0)}. On validation the ` +
    `calculator scored log loss ${fix(V.val_log_loss, 4)} against ${fix(V.val_log_loss_lr_core, 4)} for the simple ` +
    `model (Brier ${fix(V.val_brier, 4)} against ${fix(V.val_brier_lr_core, 4)}). ` +
    (V.val_log_loss > V.val_log_loss_lr_core
      ? "So on the situations real chases actually visit, the fix costs a little accuracy. We accept that " +
        "price for answers that make sense everywhere else."
      : "So the fix did not cost accuracy on the situations real chases visit.");
  $("tuning").replaceChildren(table(["Shrinkage", "k", "Validation log loss", "Validation Brier"],
    E.tuning.map((t) => [fix(t.shrinkage, 0), fix(t.k, 0), fix(t.val_log_loss, 5), fix(t.val_brier, 5)]),
    { caption: "Every setting tried (calculator = blend, then cricket logic)", numeric: [0, 1, 2, 3] }));

  const M = E.monotonicity;
  const name = { lr_core: "Simple model (LR-core)", simulation: "Simulation", blend_before_envelope: "Blend, before the cricket-logic step", calculator: "Calculator" };
  $("mono").replaceChildren(table(["Model", "More runs raises chance", "Fewer balls raises chance", "Fewer wickets raises chance"],
    Object.keys(name).map((k) => [name[k], int(M[k].more_runs_raises_p), int(M[k].fewer_balls_raises_p), int(M[k].fewer_wickets_raises_p)]),
    { caption: `Neighbouring pairs that break cricket logic, out of ${int(M.calculator.states_checked)} situations checked`, numeric: [1, 2, 3] }));

  const T = E.post_test, nw = T.near_certain_wrong;
  $("post-text").textContent =
    `On the test seasons (${int(T.n_rows)} balls, ${pct(T.share_rows_without_data, 1)} of them in ` +
    `situations with no past chase nearby). "Sure and wrong" counts balls where a method said under ` +
    `${pct(E.display_floor)} or over ${pct(1 - E.display_floor)} and the other side won. ` +
    (nw.calculator > nw.lr_core
      ? `Honest caveat: the calculator was sure and wrong on ${int(nw.calculator)} balls against ${int(nw.lr_core)} ` +
        "for the simple model. Those balls are in situations with little data, where the simulation has " +
        "a say and is sometimes too confident."
      : "");
  const lab = { lr_core: "Simple model (LR-core)", simulation: "Simulation", calculator: "Calculator" };
  const b = (o) => (o.brier == null ? "–" : fix(o.brier, 4));
  $("post").replaceChildren(table(["Method", "Brier, all balls", "Log loss, all balls", "Brier, no past chase nearby", "Sure and wrong"],
    Object.keys(lab).map((k) => [lab[k], b(T.all_rows[k]), fix(T.all_rows[k].log_loss, 4), b(T.rows_without_data[k]), int(nw[k])]),
    { caption: "Test seasons, checked after the test run", numeric: [1, 2, 3, 4] }));
}

function explore() {
  const vals = {};
  const errs = [];
  for (const [id, key, label] of [["ex-runs", "runs_needed", "Runs needed"], ["ex-balls", "balls_left", "Balls left"], ["ex-wkts", "wickets_left", "Wickets left"]]) {
    const r = parseField(label, $(id).value, model.input_ranges[key]);
    $(id).setAttribute("aria-invalid", String(!r.ok));
    if (r.ok) vals[key] = r.value; else errs.push(r.message);
  }
  $("ex-err").hidden = !errs.length;
  $("ex-err").textContent = errs.join(" ");
  if (errs.length) return;
  const { runs_needed: r, balls_left: bl, wickets_left: w } = vals;
  const pc = calc.p(r, bl, w);
  setTeamTint(pc >= 0.5 ? "#7DD3FC" : "#F472B6", Math.abs(pc - 0.5) * 2);
  $("ex-state").textContent = `Need ${r} from ${plural(bl, "ball")}, ${plural(w, "wicket")} in hand`;
  $("ex-lr").textContent = P(calc.lr(r, bl, w));
  $("ex-sim").textContent = P(calc.sim(r, bl, w));
  $("ex-calc").textContent = P(pc);
  const n = calc.support(r, bl, w);
  $("ex-support").textContent = n
    ? `${plural(n, "past chase")} passed through this spot; the simple model gets ${pct(calc.weight(r, bl, w))} of the weight.`
    : "No past chase passed through this spot: the calculator uses the simulation.";
  $("ex-caption").textContent = `${r} needed with ${plural(w, "wicket")} in hand, as the balls run out (left to right).`;
  drawChart(r, w, bl);
}

function drawChart(r, w, here) {
  if (!chartAvailable()) return;
  const xs = [];
  for (let b = 120; b >= 1; b--) xs.push(b);
  const ds = (fn) => xs.map((b) => ({ x: b, y: 100 * fn(r, b, w) }));
  const empty = xs.filter((b) => calc.support(r, b, w) === 0);
  const shade = {
    id: "nodata",
    beforeDatasetsDraw(chh) {
      const { ctx, chartArea: a, scales: { x } } = chh;
      ctx.save();
      ctx.fillStyle = cssVar("--big-over");
      for (const b of empty) {
        const x0 = x.getPixelForValue(b + 0.5), x1 = x.getPixelForValue(b - 0.5);
        ctx.fillRect(Math.min(x0, x1), a.top, Math.abs(x1 - x0) + 0.5, a.bottom - a.top);
      }
      const px = x.getPixelForValue(here);
      ctx.strokeStyle = cssVar("--ink"); ctx.globalAlpha = 0.5;
      ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
      ctx.restore();
    },
  };
  if (chart) chart.destroy();
  Chart.defaults.font = chartFonts();
  Chart.defaults.color = cssVar("--muted");
  chart = new Chart($("ex-chart"), {
    type: "line",
    data: {
      datasets: [
        { label: "Simple model", data: ds(calc.lr), borderColor: cssVar("--outfield"), borderWidth: 1.75, pointRadius: 0 },
        { label: "Simulation", data: ds(calc.sim), borderColor: cssVar("--muted"), borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0 },
        { label: "Calculator", data: ds(calc.p), borderColor: cssVar("--floodlight"), borderWidth: 2.75, pointRadius: 0 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false, events: [],
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: {
        x: { type: "linear", reverse: true, min: 1, max: 120, title: { display: true, text: "Balls left" }, ticks: { stepSize: 12 }, grid: { display: false } },
        y: { min: 0, max: 100, ticks: { stepSize: 25, callback: (t) => `${t}%` }, grid: { color: cssVar("--line") }, title: { display: true, text: "Win probability" } },
      },
    },
    plugins: [shade],
  });
}
