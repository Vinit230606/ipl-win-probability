// Team kits: name lookup (with older names), the clash rule on the known clashes, and contrast.
// Run: node docs/tests/teams.test.mjs   (exit code 1 on any failure)
import { CURRENT, TEAMS, clashes, contrast, lineFor, matchKits, teamFromName } from "../assets/js/teams.js";

let failures = 0;
const ok = (cond, msg) => { if (!cond) { failures++; console.error(`FAIL ${msg}`); } };

// names and aliases
ok(teamFromName("Kings XI Punjab").code === "PBKS", "Kings XI Punjab -> PBKS");
ok(teamFromName("  delhi daredevils ").code === "DC", "Delhi Daredevils -> DC");
ok(teamFromName("Royal Challengers Bangalore").code === "RCB", "RCB old name");
ok(teamFromName("Rising Pune Supergiants").code === "RPS", "RPS alias");
const warn = console.warn; console.warn = () => {};
ok(teamFromName("Some New Side").primary === "#3A4A6E", "unknown -> neutral kit");
console.warn = warn;
ok(CURRENT.length === 10 && CURRENT.every((c) => TEAMS[c]), "ten current teams");

// clash rule: every known clash, either way round, ends up distinguishable
const known = [["MI", "DC"], ["MI", "LSG"], ["DC", "LSG"], ["RCB", "PBKS"], ["CSK", "GT"]];
for (const day of [false, true]) {
  for (const [a, b] of known) {
    for (const [c, d] of [[a, b], [b, a]]) {
      const k = matchKits(TEAMS[c].name, TEAMS[d].name, day);
      ok(clashes(lineFor(TEAMS[c], day), lineFor(TEAMS[d], day)) || day, `${c} v ${d} is a raw clash (night)`);
      ok(!clashes(k.chase.lineColor, k.defend.lineColor) || k.defend.hatch,
        `${c} v ${d} (${day ? "day" : "night"}): resolved (${k.chase.lineColor} vs ${k.defend.lineColor})`);
      ok(k.chase.lineColor === lineFor(TEAMS[c], day), `${c} v ${d}: chasing side keeps its line`);
    }
  }
}

// every pair of current teams is resolved
let pairs = 0;
for (const day of [false, true]) for (const a of CURRENT) for (const b of CURRENT) {
  if (a === b) continue;
  const k = matchKits(TEAMS[a].name, TEAMS[b].name, day);
  pairs++;
  ok(!clashes(k.chase.lineColor, k.defend.lineColor) || k.defend.hatch, `${a} v ${b} unresolved`);
}

// line colours reach 3:1 on the sky in both themes
for (const day of [false, true]) for (const t of Object.values(TEAMS)) {
  const r = contrast(lineFor(t, day), day ? "#F2F5EC" : "#0A1633");
  ok(r >= 3, `${t.code} line ${r.toFixed(2)}:1 on the ${day ? "day" : "night"} sky`);
}
// badge ink on fill: badge codes are set at 19px+ bold (WCAG large text), so 3:1 applies
for (const t of Object.values(TEAMS)) ok(contrast(t.ink, t.primary) >= 3, `${t.code} ink on primary ${contrast(t.ink, t.primary).toFixed(2)}:1`);

console.log(`teams: ${pairs} match-ups checked, ${failures} failure(s)`);
process.exitCode = failures ? 1 : 0;
