// Dynamic backtest replay for trailing orders on Hyperliquid perps.
// Fetches real prices from Delta Lab's public timeseries endpoint and runs
// fixed-vs-trailing comparisons for SL, TP, and limit-entry orders.
//
// API base URL is delivered by the Wayfinder host shell via wf:state.apiBase
// (CLAUDE.md "Pack applets" rule — never bake dev/prod URLs into the bundle).

// Top ~20 Hyperliquid volume symbols plus PROMPT. Free-form search still works
// for anything not in this list; these are just the suggestions shown in the
// dropdown. Covers crypto, stock perps, commodity perps, and HL-specific HIP-3.
const CURATED_SYMBOLS = [
  "BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE",
  "SP500", "USA500", "TSLA", "MSTR", "HOOD", "CRCL",
  "CL", "BRENTOIL", "GOLD", "SILVER",
  "XYZ100", "XEC", "FARTCOIN", "MON", "PROMPT",
];

const WINDOWS = {
  "1d": { days: 1, label: "Last 24 hours" },
  "1w": { days: 7, label: "Last week" },
  "1m": { days: 30, label: "Last month" },
};

function resolveWindow(st) {
  if (st.windowKey === "custom") {
    // Delta Lab's public endpoint accepts integer days only; clamp to [1, 90]
    // (90 days of hourly candles ≈ the 2000-point response limit).
    const raw = Math.round(Number(st.customValue) || 7);
    const days = Math.min(90, Math.max(1, raw));
    return { days, label: days + (days === 1 ? " day" : " days") };
  }
  return WINDOWS[st.windowKey] || WINDOWS["1w"];
}

// Every kind has two params: a "primary" threshold (what arms the order) and a
// "reversal" distance (how much pullback/reversal actually fires it). For SL
// these are (initial stop %, trail distance %); for TP (activation %, retrace %);
// for entry (arming adverse-move %, fire reversal %).
const KIND_META = {
  trailing_sl: {
    label: "Trailing stop-loss",
    primaryLabel: "Stop-loss %",
    reversalLabel: "If price reverses by",
    peakLabel: "Best price reached",
    primaryColor: "#3fb950",
    primarySubject: "trailing stop",
    fixedLabel: "Fixed stop-loss",
    fixedSubject: "fixed stop",
  },
  trailing_tp: {
    label: "Trailing take-profit",
    primaryLabel: "Start trailing after profit of",
    reversalLabel: "If price reverses by (from peak)",
    peakLabel: "TP started tracking at",
    primaryColor: "#3fb950",
    primarySubject: "trailing TP",
    fixedLabel: "Fixed take-profit",
    fixedSubject: "fixed TP",
  },
  trailing_entry: {
    label: "Trailing limit entry",
    // No primary slider for entry — the controller doesn't accept a "wait
    // for N% dip" gate; the peak just tracks the adverse extreme since
    // attach and fires on reversalPct off it. syncSliderLabels hides the
    // offset control when kind === "trailing_entry".
    primaryLabel: null,
    reversalLabel: "If price reverses by (off the extreme since attach)",
    peakLabel: "Extreme reached since attach",
    primaryColor: "#d29922",
    primarySubject: "trailing entry",
    fixedLabel: null,
    fixedSubject: null,
  },
};

const FETCH_TIMEOUT_MS = 8000;
const NOTIONAL = 1000;
// Isolated-margin maintenance margin rate. Hyperliquid uses roughly 0.5% for
// major coin perps; smaller perps run higher. Close enough for illustration.
const MAINTENANCE_MARGIN_RATE = 0.005;

let apiBase = null;
let apiBaseReady = false;
let activeRequestToken = 0;

const state = {
  symbol: "ETH",
  windowKey: "1w",
  customValue: 7,
  side: "long",
  kind: "trailing_sl",
  primaryPct: 0.05,  // #offset slider: stop-loss / TP activation / entry arming
  reversalPct: 0.01, // #activation slider: trail / retrace / fire reversal
  leverage: 1,
};

// --- simulations (port of controller.py: _favorable_extreme + _trigger_from_peak + _crossed) ---

function favorableExtreme(side, peak, mid, kind) {
  if (kind === "trailing_entry") {
    if (peak === null) return mid;
    return side === "long" ? Math.min(peak, mid) : Math.max(peak, mid);
  }
  if (peak === null) return mid;
  return side === "long" ? Math.max(peak, mid) : Math.min(peak, mid);
}

function triggerFromPeak(side, peak, offsetPct, kind) {
  if (kind === "trailing_entry") {
    return side === "long" ? peak * (1 + offsetPct) : peak * (1 - offsetPct);
  }
  return side === "long" ? peak * (1 - offsetPct) : peak * (1 + offsetPct);
}

function crossed(side, mid, trigger, kind) {
  if (kind === "trailing_entry") {
    return side === "long" ? mid >= trigger : mid <= trigger;
  }
  return side === "long" ? mid <= trigger : mid >= trigger;
}

// Isolated-margin liquidation: returns the price at which the position would
// be liquidated and whether/when it's crossed during the window. At 1× leverage
// there's effectively no liquidation on perps, so we skip the analysis.
function computeLiquidation(prices, side, entry, leverage) {
  if (!leverage || leverage <= 1) return { liqPrice: null, hit: false, index: null };
  const drop = (1 - MAINTENANCE_MARGIN_RATE) / leverage;
  const liqPrice = side === "long" ? entry * (1 - drop) : entry * (1 + drop);
  for (let i = 1; i < prices.length; i++) {
    const hit = side === "long" ? prices[i] <= liqPrice : prices[i] >= liqPrice;
    if (hit) return { liqPrice, hit: true, index: i };
  }
  return { liqPrice, hit: false, index: null };
}

// Kind-aware fixed baseline:
//   SL: static stop at entry * (1 ∓ offsetPct), fires on adverse cross
//   TP: static take-profit at entry * (1 ± levelPct), fires on favorable cross
function simFixedBaseline(prices, side, entry, levelPct, kind) {
  const isTP = kind === "trailing_tp";
  const level = isTP
    ? (side === "long" ? entry * (1 + levelPct) : entry * (1 - levelPct))
    : (side === "long" ? entry * (1 - levelPct) : entry * (1 + levelPct));
  for (let i = 1; i < prices.length; i++) {
    const p = prices[i];
    const hit = isTP
      ? (side === "long" ? p >= level : p <= level)
      : (side === "long" ? p <= level : p >= level);
    if (hit) return { kind: "fixed", hit: true, index: i, exit: level, entry, stopLevel: level };
  }
  return { kind: "fixed", hit: false, index: prices.length - 1, exit: prices[prices.length - 1], entry, stopLevel: level };
}

// Helper: raw peak/trigger trailing loop used by SL post-initial and by entry
// post-arming. Returns a simTrailing-style shape with peakSeries/trail arrays.
function trailFromArmed(prices, side, reversalPct, kind, refPrice) {
  let peak = favorableExtreme(side, null, refPrice, kind);
  let trigger = triggerFromPeak(side, peak, reversalPct, kind);
  const peakSeries = [peak];
  const trail = [trigger];
  for (let i = 1; i < prices.length; i++) {
    const p = prices[i];
    if (crossed(side, p, trigger, kind)) {
      while (peakSeries.length < prices.length) peakSeries.push(peak);
      while (trail.length < prices.length) trail.push(trigger);
      return { hit: true, index: i, exit: trigger, peak, peakSeries, trail };
    }
    const newPeak = favorableExtreme(side, peak, p, kind);
    if (newPeak !== peak) {
      peak = newPeak;
      trigger = triggerFromPeak(side, peak, reversalPct, kind);
    }
    peakSeries.push(peak);
    trail.push(trigger);
  }
  return { hit: false, index: prices.length - 1, exit: prices[prices.length - 1], peak, peakSeries, trail };
}

// Trailing SL with independent initial stop + trail-reversal distance.
// Initial stop sits at entry ± initialPct. As peak ratchets, the trail line
// becomes peak ± reversalPct. The *active* stop is the tighter of the two.
function simTrailingSL(prices, side, entry, initialPct, reversalPct) {
  const initialStop = side === "long" ? entry * (1 - initialPct) : entry * (1 + initialPct);
  let peak = entry;
  let active = initialStop;
  const peakSeries = [peak];
  const trail = [active];
  for (let i = 1; i < prices.length; i++) {
    const p = prices[i];
    const hit = side === "long" ? p <= active : p >= active;
    if (hit) {
      while (peakSeries.length < prices.length) peakSeries.push(peak);
      while (trail.length < prices.length) trail.push(active);
      return { kind: "trailing_sl", hit: true, index: i, exit: active, entry, peak, peakSeries, trail, initialStop };
    }
    const newPeak = side === "long" ? Math.max(peak, p) : Math.min(peak, p);
    if (newPeak !== peak) {
      peak = newPeak;
      const trailTrig = side === "long" ? peak * (1 - reversalPct) : peak * (1 + reversalPct);
      active = side === "long" ? Math.max(initialStop, trailTrig) : Math.min(initialStop, trailTrig);
    }
    peakSeries.push(peak);
    trail.push(active);
  }
  return { kind: "trailing_sl", hit: false, index: prices.length - 1, exit: prices[prices.length - 1], entry, peak, peakSeries, trail, initialStop };
}

// Trailing TP with activation + retrace. Swapped arg order so primary = activation.
function simTrailingTP(prices, side, activationPct, retracePct, entry) {
  let activatedIndex = null;
  for (let i = 1; i < prices.length; i++) {
    const moved = side === "long" ? (prices[i] - entry) / entry : (entry - prices[i]) / entry;
    if (moved >= activationPct) { activatedIndex = i; break; }
  }
  if (activatedIndex === null) {
    return {
      kind: "trailing_tp", hit: false, index: prices.length - 1,
      exit: prices[prices.length - 1], entry, peak: null, peakSeries: null, trail: null,
      activatedIndex: null, activationPct,
    };
  }
  const post = prices.slice(activatedIndex);
  const sub = trailFromArmed(post, side, retracePct, "trailing_sl", post[0]);
  const peakSeries = new Array(prices.length).fill(null);
  const trail = new Array(prices.length).fill(null);
  for (let j = 0; j < sub.peakSeries.length; j++) peakSeries[activatedIndex + j] = sub.peakSeries[j];
  for (let j = 0; j < sub.trail.length; j++) trail[activatedIndex + j] = sub.trail[j];
  return {
    kind: "trailing_tp",
    hit: sub.hit,
    index: activatedIndex + sub.index,
    exit: sub.exit,
    entry,
    peak: sub.peak,
    peakSeries,
    trail,
    activatedIndex,
    activationPct,
  };
}

// Trailing entry — matches the live controller exactly: from tick 0, the
// peak tracks the adverse extreme (low for long, high for short) since
// attach, and the order fires as soon as price reverses `reversalPct` off
// that running extreme. There is no configurable "wait for N% dip first"
// gate; the extreme is whatever the market prints. Keeping the applet
// honest about that matters — an arming slider would imply behaviour the
// checker doesn't actually have.
function simTrailingEntry(prices, side, entry, reversalPct) {
  let peak = entry;
  const peakSeries = [entry];
  const trail = [
    side === "long" ? entry * (1 + reversalPct) : entry * (1 - reversalPct),
  ];
  for (let i = 1; i < prices.length; i++) {
    peak = side === "long" ? Math.min(peak, prices[i]) : Math.max(peak, prices[i]);
    const trigger = side === "long" ? peak * (1 + reversalPct) : peak * (1 - reversalPct);
    peakSeries.push(peak);
    trail.push(trigger);
    const crossed = side === "long" ? prices[i] >= trigger : prices[i] <= trigger;
    if (crossed) {
      return {
        kind: "trailing_entry", hit: true, index: i, exit: prices[i],
        entry, peak, peakSeries, trail,
      };
    }
  }
  return {
    kind: "trailing_entry", hit: false, index: prices.length - 1,
    exit: prices[prices.length - 1], entry, peak, peakSeries, trail,
  };
}

function runSelected(prices, st, entry) {
  if (st.kind === "trailing_sl") return simTrailingSL(prices, st.side, entry, st.primaryPct, st.reversalPct);
  if (st.kind === "trailing_tp") return simTrailingTP(prices, st.side, st.primaryPct, st.reversalPct, entry);
  if (st.kind === "trailing_entry") return simTrailingEntry(prices, st.side, entry, st.reversalPct);
}

// --- pnl / formatting -----------------------------------------------------

function pnlPct(side, entry, exit) {
  return side === "long" ? (exit - entry) / entry : (entry - exit) / entry;
}

function fmtPct(x) { return (x * 100).toFixed(2) + "%"; }
function fmtSignedPct(x) { return (x >= 0 ? "+" : "") + fmtPct(x); }
function fmtUsd(x) {
  const sign = x < 0 ? "-" : "";
  const v = Math.abs(x);
  return sign + "$" + v.toLocaleString(undefined, { maximumFractionDigits: v < 1 ? 4 : 2 });
}
function fmtSignedUsd(x) { return (x >= 0 ? "+" : "") + fmtUsd(x); }

// --- data loading ---------------------------------------------------------

function extractPriceRecords(payload) {
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
    if (!res.ok) {
      const err = new Error("HTTP " + res.status);
      err.status = res.status;
      throw err;
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function loadLiveSeries(symbol, windowSpec) {
  if (!apiBase) return { ok: false, reason: "no_api_base", records: [] };
  const url = apiBase.replace(/\/$/, "") +
    "/api/v1/delta-lab/public/assets/" + encodeURIComponent(symbol) +
    "/timeseries/?series=price&lookback_days=" + windowSpec.days + "&limit=2000";
  try {
    const payload = await fetchWithTimeout(url, FETCH_TIMEOUT_MS);
    const records = extractPriceRecords(payload);
    if (records.length < 2) return { ok: false, reason: "no_data", records: [] };
    return { ok: true, records };
  } catch (e) {
    if (e && e.name === "AbortError") return { ok: false, reason: "timeout", records: [] };
    if (e && e.status === 404) return { ok: false, reason: "not_found", records: [] };
    return { ok: false, reason: "fetch_error", records: [] };
  }
}

// --- synthetic fallback (file:// only) ------------------------------------

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

function syntheticSeries(symbol, windowSpec) {
  const days = windowSpec.days;
  const hours = Math.max(2, Math.ceil(days * 24));
  const vol = 0.03;
  const base = 100;
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

// --- chart ---------------------------------------------------------------

function drawChart(canvas, records, fixed, primary, st, entryPrice, liq) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  const prices = records.map((r) => r.price);
  const pad = { l: 64, r: 12, t: 12, b: 20 };
  const chartW = w - pad.l - pad.r;
  const chartH = h - pad.t - pad.b;
  const showFixed = st.kind !== "trailing_entry";
  const showLiq = liq && liq.liqPrice !== null;

  const allPoints = prices.slice();
  allPoints.push(entryPrice);
  if (showFixed && fixed) allPoints.push(fixed.stopLevel);
  if (showLiq) allPoints.push(liq.liqPrice);
  if (primary.trail) for (const v of primary.trail) if (v !== null && Number.isFinite(v)) allPoints.push(v);
  if (primary.peakSeries) for (const v of primary.peakSeries) if (v !== null && Number.isFinite(v)) allPoints.push(v);
  let min = Math.min.apply(null, allPoints);
  let max = Math.max.apply(null, allPoints);
  const padV = (max - min) * 0.08 || max * 0.01;
  min -= padV; max += padV;

  const xAt = (i) => pad.l + (i / Math.max(prices.length - 1, 1)) * chartW;
  const yAt = (v) => pad.t + chartH - ((v - min) / (max - min)) * chartH;

  // gridlines + axis labels
  ctx.strokeStyle = "#30363d"; ctx.lineWidth = 1;
  ctx.fillStyle = "#8b949e"; ctx.font = "11px -apple-system, sans-serif";
  for (let i = 0; i <= 4; i++) {
    const v = min + ((max - min) * i) / 4;
    const y = yAt(v);
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y);
    ctx.globalAlpha = 0.25; ctx.stroke(); ctx.globalAlpha = 1;
    ctx.fillText(fmtUsd(v), 4, y + 3);
  }

  // TP awaiting-activation shaded region
  if (primary.kind === "trailing_tp") {
    const endIdx = primary.activatedIndex !== null ? primary.activatedIndex : prices.length - 1;
    if (endIdx > 0) {
      ctx.fillStyle = "rgba(210, 153, 34, 0.08)";
      ctx.fillRect(pad.l, pad.t, xAt(endIdx) - pad.l, chartH);
    }
  }

  // entry / reference-price horizontal line (muted)
  ctx.strokeStyle = "#8b949e"; ctx.lineWidth = 1; ctx.setLineDash([1, 3]); ctx.globalAlpha = 0.5;
  ctx.beginPath();
  ctx.moveTo(pad.l, yAt(entryPrice)); ctx.lineTo(w - pad.r, yAt(entryPrice));
  ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
  ctx.fillStyle = "#8b949e"; ctx.font = "10px -apple-system, sans-serif";
  const entryLbl = st.kind === "trailing_entry" ? "reference" : "entry";
  ctx.fillText(entryLbl + " " + fmtUsd(entryPrice), w - pad.r - 90, yAt(entryPrice) - 4);

  // price line
  ctx.strokeStyle = "#58a6ff"; ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let i = 0; i < prices.length; i++) {
    const x = xAt(i), y = yAt(prices[i]);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // primary peak/extreme tracking line (solid)
  if (primary.peakSeries) {
    const color = KIND_META[primary.kind].primaryColor;
    ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.globalAlpha = 0.6;
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < primary.peakSeries.length; i++) {
      const v = primary.peakSeries[i];
      if (v === null || !Number.isFinite(v)) { started = false; continue; }
      const x = xAt(i), y = yAt(v);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke(); ctx.globalAlpha = 1;
  }

  // primary trigger trail (dashed)
  if (primary.trail) {
    const color = KIND_META[primary.kind].primaryColor;
    ctx.strokeStyle = color; ctx.lineWidth = 1.4; ctx.setLineDash([4, 3]);
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < primary.trail.length; i++) {
      const v = primary.trail[i];
      if (v === null || !Number.isFinite(v)) { started = false; continue; }
      const x = xAt(i), y = yAt(v);
      if (!started) { ctx.moveTo(x, y); started = true; } else ctx.lineTo(x, y);
    }
    ctx.stroke(); ctx.setLineDash([]);
  }

  // fixed-stop level (red dashed) — only for SL/TP, not entry orders
  if (showFixed && fixed) {
    ctx.strokeStyle = "#f85149"; ctx.lineWidth = 1.2; ctx.setLineDash([2, 4]);
    ctx.globalAlpha = fixed.hit ? 0.9 : 0.45;
    ctx.beginPath();
    ctx.moveTo(pad.l, yAt(fixed.stopLevel)); ctx.lineTo(w - pad.r, yAt(fixed.stopLevel));
    ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha = 1;
  }

  // liquidation line (solid, bright red) + "danger zone" shading below it
  if (showLiq) {
    const liqY = yAt(liq.liqPrice);
    ctx.fillStyle = "rgba(248, 81, 73, 0.09)";
    if (st.side === "long") ctx.fillRect(pad.l, liqY, chartW, (pad.t + chartH) - liqY);
    else ctx.fillRect(pad.l, pad.t, chartW, liqY - pad.t);
    ctx.strokeStyle = "#ff4d4d"; ctx.lineWidth = 1.5;
    ctx.beginPath(); ctx.moveTo(pad.l, liqY); ctx.lineTo(w - pad.r, liqY); ctx.stroke();
    ctx.fillStyle = "#ff4d4d"; ctx.font = "bold 10px -apple-system, sans-serif";
    ctx.fillText("LIQ " + fmtUsd(liq.liqPrice), pad.l + 4, liqY - 4);
  }

  // markers — only when actually fired
  function marker(x, y, color) {
    ctx.fillStyle = color; ctx.strokeStyle = "#0b0d10"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
  }
  function xMarker(x, y, color) {
    ctx.strokeStyle = color; ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(x - 6, y - 6); ctx.lineTo(x + 6, y + 6);
    ctx.moveTo(x - 6, y + 6); ctx.lineTo(x + 6, y - 6);
    ctx.stroke();
  }
  if (showFixed && fixed && fixed.hit) marker(xAt(fixed.index), yAt(fixed.exit), "#f85149");
  if (primary.hit) marker(xAt(primary.index), yAt(primary.exit), KIND_META[primary.kind].primaryColor);
  if (showLiq && liq.hit) xMarker(xAt(liq.index), yAt(liq.liqPrice), "#ff4d4d");
}

function renderLegend(kind) {
  const meta = KIND_META[kind];
  const items = [
    `<span><span class="dot" style="background:#58a6ff"></span>Price</span>`,
  ];
  if (kind === "trailing_entry") {
    items.push(`<span style="color:#8b949e"><span class="dash"></span>Reference price</span>`);
    items.push(`<span style="color:${meta.primaryColor}"><span class="dash"></span>Reversal trigger (entry fires)</span>`);
  } else {
    items.push(`<span style="color:#8b949e"><span class="dash"></span>Entry price</span>`);
    const fixedLegendLabel = kind === "trailing_tp" ? "Fixed TP level" : "Fixed-stop level";
    items.push(`<span style="color:var(--red)"><span class="dash"></span>${fixedLegendLabel}</span>`);
    if (kind === "trailing_sl") {
      items.push(`<span style="color:${meta.primaryColor}"><span class="dash"></span>Trailing SL trigger</span>`);
    } else if (kind === "trailing_tp") {
      items.push(`<span style="color:${meta.primaryColor}"><span class="dash"></span>Trailing TP trigger (post-activation)</span>`);
    }
    items.push(`<span style="color:#ff4d4d"><span class="dash" style="border-top-style:solid"></span>Liquidation (isolated margin)</span>`);
  }
  document.getElementById("legend").innerHTML = items.join(" ");
}

function syncCardVisibility(kind) {
  const hideFixed = kind === "trailing_entry";
  document.getElementById("fixed-card").classList.toggle("hidden", hideFixed);
  document.getElementById("delta-card").classList.toggle("hidden", hideFixed);
}

// --- summary / commentary ------------------------------------------------

function setStatus(message, tone) {
  const el = document.getElementById("data-status");
  el.textContent = message;
  el.className = "status " + (tone || "");
}

function clearChartAndSummary() {
  const canvas = document.getElementById("chart");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ["fixed-pnl", "trail-pnl", "delta", "peak"].forEach((id) => {
    const el = document.getElementById(id);
    el.textContent = "—";
    el.className = "val";
  });
  ["fixed-sub", "trail-sub", "delta-sub", "peak-sub"].forEach((id) => {
    document.getElementById(id).textContent = "";
  });
}

function renderSummary(records, fixed, primary, st, entryPrice, liq) {
  const meta = KIND_META[st.kind];
  document.getElementById("trail-lbl").textContent = meta.label + " $ outcome";
  document.getElementById("peak-lbl").textContent = meta.peakLabel;
  const fixedCard = document.getElementById("fixed-card");
  const fixedLblEl = fixedCard ? fixedCard.querySelector(".lbl") : null;
  if (fixedLblEl && meta.fixedLabel) fixedLblEl.textContent = meta.fixedLabel + " $ outcome";

  const entry = entryPrice;
  const lev = st.leverage;

  // Liquidation dominates: if liq fires before a close, the close never happens.
  const fixedLiquidated = liq && liq.hit && fixed && (!fixed.hit || liq.index < fixed.index);
  const primaryLiquidated = liq && liq.hit && (!primary.hit || liq.index < primary.index);

  // Fixed stop $: only meaningful for SL/TP (fixed === null for trailing_entry)
  const fEl = document.getElementById("fixed-pnl");
  const fSub = document.getElementById("fixed-sub");
  if (!fixed) {
    fEl.textContent = "—";
    fEl.className = "val";
    fSub.textContent = "";
  } else if (fixedLiquidated) {
    fEl.textContent = fmtSignedUsd(-NOTIONAL);
    fEl.className = "val neg";
    fSub.textContent = "LIQUIDATED at " + fmtUsd(liq.liqPrice) + " — margin wiped before stop could fire";
  } else if (fixed.hit) {
    const pct = pnlPct(st.side, entry, fixed.exit);
    const dollars = pct * lev * NOTIONAL;
    fEl.textContent = fmtSignedUsd(dollars);
    fEl.className = "val " + (dollars >= 0 ? "pos" : "neg");
    fSub.textContent = fmtSignedPct(pct) + " spot · " + lev + "× leverage · $" + NOTIONAL.toLocaleString() + " notional";
  } else {
    fEl.textContent = st.kind === "trailing_tp" ? "TP never hit" : "Stop never fired";
    fEl.className = "val";
    fSub.textContent = "Trade still open at " + fmtUsd(records[records.length - 1].price);
  }

  // Selected order $
  const tEl = document.getElementById("trail-pnl");
  const tSub = document.getElementById("trail-sub");
  if (primaryLiquidated && st.kind !== "trailing_entry") {
    tEl.textContent = fmtSignedUsd(-NOTIONAL);
    tEl.className = "val neg";
    tSub.textContent = "LIQUIDATED at " + fmtUsd(liq.liqPrice) + " — trailing trigger was too loose for this leverage";
  } else if (st.kind === "trailing_entry") {
    if (primary.hit) {
      tSub.textContent = "Entry filled at " + fmtUsd(primary.exit) + " (bar " + primary.index + " / " + records.length + ")";
      tEl.textContent = "Filled";
      tEl.className = "val pos";
    } else {
      tEl.textContent = "Never filled";
      tEl.className = "val";
      tSub.textContent = "Reversal threshold not hit in window";
    }
  } else if (st.kind === "trailing_tp" && primary.activatedIndex === null) {
    tEl.textContent = "Never activated";
    tEl.className = "val";
    tSub.textContent = "Position never moved " + fmtPct(st.primaryPct) + " in our favor";
  } else if (!primary.hit) {
    tEl.textContent = (st.kind === "trailing_sl") ? "Stop never fired" : "TP never fired";
    tEl.className = "val";
    tSub.textContent = "Trade still open at " + fmtUsd(records[records.length - 1].price);
  } else {
    const pct = pnlPct(st.side, entry, primary.exit);
    const dollars = pct * lev * NOTIONAL;
    tEl.textContent = fmtSignedUsd(dollars);
    tEl.className = "val " + (dollars >= 0 ? "pos" : "neg");
    tSub.textContent = fmtSignedPct(pct) + " spot · " + lev + "× leverage";
  }

  // Difference (only meaningful when both fixed and primary close)
  const dEl = document.getElementById("delta");
  const dSub = document.getElementById("delta-sub");
  if (st.kind === "trailing_entry") {
    dEl.textContent = "—";
    dEl.className = "val";
    dSub.textContent = "Limit entry — no fixed-stop comparison";
  } else if (fixed && fixed.hit && primary.hit) {
    const fixedPct = pnlPct(st.side, entry, fixed.exit);
    const primaryPct = pnlPct(st.side, entry, primary.exit);
    const delta = (primaryPct - fixedPct) * lev * NOTIONAL;
    dEl.textContent = fmtSignedUsd(delta);
    dEl.className = "val " + (delta >= 0 ? "pos" : "neg");
    dSub.textContent = fmtSignedPct(primaryPct - fixedPct) + " at " + lev + "× leverage";
  } else {
    dEl.textContent = "—";
    dEl.className = "val";
    dSub.textContent = "Awaiting both orders to close";
  }

  // Peak / context
  const pEl = document.getElementById("peak");
  const pSub = document.getElementById("peak-sub");
  if (st.kind === "trailing_tp") {
    if (primary.activatedIndex === null) {
      pEl.textContent = "Not reached";
      pSub.textContent = "Activation needs " + fmtPct(st.primaryPct) + " favorable move";
    } else {
      pEl.textContent = fmtUsd(records[primary.activatedIndex].price);
      pSub.textContent = "Bar " + primary.activatedIndex + " of " + records.length;
    }
  } else if (st.kind === "trailing_entry") {
    pEl.textContent = primary.peak !== null ? fmtUsd(primary.peak) : "—";
    pSub.textContent = (st.side === "long" ? "Lowest" : "Highest") + " price seen pre-fire";
  } else {
    pEl.textContent = primary.peak !== null ? fmtUsd(primary.peak) : "—";
    pSub.textContent = (st.side === "long" ? "Highest" : "Lowest") + " price during trade";
  }

  // Commentary
  const comm = document.getElementById("commentary");
  comm.textContent = buildCommentary(records, fixed, primary, st, liq);
}

function buildCommentary(records, fixed, primary, st, liq) {
  const lev = st.leverage;
  const entry = primary.entry;
  // Liquidation trumps everything for SL/TP kinds.
  if (liq && liq.hit && st.kind !== "trailing_entry") {
    const primaryBeat = primary.hit && primary.index <= liq.index;
    const fixedBeat = fixed && fixed.hit && fixed.index <= liq.index;
    if (!primaryBeat && !fixedBeat) {
      return `At ${lev}× leverage the position would have been liquidated at ${fmtUsd(liq.liqPrice)} (bar ${liq.index}) before either stop could fire — full $${NOTIONAL.toLocaleString()} margin wiped. Lower leverage or tighten the "Stop-loss %" slider to ensure the stop fires before liq.`;
    }
    if (primaryBeat && !fixedBeat) {
      return `The ${KIND_META[st.kind].primarySubject} closed the trade at ${fmtUsd(primary.exit)} — saving the position from liquidation at ${fmtUsd(liq.liqPrice)} only ${liq.index - primary.index} bar(s) later. The fixed baseline would NOT have saved you here.`;
    }
    if (fixedBeat && !primaryBeat) {
      return `The ${KIND_META[st.kind].fixedSubject} closed at ${fmtUsd(fixed.exit)} and saved the position; the ${KIND_META[st.kind].primarySubject} would have held on until liquidation at ${fmtUsd(liq.liqPrice)}. Tighten the trailing distance at this leverage.`;
    }
    // Both beat liquidation — fall through to normal commentary.
  }
  if (st.kind === "trailing_entry") {
    const extremeLabel = st.side === "long" ? "low" : "high";
    if (primary.hit) {
      return `Filled at ${fmtUsd(primary.exit)} — price reversed ${fmtPct(st.reversalPct)} off the ${extremeLabel} of ${fmtUsd(primary.peak)} seen since attach.`;
    }
    return `Order never fired — price never reversed ${fmtPct(st.reversalPct)} off its ${extremeLabel} of ${fmtUsd(primary.peak)} in this window. Tighten the reversal slider to see when it would have filled.`;
  }
  if (st.kind === "trailing_tp" && primary.activatedIndex === null) {
    return `Position never moved ${fmtPct(st.primaryPct)} in your favor, so the trailing TP never armed. Lower the "Start trailing after profit of" slider to see when it would arm.`;
  }
  // SL or activated TP — both fixed and primary in scope
  const meta = KIND_META[st.kind];
  const fixedSubj = meta.fixedSubject;
  const latest = records[records.length - 1].price;
  const openPct = pnlPct(st.side, entry, latest);
  const openDollars = openPct * lev * NOTIONAL;
  if (!fixed.hit && !primary.hit) {
    return `Neither order would have fired — price never reversed ${fmtPct(st.reversalPct)} from its best level, and never hit the ${fmtPct(st.primaryPct)} initial stop. Trade is still open at ${fmtUsd(latest)} (${fmtSignedPct(openPct)} spot, ${fmtSignedUsd(openDollars)} at ${lev}×). Tighten either slider to see when the trailing stop would fire.`;
  }
  if (!fixed.hit && primary.hit) {
    const pct = pnlPct(st.side, entry, primary.exit);
    return `The ${fixedSubj} never fired, but the ${meta.primarySubject} closed at ${fmtUsd(primary.exit)} (${fmtSignedPct(pct)} spot, ${fmtSignedUsd(pct * lev * NOTIONAL)} on $${NOTIONAL.toLocaleString()} at ${lev}×).`;
  }
  if (fixed.hit && !primary.hit) {
    const pct = pnlPct(st.side, entry, fixed.exit);
    return `The ${fixedSubj} closed at ${fmtUsd(fixed.exit)} (${fmtSignedPct(pct)} spot, ${fmtSignedUsd(pct * lev * NOTIONAL)} at ${lev}×); the ${meta.primarySubject} kept the trade open and is now at ${fmtUsd(latest)} (${fmtSignedPct(openPct)} spot, ${fmtSignedUsd(openDollars)} at ${lev}×) — it ratcheted its trigger above the fixed-stop level.`;
  }
  const fixedPct = pnlPct(st.side, entry, fixed.exit);
  const primaryPct = pnlPct(st.side, entry, primary.exit);
  const deltaDollars = (primaryPct - fixedPct) * lev * NOTIONAL;
  if (Math.abs(deltaDollars) < 1) {
    return `On this window a $${NOTIONAL.toLocaleString()} trade at ${lev}× would have ended in roughly the same place with either order.`;
  }
  if (deltaDollars > 0) {
    return `On this window a $${NOTIONAL.toLocaleString()} trade at ${lev}× with the ${meta.primarySubject} would have kept ${fmtUsd(deltaDollars)} more than the ${fixedSubj}.`;
  }
  return `On this window a $${NOTIONAL.toLocaleString()} trade at ${lev}× with the ${meta.primarySubject} would have left ${fmtUsd(-deltaDollars)} on the table vs. the ${fixedSubj} ${st.kind === "trailing_tp" ? "(a reversal clipped the trailing stop before price ran further)" : "(a wick took out the trail before the real move developed)"}.`;
}

// --- main render ---------------------------------------------------------

async function computeAndRender() {
  const symbol = state.symbol.trim().toUpperCase();
  if (!symbol) {
    setStatus("Type a symbol to begin.", "muted");
    clearChartAndSummary();
    return;
  }

  const requestToken = ++activeRequestToken;
  if (!apiBaseReady) {
    setStatus("Waiting for host API…", "muted");
    clearChartAndSummary();
    return;
  }

  setStatus("Loading " + symbol + " price data from Delta Lab…", "muted");
  renderLegend(state.kind);

  const windowSpec = resolveWindow(state);
  let records;
  if (apiBase === null) {
    // file:// fallback only
    records = syntheticSeries(symbol, windowSpec);
    setStatus("No API reachable — showing synthetic demo data for " + symbol, "warn");
  } else {
    const result = await loadLiveSeries(symbol, windowSpec);
    if (requestToken !== activeRequestToken) return;
    if (!result.ok) {
      const msg = result.reason === "timeout"
        ? "Delta Lab took too long for " + symbol + " — try again or pick another window."
        : "Data unavailable for " + symbol + " — try BTC, ETH, SOL, HYPE, or another listed HL perp.";
      setStatus(msg, "warn");
      clearChartAndSummary();
      return;
    }
    records = result.records;
    setStatus("Delta Lab • " + records.length + " points • " + windowSpec.label + " • " + symbol, "ok");
  }

  const prices = records.map((r) => r.price);
  const entryPrice = prices[0];
  // Fixed baseline = the "primary" threshold as a static order:
  //   SL  → fixed stop at entry ± primary_pct
  //   TP  → fixed take-profit at entry ± primary_pct (= the activation target)
  //   Entry → no baseline
  let fixed = null;
  if (state.kind === "trailing_sl") {
    fixed = simFixedBaseline(prices, state.side, entryPrice, state.primaryPct, "trailing_sl");
  } else if (state.kind === "trailing_tp") {
    fixed = simFixedBaseline(prices, state.side, entryPrice, state.primaryPct, "trailing_tp");
  }
  const primary = runSelected(prices, state, entryPrice);
  // Entry orders don't have a position open until fill, so no pre-fill liq risk.
  const liq = state.kind === "trailing_entry"
    ? { liqPrice: null, hit: false, index: null }
    : computeLiquidation(prices, state.side, entryPrice, state.leverage);

  updateSliderHints(entryPrice);

  drawChart(document.getElementById("chart"), records, fixed, primary, state, entryPrice, liq);
  renderSummary(records, fixed, primary, state, entryPrice, liq);
}

// Given a price-move pct, describe it in the three framings users think
// in: price move, ROI on margin, and absolute PnL $ on the applet's
// $NOTIONAL position. Matches the skill's AskUserQuestion wording so the
// applet + live prompt speak the same language.
function pnlEquivalents(pct) {
  const lev = state.leverage;
  const roiPct = pct * lev;                 // unrealized ROI = price move × leverage
  const dollars = pct * NOTIONAL;           // PnL$ on notional (sign-agnostic)
  return `= ${fmtSignedPct(roiPct)} ROI · ${fmtSignedUsd(dollars)} on $${NOTIONAL.toLocaleString()} @ ${lev}×`;
}

// Per-kind copy for the two slider hints. Shows both the price-level meaning
// AND the leverage-aware ROI / $PnL so a 5% pullback at 10× doesn't look
// innocuous — users get the full cost of the trigger at their leverage.
function updateSliderHints(entryPrice) {
  const primaryHint = document.getElementById("offset-hint");
  const reversalHint = document.getElementById("activation-hint");
  if (!primaryHint || !reversalHint) return;
  const pPct = fmtPct(state.primaryPct);
  const rPct = fmtPct(state.reversalPct);
  const pDollar = fmtUsd(entryPrice * state.primaryPct);
  const rDollar = fmtUsd(entryPrice * state.reversalPct);
  const pEquiv = pnlEquivalents(state.primaryPct);
  const rEquiv = pnlEquivalents(state.reversalPct);
  if (state.kind === "trailing_sl") {
    const dir = state.side === "long" ? "below" : "above";
    const stopLevel = state.side === "long"
      ? entryPrice * (1 - state.primaryPct)
      : entryPrice * (1 + state.primaryPct);
    primaryHint.textContent = `Initial stop at ${fmtUsd(stopLevel)} (${pPct} ${dir} ${fmtUsd(entryPrice)} entry) ${pEquiv}.`;
    reversalHint.textContent = `Once in profit, stop trails the best price by ${rPct} (≈ ${rDollar}) ${rEquiv}. Active stop = tighter of the two.`;
  } else if (state.kind === "trailing_tp") {
    const dir = state.side === "long" ? "above" : "below";
    primaryHint.textContent = `TP arms once the trade is up ${pPct} (≈ ${pDollar} ${dir} entry) ${pEquiv}. Fixed TP also fires at this level.`;
    reversalHint.textContent = `After arming, closes once price retraces ${rPct} (≈ ${rDollar}) from its peak ${rEquiv}.`;
  } else if (state.kind === "trailing_entry") {
    const extreme = state.side === "long" ? "low" : "high";
    primaryHint.textContent = "";
    reversalHint.textContent = `Fires the moment price reverses ${rPct} (≈ ${rDollar}) off the ${extreme} seen since attach ${rEquiv}. No "wait for N% dip" gate — the extreme is just the running min/max.`;
  }
}

// --- wiring --------------------------------------------------------------

let debounceTimer = null;
function debouncedCompute() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(computeAndRender, 350);
}

function syncSliderLabels() {
  const meta = KIND_META[state.kind];
  const offsetWrap = document.getElementById("offset-wrap");
  if (meta.primaryLabel) {
    document.getElementById("offset-label").textContent = meta.primaryLabel;
    if (offsetWrap) offsetWrap.classList.remove("hidden");
  } else if (offsetWrap) {
    // trailing_entry has no primary param — hide the slider entirely so
    // the UI mirrors the controller's single-knob reality.
    offsetWrap.classList.add("hidden");
  }
  document.getElementById("activation-label").textContent = meta.reversalLabel;
}

function init() {
  const symbol = document.getElementById("symbol");
  for (const sym of CURATED_SYMBOLS) {
    const opt = document.createElement("option");
    opt.value = sym;
    opt.textContent = sym;
    if (sym === state.symbol) opt.selected = true;
    symbol.appendChild(opt);
  }
  symbol.addEventListener("change", () => {
    state.symbol = symbol.value;
    computeAndRender();
  });

  const kind = document.getElementById("kind");
  kind.addEventListener("change", () => {
    state.kind = kind.value;
    syncSliderLabels();
    syncCardVisibility(state.kind);
    renderLegend(state.kind);
    computeAndRender();
  });

  const windowSel = document.getElementById("window");
  const customWrap = document.getElementById("custom-window-wrap");
  const customInput = document.getElementById("custom-window");
  const syncCustomVisibility = () => {
    if (state.windowKey === "custom") customWrap.classList.remove("hidden");
    else customWrap.classList.add("hidden");
  };
  windowSel.addEventListener("change", (e) => {
    state.windowKey = e.target.value;
    syncCustomVisibility();
    computeAndRender();
  });
  customInput.addEventListener("input", () => {
    const v = parseInt(customInput.value, 10);
    if (Number.isFinite(v) && v > 0) {
      state.customValue = v;
      debouncedCompute();
    }
  });
  syncCustomVisibility();
  document.getElementById("side").addEventListener("change", (e) => {
    state.side = e.target.value;
    computeAndRender();
  });

  const offset = document.getElementById("offset");
  const offsetVal = document.getElementById("offset-val");
  offset.value = (state.primaryPct * 100).toFixed(1);
  offsetVal.textContent = (state.primaryPct * 100).toFixed(1) + "%";
  offset.addEventListener("input", () => {
    state.primaryPct = parseFloat(offset.value) / 100;
    offsetVal.textContent = parseFloat(offset.value).toFixed(1) + "%";
    debouncedCompute();
  });

  const activation = document.getElementById("activation");
  const activationVal = document.getElementById("activation-val");
  activation.value = (state.reversalPct * 100).toFixed(1);
  activationVal.textContent = (state.reversalPct * 100).toFixed(1) + "%";
  activation.addEventListener("input", () => {
    state.reversalPct = parseFloat(activation.value) / 100;
    activationVal.textContent = parseFloat(activation.value).toFixed(1) + "%";
    debouncedCompute();
  });

  const leverage = document.getElementById("leverage");
  const leverageVal = document.getElementById("leverage-val");
  leverage.addEventListener("input", () => {
    state.leverage = parseInt(leverage.value, 10);
    leverageVal.textContent = state.leverage + "×";
    debouncedCompute();
  });

  window.addEventListener("resize", debouncedCompute);

  // Wayfinder host bridge — apiBase from wf:state (preferred) or wf:hello origin.
  // Defer the hello-origin fallback by one tick so that a wf:state message
  // arriving in the same iframe-load event wins the race (avoiding a CORS-bound
  // fetch against the parent origin before the explicit apiBase arrives).
  let parentOrigin = null;
  let helloFallbackTimer = null;
  window.addEventListener("message", (e) => {
    const d = e.data;
    if (!d || typeof d !== "object") return;
    if (d.type === "wf:hello") {
      parentOrigin = e.origin;
      window.parent.postMessage({ type: "wf:hello_ack" }, parentOrigin);
      if (apiBaseReady) return;
      clearTimeout(helloFallbackTimer);
      helloFallbackTimer = setTimeout(() => {
        if (apiBaseReady) return;
        apiBase = e.origin;
        apiBaseReady = true;
        computeAndRender();
      }, 120);
    }
    if (d.type === "wf:state" && d.state && typeof d.state.apiBase === "string") {
      clearTimeout(helloFallbackTimer);
      apiBase = d.state.apiBase;
      apiBaseReady = true;
      computeAndRender();
    }
  });

  // Not embedded? After a short wait: same-origin probe over HTTP, or synthetic data over file://.
  setTimeout(() => {
    if (apiBaseReady) return;
    if (window.location.protocol === "file:") {
      apiBase = null;  // signals synthetic fallback
      apiBaseReady = true;
      computeAndRender();
    } else if (window.location.protocol.startsWith("http")) {
      apiBase = window.location.origin;
      apiBaseReady = true;
      computeAndRender();
    }
  }, 400);

  syncSliderLabels();
  syncCardVisibility(state.kind);
  renderLegend(state.kind);
  setStatus("Waiting for host API…", "muted");
  clearChartAndSummary();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
