// JS models must equal the Python predictions on every exported test vector.
// 1. LR-core (data/lr_core.json); 2. the calculator: ball-by-ball simulation (raw and
// calibrated) and the final blended, monotone table (data/calculator.json).
// Run: node docs/tests/parity.test.mjs   (exit code 1 on any failure)
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { predict, parseField } from "../assets/js/lr_core.js";
import { buildCalculator } from "../assets/js/simulation.js";

const here = dirname(fileURLToPath(import.meta.url));
const load = (f) => JSON.parse(readFileSync(join(here, "..", "data", f), "utf8"));
const model = load("lr_core.json");
const simModel = load("calculator.json");
const TOL = 1e-9;
let failures = 0;

function check(name, vectors, fn, key) {
  let worst = 0;
  for (const v of vectors) {
    const p = fn(v.runs_needed, v.balls_left, v.wickets_left);
    const d = Math.abs(p - v[key]);
    worst = Math.max(worst, d);
    if (!(d <= TOL)) { failures++; if (failures < 10) console.error(`FAIL ${name} ${JSON.stringify(v)} js=${p} diff=${d}`); }
  }
  if (vectors.length < 200) { failures++; console.error(`${name}: only ${vectors.length} vectors`); }
  console.log(`${name}: ${vectors.length} vectors, max |JS - Python| = ${worst.toExponential(2)}`);
}

check("LR-core", model.test_vectors, (r, b, w) => predict(model, r, b, w), "p");
const t0 = performance.now();
const calc = buildCalculator(model, simModel);
console.log(`calculator table built in ${(performance.now() - t0).toFixed(0)} ms`);
check("simulation (raw)", simModel.parity_vectors, calc.raw, "raw");
check("simulation (calibrated)", simModel.parity_vectors, calc.sim, "sim");
check("calculator (final)", simModel.parity_vectors, calc.p, "p");

// cricket logic on the final table: more runs needed / fewer balls / fewer wickets never raise p
let mono = 0;
for (let r = 1; r < calc.maxRuns; r++) for (let b = 1; b <= calc.balls; b++) for (let w = 1; w <= calc.wickets; w++) {
  const p = calc.p(r, b, w);
  if (calc.p(r + 1, b, w) > p + 1e-12) mono++;
  if (b > 1 && calc.p(r, b - 1, w) > p + 1e-12) mono++;
  if (w > 1 && calc.p(r, b, w - 1) > p + 1e-12) mono++;
}
if (mono) { failures++; console.error(`monotonicity violations: ${mono}`); }
console.log(`monotonicity violations in the JS table: ${mono}`);

const rb = model.input_ranges.balls_left;
const checks = [
  [parseField("Balls left", "25", rb).ok, true],
  [parseField("Balls left", "0", rb).ok, false],
  [parseField("Balls left", "121", rb).ok, false],
  [parseField("Balls left", "4.5", rb).ok, false],
  [parseField("Balls left", "", rb).ok, false],
  [parseField("Balls left", "x", rb).message, "Balls left must be a whole number from 1 to 120."],
];
checks.forEach(([got, want], k) => {
  if (got !== want) { failures++; console.error(`input check ${k}: got ${got}, want ${want}`); }
});

console.log(`parity: ${failures} failure(s)`);
process.exitCode = failures ? 1 : 0;
