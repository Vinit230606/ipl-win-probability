// JS LR-core must equal the Python (scikit-learn) predictions on every exported test vector.
// Run: node docs/tests/parity.test.mjs   (exit code 1 on any failure)
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { predict, parseField } from "../assets/js/lr_core.js";

const here = dirname(fileURLToPath(import.meta.url));
const model = JSON.parse(readFileSync(join(here, "..", "data", "lr_core.json"), "utf8"));
const TOL = 1e-9;
let worst = 0;
let failures = 0;

for (const v of model.test_vectors) {
  const p = predict(model, v.runs_needed, v.balls_left, v.wickets_left);
  const d = Math.abs(p - v.p);
  worst = Math.max(worst, d);
  if (!(d <= TOL)) {
    failures++;
    console.error(`FAIL ${JSON.stringify(v)} js=${p} diff=${d}`);
  }
}
if (model.test_vectors.length < 200) {
  failures++;
  console.error(`only ${model.test_vectors.length} test vectors (need >= 200)`);
}

const r = model.input_ranges.balls_left;
const checks = [
  [parseField("Balls left", "25", r).ok, true],
  [parseField("Balls left", "0", r).ok, false],
  [parseField("Balls left", "121", r).ok, false],
  [parseField("Balls left", "4.5", r).ok, false],
  [parseField("Balls left", "", r).ok, false],
  [parseField("Balls left", "x", r).message, "Balls left must be a whole number from 1 to 120."],
];
checks.forEach(([got, want], k) => {
  if (got !== want) { failures++; console.error(`input check ${k}: got ${got}, want ${want}`); }
});

console.log(`parity: ${model.test_vectors.length} vectors, max |JS - Python| = ${worst.toExponential(2)}, ` +
  `${failures} failure(s)`);
process.exitCode = failures ? 1 : 0;
