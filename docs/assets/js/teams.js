// Team kits ("Under the lights" theme, section 3). The only place team colours are defined.
// Hex values approximate each franchise's kit colours; no logos or official marks are used.
// Each kit: code, name, aliases (older names in Cricsheet data), primary, secondary, line (the
// team colour readable on the night sky), alt (used when it clashes with the opponent), ink
// (text colour on a primary badge).

const K = (code, name, aliases, primary, secondary, line, alt, ink) =>
  ({ code, name, aliases, primary, secondary, line, alt, ink });

export const TEAMS = {
  CSK: K("CSK", "Chennai Super Kings", [], "#FDB913", "#0A4595", "#FDB913", "#5B8CE0", "#0A1633"),
  MI: K("MI", "Mumbai Indians", [], "#004BA0", "#D1AB3E", "#4C9BE8", "#D1AB3E", "#FFFFFF"),
  RCB: K("RCB", "Royal Challengers Bengaluru", ["Royal Challengers Bangalore"], "#EC1C24", "#1A1A1A", "#F0444B", "#C9A64B", "#FFFFFF"),
  KKR: K("KKR", "Kolkata Knight Riders", [], "#3A225D", "#B3A123", "#A98BE0", "#D4BF3A", "#FFFFFF"),
  SRH: K("SRH", "Sunrisers Hyderabad", [], "#F26522", "#000000", "#FF822A", "#FFC24D", "#0A1633"),
  RR: K("RR", "Rajasthan Royals", [], "#EA1A85", "#254AA5", "#F04BA0", "#6C8FE6", "#FFFFFF"),
  DC: K("DC", "Delhi Capitals", ["Delhi Daredevils"], "#17449B", "#EF1B23", "#5C8FE6", "#EF4B52", "#FFFFFF"),
  PBKS: K("PBKS", "Punjab Kings", ["Kings XI Punjab"], "#DD1F2D", "#A7A9AC", "#F0505C", "#C7C9CC", "#FFFFFF"),
  GT: K("GT", "Gujarat Titans", [], "#1B2133", "#DBBE6E", "#DBBE6E", "#8FA3C8", "#DBBE6E"),
  LSG: K("LSG", "Lucknow Super Giants", [], "#0057E2", "#F28B00", "#3FB6F0", "#F28B00", "#FFFFFF"),
  // defunct teams (only if they appear in the data)
  DCH: K("DCH", "Deccan Chargers", [], "#1D3B6E", "#1D3B6E", "#8FB0E0", "#8FB0E0", "#FFFFFF"),
  KTK: K("KTK", "Kochi Tuskers Kerala", [], "#5B2C83", "#5B2C83", "#B08AD8", "#B08AD8", "#FFFFFF"),
  PWI: K("PWI", "Pune Warriors", ["Pune Warriors India"], "#2F9BE3", "#2F9BE3", "#2F9BE3", "#2F9BE3", "#0A1633"),
  RPS: K("RPS", "Rising Pune Supergiant", ["Rising Pune Supergiants"], "#6F2DA8", "#6F2DA8", "#B58AE6", "#B58AE6", "#FFFFFF"),
  GL: K("GL", "Gujarat Lions", [], "#E04F16", "#E04F16", "#FF7A45", "#FF7A45", "#FFFFFF"),
};

// Current franchises, in the order of the kit table (used for the team filter).
export const CURRENT = ["CSK", "MI", "RCB", "KKR", "SRH", "RR", "DC", "PBKS", "GT", "LSG"];

const NEUTRAL = K("", "", [], "#3A4A6E", "#3A4A6E", "#C9D3E8", "#C9D3E8", "#FFFFFF");

const BY_NAME = new Map();
for (const t of Object.values(TEAMS)) {
  for (const n of [t.name, ...t.aliases, t.code]) BY_NAME.set(n.trim().toLowerCase(), t);
}
const warned = new Set();

/** Kit for a full team name, an older alias or a code; a neutral kit (and one warning) otherwise. */
export function teamFromName(name) {
  const key = String(name ?? "").trim().toLowerCase();
  const t = BY_NAME.get(key);
  if (t) return t;
  if (key && !warned.has(key) && typeof console !== "undefined") {
    warned.add(key);
    console.warn(`teams.js: no kit for team "${name}"; using the neutral kit. Add it to TEAMS.`);
  }
  return { ...NEUTRAL, code: String(name ?? "?").split(/\s+/).map((w) => w[0]).join("").toUpperCase(), name: String(name ?? "") };
}

// ---------------------------------------------------------------- colour maths
function srgb(hex) {
  const n = Number.parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => v / 255);
}
const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);

export function luminance(hex) {
  const [r, g, b] = srgb(hex).map(lin);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a, b) {
  const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}

/** OKLCH (Björn Ottosson's OKLab, https://bottosson.github.io/posts/oklab/) as [L, C, h°]. */
export function oklch(hex) {
  const [r, g, b] = srgb(hex).map(lin);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  const h = (Math.atan2(B, A) * 180) / Math.PI;
  return [L, Math.hypot(A, B), (h + 360) % 360];
}

/** Clash test from the theme: hue difference < 35° and lightness difference < 0.15.
 *  Near-grey colours (chroma < 0.04) have no reliable hue, so grey only clashes with grey. */
export function clashes(a, b) {
  const [L1, C1, h1] = oklch(a), [L2, C2, h2] = oklch(b);
  const grey1 = C1 < 0.04, grey2 = C2 < 0.04;
  let dh = Math.abs(h1 - h2);
  dh = Math.min(dh, 360 - dh);
  if (grey1 !== grey2) dh = 180;
  if (grey1 && grey2) dh = 0;
  return dh < 35 && Math.abs(L1 - L2) < 0.15;
}

const SKY = { night: "#0A1633", day: "#F2F5EC" };
const CHALK = { night: "#EEF2FA", day: "#0E1A33" };

export const isDay = () =>
  typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: light)").matches;

/** The team colour to draw lines and fills with: `line` at night; in the day theme the first of
 *  line, primary, secondary, alt that reaches 3:1 on the day sky. */
export function lineFor(team, day = isDay()) {
  if (!day) return team.line;
  for (const c of [team.line, team.primary, team.secondary, team.alt]) if (contrast(c, SKY.day) >= 3) return c;
  return CHALK.day;
}
function altFor(team, day) {
  if (!day || contrast(team.alt, SKY.day) >= 3) return team.alt;
  return lineFor({ ...team, line: team.alt }, true);
}

/** Kits for one chase with the clash rule applied. The chasing side always keeps its line. */
export function matchKits(chasingName, defendingName, day = isDay()) {
  const ct = teamFromName(chasingName), dt = teamFromName(defendingName);
  const chase = { ...ct, fill: ct.primary, lineColor: lineFor(ct, day), hatch: false };
  const defend = { ...dt, fill: dt.primary, lineColor: lineFor(dt, day), hatch: false, usedAlt: false };
  if (clashes(chase.lineColor, defend.lineColor)) {
    defend.lineColor = altFor(dt, day);
    defend.usedAlt = true;
    if (clashes(chase.lineColor, defend.lineColor)) {
      defend.lineColor = day ? CHALK.day : CHALK.night;
      defend.hatch = true;
    }
  }
  return { chase, defend };
}

/** Put a chase's kits on <body>: data-chase / data-defend and the six team variables. */
export function applyKits(kits, el = document.body) {
  const { chase, defend } = kits;
  el.dataset.chase = chase.code;
  el.dataset.defend = defend.code;
  el.classList.toggle("defend-hatch", defend.hatch);
  const s = el.style;
  s.setProperty("--chase", chase.fill);
  s.setProperty("--chase-line", chase.lineColor);
  s.setProperty("--chase-ink", chase.ink);
  s.setProperty("--defend", defend.fill);
  s.setProperty("--defend-line", defend.lineColor);
  s.setProperty("--defend-ink", defend.ink);
}

/** Inline style for a badge of one team (fill, ink, and a line-coloured border for contrast). */
export function badgeStyle(team, day = isDay()) {
  return `--b-fill:${team.primary};--b-ink:${team.ink};--b-line:${lineFor(team, day)}`;
}
