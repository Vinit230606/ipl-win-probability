// Shared helpers: JSON loading with a visible error panel, formatters, nav highlighting, team names.
import { linkRepo } from "./repo.js";
import { teamFromName } from "./teams.js";

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
export const teamName = (n) => TEAM_DISPLAY[n] ?? n;
export const teamShort = (n) => teamFromName(n).code || teamName(n);

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

// rowLines (optional): one colour (or null) per row; a coloured 3px left border marks rows about a
// specific match, in that chasing team's line colour.
export function table(headers, rows, { caption, numeric = [], rowLines = [] } = {}) {
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
  for (const [i, r] of rows.entries()) {
    const tr = el("tr", rowLines[i] ? { class: "match-row-tag", style: `--row-line:${rowLines[i]}` } : {});
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

// Colour of the side the main model favours: drives the 4px bar under the score strip (and the
// strips on the calculator and edge-cases pages). Team colours themselves live in teams.js.
// Callers may pass a second argument; it is ignored.
export function setTeamTint(color) {
  if (color) document.documentElement.style.setProperty("--lead", color);
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
