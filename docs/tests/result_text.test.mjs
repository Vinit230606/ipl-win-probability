// The replay rebuilds each result sentence from the last ball ("RR won by 6 wickets with 4 balls
// left", "CSK defended 180, won by 12 runs"). Check its margins agree with the exported
// result_text for every chase, so the restyle changes no number.
// Run: node docs/tests/result_text.test.mjs
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const data = join(dirname(fileURLToPath(import.meta.url)), "..", "data");
const index = JSON.parse(readFileSync(join(data, "matches.json"), "utf8"));
let bad = 0;
for (const m of index.matches) {
  const doc = JSON.parse(readFileSync(join(data, "matches", `${m.match_id}.json`), "utf8"));
  const last = doc.balls[doc.balls.length - 1];
  const n = Number((m.result_text.match(/won by (\d+)/) ?? [])[1]);
  const margin = m.chase_won ? last.wickets_left : m.target - 1 - Number.parseInt(last.score, 10);
  const unit = m.chase_won ? "wicket" : "run";
  if (!(n === margin && m.result_text.includes(unit))) { bad++; console.error(`FAIL ${m.match_id}: "${m.result_text}" vs ${margin} ${unit}s`); }
}
console.log(`result text: ${index.matches.length} chases checked, ${bad} mismatch(es)`);
process.exitCode = bad ? 1 : 0;
