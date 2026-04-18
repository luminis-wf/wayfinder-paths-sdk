// Static backtest replay: fixed SL vs trailing SL on synthetic-but-realistic
// price paths seeded per-token. The controller logic mirrors controller.py.

const TOKENS = [
  { id: "BTC", label: "BTC", base: 68000, vol: 0.018 },
  { id: "HYPE", label: "HYPE", base: 32, vol: 0.038 },
  { id: "PROMPT", label: "PROMPT", base: 0.42, vol: 0.05 },
  { id: "xyz:CL-USDC", label: "CL (crude oil, HIP-3)", base: 78.5, vol: 0.012 },
  { id: "xyz:GOLD-USDC", label: "GOLD (HIP-3)", base: 2380, vol: 0.008 },
];

const WINDOWS = {
  "1d": { hours: 24, label: "Last 24 hours" },
  "1w": { hours: 24 * 7, label: "Last week" },
  "1m": { hours: 24 * 30, label: "Last month" },
};

// --- seeded PRNG (mulberry32) ----------------------------------------------
function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashSeed(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}

// Geometric random walk with a slow-drifting drift component and occasional wicks.
function generateSeries(tokenId, windowKey, vol, base) {
  const { hours } = WINDOWS[windowKey];
  const rng = mulberry32(hashSeed(tokenId + ":" + windowKey));
  const hourlyVol = vol / Math.sqrt(24);
  const values = [];
  let price = base * (0.92 + 0.16 * rng());
  let driftPhase = rng() * Math.PI * 2;
  for (let i = 0; i < hours; i++) {
    const shock = (rng() + rng() + rng() - 1.5) * hourlyVol;
    const drift = 0.0004 * Math.sin(driftPhase + (i / hours) * Math.PI * 2);
    const wick = rng() < 0.03 ? (rng() - 0.5) * hourlyVol * 6 : 0;
    price = price * (1 + drift + shock + wick);
    values.push(price);
  }
  return values;
}

// --- controller (mirrors controller.py, trailing_sl only for the applet) ---
function runFixedStop(prices, side, offsetPct) {
  const entry = prices[0];
  const stop = side === "long" ? entry * (1 - offsetPct) : entry * (1 + offsetPct);
  for (let i = 1; i < prices.length; i++) {
    const p = prices[i];
    const hit = side === "long" ? p <= stop : p >= stop;
    if (hit) return { exit: stop, index: i, hit: true };
  }
  return { exit: prices[prices.length - 1], index: prices.length - 1, hit: false };
}

function runTrailingStop(prices, side, offsetPct) {
  const entry = prices[0];
  let peak = entry;
  let trigger = side === "long" ? entry * (1 - offsetPct) : entry * (1 + offsetPct);
  const trail = [trigger];
  for (let i = 1; i < prices.length; i++) {
    const p = prices[i];
    const hit = side === "long" ? p <= trigger : p >= trigger;
    if (hit) {
      while (trail.length < prices.length) trail.push(trigger);
      return { exit: trigger, index: i, hit: true, peak, trail };
    }
    const newPeak = side === "long" ? Math.max(peak, p) : Math.min(peak, p);
    if (newPeak !== peak) {
      peak = newPeak;
      trigger = side === "long" ? peak * (1 - offsetPct) : peak * (1 + offsetPct);
    }
    trail.push(trigger);
  }
  return { exit: prices[prices.length - 1], index: prices.length - 1, hit: false, peak, trail };
}

function pnlPct(side, entry, exit) {
  return side === "long" ? (exit - entry) / entry : (entry - exit) / entry;
}

function fmtPct(x) { return (x * 100).toFixed(2) + "%"; }
function fmtUsd(x) { return "$" + x.toLocaleString(undefined, { maximumFractionDigits: Math.abs(x) < 1 ? 4 : 2 }); }

// --- rendering -------------------------------------------------------------
function drawChart(canvas, prices, fixed, trailing, side) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  const pad = { l: 48, r: 12, t: 12, b: 20 };
  const chartW = w - pad.l - pad.r;
  const chartH = h - pad.t - pad.b;

  const trail = trailing.trail || [];
  const all = prices.concat(trail).concat([fixed.exit]);
  let min = Math.min.apply(null, all), max = Math.max.apply(null, all);
  const padV = (max - min) * 0.08 || max * 0.01;
  min -= padV; max += padV;

  const xAt = (i) => pad.l + (i / (prices.length - 1)) * chartW;
  const yAt = (v) => pad.t + chartH - ((v - min) / (max - min)) * chartH;

  // grid + axis labels
  ctx.strokeStyle = "#30363d"; ctx.lineWidth = 1;
  ctx.fillStyle = "#8b949e"; ctx.font = "11px -apple-system, sans-serif";
  for (let i = 0; i <= 4; i++) {
    const v = min + ((max - min) * i) / 4;
    const y = yAt(v);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.globalAlpha = 0.25; ctx.stroke(); ctx.globalAlpha = 1;
    ctx.fillText(fmtUsd(v), 4, y + 3);
  }

  // price line
  ctx.strokeStyle = "#58a6ff"; ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let i = 0; i < prices.length; i++) {
    const x = xAt(i), y = yAt(prices[i]);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // trailing trigger line
  if (trail.length) {
    ctx.strokeStyle = "#3fb950"; ctx.lineWidth = 1.2; ctx.setLineDash([4, 3]);
    ctx.beginPath();
    for (let i = 0; i < trail.length && i < prices.length; i++) {
      const x = xAt(i), y = yAt(trail[i]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke(); ctx.setLineDash([]);
  }

  // fixed stop horizontal line
  ctx.strokeStyle = "#f85149"; ctx.lineWidth = 1.2; ctx.setLineDash([2, 4]);
  ctx.beginPath();
  const fy = yAt(side === "long" ? prices[0] * (1 - (prices[0] - fixed.exit) / prices[0]) : fixed.exit);
  ctx.moveTo(pad.l, yAt(fixed.exit)); ctx.lineTo(w - pad.r, yAt(fixed.exit));
  ctx.stroke(); ctx.setLineDash([]);

  // exit markers
  function marker(decision, color) {
    ctx.fillStyle = color;
    const x = xAt(decision.index), y = yAt(decision.exit);
    ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
  }
  marker(fixed, "#f85149");
  marker(trailing, "#3fb950");
}

function computeAndRender() {
  const tokenId = document.getElementById("coin").value;
  const windowKey = document.getElementById("window").value;
  const side = document.getElementById("side").value;
  const offsetPct = parseFloat(document.getElementById("offset").value) / 100;

  const token = TOKENS.find(t => t.id === tokenId);
  const prices = generateSeries(token.id, windowKey, token.vol, token.base);

  const fixed = runFixedStop(prices, side, offsetPct);
  const trailing = runTrailingStop(prices, side, offsetPct);
  drawChart(document.getElementById("chart"), prices, fixed, trailing, side);

  const entry = prices[0];
  const fixedPnl = pnlPct(side, entry, fixed.exit);
  const trailPnl = pnlPct(side, entry, trailing.exit);
  const delta = trailPnl - fixedPnl;
  const peak = trailing.peak || (side === "long" ? Math.max.apply(null, prices) : Math.min.apply(null, prices));

  const fEl = document.getElementById("fixed-pnl");
  const tEl = document.getElementById("trail-pnl");
  const dEl = document.getElementById("delta");
  fEl.textContent = fmtPct(fixedPnl);
  tEl.textContent = fmtPct(trailPnl);
  dEl.textContent = (delta >= 0 ? "+" : "") + fmtPct(delta);
  fEl.className = "val " + (fixedPnl >= 0 ? "pos" : "neg");
  tEl.className = "val " + (trailPnl >= 0 ? "pos" : "neg");
  dEl.className = "val " + (delta >= 0 ? "pos" : "neg");
  document.getElementById("peak").textContent = fmtUsd(peak);

  const comm = document.getElementById("commentary");
  const notional = 10000;
  const dollars = delta * notional;
  if (Math.abs(delta) < 0.001) {
    comm.textContent = "On a $10,000 trade the two stops would have left you in roughly the same place this window.";
  } else if (delta > 0) {
    comm.textContent = "On a $10,000 trade the trailing stop would have kept " + fmtUsd(dollars) + " more than the fixed stop.";
  } else {
    comm.textContent = "On a $10,000 trade the trailing stop would have left " + fmtUsd(-dollars) + " on the table versus the fixed stop (this happens when a wick takes out the trail before the real move develops).";
  }
}

// --- wiring ----------------------------------------------------------------
function init() {
  const coinSel = document.getElementById("coin");
  for (const t of TOKENS) {
    const opt = document.createElement("option");
    opt.value = t.id; opt.textContent = t.label; coinSel.appendChild(opt);
  }
  const offset = document.getElementById("offset");
  const offsetVal = document.getElementById("offset-val");
  offset.addEventListener("input", () => {
    offsetVal.textContent = parseFloat(offset.value).toFixed(1) + "%";
    computeAndRender();
  });
  document.getElementById("coin").addEventListener("change", computeAndRender);
  document.getElementById("window").addEventListener("change", computeAndRender);
  document.getElementById("side").addEventListener("change", computeAndRender);
  window.addEventListener("resize", computeAndRender);

  // Wayfinder host bridge (capture parent origin for any future postMessage reply).
  let parentOrigin = null;
  window.addEventListener("message", (e) => {
    const d = e.data;
    if (!d || typeof d !== "object") return;
    if (d.type === "wf:hello") {
      parentOrigin = e.origin;
      window.parent.postMessage({ type: "wf:hello_ack" }, parentOrigin);
    }
  });

  computeAndRender();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
