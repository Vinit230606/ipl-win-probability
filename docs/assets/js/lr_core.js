// LR-core in JavaScript. Mirrors src/iplwp/features.py core_terms() and the scikit-learn
// Pipeline(StandardScaler, LogisticRegression) exported to data/lr_core.json.
// Used by calculator.js and by docs/tests/parity.test.mjs, so the page and the test share one code path.

export function coreTerms(runsNeeded, ballsLeft, wicketsLeft, rrrClip) {
  const r = runsNeeded, b = ballsLeft, w = wicketsLeft;
  const raw = b > 0 ? (6.0 * r) / b : (r > 0 ? rrrClip : 0.0);
  const rrr = Math.min(Math.max(raw, 0.0), rrrClip);
  return {
    runs_needed: r,
    balls_left: b,
    wickets_left: w,
    rrr,
    log_runs_needed: Math.log1p(Math.max(r, 0)),
    log_balls_left: Math.log1p(Math.max(b, 0)),
    rrr_x_wkts: (rrr * w) / 10.0,
    runs_per_wicket: w > 0 ? r / w : NaN,
  };
}

export function features(model, runsNeeded, ballsLeft, wicketsLeft) {
  const t = coreTerms(runsNeeded, ballsLeft, wicketsLeft, model.rrr_clip);
  return model.feature_order.map((name) => {
    if (!(name in t)) throw new Error(`lr_core.json asks for unknown feature ${name}`);
    return t[name];
  });
}

export function predict(model, runsNeeded, ballsLeft, wicketsLeft) {
  const x = features(model, runsNeeded, ballsLeft, wicketsLeft);
  let z = model.intercept;
  for (let j = 0; j < x.length; j++) {
    z += model.coef[j] * ((x[j] - model.scaler_mean[j]) / model.scaler_scale[j]);
  }
  return 1 / (1 + Math.exp(-z));
}

// Returns {ok, value} or {ok: false, message} for one calculator field.
export function parseField(label, raw, [lo, hi]) {
  const s = String(raw ?? "").trim();
  const message = `${label} must be a whole number from ${lo} to ${hi}.`;
  if (!/^[+-]?\d+$/.test(s)) return { ok: false, message };
  const v = Number(s);
  if (v < lo || v > hi) return { ok: false, message };
  return { ok: true, value: v };
}
