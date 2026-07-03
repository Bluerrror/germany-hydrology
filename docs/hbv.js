// HBV-96 rainfall-runoff model + DDS calibration, JS port of
// germany_hydrology.hbv. Forcing daily, mm/day and degC; Q in mm/day.

export const PARAM_BOUNDS = {
  TT:[-2.5,2.5], CFMAX:[0.5,10], SFCF:[0.4,1.4], CFR:[0,0.1], CWH:[0,0.2],
  FC:[50,700], LP:[0.2,1], BETA:[1,6], K0:[0.05,0.9], K1:[0.01,0.5],
  K2:[0.001,0.2], UZL:[0,100], PERC:[0,6], MAXBAS:[1,7],
};
export const PARAM_NAMES = Object.keys(PARAM_BOUNDS);
const FIXED = { CFR: 0.05, CWH: 0.1 };

function maxbasWeights(mb) {
  const n = Math.ceil(mb), half = mb / 2;
  const cdf = t => {
    t = Math.max(0, Math.min(mb, t));
    return t <= half ? 2 * t * t / (mb * mb)
                     : 1 - 2 * (mb - t) * (mb - t) / (mb * mb);
  };
  const w = [];
  for (let i = 0; i < n; i++) w.push(cdf(i + 1) - cdf(i));
  const s = w.reduce((a, b) => a + b, 0);
  return w.map(x => x / s);
}

// P,T,E: Float arrays (mm, degC, mm). params: object. -> Float64Array Q (mm/day)
export function simulate(P, T, E, p) {
  const nt = P.length;
  let snow = 0, liquid = 0, sm = p.FC * 0.5, suz = 0, slz = 0;
  const q = new Float64Array(nt);
  for (let t = 0; t < nt; t++) {
    const pr = P[t], tt = T[t], et = E[t];
    const rain = tt >= p.TT ? pr : 0;
    const snowfall = (tt < p.TT ? pr : 0) * p.SFCF;
    snow += snowfall;
    const melt = Math.min(p.CFMAX * Math.max(tt - p.TT, 0), snow);
    snow -= melt; liquid += melt;
    const refreeze = Math.min(p.CFR * p.CFMAX * Math.max(p.TT - tt, 0), liquid);
    snow += refreeze; liquid -= refreeze;
    const outflow = Math.max(liquid - p.CWH * snow, 0);
    liquid -= outflow;
    const waterIn = rain + outflow;
    let recharge = waterIn * Math.pow(sm / p.FC, p.BETA);
    sm += waterIn - recharge;
    const excess = Math.max(sm - p.FC, 0);
    sm -= excess; recharge += excess;
    let aet = et * Math.max(0, Math.min(sm / (p.LP * p.FC), 1));
    aet = Math.min(aet, sm); sm -= aet;
    suz += recharge;
    const perc = Math.min(p.PERC, suz);
    suz -= perc; slz += perc;
    const q0 = p.K0 * Math.max(suz - p.UZL, 0);
    const q1 = p.K1 * suz;
    const q2 = p.K2 * slz;
    suz -= q0 + q1; slz -= q2;
    q[t] = q0 + q1 + q2;
  }
  // triangular routing
  const w = maxbasWeights(p.MAXBAS), out = new Float64Array(nt);
  for (let i = 0; i < nt; i++) {
    let acc = 0;
    for (let k = 0; k < w.length && i - k >= 0; k++) acc += w[k] * q[i - k];
    out[i] = acc;
  }
  return out;
}

// ---- metrics (pairwise over a mask of valid indices) --------------------
function pairStats(obs, sim, idx) {
  let n = 0, so = 0, ss = 0;
  for (const i of idx) { so += obs[i]; ss += sim[i]; n++; }
  const mo = so / n, ms = ss / n;
  let num = 0, den = 0, cov = 0, vo = 0, vs = 0;
  for (const i of idx) {
    num += (obs[i] - sim[i]) ** 2;
    den += (obs[i] - mo) ** 2;
    cov += (obs[i] - mo) * (sim[i] - ms);
    vo += (obs[i] - mo) ** 2; vs += (sim[i] - ms) ** 2;
  }
  const nse = 1 - num / den;
  const r = cov / Math.sqrt(vo * vs);
  const alpha = Math.sqrt(vs / n) / Math.sqrt(vo / n);
  const beta = ms / mo;
  const kge = 1 - Math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2);
  return { nse, kge, n };
}

export function metrics(obs, sim, idx) { return pairStats(obs, sim, idx); }

function objective(kind, obs, sim, idx) {
  if (kind === 'kge') return pairStats(obs, sim, idx).kge;
  if (kind === 'nse') return pairStats(obs, sim, idx).nse;
  if (kind === 'rmse') {
    let s = 0, n = 0; for (const i of idx) { s += (obs[i] - sim[i]) ** 2; n++; }
    return -Math.sqrt(s / n);
  }
  if (kind === 'lognse') {
    const lo = obs.map(v => Math.log(v + 0.01)), ls = sim.map(v => Math.log(v + 0.01));
    return pairStats(lo, ls, idx).nse;
  }
  return pairStats(obs, sim, idx).nse;
}

// ---- DDS calibration ----------------------------------------------------
// P,T,E,Q: arrays. trainIdx: indices used for the objective (>= warmup,
// finite Q). onProgress(bestScore, iter) optional.
export function calibrate(P, T, E, Q, {
  objectiveKind = 'nse', trials = 500, trainIdx, r = 0.2, seed = 42,
  onProgress = null,
} = {}) {
  let s = seed >>> 0;
  const rnd = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
  const gauss = () => {
    let u = 0, v = 0; while (!u) u = rnd(); while (!v) v = rnd();
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  };
  const D = PARAM_NAMES.filter(n => !(n in FIXED));
  const lo = {}, hi = {};
  for (const n of PARAM_NAMES) { [lo[n], hi[n]] = PARAM_BOUNDS[n]; }

  const clip = (n, v) => Math.max(lo[n], Math.min(hi[n], v));
  const reflect = (n, v) => {           // reflecting boundary keeps DDS moves valid
    const a = lo[n], b = hi[n];
    if (v < a) v = a + (a - v);
    if (v > b) v = b - (v - b);
    return clip(n, v);
  };
  const ordered = p => p.K0 > p.K1 && p.K1 > p.K2;

  const mk = () => {
    const p = { ...FIXED };
    for (const n of D) p[n] = lo[n] + (hi[n] - lo[n]) * rnd();
    return p;
  };
  const score = p => ordered(p) ? objective(objectiveKind, Q, simulate(P, T, E, p), trainIdx) : -1e9;

  // start from the mid-point (a sane HBV guess), else a random valid draw
  let best = { ...FIXED };
  for (const n of D) best[n] = 0.5 * (lo[n] + hi[n]);
  if (!ordered(best)) { do { best = mk(); } while (!ordered(best)); }
  let bestScore = score(best);

  for (let it = 1; it < trials; it++) {
    const cand = { ...best };
    const prob = 1 - Math.log(it) / Math.log(trials);   // DDS dim-selection prob
    let picked = false;
    for (const n of D) {
      if (rnd() < prob) {
        picked = true;
        cand[n] = reflect(n, best[n] + r * (hi[n] - lo[n]) * gauss());
      }
    }
    if (!picked) {                                       // always perturb >=1 dim
      const n = D[Math.floor(rnd() * D.length)];
      cand[n] = reflect(n, best[n] + r * (hi[n] - lo[n]) * gauss());
    }
    const sc = score(cand);
    if (sc > bestScore) { best = cand; bestScore = sc; }
    if (onProgress && it % 25 === 0) onProgress(bestScore, it);
  }
  return { params: best, score: bestScore, simulation: simulate(P, T, E, best) };
}
