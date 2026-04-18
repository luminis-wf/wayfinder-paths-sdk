// Dynamic backtest replay: fetches real price data from Delta Lab's public
// timeseries endpoint and runs a fixed-vs-trailing stop comparison.
// Falls back to a deterministic synthetic series when the API is unreachable
// (e.g. localhost dev, where the public endpoint is cross-origin).

const TOKENS = [
  { id: "BTC", label: "BTC" },
  { id: "ETH", label: "ETH" },
  { id: "SOL", label: "SOL" },
  { id: "HYPE", label: "HYPE" },
];

const WINDOWS = {
  "1d": { days: 1, label: "Last 24 hours" },
  "1w": { days: 7, label: "Last week" },
  "1m": { days: 30, label: "Last month" },
};

const FETCH_TIMEOUT_MS = 8000;
const DEMO_FALLBACK_VOLS = { BTC: 0.018, ETH: 0.025, SOL: 0.04, HYPE: 0.038 };
const DEMO_FALLBACK_BASES = { BTC: 68000, ETH: 3500, SOL: 160, HYPE: 32 };

let apiBase = null;        // populated from wf:state.apiBase or wf:hello origin
let apiBaseReady = false;  // false until the host bridge speaks to us
let activeRequestToken = 0;

// --- controller (matches controller.py, trailing_sl only for the applet) ---
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

// --- data loading ----------------------------------------------------------
function extractPriceRecords(payload) {
  // Delta Lab returns { price: [{ts, price_usd}, ...], symbol, asset_id, ... }.
  // Some backends may return { data: { price: [...] } }. Tolerate both.
  const container = payload && typeof payload === "object"
    ? (payload.price ? payload : (payload.data || {}))
    : {};
  const records = Array.isArray(container.price) ? container.price : [];
  return records
    .map((r) => ({
      ts: new Date(r.ts || r.time || r.timestamp || 0).getTime(),
      price: Number(r.price_usd ?? r.price ?? r.value ?? NaN),
    }))
    .filter((r) => Number.isFinite(r.price) && Number.isFinite(r.ts))
    .sort((a, b) => a.ts - b.ts);
}

async function fetchWithTimeout(url, ms) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    const res = await fetch(url, { signal: ctrl.signal });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function loadLiveSeries(symbol, windowKey) {
  if (!apiBase) return null;
  const days = WINDOWS[windowKey].days;
  const url = apiBase.replace(/\/$/, "") +
    "/api/v1/delta-lab/public/assets/" + encodeURIComponent(symbol) +
    "/timeseries/?series=price&lookback_days=" + days + "&limit=2000";
  try {
    const payload = await fetchWithTimeout(url, FETCH_TIMEOUT_MS);
    const records = extractPriceRecords(payload);
    if (records.length < 2) return null;
    return records;
  } catch (e) {
    return null;
  }
}

// --- synthetic fallback (only for localhost / cross-origin dev) ------------
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

function syntheticSeries(symbol, windowKey) {
  const days = WINDOWS[windowKey].days;
  const hours = days * 24;
  const vol = DEMO_FALLBACK_VOLS[symbol] || 0.03;
  const base = DEMO_FALLBACK_BASES[symbol] || 100;
  const rng = mulberry32(hashSeed(symbol + ":" + windowKey));
  const hourlyVol = vol / Math.sqrt(24);
  let price = base * (0.94 + 0.12 * rng());
  const driftPhase = rng() * Math.PI * 2;
  const now = Date.now();
  const out = [];
  for (let i = 0; i < hours; i++) {
    const shock = (rng() + rng() + rng() - 1.5) * hourlyVol;
    const drift = 0.0004 * Math.sin(driftPhase + (i / hours) * Math.PI * 2);
    const wick = rng() < 0.03 ? (rng() - 0.5) * hourlyVol * 6 : 0;
    price = price * (1 + drift + shock + wick);
    out.push({ ts: now - (hours - i) * 3600_000, price });
  }
  return out;
}

// --- rendering -------------------------------------------------------------
function drawChart(canvas, records, fixed, trailing) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  const prices = records.map((r) => r.price);
  const pad = { l: 58, r: 12, t: 12, b: 20 };
  const chartW = w - pad.l - pad.r;
  const chartH = h - pad.t - pad.b;

  const trail = trailing.trail || [];
  const all = prices.concat(trail).concat([fixed.exit]);
  let min = Math.min.apply(null, all), max = Math.max.apply(null, all);
  const padV = (max - min) * 0.08 || max * 0.01;
  min -= padV; max += padV;

  const xAt = (i) => pad.l + (i / (prices.length - 1)) * chartW;
  const yAt = (v) => pad.t + chartH - ((v - min) / (max - min)) * chartH;

  ctx.strokeStyle = "#30363d"; ctx.lineWidth = 1;
  ctx.fillStyle = "#8b949e"; ctx.font = "11px -apple-system, sans-serif";
  for (let i = 0; i <= 4; i++) {
    const v = min + ((max - min) * i) / 4;
    const y = yAt(v);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y);
    ctx.globalAlpha = 0.25; ctx.stroke(); ctx.globalAlpha = 1;
    ctx.fillText(fmtUsd(v), 4, y + 3);
  }

  ctx.strokeStyle = "#58a6ff"; ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let i = 0; i < prices.length; i++) {
    const x = xAt(i), y = yAt(prices[i]);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  if (trail.length) {
    ctx.strokeStyle = "#3fb950"; ctx.lineWidth = 1.2; ctx.setLineDash([4, 3]);
    ctx.beginPath();
    for (let i = 0; i < trail.length && i < prices.length; i++) {
      const x = xAt(i), y = yAt(trail[i]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke(); ctx.setLineDash([]);
  }

  ctx.strokeStyle = "#f85149"; ctx.lineWidth = 1.2; ctx.setLineDash([2, 4]);
  ctx.beginPath();
  ctx.moveTo(pad.l, yAt(fixed.exit)); ctx.lineTo(w - pad.r, yAt(fixed.exit));
  ctx.stroke(); ctx.setLineDash([]);

  function marker(decision, color) {
    ctx.fillStyle = color;
    const x = xAt(decision.index), y = yAt(decision.exit);
    ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
  }
  marker(fixed, "#f85149");
  marker(trailing, "#3fb950");
}

function setStatus(message, tone) {
  const el = document.getElementById("data-status");
  el.textContent = message;
  el.className = "status " + (tone || "");
}

function clearSummary() {
  ["fixed-pnl", "trail-pnl", "delta", "peak"].forEach((id) => {
    const el = document.getElementById(id);
    el.textContent = "—";
    el.className = "val";
  });
  document.getElementById("commentary").textContent =
    "Pick a token and window, then slide the percentage to see how the outcomes diverge.";
}

async function computeAndRender() {
  const tokenId = document.getElementById("coin").value;
  const windowKey = document.getElementById("window").value;
  const side = document.getElementById("side").value;
  const offsetPct = parseFloat(document.getElementById("offset").value) / 100;

  const requestToken = ++activeRequestToken;
  if (!apiBaseReady) {
    setStatus("Waiting for host API…", "muted");
    clearSummary();
    return;
  }
  setStatus("Loading " + tokenId + " price data from Delta Lab…", "muted");

  let records = await loadLiveSeries(tokenId, windowKey);
  if (requestToken !== activeRequestToken) return; // a newer request superseded this one

  let usedFallback = false;
  if (!records || records.length < 2) {
    records = syntheticSeries(tokenId, windowKey);
    usedFallback = true;
    setStatus("Data unavailable for " + tokenId + " — showing demo data", "warn");
  } else {
    setStatus("Delta Lab • " + records.length + " points • " + WINDOWS[windowKey].label, "ok");
  }

  const prices = records.map((r) => r.price);
  const fixed = runFixedStop(prices, side, offsetPct);
  const trailing = runTrailingStop(prices, side, offsetPct);
  drawChart(document.getElementById("chart"), records, fixed, trailing);

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
  const prefix = usedFallback ? "On demo data, a " : "On this window, a ";
  if (Math.abs(delta) < 0.001) {
    comm.textContent = prefix + "$10,000 trade would have ended in roughly the same place with either stop.";
  } else if (delta > 0) {
    comm.textContent = prefix + "$10,000 trade with the trailing stop would have kept " + fmtUsd(dollars) + " more than the fixed stop.";
  } else {
    comm.textContent = prefix + "$10,000 trade with the trailing stop would have left " + fmtUsd(-dollars) + " on the table vs. the fixed stop (a wick took out the trail before the real move developed).";
  }
}

// --- wiring ----------------------------------------------------------------
let debounceTimer = null;
function debouncedCompute() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(computeAndRender, 250);
}

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
    debouncedCompute();
  });
  document.getElementById("coin").addEventListener("change", computeAndRender);
  document.getElementById("window").addEventListener("change", computeAndRender);
  document.getElementById("side").addEventListener("change", computeAndRender);
  window.addEventListener("resize", debouncedCompute);

  // Wayfinder host bridge — capture apiBase from wf:state (preferred) or wf:hello origin.
  let parentOrigin = null;
  window.addEventListener("message", (e) => {
    const d = e.data;
    if (!d || typeof d !== "object") return;
    if (d.type === "wf:hello") {
      parentOrigin = e.origin;
      if (!apiBase) apiBase = e.origin;
      apiBaseReady = true;
      window.parent.postMessage({ type: "wf:hello_ack" }, parentOrigin);
      computeAndRender();
    }
    if (d.type === "wf:state" && d.state && typeof d.state.apiBase === "string") {
      apiBase = d.state.apiBase;
      apiBaseReady = true;
      computeAndRender();
    }
  });

  // Not embedded? After a short wait, probe same-origin (served directly from a web server)
  // or fall back to demo data. Never probe both dev + prod — that violates CLAUDE.md rules.
  setTimeout(() => {
    if (apiBaseReady) return;
    if (window.location.protocol.startsWith("http")) {
      apiBase = window.location.origin;
      apiBaseReady = true;
      computeAndRender();
    } else {
      // file:// context — no API reachable. Go straight to demo data.
      apiBaseReady = true;
      computeAndRender();
    }
  }, 400);

  setStatus("Waiting for host API…", "muted");
  clearSummary();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
