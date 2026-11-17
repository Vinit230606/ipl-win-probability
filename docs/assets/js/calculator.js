// What-if calculator: LR-core blended with the ball-by-ball simulation where the data is thin,
// then made consistent with cricket logic (see edge-cases.html). Everything is computed in the
// browser from data/lr_core.json and data/calculator.json. Team pickers only change colours.
import {
  CHART_MISSING, chartAvailable, chartFonts, cssVar, el, fix, highlightNav, loadJSON, onThemeChange,
  pct, plural, setTeamTint, showError,
} from "./common.js";
import { parseField } from "./lr_core.js";
import { buildCalculator } from "./simulation.js";
import { CURRENT, TEAMS, applyKits, isDay, matchKits } from "./teams.js";

const FIELDS = [
  { id: "runs", key: "runs_needed", label: "Runs needed" },
  { id: "balls", key: "balls_left", label: "Balls left" },
  { id: "wkts", key: "wickets_left", label: "Wickets in hand" },
];
const $ = (id) => document.getElementById(id);
let model = null, calc = null, chart = null;
let side = { chase: { code: "Chasing side", line: null }, defend: { code: "Defending side", line: null } };

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
    "about the teams, the venue or the target, so it gives a league-average answer. Picking teams " +
    "only changes the colours.";
  if (!chartAvailable()) showError(CHART_MISSING);
  for (const id of ["pick-chase", "pick-defend"]) {
    $(id).replaceChildren(el("option", { value: "", text: "Neutral" }),
      ...CURRENT.map((c) => el("option", { value: c, text: `${c}, ${TEAMS[c].name}` })));
    $(id).addEventListener("change", () => { setSides(); chart?.destroy(); chart = null; update(); });
  }
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
  onThemeChange(() => { setSides(); chart?.destroy(); chart = null; update(); });
  setSides();
  update();
}

// Team colours: picked kits (with the clash rule), else turf for the chasing side and chalk-dim
// for the defending side.
function setSides() {
  const c = $("pick-chase").value, d = $("pick-defend").value;
  const body = document.body;
  if (c && d && c !== d) {
    const k = matchKits(TEAMS[c].name, TEAMS[d].name, isDay());
    applyKits(k);
    side = { chase: { code: c, line: k.chase.lineColor }, defend: { code: d, line: k.defend.lineColor } };
    return;
  }
  for (const v of ["--chase", "--chase-line", "--chase-ink", "--defend", "--defend-line", "--defend-ink"]) body.style.removeProperty(v);
  delete body.dataset.chase; delete body.dataset.defend; body.classList.remove("defend-hatch");
  side = { chase: { code: c || "Chasing side", line: c ? null : null }, defend: { code: d || "Defending side", line: null } };
  if (c) { const k = matchKits(TEAMS[c].name, "", isDay()); body.style.setProperty("--chase-line", k.chase.lineColor); body.style.setProperty("--chase", k.chase.fill); side.chase.line = k.chase.lineColor; }
  if (d) { const k = matchKits("", TEAMS[d].name, isDay()); body.style.setProperty("--defend-line", k.defend.lineColor); body.style.setProperty("--defend", k.defend.fill); side.defend.line = k.defend.lineColor; }
}
// neutral: DESIGN.md tiles, Iris Gleam for the chasing side and Orchid Bloom for the defending side
const chaseLine = () => side.chase.line ?? cssVar("--color-iris-gleam");
const defendLine = () => side.defend.line ?? cssVar("--color-orchid-bloom");

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

function pips(w) {
  $("pips").replaceChildren(...Array.from({ length: 10 }, (_, i) => el("span", { class: `pip${i < w ? " on" : ""}` })));
}

function update() {
  const v = readInputs();
  const wv = Number.parseInt($("wkts").value, 10);
  pips(Number.isFinite(wv) ? Math.max(0, Math.min(10, wv)) : 0);
  if (!v) {
    $("readout").textContent = "–";
    $("sentence").textContent = "Fix the highlighted field to see a probability.";
    $("source").textContent = "";
    return;
  }
  const { runs_needed: r, balls_left: b, wickets_left: w } = v;
  const p = calc.p(r, b, w);
  setTeamTint(p >= 0.5 ? chaseLine() : defendLine());
  $("readout").textContent = shown(p);
  const who = side.chase.code === "Chasing side" ? "A team" : side.chase.code;
  $("sentence").textContent =
    `${who} needing ${r} off ${plural(b, "ball")} with ${plural(w, "wicket")} in hand wins ` +
    `${p < calc.floor ? "very rarely" : p > 1 - calc.floor ? "almost always" : `about ${pct(p)} of the time`} ` +
    "in our model.";
  $("pred-bar").style.width = `${(100 * p).toFixed(2)}%`;
  $("pred-chase").textContent = `${side.chase.code} ${shown(p)}`;
  $("pred-defend").textContent = `${shown(1 - p)} ${side.defend.code}`;
  const n = calc.support(r, b, w);
  const a = calc.weight(r, b, w);
  $("source").textContent = n === 0
    ? "No past chase passed through this spot, so this comes from the ball-by-ball simulation. " +
      `The simple model alone would say ${shown(calc.lr(r, b, w))}.`
    : `${plural(n, "past chase")} passed through this spot, so the simple model gets ${pct(a)} of the ` +
      `weight and the simulation ${pct(1 - a)}.`;
  drawCurve(v);
}

function rgba(hex, al) {
  const n = Number.parseInt(hex.replace("#", "").slice(0, 6), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${al})`;
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
  const halves = {
    id: "halves",
    beforeDatasetsDraw(ch) {
      const { ctx, chartArea: a, scales: { y } } = ch;
      const mid = y.getPixelForValue(50);
      ctx.save();
      ctx.fillStyle = rgba(chaseLine(), 0.08); ctx.fillRect(a.left, a.top, a.right - a.left, mid - a.top);
      ctx.fillStyle = rgba(defendLine(), 0.08); ctx.fillRect(a.left, mid, a.right - a.left, a.bottom - mid);
      ctx.restore();
    },
  };
  Chart.defaults.font = chartFonts();
  Chart.defaults.color = cssVar("--chalk-dim");
  chart = new Chart($("curve"), {
    type: "line",
    data: {
      datasets: [
        { data: curve, borderColor: cssVar("--chalk"), borderWidth: 2.5, pointRadius: 0 },
        { type: "scatter", data: here, backgroundColor: chaseLine(), borderColor: cssVar("--chalk"), borderWidth: 2, pointRadius: 7 },
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
             grid: { color: cssVar("--rope") }, title: { display: true, text: "Win probability" } },
      },
    },
  });
}
