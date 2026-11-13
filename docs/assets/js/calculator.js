// What-if calculator (design 13.3): LR-core computed in the browser from data/lr_core.json.
import {
  CHART_MISSING, chartAvailable, chartFonts, cssVar, fix, highlightNav, loadJSON, onThemeChange,
  pct, plural, showError,
} from "./common.js";
import { parseField, predict } from "./lr_core.js";

const FIELDS = [
  { id: "runs", key: "runs_needed", label: "Runs needed" },
  { id: "balls", key: "balls_left", label: "Balls left" },
  { id: "wkts", key: "wickets_left", label: "Wickets left" },
];
const $ = (id) => document.getElementById(id);
let model = null;
let chart = null;

init();

async function init() {
  highlightNav();
  try {
    model = await loadJSON("data/lr_core.json");
  } catch {
    return;
  }
  const t = model.test_metrics;
  $("model-note").textContent =
    `Uses the simple model (LR-core). Test Brier ${fix(t.brier)}; skill against the historical ` +
    `baseline ${fix(t.bss)} (95% interval ${fix(t.bss_ci[0])} to ${fix(t.bss_ci[1])}). It knows ` +
    "nothing about the teams, the venue or the target, so it gives a league-average answer.";
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

function update() {
  const v = readInputs();
  if (!v) {
    $("readout").textContent = "–";
    $("sentence").textContent = "Fix the highlighted field to see a probability.";
    return;
  }
  const p = predict(model, v.runs_needed, v.balls_left, v.wickets_left);
  $("readout").textContent = pct(p);
  $("sentence").textContent =
    `A team needing ${v.runs_needed} from ${plural(v.balls_left, "ball")} with ` +
    `${plural(v.wickets_left, "wicket")} in hand won about ${pct(p)} of the time in our model.`;
  drawCurve(v);
}

function drawCurve(v) {
  $("curve-caption").textContent =
    `Win probability for ${v.runs_needed} needed with ${plural(v.wickets_left, "wicket")} in hand, ` +
    "as the balls run out (left to right). The dot is your entry.";
  if (!chartAvailable()) return;
  const [lo, hi] = model.input_ranges.balls_left;
  const curve = [];
  for (let b = hi; b >= lo; b--) curve.push({ x: b, y: 100 * predict(model, v.runs_needed, b, v.wickets_left) });
  const here = [{ x: v.balls_left, y: 100 * predict(model, v.runs_needed, v.balls_left, v.wickets_left) }];
  if (chart) {
    chart.data.datasets[0].data = curve;
    chart.data.datasets[1].data = here;
    chart.update("none");
    return;
  }
  const accent = cssVar("--floodlight");
  Chart.defaults.font = chartFonts();
  Chart.defaults.color = cssVar("--muted");
  chart = new Chart($("curve"), {
    type: "line",
    data: {
      datasets: [
        { data: curve, borderColor: accent, borderWidth: 2.5, pointRadius: 0 },
        { type: "scatter", data: here, backgroundColor: cssVar("--ink"), pointRadius: 5 },
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
