// Calculator model in the browser: LR-core blended with the ball-by-ball simulation, then a
// monotone envelope. Mirrors src/iplwp/simulate.py and src/iplwp/edge_cases.py step for step,
// in the same summation order, so docs/tests/parity.test.mjs can compare it with Python.
import { predict as lrPredict } from "./lr_core.js";

const EPS = 1e-6;

export function buildCalculator(lr, sim) {
  const B = sim.balls, W = sim.wickets, R = sim.max_runs;
  const bands = sim.rrr_bands, groups = sim.wicket_groups, nb = bands.length + 1, ng = groups.length;
  const P = sim.outcome_probs;
  const legal = [], extra = [];
  sim.classes.forEach(([kind, k, wk], j) => (kind === "L" ? legal : extra).push([j, k, wk]));

  const groupOf = (w) => {
    for (let i = 0; i < ng; i++) if (w >= groups[i][0] && w <= groups[i][1]) return i;
    return ng - 1;
  };
  const ctxOf = (r, b, w) => {
    const over = Math.floor((B - b) / 6);
    const phase = over <= 5 ? 0 : over <= 14 ? 1 : 2;
    const x = (6.0 * r) / Math.max(b, 1.0);
    let band = 0;
    for (const e of bands) if (e <= x) band++;
    return (phase * ng + groupOf(w)) * nb + band;
  };

  // 1. solve the chase: V[b][w][r]
  const S = R + 1;
  const vi = (b, w, r) => (b * (W + 1) + w) * S + r;
  const V = new Float64Array((B + 1) * (W + 1) * S);
  for (let b = 0; b <= B; b++) for (let w = 0; w <= W; w++) V[vi(b, w, 0)] = 1.0;
  for (let b = 1; b <= B; b++) {
    for (let w = 1; w <= W; w++) {
      for (let r = 1; r <= R; r++) {
        const pr = P[ctxOf(r, b, w)];
        let s = 0;
        for (const [j, k, wk] of legal) {
          const nr = r - k;
          s = s + pr[j] * (nr <= 0 ? 1.0 : V[vi(b - 1, w - wk, nr)]);
        }
        for (const [j, k, wk] of extra) {
          const nr = r - k;
          s = s + pr[j] * (nr <= 0 ? 1.0 : wk === 0 ? V[vi(b, w, nr)] : V[vi(b, w - 1, nr)]);
        }
        V[vi(b, w, r)] = s;
      }
    }
  }
  const raw = (r, b, w) => V[vi(b, w, Math.min(Math.max(r, 0), R))];
  const [pa, pc] = sim.platt;
  const simP = (r, b, w) => {
    const p = Math.min(Math.max(raw(r, b, w), EPS), 1 - EPS);
    return 1.0 / (1.0 + Math.exp(-(pa * Math.log(p / (1 - p)) + pc)));
  };

  // 2. data support and blend weight
  const [sr, sb] = sim.support_bucket;
  const support = (r, b, w) => sim.support[w][Math.floor(Math.min(r, R) / sr)][Math.floor((b - 1) / sb)];
  const weight = (r, b, w) => { const n = support(r, b, w); return n / (n + sim.blend_k); };

  // 3. blended table H, then the monotone envelope G = (U + L) / 2
  const ti = (r, b, w) => (r * (B + 1) + b) * (W + 1) + w;
  const N = (R + 1) * (B + 1) * (W + 1);
  const H = new Float64Array(N);
  for (let b = 0; b <= B; b++) for (let w = 0; w <= W; w++) H[ti(0, b, w)] = 1.0;
  for (let r = 1; r <= R; r++) for (let b = 1; b <= B; b++) for (let w = 1; w <= W; w++) {
    const a = weight(r, b, w);
    H[ti(r, b, w)] = a * lrPredict(lr, r, b, w) + (1 - a) * simP(r, b, w);
  }
  const ui = (r, b, w) => (r * (B + 1) + b) * (W + 1) + w;              // U: r 0..R+1
  const U = new Float64Array((R + 2) * (B + 1) * (W + 1));
  for (let r = R; r >= 1; r--) for (let b = 1; b <= B; b++) for (let w = 1; w <= W; w++) {
    let v = H[ti(r, b, w)];
    const n1 = U[ui(r + 1, b, w)], n2 = U[ui(r, b - 1, w)], n3 = U[ui(r, b, w - 1)];
    if (n1 > v) v = n1;
    if (n2 > v) v = n2;
    if (n3 > v) v = n3;
    U[ui(r, b, w)] = v;
  }
  const li = (r, b, w) => (r * (B + 2) + b) * (W + 2) + w;              // L: b 0..B+1, w 0..W+1
  const L = new Float64Array((R + 1) * (B + 2) * (W + 2)).fill(1.0);
  for (let r = 1; r <= R; r++) for (let b = B; b >= 1; b--) for (let w = W; w >= 1; w--) {
    let v = H[ti(r, b, w)];
    const n1 = L[li(r - 1, b, w)], n2 = L[li(r, b + 1, w)], n3 = L[li(r, b, w + 1)];
    if (n1 < v) v = n1;
    if (n2 < v) v = n2;
    if (n3 < v) v = n3;
    L[li(r, b, w)] = v;
  }
  const G = new Float64Array(N);
  for (let b = 0; b <= B; b++) for (let w = 0; w <= W; w++) G[ti(0, b, w)] = 1.0;
  for (let r = 1; r <= R; r++) for (let b = 1; b <= B; b++) for (let w = 1; w <= W; w++) {
    G[ti(r, b, w)] = 0.5 * (U[ui(r, b, w)] + L[li(r, b, w)]);
  }

  return {
    maxRuns: R, balls: B, wickets: W, floor: sim.display_floor,
    p: (r, b, w) => G[ti(Math.min(Math.max(r, 0), R), b, w)],
    lr: (r, b, w) => lrPredict(lr, r, b, w),
    sim: simP, raw, support, weight,
  };
}
