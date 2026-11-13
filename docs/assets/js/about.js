// About page: fills the cleaning numbers, splits and method descriptions from data/results.json.
import { el, highlightNav, int, loadJSON, table } from "./common.js";

const REASONS = {
  DUPLICATE: "The same match appears twice",
  NO_RESULT: "No result",
  TIE: "Tie, including matches decided by a super over",
  DLS: "Target revised by the DLS method",
  NO_CHASE: "No second innings recorded",
  REDUCED_OVERS: "Shortened match, or a first innings that stopped early without being bowled out",
  TARGET_MISMATCH: "Rebuilt target disagrees with the recorded one",
  CHASE_INCOMPLETE: "Chase ended early without being bowled out or reaching the target",
  LABEL_MISMATCH: "Recorded winner disagrees with the runs scored",
};

highlightNav();
init();

async function init() {
  let R;
  try {
    R = await loadJSON("data/results.json");
  } catch {
    return;
  }
  const c = R.cleaning;
  const terminal = R.splits.table.reduce((a, r) => a + r.terminal_rows, 0);
  const model = R.splits.table.reduce((a, r) => a + r.model_rows, 0);
  document.getElementById("cleaning-summary").textContent =
    `Of ${int(c.raw_matches)} matches in the data, ${int(c.excluded)} were removed and ` +
    `${int(c.kept)} complete 20-over chases were kept. They give ${int(model)} balls where the ` +
    `result was still open, plus ${int(terminal)} final balls where it was already settled.`;

  const ex = Object.entries(R.exclusions).sort((a, b) => b[1] - a[1]);
  document.getElementById("exclusions").replaceChildren(table(["Reason", "Matches"],
    ex.map(([k, n]) => [REASONS[k] ?? k, int(n)]), { caption: "Matches removed", numeric: [1] }));

  const role = { train: "Training", val: "Validation", test: "Test" };
  document.getElementById("splits").replaceChildren(table(
    ["Split", "Seasons", "Chases", "Balls (open)", "Chase win rate"],
    R.splits.table.map((r) => [role[r.split] ?? r.split, r.seasons, int(r.matches), int(r.model_rows), r.chase_win_rate]),
    { caption: "How the kept chases were split", numeric: [2, 3, 4] }));

  document.getElementById("momentum-item").textContent =
    `runs scored and wickets lost in the last ${R.evaluation.momentum_window} legal balls, ` +
    "including any wides and no-balls bowled among them.";

  const order = ["baseline", "lr_full", "lr_core", "gbm"];
  const dl = el("dl");
  for (const k of order) {
    dl.append(el("dt", { text: R.methods[k].label }), el("dd", { text: R.methods[k].description }));
  }
  document.getElementById("methods").replaceChildren(dl);

  const best = R.methods[R.best_model].label, other = R.methods[R.other_model].label;
  document.getElementById("selection-decision").textContent =
    `${best} was chosen on validation as the replay's main model. On the test seasons it did worse ` +
    `than ${other}. Because changing the choice after seeing test results would break the ` +
    `test-once rule, the replay keeps ${best} as the main line and draws ${other} beside it.`;
}
