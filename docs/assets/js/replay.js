// Match replay (design 13.3): filters, deep links, chart, scoreboard strip, keyboard, table.
import {
  CHART_MISSING, chartAvailable, chartFonts, cssVar, el, fix, fmtDate, highlightNav, loadJSON,
  onThemeChange, pct, plural, reducedMotion, setTeamTint, showError, table, teamColors, teamName,
  teamShort,
} from "./common.js";

const $ = (id) => document.getElementById(id);
const ui = {
  season: $("season"), team: $("team"), search: $("search"), select: $("match-select"),
  featured: $("featured"), filterMsg: $("filter-msg"), title: $("match-title"), meta: $("match-meta"),
  state: $("strip-state"), pModel: $("p-model"), pOther: $("p-other"), pBase: $("p-base"),
  box: $("chart-box"), canvas: $("chart"), detail: $("detail"), summary: $("summary"),
  toggle: $("table-toggle"), tableWrap: $("ball-table-wrap"), live: $("live"), note: $("note-models"),
  lead: $("strip-lead"), teamBat: $("sw-bat"), teamBowl: $("sw-bowl"),
  teamBatName: $("leg-bat"), teamBowlName: $("leg-bowl"),
};
let teamTint = { batting: "#7DD3FC", bowling: "#F472B6" };

let index = null;     // matches.json
let results = null;   // results.json
let labels = null;    // {model, other, base}
let match = null;     // current per-match JSON
let points = [];      // start state + balls
let sel = 0;          // selected point index
let chart = null;
let drawProgress = 1; // 0..1 while the model line draws in
let clipping = false;
let WINDOW = 0;     // last-N legal balls window, from results.json

init();

async function init() {
  highlightNav();
  try {
    [index, results] = await Promise.all([loadJSON("data/matches.json"), loadJSON("data/results.json")]);
  } catch {
    return;
  }
  labels = {
    model: results.methods[index.best_model].label,
    other: results.methods[index.other_model].label,
    base: results.methods.baseline.label,
  };
  for (const [id, text] of [["lab-model", labels.model], ["lab-other", labels.other], ["lab-base", labels.base],
    ["leg-model", labels.model], ["leg-other", labels.other], ["leg-base", labels.base]]) $(id).textContent = text;
  $("leg-big").textContent = `Big over (${results.evaluation.big_over_runs}+ runs)`;
  WINDOW = results.evaluation.momentum_window;
  $("win18").textContent = String(WINDOW);
  if (!chartAvailable()) showError(CHART_MISSING);
  writeModelNote();
  writeIntroAnswer();
  populateFilters();

  const want = new URLSearchParams(location.search).get("match");
  const known = index.matches.some((m) => m.match_id === want);
  if (want && !known) {
    notice(`Match ${want} isn't one of the test-season chases on this site. Showing the featured chase instead.`);
  }
  renderOptions();
  await openMatch(known ? want : index.featured_match_id);

  ui.season.addEventListener("change", renderOptions);
  ui.team.addEventListener("change", renderOptions);
  ui.search.addEventListener("input", renderOptions);
  ui.select.addEventListener("change", () => ui.select.value && openMatch(ui.select.value));
  ui.featured.addEventListener("click", () => {
    ui.season.value = ""; ui.team.value = ""; ui.search.value = "";
    renderOptions();
    openMatch(index.featured_match_id);
  });
  ui.box.addEventListener("keydown", onKey);
  ui.toggle.addEventListener("click", toggleTable);
  onThemeChange(() => match && buildChart(false));
}

function writeModelNote() {
  const s = results.splits.seasons;
  const best = results.test[index.best_model];
  const other = results.test[index.other_model];
  ui.note.textContent =
    `${labels.model} is the main line because it had the lowest Brier score on the ${s.val.join(", ")} ` +
    `validation season, before the test seasons (${s.test.join(" and ")}) were scored. That choice was ` +
    `not changed afterwards. On the test seasons: ${best.verdict} ${other.verdict} ` +
    `${labels.other} is drawn as a second line so you can see where the two disagree. `;
  ui.note.append(el("a", { href: "results.html", text: "See the full results" }), ".");
}

function writeIntroAnswer() {
  const T = results.test;
  const beats = ["lr_full", "lr_core", "gbm"].filter((k) => T[k].bss_ci[0] > 0);
  const lab = (k) => results.methods[k].label;
  const seasons = results.splits.seasons.test.join(" and ");
  $("intro-answer").textContent = beats.length
    ? `On the ${seasons} seasons, ${beats.map(lab).join(" and ")} beat the baseline; ` +
      `${["lr_full", "lr_core", "gbm"].filter((k) => !beats.includes(k)).map(lab).join(" and ") || "every model did"}` +
      `${beats.length < 3 ? " did not" : ""}.`
    : `On the ${seasons} seasons, no model was shown to beat the baseline.`;
}

// ---------- filters ----------
function populateFilters() {
  const seasons = [...new Set(index.matches.map((m) => m.season))].sort((a, b) => b - a);
  ui.season.replaceChildren(el("option", { value: "", text: "All seasons" }),
    ...seasons.map((s) => el("option", { value: String(s), text: String(s) })));
  const teams = [...new Set(index.matches.flatMap((m) => [teamName(m.batting_team), teamName(m.bowling_team)]))].sort();
  ui.team.replaceChildren(el("option", { value: "", text: "All teams" }),
    ...teams.map((t) => el("option", { value: t, text: t })));
}

function matchText(m) {
  return [m.match_id, m.date, fmtDate(m.date), m.venue ?? "", m.result_text, String(m.target),
    teamName(m.batting_team), teamName(m.bowling_team), teamShort(m.batting_team), teamShort(m.bowling_team)]
    .join(" ").toLowerCase();
}

function filtered() {
  const season = ui.season.value, team = ui.team.value;
  const words = ui.search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return index.matches.filter((m) =>
    (!season || String(m.season) === season) &&
    (!team || teamName(m.batting_team) === team || teamName(m.bowling_team) === team) &&
    words.every((w) => matchText(m).includes(w)));
}

function renderOptions() {
  const list = filtered();
  const q = ui.search.value.trim();
  if (!list.length) {
    notice(q ? `No chase matches "${q}". Try a team name or clear the filters.`
      : "No chase matches these filters. Clear the filters to see every chase.");
  } else {
    ui.filterMsg.hidden = true;
  }
  ui.select.disabled = !list.length;
  ui.select.replaceChildren(
    el("option", { value: "", text: list.length ? `${plural(list.length, "chase")} to choose from` : "No chases" }),
    ...list.map((m) => el("option", {
      value: m.match_id,
      text: `${fmtDate(m.date)} · ${teamShort(m.batting_team)} chasing ${m.target} v ${teamShort(m.bowling_team)}`,
    })));
  if (match && list.some((m) => m.match_id === match.match_id)) ui.select.value = match.match_id;
}

function notice(text) {
  ui.filterMsg.textContent = text;
  ui.filterMsg.hidden = false;
}

// ---------- match ----------
async function openMatch(id) {
  let m;
  try {
    m = await loadJSON(`data/matches/${encodeURIComponent(id)}.json`);
  } catch {
    return;
  }
  match = m;
  points = [{
    i: 0, start: true, label: "start", event: "", score: "0/0", runs_needed: m.target,
    balls_left: 120, wickets_left: 10, rrr: (6 * m.target) / 120, r18: 0, w18: 0,
    terminal: false, wicket: false, ...m.start,
  }, ...m.balls];
  sel = 0;
  if ([...ui.select.options].some((o) => o.value === id)) ui.select.value = id;
  history.replaceState(null, "", `?match=${encodeURIComponent(id)}`);

  teamTint = teamColors(m.batting_team, m.bowling_team);
  ui.teamBat.style.background = teamTint.batting;
  ui.teamBowl.style.background = teamTint.bowling;
  ui.teamBatName.textContent = `${teamShort(m.batting_team)} ahead`;
  ui.teamBowlName.textContent = `${teamShort(m.bowling_team)} ahead`;
  ui.title.textContent = `${teamName(m.batting_team)} v ${teamName(m.bowling_team)}`;
  ui.meta.textContent = `${m.venue ? m.venue + ", " : ""}${fmtDate(m.date)}. Target ${m.target}. ${m.result_text}.`;
  const s = m.summary;
  ui.summary.textContent =
    `This match: ${labels.model} Brier ${fix(s.brier_model)}, ${labels.other} ${fix(s.brier_other)}, ` +
    `${labels.base} ${fix(s.brier_baseline)} (lower is better). ${labels.model} was closer to the result ` +
    `than the baseline on ${pct(s.model_closer_share)} of balls.`;
  renderTable();
  buildChart(true);
  select(0, false);
}

function stateText(p) {
  if (p.terminal) return match.chase_won ? "Chase won: target reached" : "Chase lost";
  return `Need ${p.runs_needed} from ${plural(p.balls_left, "ball")}, ${plural(p.wickets_left, "wicket")} in hand`;
}

const probText = (p, v) => (p.terminal ? `${pct(v)} decided` : pct(v));
const eventText = (e) => (e === "·" ? "dot ball" : e);

function detailText(p) {
  if (p.start) return `Before ball 1: target ${match.target}, required rate ${fix(p.rrr, 1)}.`;
  return `Ball ${p.label}: ${eventText(p.event)}. ${p.score}. RRR ${fix(p.rrr, 1)}. ` +
    `Last ${WINDOW}: ${plural(p.r18, "run")}, ${p.w18}w.${p.terminal ? " Decided." : ""}`;
}

// Page tint follows the main model: the colour of the side it favours, stronger as it gets surer.
function tint(p) {
  const v = p.p_model;
  const chasing = v >= 0.5;
  const team = chasing ? match.batting_team : match.bowling_team;
  setTeamTint(chasing ? teamTint.batting : teamTint.bowling, Math.abs(v - 0.5) * 2);
  const share = chasing ? v : 1 - v;
  ui.lead.textContent = p.terminal
    ? `${teamName(match.chase_won ? match.batting_team : match.bowling_team)} won`
    : Math.abs(v - 0.5) < 0.02 ? "Level: anyone's game"
      : `${teamName(team)} ahead · ${pct(share)} by ${labels.model}`;
}

function select(k, announce = true) {
  sel = Math.max(0, Math.min(points.length - 1, k));
  const p = points[sel];
  tint(p);
  ui.state.textContent = stateText(p);
  ui.pModel.textContent = probText(p, p.p_model);
  ui.pOther.textContent = probText(p, p.p_other);
  ui.pBase.textContent = probText(p, p.p_base);
  ui.detail.textContent = detailText(p);
  if (announce) {
    ui.live.textContent = `${detailText(p)} ${stateText(p)}. ${labels.model} ${probText(p, p.p_model)}, ` +
      `${labels.other} ${probText(p, p.p_other)}, ${labels.base} ${probText(p, p.p_base)}.`;
  }
  ui.tableWrap.querySelectorAll("tr.selected").forEach((r) => r.classList.remove("selected"));
  ui.tableWrap.querySelector(`tr[data-i="${sel}"]`)?.classList.add("selected");
  if (chart) chart.draw();
}

function onKey(e) {
  const moves = { ArrowLeft: sel - 1, ArrowRight: sel + 1, Home: 0, End: points.length - 1 };
  if (!(e.key in moves)) return;
  e.preventDefault();
  select(moves[e.key]);
}

// ---------- chart ----------
function colors() {
  return {
    model: cssVar("--floodlight"), other: cssVar("--outfield"), base: cssVar("--muted"),
    red: cssVar("--ball-red"), big: cssVar("--big-over"), ink: cssVar("--ink"), line: cssVar("--line"),
  };
}

const bigOverPlugin = {
  id: "bigOvers",
  beforeDatasetsDraw(ch) {
    const { ctx, chartArea: a, scales: { x } } = ch;
    ctx.save();
    ctx.fillStyle = colors().big;
    for (const b of match.big_overs) {
      const x0 = Math.max(a.left, x.getPixelForValue(b.i_from - 0.5));
      const x1 = Math.min(a.right, x.getPixelForValue(b.i_to + 0.5));
      ctx.fillRect(x0, a.top, x1 - x0, a.bottom - a.top);
    }
    ctx.restore();
  },
};

// Selected ball: a soft glowing band and a glowing dot on the main line, in the leading side's colour.
const cursorPlugin = {
  id: "cursor",
  afterDatasetsDraw(ch) {
    const { ctx, chartArea: a, scales: { x, y } } = ch;
    const p = points[sel];
    if (!p) return;
    const px = x.getPixelForValue(sel);
    const py = y.getPixelForValue(100 * p.p_model);
    const col = p.p_model >= 0.5 ? teamTint.batting : teamTint.bowling;
    ctx.save();
    const band = ctx.createLinearGradient(px - 28, 0, px + 28, 0);
    band.addColorStop(0, "rgba(0,0,0,0)");
    band.addColorStop(0.5, hexA(col, 0.18));
    band.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = band;
    ctx.fillRect(px - 28, a.top, 56, a.bottom - a.top);
    ctx.strokeStyle = hexA(col, 0.7);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(px, a.top);
    ctx.lineTo(px, a.bottom);
    ctx.stroke();
    const halo = ctx.createRadialGradient(px, py, 0, px, py, 26);
    halo.addColorStop(0, hexA(col, 0.65));
    halo.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(px, py, 26, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = col;
    ctx.shadowColor = col;
    ctx.shadowBlur = 14;
    ctx.beginPath();
    ctx.arc(px, py, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  },
};

function hexA(hex, a) {
  const n = Number.parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

// Draw-in of the model line and its wicket markers on match change (the one motion moment).
const drawInPlugin = {
  id: "drawIn",
  beforeDatasetDraw(ch, args) {
    if (drawProgress >= 1 || (args.index !== 0 && args.index !== 3)) return;
    const a = ch.chartArea;
    ch.ctx.save();
    ch.ctx.beginPath();
    ch.ctx.rect(a.left - 6, a.top - 6, (a.right - a.left + 12) * drawProgress, a.bottom - a.top + 12);
    ch.ctx.clip();
    clipping = true;
  },
  afterDatasetDraw(ch) {
    if (clipping) { ch.ctx.restore(); clipping = false; }
  },
};

function overTicks() {
  const firsts = [];
  let last = -1;
  points.forEach((p) => {
    if (p.start) return;
    const over = Number(p.label.split(".")[0]);
    if (over !== last) { firsts.push({ value: p.i, over: over + 1 }); last = over; }
  });
  return firsts;
}

function buildChart(animate) {
  if (!chartAvailable()) return;
  const c = colors();
  const ticks = overTicks();
  const tickLabel = new Map(ticks.map((t) => [t.value, String(t.over)]));
  const line = (key) => points.map((p) => ({ x: p.i, y: 100 * p[key] }));
  Chart.defaults.font = chartFonts();
  Chart.defaults.color = c.base;
  if (chart) chart.destroy();
  chart = new Chart(ui.canvas, {
    type: "line",
    data: {
      datasets: [
        {
          label: labels.model, data: line("p_model"), borderColor: c.model, borderWidth: 2.5, pointRadius: 0, order: 1,
          // shade between the main line and 50%: chasing side's colour above, defending side's below
          fill: { target: { value: 50 }, above: hexA(teamTint.batting, 0.16), below: hexA(teamTint.bowling, 0.16) },
        },
        { label: labels.other, data: line("p_other"), borderColor: c.other, borderWidth: 1.5, pointRadius: 0, order: 2 },
        { label: labels.base, data: line("p_base"), borderColor: c.base, borderWidth: 1.5, borderDash: [6, 4], pointRadius: 0, order: 3 },
        {
          type: "scatter", label: "Wicket", order: 0,
          data: points.filter((p) => p.wicket).map((p) => ({ x: p.i, y: 100 * p.p_model })),
          backgroundColor: c.red, borderColor: c.red, pointRadius: 5, pointHoverRadius: 5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      events: ["mousemove", "click", "touchstart", "touchmove"],
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: {
        x: {
          type: "linear", min: 0, max: points.length - 1,
          afterBuildTicks: (ax) => {
            const step = ax.width && ax.width < 520 ? 2 : 1;
            ax.ticks = ticks.filter((t, k) => k % step === 0).map((t) => ({ value: t.value }));
          },
          ticks: { autoSkip: false, maxRotation: 0, callback: (v) => tickLabel.get(v) ?? "" },
          grid: { display: false },
          title: { display: true, text: "Over" },
        },
        y: {
          min: 0, max: 100,
          ticks: { stepSize: 25, callback: (v) => `${v}%` },
          grid: { color: c.line },
          title: { display: true, text: "Chasing team win probability" },
        },
      },
      onHover: (evt) => pick(evt),
      onClick: (evt) => pick(evt),
    },
    plugins: [bigOverPlugin, cursorPlugin, drawInPlugin],
  });
  if (animate && !reducedMotion()) drawIn(); else { drawProgress = 1; chart.draw(); }
}

function pick(evt) {
  if (!chart || evt.x == null) return;
  const v = chart.scales.x.getValueForPixel(evt.x);
  if (!Number.isFinite(v)) return;
  const k = Math.round(v);
  if (k !== sel && k >= 0 && k < points.length) select(k);
}

function drawIn() {
  const t0 = performance.now();
  const dur = 700;
  drawProgress = 0;
  const step = (t) => {
    drawProgress = Math.min(1, (t - t0) / dur);
    chart.draw();
    if (drawProgress < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ---------- table fallback ----------
function renderTable() {
  const rows = points.map((p) => [
    p.start ? "Start" : p.label, p.start ? "" : eventText(p.event), p.score,
    p.terminal ? "–" : String(p.runs_needed), String(p.balls_left), String(p.wickets_left),
    fix(p.rrr, 1), `${p.r18}/${p.w18}`,
    probText(p, p.p_model), probText(p, p.p_other), probText(p, p.p_base),
  ]);
  const wrap = table(
    ["Ball", "Event", "Score", "Need", "Balls left", "Wickets left", "RRR", `Last ${WINDOW} (runs/w)`,
      labels.model, labels.other, labels.base],
    rows,
    { caption: `${teamName(match.batting_team)} chasing ${match.target}: every ball`, numeric: [3, 4, 5, 6, 8, 9, 10] },
  );
  wrap.querySelectorAll("tbody tr").forEach((tr, k) => {
    tr.dataset.i = String(k);
    if (points[k].terminal) tr.classList.add("decided");
  });
  ui.tableWrap.replaceChildren(wrap);
}

function toggleTable() {
  const open = ui.tableWrap.hidden;
  ui.tableWrap.hidden = !open;
  ui.toggle.setAttribute("aria-expanded", String(open));
  ui.toggle.textContent = open ? "Hide table" : "View as table";
}
