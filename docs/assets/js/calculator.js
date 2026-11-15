// What-if calculator: LR-core blended with the ball-by-ball simulation where the data is thin,
// then made consistent with cricket logic (see edge-cases.html). Everything is computed in the
// browser from data/lr_core.json and data/calculator.json.
import {
  CHART_MISSING, chartAvailable, chartFonts, cssVar, fix, highlightNav, loadJSON, onThemeChange,
  pct, plural, setTeamTint, showError,
} from "./common.js";
import { parseField } from "./lr_core.js";
import { buildCalculator } from "./simulation.js";

const FIELDS = [
  { id: "runs", key: "runs_needed", label: "Runs needed" },
  { id: "balls", key: "balls_left", label: "Balls left" },
  { id: "wkts", key: "wickets_left", label: "Wickets left" },
];
const CHASE = "#7DD3FC", DEFEND = "#F472B6";
const $ = (id) => document.getElementById(id);
let model = null, calc = null, chart = null;

init();

async function init() {
  highlightNav();
  let sim;
  try {
    [model, sim] = await Promise.all([loadJSON("data/lr_core.json"), loadJSON("data/calculator.json")]);
  } catch {
    return;
  }
  calc = buildCalculator(model, sim);
  const t = model.test_metrics;
  $("model-note").textContent =
    "Uses the simple model (LR-core, test Brier " + fix(t.brier) + ") where past chases passed " +
    "through a similar spot, and a ball-by-ball simulation where they did not. It knows nothing " +
    "about the teams, the venue or the target, so it gives a league-average answer.";
  if (!chartAvailable()) showError(CHART_MISSING);
  for (const f of FIELDS) {
    const [lo, hi] = model.input_ranges[f.key];
    Object.assign($(f.id), { min: lo, max: hi });
    $(f.id).addEventListener("input", update);
  }
  document.querySelectorAll("[data-step]").forEach((b) => b.addEventListener("click", () => {
    const input = $(b.dataset.for);
    const f = FIELDS.find((x) => x.id === b.dataset.for);
    const [lo, hi] = model.input_ranges[f.key];
    const cur = Number.parseInt(input.value, 10);
    const next = Number.isFinite(cur) ? cur + Number(b.dataset.step) : lo;
    input.value = String(Math.min(hi, Math.max(lo, next)));
    update();
  }));
  $("calc-form").addEventListener("submit", (e) => e.preventDefault());
  onThemeChange(() => { chart?.destroy(); chart = null; update(); });
  update();
}

function readInputs() {
  const values = {};
  let ok = true;
  for (const f of FIELDS) {
    const input = $(f.id);
    const err = $(`err-${f.id}`);
    const r = parseField(f.label, input.value, model.input_ranges[f.key]);
    input.setAttribute("aria-invalid", String(!r.ok));
    err.hidden = r.ok;
    err.textContent = r.ok ? "" : r.message;
    if (r.ok) values[f.key] = r.value; else ok = false;
  }
  return ok ? values : null;
}

// Never print a hard 0% or 100% for an open chase: below the floor say "under 1%".
function shown(p) {
  if (p < calc.floor) return `under ${pct(calc.floor)}`;
  if (p > 1 - calc.floor) return `over ${pct(1 - calc.floor)}`;
  return pct(p);
}

function update() {
  const v = readInputs();
  if (!v) {
    $("readout").textContent = "–";
    $("sentence").textContent = "Fix the highlighted field to see a probability.";
    $("source").textContent = "";
    return;
  }
  const { runs_needed: r, balls_left: b, wickets_left: w } = v;
  const p = calc.p(r, b, w);
  setTeamTint(p >= 0.5 ? CHASE : DEFEND, Math.abs(p - 0.5) * 2);
  $("readout").textContent = shown(p);
  $("sentence").textContent =
    `A team needing ${r} from ${plural(b, "ball")} with ${plural(w, "wicket")} in hand wins ` +
    `${p < calc.floor ? "very rarely" : p > 1 - calc.floor ? "almost always" : `about ${pct(p)} of the time`} ` +
    "in our model.";
  const n = calc.support(r, b, w);
  const a = calc.weight(r, b, w);
  $("source").textContent = n === 0
    ? "No past chase passed through this spot, so this comes from the ball-by-ball simulation. " +
      `The simple model alone would say ${shown(calc.lr(r, b, w))}.`
    : `${plural(n, "past chase")} passed through this spot, so the simple model gets ${pct(a)} of the ` +
      `weight and the simulation ${pct(1 - a)}.`;
  drawCurve(v);
}

function drawCurve(v) {
  $("curve-caption").textContent =
    `Win probability for ${v.runs_needed} needed with ${plural(v.wickets_left, "wicket")} in hand, ` +
    "as the balls run out (left to right). The dot is your entry.";
  if (!chartAvailable()) return;
  const [lo, hi] = model.input_ranges.balls_left;
  const curve = [];
  for (let b = hi; b >= lo; b--) curve.push({ x: b, y: 100 * calc.p(v.runs_needed, b, v.wickets_left) });
  const here = [{ x: v.balls_left, y: 100 * calc.p(v.runs_needed, v.balls_left, v.wickets_left) }];
  if (chart) {
    chart.data.datasets[0].data = curve;
    chart.data.datasets[1].data = here;
    chart.update("none");
    return;
  }
  Chart.defaults.font = chartFonts();
  Chart.defaults.color = cssVar("--muted");
  chart = new Chart($("curve"), {
    type: "line",
    data: {
      datasets: [
        { data: curve, borderColor: cssVar("--floodlight"), borderWidth: 2.5, pointRadius: 0,
          fill: { target: { value: 50 }, above: "rgba(125, 211, 252, .14)", below: "rgba(244, 114, 182, .14)" } },
        { type: "scatter", data: here, backgroundColor: cssVar("--ink"), pointRadius: 6 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      events: [],
      scales: {
        x: { type: "linear", reverse: true, min: lo, max: hi, title: { display: true, text: "Balls left" },
             ticks: { stepSize: 12 }, grid: { display: false } },
        y: { min: 0, max: 100, ticks: { stepSize: 25, callback: (t) => `${t}%` },
             grid: { color: cssVar("--line") }, title: { display: true, text: "Win probability" } },
      },
    },
  });
}
