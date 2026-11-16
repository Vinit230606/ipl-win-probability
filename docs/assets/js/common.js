// Shared helpers: JSON loading with a visible error panel, formatters, nav highlighting, team names.
import { linkRepo } from "./repo.js";

export const LOAD_ERROR =
  "Match data didn't load. Refresh the page. If it keeps failing, the data files are missing from this deployment.";
export const CHART_MISSING =
  "The chart library (assets/vendor/chart.umd.min.js) is missing from this deployment, so charts are not drawn. The numbers and tables below still work.";

// Historical names -> current names (same map as src/iplwp/schema.py TEAM_DISPLAY).
export const TEAM_DISPLAY = {
  "Delhi Daredevils": "Delhi Capitals",
  "Kings XI Punjab": "Punjab Kings",
  "Royal Challengers Bangalore": "Royal Challengers Bengaluru",
  "Rising Pune Supergiants": "Rising Pune Supergiant",
};
const TEAM_SHORT = {
  "Chennai Super Kings": "CSK", "Delhi Capitals": "DC", "Gujarat Titans": "GT",
  "Kolkata Knight Riders": "KKR", "Lucknow Super Giants": "LSG", "Mumbai Indians": "MI",
  "Punjab Kings": "PBKS", "Rajasthan Royals": "RR", "Royal Challengers Bengaluru": "RCB",
  "Sunrisers Hyderabad": "SRH",
};
export const teamName = (n) => TEAM_DISPLAY[n] ?? n;
export const teamShort = (n) => TEAM_SHORT[teamName(n)] ?? teamName(n);

export function showError(message = LOAD_ERROR) {
  let el = document.getElementById("load-error");
  if (!el) {
    el = document.createElement("div");
    el.id = "load-error";
    el.className = "error-panel";
    el.setAttribute("role", "alert");
    (document.querySelector("main") ?? document.body).prepend(el);
  }
  el.textContent = message;
  el.hidden = false;
}

export async function loadJSON(path) {
  try {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
    return await res.json();
  } catch (err) {
    showError();
    throw err;
  }
}

export const pct = (p, digits = 0) => (p == null || Number.isNaN(p) ? "–" : `${(100 * p).toFixed(digits)}%`);
export const fix = (v, digits = 3) => (v == null || Number.isNaN(v) ? "–" : Number(v).toFixed(digits));
export const int = (v) => (v == null ? "–" : Number(v).toLocaleString("en-GB"));
export const ciText = (b, ci) => `${fix(b)} [${fix(ci[0])}, ${fix(ci[1])}]`;
export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function fmtDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-GB",
    { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}

export function table(headers, rows, { caption, numeric = [] } = {}) {
  const t = el("table");
  if (caption) t.append(el("caption", { text: caption }));
  const head = el("tr");
  headers.forEach((h, j) => {
    const th = el("th", { scope: "col", class: numeric.includes(j) ? "r" : null });
    if (h) th.textContent = h; else th.append(el("span", { class: "visually-hidden", text: "Link" }));
    head.append(th);
  });
  t.append(el("thead", {}, head));
  const body = el("tbody");
  for (const r of rows) {
    const tr = el("tr");
    r.forEach((c, j) => {
      const td = el("td", { class: numeric.includes(j) ? "r" : null });
      if (c instanceof Node) td.append(c); else td.textContent = c;
      tr.append(td);
    });
    body.append(tr);
  }
  t.append(body);
  // focusable region so keyboard users can scroll wide tables (AccessLint: scrollable-region)
  return el("div", { class: "table-wrap", tabindex: "0", role: "region",
    "aria-label": caption || `Table: ${headers.filter(Boolean).slice(0, 3).join(", ")}` }, t);
}

export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Team colours tuned to read on the dark background: [primary, secondary]. When both sides of a
// match would look alike, the bowling side uses its secondary colour.
const TEAM_COLORS = {
  "Chennai Super Kings": ["#FDB913", "#3B82F6"],
  "Mumbai Indians": ["#1E90FF", "#D1AB3E"],
  "Royal Challengers Bengaluru": ["#EF3340", "#C9A13B"],
  "Kolkata Knight Riders": ["#8B5CF6", "#D4AF37"],
  "Sunrisers Hyderabad": ["#FF7A1A", "#FACC15"],
  "Rajasthan Royals": ["#FF4FA3", "#3B82F6"],
  "Delhi Capitals": ["#3D6BFF", "#EF4444"],
  "Punjab Kings": ["#ED1B24", "#D7D2CB"],
  "Lucknow Super Giants": ["#22B8CF", "#FF8A3D"],
  "Gujarat Titans": ["#D9B65D", "#5B8DEF"],
  "Deccan Chargers": ["#9CA3AF", "#F59E0B"],
  "Gujarat Lions": ["#F97316", "#EF4444"],
  "Kochi Tuskers Kerala": ["#F97316", "#7C3AED"],
  "Pune Warriors": ["#38BDF8", "#E5E7EB"],
  "Rising Pune Supergiant": ["#C084FC", "#F472B6"],
};
const NEUTRAL = "#7DD3FC";

function rgb(hex) {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const dist = (a, b) => Math.hypot(...rgb(a).map((v, i) => v - rgb(b)[i]));

export function teamColors(batting, bowling) {
  const a = TEAM_COLORS[teamName(batting)] ?? [NEUTRAL, NEUTRAL];
  const b = TEAM_COLORS[teamName(bowling)] ?? ["#F472B6", "#F472B6"];
  return { batting: a[0], bowling: dist(a[0], b[0]) < 110 ? b[1] : b[0] };
}

// Colour of the side that is ahead: the fill of the scoreboard tile (DESIGN.md: colour appears as
// full-bleed tiles). Callers may pass a second argument; it is ignored.
export function setTeamTint(color) {
  const c = color ?? NEUTRAL;
  const s = document.documentElement.style;
  s.setProperty("--team", c);
  s.setProperty("--on-team", readableOn(c));
}

// WCAG relative luminance, and the readable text colour (black or white) on a background.
function luminance(hex) {
  return rgb(hex).map((v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; })
    .reduce((s, c, i) => s + c * [0.2126, 0.7152, 0.0722][i], 0);
}
export function readableOn(hex) {
  const L = luminance(hex);
  return (L + 0.05) / 0.05 >= 1.05 / (L + 0.05) ? "#000000" : "#ffffff";
}

export function highlightNav() {
  linkRepo();
  const here = location.pathname.split("/").pop() || "index.html";
  document.querySelectorAll(".site-nav a").forEach((a) => {
    if (a.getAttribute("href") === here) a.setAttribute("aria-current", "page");
  });
}

export const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
export const onThemeChange = (cb) => matchMedia("(prefers-color-scheme: dark)").addEventListener("change", cb);
export const chartAvailable = () => typeof window.Chart === "function";

export function chartFonts() {
  return { family: getComputedStyle(document.body).fontFamily, size: 13 };
}
