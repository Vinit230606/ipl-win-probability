// Match replay ("Under the lights"): TV score strip, win predictor bar, team-coloured chart,
// match picker, deep links (?match=), keyboard stepping, table fallback. Numbers come unchanged
// from data/matches.json, data/matches/<id>.json and data/results.json.
import {
  CHART_MISSING, chartAvailable, chartFonts, cssVar, el, fix, fmtDate, highlightNav, loadJSON,
  onThemeChange, pct, plural, reducedMotion, setTeamTint, showError, table, teamName,
} from "./common.js";
import { CURRENT, TEAMS, applyKits, badgeStyle, isDay, lineFor, matchKits, teamFromName } from "./teams.js";

const MATCH_ERROR = "This match couldn't be loaded. Check the match ID in the address bar or pick a chase from the list.";
const $ = (id) => document.getElementById(id);
const ui = {
  search: $("search"), list: $("match-list"), count: $("list-count"), seasons: $("season-pills"),
  teams: $("team-badges"), featured: $("featured"), filterMsg: $("filter-msg"), title: $("match-title"),
  meta: $("match-meta"), board: $("scoreboard"), sbChase: $("sb-chase"), sbDefend: $("sb-defend"),
  sbScore: $("sb-score"), sbOvers: $("sb-overs"), sbEq: $("sb-eq"), sbRrr: $("sb-rrr"), sbTarget: $("sb-target"),
  predChase: $("pred-chase"), predDefend: $("pred-defend"), predBar: $("pred-bar"),
  pModel: $("p-model"), pOther: $("p-other"), pBase: $("p-base"),
  box: $("chart-box"), canvas: $("chart"), detail: $("detail"), summary: $("summary"),
  toggle: $("table-toggle"), tableWrap: $("ball-table-wrap"), live: $("live"), note: $("note-models"),
  legBat: $("leg-bat"), legBowl: $("leg-bowl"),
};

let index = null, results = null, labels = null;
let match = null, points = [], sel = 0, chart = null, kits = null, pulsed = false;
let WINDOW = 0, BIG = 15;
const filters = { season: "", team: "" };

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
    ["leg-model", labels.model], ["leg-other", labels.other], ["leg-base", `${labels.base} (historical)`]]) $(id).textContent = text;
  BIG = results.evaluation.big_over_runs;
  $("leg-big").textContent = `Big over (${BIG}+ runs)`;
  WINDOW = results.evaluation.momentum_window;
  $("win18").textContent = String(WINDOW);
  if (!chartAvailable()) showError(CHART_MISSING);
  writeModelNote();
  writeIntroAnswer();
  buildPicker();

  const want = new URLSearchParams(location.search).get("match");
  const known = index.matches.some((m) => m.match_id === want);
  if (want && !known) {
    notice(`Match ${want} isn't one of the test-season chases on this site. Showing the featured chase instead.`);
  }
  renderList();
  await openMatch(known ? want : index.featured_match_id);

  ui.search.addEventListener("input", renderList);
  $("hero-search").addEventListener("submit", onHeroSubmit);
  ui.featured.addEventListener("click", () => {
    ui.search.value = ""; filters.season = ""; filters.team = "";
    syncPressed();
    renderList();
    openMatch(index.featured_match_id);
  });
  ui.box.addEventListener("keydown", onKey);
  ui.toggle.addEventListener("click", toggleTable);
  onThemeChange(() => { if (match) { setKits(); buildPicker(); renderList(); buildChart(); select(sel, false); } });
}

function writeModelNote() {
  const s = results.splits.seasons;
  const best = results.test[index.best_model];
  const other = results.test[index.other_model];
  ui.note.textContent =
    `${labels.model} is the main line because it had the lowest Brier score on the ${s.val.join(", ")} ` +
    `validation season, before the test seasons (${s.test.join(" and ")}) were scored. That choice was ` +
    `not changed afterwards. On the test seasons: ${best.verdict} ${other.verdict} ` +
    `${labels.other} is drawn as a second, dotted line so you can see where the two disagree. `;
  ui.note.append(el("a", { href: "results.html", text: "See the full results" }), ".");
}

function writeIntroAnswer() {
  const T = results.test;
  const beats = ["lr_full", "lr_core", "gbm"].filter((k) => T[k].bss_ci[0] > 0);
  const lab = (k) => results.methods[k].label;
  const seasons = results.splits.seasons.test.join(" and ");
  const rest = ["lr_full", "lr_core", "gbm"].filter((k) => !beats.includes(k)).map(lab);
  $("intro-answer").textContent = beats.length
    ? `On ${seasons}, ${beats.map(lab).join(" and ")} beat the historical baseline${rest.length ? `; ${rest.join(" and ")} did not` : ""}.`
    : `On ${seasons}, no model was shown to beat the historical baseline.`;
  const best = beats.reduce((a, k) => (T[k].bss > T[a].bss ? k : a), beats[0] ?? "lr_full");
  $("stat-head").textContent = beats.length
    ? `${lab(best)} removed ${pct(T[best].bss)} of the baseline's error on chases it had never seen.`
    : "No model was shown to beat the historical baseline.";
  $("stat-text").textContent =
    `Brier skill score ${T[best].bss.toFixed(3)}, 95% interval ${T[best].bss_ci[0].toFixed(3)} to ` +
    `${T[best].bss_ci[1].toFixed(3)}, test seasons ${seasons}.`;
}

function onHeroSubmit(e) {
  e.preventDefault();
  const list = filtered();
  if (!list.length) return;
  openMatch(list[0].match_id).then(() => {
    $("replay").scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth" });
    ui.box.focus({ preventScroll: true });
  });
}

// ---------- match picker ----------
function badge(name, extra = "") {
  const t = teamFromName(name);
  return el("span", { class: `badge ${extra}`.trim(), style: badgeStyle(t), title: teamName(name), text: t.code });
}

function buildPicker() {
  const seasons = [...new Set(index.matches.map((m) => m.season))].sort((a, b) => b - a);
  ui.seasons.replaceChildren(...[["", "All seasons"], ...seasons.map((s) => [String(s), String(s)])].map(([v, t]) => {
    const b = el("button", { type: "button", class: "pill", "data-season": v, "aria-pressed": String(filters.season === v), text: t });
    b.addEventListener("click", () => { filters.season = v; syncPressed(); renderList(); });
    return b;
  }));
  ui.teams.replaceChildren(...CURRENT.map((code) => {
    const t = TEAMS[code];
    const b = el("button", { type: "button", class: "badge", style: badgeStyle(t), "data-team": code,
      "aria-pressed": String(filters.team === code), "aria-label": `${code}, ${t.name}`, title: t.name, text: code });
    b.addEventListener("click", () => { filters.team = filters.team === code ? "" : code; syncPressed(); renderList(); });
    return b;
  }));
}

function syncPressed() {
  ui.seasons.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.season === filters.season)));
  ui.teams.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.team === filters.team)));
}

function matchText(m) {
  const a = teamFromName(m.batting_team), b = teamFromName(m.bowling_team);
  return [m.match_id, m.date, fmtDate(m.date), m.venue ?? "", m.result_text, String(m.target),
    teamName(m.batting_team), teamName(m.bowling_team), a.code, b.code].join(" ").toLowerCase();
}

function filtered() {
  const words = ui.search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return index.matches.filter((m) =>
    (!filters.season || String(m.season) === filters.season) &&
    (!filters.team || teamFromName(m.batting_team).code === filters.team || teamFromName(m.bowling_team).code === filters.team) &&
    words.every((w) => matchText(m).includes(w)));
}

function shortResult(m) {
  const c = teamFromName(m.batting_team).code, d = teamFromName(m.bowling_team).code;
  const n = (m.result_text.match(/won by (\d+)/) ?? [])[1];
  if (!n) return m.result_text;
  return m.chase_won ? `${c} won by ${plural(Number(n), "wicket")}` : `${d} defended ${m.target - 1}, won by ${plural(Number(n), "run")}`;
}

function renderList() {
  const list = filtered();
  const q = ui.search.value.trim();
  if (!list.length) {
    notice(q ? `No chase matches "${q}". Try a team name or clear the filters.`
      : "No chase matches these filters. Clear the filters to see every chase.");
  } else if (!ui.filterMsg.dataset.sticky) {
    ui.filterMsg.hidden = true;
  }
  ui.count.textContent = list.length ? `${plural(list.length, "chase")}` : "No chases";
  ui.list.replaceChildren(...list.map((m) => {
    const line = lineFor(teamFromName(m.batting_team));
    const b = el("button", { type: "button", class: "match-row", style: `--row-line:${line}`, "data-id": m.match_id,
      "aria-current": String(match?.match_id === m.match_id) },
      badge(m.batting_team), el("span", { class: "mr-chased", text: `chased ${m.target} v` }), badge(m.bowling_team),
      el("span", { class: "mr-where", text: `${m.venue ?? "Venue not recorded"}, ${fmtDate(m.date)}` }),
      el("span", { class: "mr-result", text: shortResult(m) }));
    b.addEventListener("click", () => openMatch(m.match_id).then(() => $("replay").scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth" })));
    return el("li", {}, b);
  }));
}

function notice(text) {
  ui.filterMsg.textContent = text;
  ui.filterMsg.hidden = false;
}

// ---------- match ----------
function setKits() {
  kits = matchKits(match.batting_team, match.bowling_team, isDay());
  applyKits(kits);
}

async function openMatch(id) {
  let m;
  try {
    m = await loadJSON(`data/matches/${encodeURIComponent(id)}.json`);
  } catch {
    showError(MATCH_ERROR);
    ui.title.textContent = "This match couldn't be loaded";
    return;
  }
  match = m;
  pulsed = false;
  points = [{
    i: 0, start: true, label: "0.0", event: "", score: "0/0", runs_needed: m.target,
    balls_left: 120, wickets_left: 10, rrr: (6 * m.target) / 120, r18: 0, w18: 0,
    terminal: false, wicket: false, ...m.start,
  }, ...m.balls];
  sel = 0;
  history.replaceState(null, "", `?match=${encodeURIComponent(id)}`);
  setKits();

  const c = kits.chase, d = kits.defend;
  ui.sbChase.textContent = c.code;
  ui.sbChase.title = teamName(m.batting_team);
  ui.sbDefend.textContent = d.code;
  ui.sbDefend.title = teamName(m.bowling_team);
  ui.legBat.textContent = `${c.code} ahead`;
  ui.legBowl.textContent = `${d.code} ahead`;
  ui.title.textContent = `${teamName(m.batting_team)} v ${teamName(m.bowling_team)}`;
  ui.meta.textContent = `${m.venue ? m.venue + ", " : ""}${fmtDate(m.date)}. Target ${m.target}. ${resultText()}.`;
  const s = m.summary;
  ui.summary.textContent =
    `This match: ${labels.model} Brier ${fix(s.brier_model)}, ${labels.other} ${fix(s.brier_other)}, ` +
    `${labels.base} ${fix(s.brier_baseline)} (lower is better). ${labels.model} was closer to the result ` +
    `than the baseline on ${pct(s.model_closer_share)} of balls.`;
  ui.list.querySelectorAll(".match-row").forEach((b) => b.setAttribute("aria-current", String(b.dataset.id === id)));
  renderTable();
  buildChart();
  select(0, false);
}

// "RR won by 6 wickets with 4 balls left" / "CSK defended 180, won by 12 runs" (from the last ball)
function resultText() {
  const last = match.balls[match.balls.length - 1];
  const c = kits.chase.code, d = kits.defend.code;
  if (match.chase_won) {
    const w = plural(last.wickets_left, "wicket");
    return last.balls_left > 0 ? `${c} won by ${w} with ${plural(last.balls_left, "ball")} left` : `${c} won by ${w} off the last ball`;
  }
  const runs = Number.parseInt(last.score, 10);
  return `${d} defended ${match.target - 1}, won by ${plural(match.target - 1 - runs, "run")}`;
}

const eventText = (e) => (e === "·" ? "dot ball" : e);
const probText = (p, v) => (p.terminal ? `${pct(v)} decided` : pct(v));

function detailText(p) {
  if (p.start) return `Before ball 1: target ${match.target}, required rate ${fix(p.rrr, 2)}.`;
  const big = bigOverAt(p.i);
  return `Over ${p.label}: ${p.wicket ? `Wicket (${eventText(p.event)})` : eventText(p.event)}. ${p.score}. ` +
    `Required rate ${fix(p.rrr, 2)}. Last ${WINDOW} balls: ${plural(p.r18, "run")}, ${plural(p.w18, "wicket")}.` +
    `${big ? ` Big over: ${big.runs} off the over.` : ""}${p.terminal ? " Decided." : ""}`;
}

function bigOverAt(i) {
  return match.big_overs.find((b) => i >= b.i_from && i <= b.i_to);
}

function select(k, announce = true) {
  sel = Math.max(0, Math.min(points.length - 1, k));
  const p = points[sel];
  const v = p.p_model;
  // scoreboard
  ui.sbScore.textContent = p.score;
  ui.sbOvers.textContent = `(${p.label} ov)`;
  ui.board.classList.toggle("decided", p.terminal);
  if (p.terminal) {
    ui.sbEq.textContent = resultText();
    ui.sbRrr.textContent = "";
  } else {
    ui.sbEq.textContent = `need ${p.runs_needed} off ${p.balls_left}`;
    ui.sbRrr.textContent = `RRR ${fix(p.rrr, 2)}, ${plural(p.wickets_left, "wicket")} in hand`;
  }
  ui.sbTarget.replaceChildren("target ", el("b", { text: String(match.target) }));
  const lead = p.terminal ? (match.chase_won ? kits.chase.lineColor : kits.defend.lineColor)
    : v >= 0.5 ? kits.chase.lineColor : kits.defend.lineColor;
  setTeamTint(lead);
  ui.sbChase.classList.toggle("winner", p.terminal && match.chase_won);
  ui.sbDefend.classList.toggle("winner", p.terminal && !match.chase_won);
  if (p.terminal && !pulsed && !reducedMotion()) {
    pulsed = true;
    ui.board.style.setProperty("--win-line", lead);
    ui.board.classList.remove("pulse");
    void ui.board.offsetWidth;
    ui.board.classList.add("pulse");
    setTimeout(() => ui.board.classList.remove("pulse"), 700);
  }
  // predictor bar: the main model's number
  ui.predBar.style.width = `${(100 * v).toFixed(2)}%`;
  ui.predChase.textContent = `${kits.chase.code} ${pct(v)}`;
  ui.predDefend.textContent = `${pct(1 - v)} ${kits.defend.code}`;
  ui.pModel.textContent = probText(p, p.p_model);
  ui.pOther.textContent = probText(p, p.p_other);
  ui.pBase.textContent = probText(p, p.p_base);
  ui.detail.textContent = detailText(p);
  if (announce) {
    ui.live.textContent = `${detailText(p)} ${p.terminal ? resultText() : `Need ${p.runs_needed} off ${p.balls_left}`}. ` +
      `${labels.model} ${probText(p, p.p_model)}, ${labels.other} ${probText(p, p.p_other)}, ${labels.base} ${probText(p, p.p_base)}.`;
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
  return { chalk: cssVar("--chalk"), dim: cssVar("--chalk-dim"), rope: cssVar("--rope"), turf: cssVar("--turf"),
    turfLine: cssVar("--turf-line"), leather: cssVar("--leather"), sky: cssVar("--sky") };
}

function rgba(hex, a) {
  const n = Number.parseInt(hex.replace("#", "").slice(0, 6), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

function hatch(ctx, color) {
  const c = document.createElement("canvas");
  c.width = c.height = 8;
  const g = c.getContext("2d");
  g.strokeStyle = rgba(color, 0.35);
  g.lineWidth = 1.5;
  g.beginPath(); g.moveTo(0, 8); g.lineTo(8, 0); g.stroke();
  return ctx.createPattern(c, "repeat");
}

// halves in team colours, big-over columns, phase gridlines
const backdropPlugin = {
  id: "backdrop",
  beforeDatasetsDraw(ch) {
    const { ctx, chartArea: a, scales: { x, y } } = ch;
    const c = colors();
    const mid = y.getPixelForValue(50);
    ctx.save();
    ctx.fillStyle = rgba(kits.chase.lineColor, 0.08);
    ctx.fillRect(a.left, a.top, a.right - a.left, mid - a.top);
    ctx.fillStyle = kits.defend.hatch ? hatch(ctx, kits.defend.lineColor) : rgba(kits.defend.lineColor, 0.08);
    ctx.fillRect(a.left, mid, a.right - a.left, a.bottom - mid);
    ctx.fillStyle = rgba(c.turf, 0.18);
    for (const b of match.big_overs) {
      const x0 = Math.max(a.left, x.getPixelForValue(b.i_from - 0.5));
      const x1 = Math.min(a.right, x.getPixelForValue(b.i_to + 0.5));
      ctx.fillRect(x0, a.top, x1 - x0, a.bottom - a.top);
    }
    ctx.strokeStyle = rgba(c.dim, 0.45);
    ctx.fillStyle = c.dim;
    ctx.font = `500 12px ${getComputedStyle(document.body).fontFamily}`;
    ctx.setLineDash([3, 4]);
    for (const [over, text, align] of [[6, "Powerplay", "right"], [15, "Death overs", "left"]]) {
      const first = points.find((p) => !p.start && Number(p.label.split(".")[0]) === over);
      if (!first) continue;
      const px = x.getPixelForValue(first.i - 0.5);
      ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
      ctx.textAlign = align;
      ctx.fillText(text, px + (align === "right" ? -6 : 6), a.top + 14);
    }
    ctx.restore();
  },
};

// wickets as stumps, the selected ball, a big-over label, the "Decided" tag
const overlayPlugin = {
  id: "overlay",
  afterDatasetsDraw(ch) {
    const { ctx, chartArea: a, scales: { x, y } } = ch;
    const c = colors();
    ctx.save();
    for (const p of points) {
      if (!p.wicket) continue;
      const px = x.getPixelForValue(p.i), py = y.getPixelForValue(100 * p.p_model);
      ctx.strokeStyle = rgba(c.leather, 0.55);
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(px, a.bottom - 14); ctx.lineTo(px, py); ctx.stroke();
      ctx.fillStyle = c.leather;
      for (const dx of [-4, 0, 4]) ctx.fillRect(px + dx - 1, a.bottom - 11, 2, 10);
      ctx.fillRect(px - 5, a.bottom - 14, 10, 2);
    }
    const last = points[points.length - 1];
    if (last.terminal) {
      ctx.fillStyle = c.turfLine;
      ctx.font = `600 13px ${getComputedStyle(document.body).fontFamily}`;
      ctx.textAlign = "right";
      const ly = y.getPixelForValue(100 * last.p_model);
      ctx.fillText("Decided", x.getPixelForValue(last.i) - 14, ly + (last.p_model > 0.5 ? 22 : -12));
    }
    const p = points[sel];
    if (p) {
      const px = x.getPixelForValue(sel), py = y.getPixelForValue(100 * p.p_model);
      const big = bigOverAt(p.i);
      if (big) {
        ctx.fillStyle = c.chalk;
        ctx.font = `600 13px ${getComputedStyle(document.body).fontFamily}`;
        ctx.textAlign = "center";
        const cx = (x.getPixelForValue(big.i_from - 0.5) + x.getPixelForValue(big.i_to + 0.5)) / 2;
        ctx.fillText(`${big.runs} off the over`, Math.min(Math.max(cx, a.left + 50), a.right - 50), a.top + 30);
      }
      ctx.strokeStyle = rgba(c.chalk, 0.6);
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(px, a.top); ctx.lineTo(px, a.bottom); ctx.stroke();
      ctx.fillStyle = p.p_model >= 0.5 ? kits.chase.lineColor : kits.defend.lineColor;
      ctx.strokeStyle = c.chalk;
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(px, py, 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    }
    ctx.restore();
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

function buildChart() {
  if (!chartAvailable()) return;
  const c = colors();
  const ticks = overTicks();
  const tickLabel = new Map(ticks.map((t) => [t.value, String(t.over)]));
  const line = (key) => points.map((p) => ({ x: p.i, y: 100 * p[key] }));
  const decided = (fallback) => (ctx) => (points[ctx.p1DataIndex]?.terminal ? c.turfLine : fallback);
  Chart.defaults.font = chartFonts();
  Chart.defaults.color = c.dim;
  if (chart) chart.destroy();
  chart = new Chart(ui.canvas, {
    type: "line",
    data: {
      datasets: [
        { label: labels.model, data: line("p_model"), borderColor: c.chalk, borderWidth: 2.5, pointRadius: 0, order: 1,
          segment: { borderColor: decided(c.chalk) } },
        { label: labels.other, data: line("p_other"), borderColor: c.chalk, borderWidth: 1.75, borderDash: [2, 4], pointRadius: 0, order: 2,
          segment: { borderColor: decided(c.chalk) } },
        { label: labels.base, data: line("p_base"), borderColor: c.dim, borderWidth: 1.5, borderDash: [7, 5], pointRadius: 0, order: 3,
          segment: { borderColor: decided(c.dim) } },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { mode: "index", intersect: false },
      events: ["mousemove", "click", "touchstart", "touchmove"],
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: {
        x: {
          type: "linear", min: 0, max: points.length - 1,
          afterBuildTicks: (ax) => { ax.ticks = ticks.map((t) => ({ value: t.value })); },
          ticks: { autoSkip: false, maxRotation: 0, callback: (v) => tickLabel.get(v) ?? "" },
          grid: { display: false },
          title: { display: true, text: "Over" },
        },
        y: {
          min: 0, max: 100,
          ticks: { stepSize: 25, callback: (v) => `${v}%` },
          grid: { color: rgba(c.rope, 0.9) },
          title: { display: true, text: "Chasing team win probability" },
        },
      },
      onHover: (evt) => pick(evt),
      onClick: (evt) => pick(evt),
    },
    plugins: [backdropPlugin, overlayPlugin],
  });
}

function pick(evt) {
  if (!chart || evt.x == null) return;
  const v = chart.scales.x.getValueForPixel(evt.x);
  if (!Number.isFinite(v)) return;
  const k = Math.round(v);
  if (k !== sel && k >= 0 && k < points.length) select(k);
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
    ["Over", "Event", "Score", "Need", "Balls left", "Wickets in hand", "RRR", `Last ${WINDOW} (runs/w)`,
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
