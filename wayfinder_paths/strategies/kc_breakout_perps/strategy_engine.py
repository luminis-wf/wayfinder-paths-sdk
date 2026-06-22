"""Event-driven backtester for the KC-breakout + Ulcer-filter strategy.

Faithful to Mangrove's dynamic_atr execution model:
  stop_distance = ATR(atr_period) * atr_volatility_factor   (ATR at signal bar)
  long:  stop = entry - d,  tp = entry + d*reward_factor
  short: stop = entry + d,  tp = entry - d*reward_factor
  size  = (account_value * max_risk_per_trade) / stop_distance   [risk-based]

Modeling choices (documented, configurable):
  - Entry at NEXT bar open after the signal bar (no lookahead).
  - Intrabar exit: stop checked before TP when both touch in one bar (pessimistic).
  - Sizing account_value = realized cash balance (no unrealized feedback).
  - Single position per symbol at a time (portfolio max_open_positions not binding
    in single-symbol backtests).
  - Funding accrued each bar on current notional; +rate => longs pay / shorts earn.
  - Fee + slippage applied per side on the executed fill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from . import indicators as M

Direction = Literal["long", "short", "both"]


@dataclass
class Config:
    # entry signal (Keltner breakout)
    kc_window: int = 10
    kc_window_atr: int = 27
    kc_multiplier: float = 1.7536
    kc_original_version: bool = False
    # filter (Ulcer Index)
    ulcer_window: int = 39
    ulcer_threshold: float = 6.1425
    # execution (dynamic ATR)
    atr_period: int = 14
    atr_volatility_factor: float = 2.0
    reward_factor: float = 2.59
    max_risk_per_trade: float = 0.0397
    cooldown_bars: int = 24
    max_hold_bars: int = 1000
    # costs
    fee_pct: float = 0.0085
    slippage_pct: float = 0.004
    # account
    initial_balance: float = 10_000.0
    # per-trade notional cap (notional <= max_leverage * equity). Risk-based sizing
    # is uncapped by construction; without this, tiny-ATR bars produce absurd
    # leverage. Real venues (and Mangrove's atr_cap/position_size v2) enforce a cap.
    max_leverage: float = 10.0
    # exit execution model. "at_level": idealized fill at the stop/TP price (intrabar).
    # "next_open": realistic for an hourly live strategy — a stop/TP touched during a
    # bar is detected at bar close and the position exits at the NEXT bar's open.
    exit_execution: str = "at_level"
    # behavior
    direction: Direction = "long"
    include_funding: bool = True
    min_notional: float = 0.0
    # regime/trend filter (entry gate). "none" | "ema_above" | "ema_above_rising".
    # Longs only fire when close > EMA(trend_window) (and EMA rising, if _rising).
    trend_filter: str = "none"
    trend_window: int = 100
    trend_slope_lookback: int = 24


@dataclass
class Trade:
    side: int  # +1 long, -1 short
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    size: float
    bars_held: int
    pnl: float
    ret_pct: float
    fees: float
    funding: float
    reason: str
    lev: float = 0.0


@dataclass
class Result:
    trades: list[Trade] = field(default_factory=list)
    equity: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    stats: dict = field(default_factory=dict)
    # per-bar target leverage (notional/equity): risk-based leverage while in a
    # trade (held constant for the trade), 0 when flat. The live strategy's
    # signal consumes this — decide() multiplies by NAV to get target size.
    weights: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))


def _precompute(df: pd.DataFrame, cfg: Config) -> dict[str, np.ndarray]:
    h, l, c = df["high"], df["low"], df["close"]
    atr_exec = M.atr_wilder(h, l, c, cfg.atr_period)
    upper = M.kc_upper_breakout_series(h, l, c, cfg.kc_window, cfg.kc_window_atr,
                                       cfg.kc_multiplier, cfg.kc_original_version)
    lower = M.kc_lower_breakout_series(h, l, c, cfg.kc_window, cfg.kc_window_atr,
                                       cfg.kc_multiplier, cfg.kc_original_version)
    ulcer_ok = M.ulcer_low_risk_series(c, cfg.ulcer_window, cfg.ulcer_threshold)
    if cfg.trend_filter == "none":
        trend_long = pd.Series(True, index=c.index)
        trend_short = pd.Series(True, index=c.index)
    else:
        ema = c.ewm(span=cfg.trend_window, adjust=False).mean()
        above = c > ema
        if cfg.trend_filter == "ema_above_rising":
            rising = ema > ema.shift(cfg.trend_slope_lookback)
            trend_long = (above & rising).fillna(False)
            trend_short = (~above & (ema < ema.shift(cfg.trend_slope_lookback))).fillna(False)
        else:  # ema_above
            trend_long = above.fillna(False)
            trend_short = (~above).fillna(False)
    return {
        "atr": atr_exec.to_numpy(),
        "upper": upper.to_numpy(),
        "lower": lower.to_numpy(),
        "ulcer_ok": ulcer_ok.to_numpy(),
        "trend_long": trend_long.to_numpy(),
        "trend_short": trend_short.to_numpy(),
    }


def run(df: pd.DataFrame, cfg: Config, funding: pd.Series | None = None,
        eval_start: int = 0, eval_end: int | None = None) -> Result:
    """df: index=UTC ts, columns open/high/low/close. funding: hourly rate series.

    Indicators are computed on the FULL df (so warm-up/history is correct), but the
    simulation only runs over [eval_start, eval_end) with fresh account state. This
    lets walk-forward train/test slices share one indicator computation while keeping
    PnL isolated."""
    df = df.sort_index()
    ind = _precompute(df, cfg)
    o = df["open"].to_numpy(); h = df["high"].to_numpy()
    lo = df["low"].to_numpy(); c = df["close"].to_numpy()
    ts = df.index
    n = len(df)
    hi = n if eval_end is None else min(eval_end, n)

    fund_arr = None
    if cfg.include_funding and funding is not None and len(funding):
        fund_arr = funding.reindex(df.index).fillna(0.0).to_numpy()

    balance = cfg.initial_balance
    pos: dict | None = None
    pending_side = 0          # signal fired previous bar -> open at this bar's open
    pending_stop_distance = 0.0  # ATR stop distance captured at the signal bar
    pending_exit: str | None = None  # stop/tp detected last bar -> close at this bar's open
    cooldown_until = -1
    trades: list[Trade] = []
    equity_vals: list[float] = []
    weight_vals: list[float] = []
    equity_idx: list = []

    slip = cfg.slippage_pct
    fee = cfg.fee_pct

    def close_position(p: dict, exit_idx: int, fill: float, reason: str) -> float:
        side = p["side"]; size = p["size"]
        exit_fee = size * fill * fee
        gross = side * (fill - p["entry_price"]) * size
        p["fees"] += exit_fee
        net = gross - p["fees"] + p["funding"]
        trades.append(Trade(
            side=side, entry_time=ts[p["entry_idx"]], exit_time=ts[exit_idx],
            entry_price=p["entry_price"], exit_price=fill, size=size,
            bars_held=exit_idx - p["entry_idx"], pnl=net,
            ret_pct=net / cfg.initial_balance * 100,
            fees=p["fees"], funding=p["funding"], reason=reason, lev=p["lev"],
        ))
        return gross - exit_fee + p["funding"]  # cash delta to balance

    for i in range(eval_start, hi):
        # 0) execute a pending (next-open) exit at this bar's open
        if pos is not None and pending_exit is not None:
            side = pos["side"]
            fill = o[i] * (1 - slip) if side > 0 else o[i] * (1 + slip)
            balance += close_position(pos, i, fill, pending_exit)
            cooldown_until = i + cfg.cooldown_bars
            pos = None
            pending_exit = None

        # 1) open a pending entry at this bar's open
        if pos is None and pending_side != 0 and i >= cooldown_until:
            side = pending_side
            d = pending_stop_distance
            entry = o[i] * (1 + slip) if side > 0 else o[i] * (1 - slip)
            if d > 0 and np.isfinite(d):
                size = (balance * cfg.max_risk_per_trade) / d
                notional = size * entry
                cap = cfg.max_leverage * balance
                if notional > cap:  # clip to leverage cap (reduces realized risk below max)
                    notional = cap
                    size = notional / entry
                if notional >= cfg.min_notional and size > 0:
                    entry_fee = notional * fee
                    balance -= entry_fee
                    stop = entry - d if side > 0 else entry + d
                    tp = entry + d * cfg.reward_factor if side > 0 else entry - d * cfg.reward_factor
                    pos = {"side": side, "entry_idx": i, "entry_price": entry, "size": size,
                           "stop": stop, "tp": tp, "fees": entry_fee, "funding": 0.0,
                           "lev": notional / balance if balance > 0 else 0.0}
        pending_side = 0

        # 2) manage open position (funding, intrabar exit, max hold)
        if pos is not None:
            side = pos["side"]; size = pos["size"]
            if fund_arr is not None:
                # +rate => longs pay (-), shorts earn (+)
                pos["funding"] += -side * size * c[i] * fund_arr[i]
            exit_price = None; reason = ""
            if side > 0:
                if lo[i] <= pos["stop"]:
                    exit_price, reason = pos["stop"], "stop"
                elif h[i] >= pos["tp"]:
                    exit_price, reason = pos["tp"], "tp"
            else:
                if h[i] >= pos["stop"]:
                    exit_price, reason = pos["stop"], "stop"
                elif lo[i] <= pos["tp"]:
                    exit_price, reason = pos["tp"], "tp"
            hit_level = exit_price is not None
            if not hit_level and (i - pos["entry_idx"]) >= cfg.max_hold_bars:
                exit_price, reason = c[i], "max_hold"
            if exit_price is not None:
                # next_open: defer stop/TP fills to the next bar's open (live realism).
                # max_hold and last-bar exits always fill now (at close/level).
                if (cfg.exit_execution == "next_open" and reason in ("stop", "tp")
                        and i + 1 < hi):
                    pending_exit = reason
                else:
                    fill = exit_price * (1 - slip) if side > 0 else exit_price * (1 + slip)
                    balance += close_position(pos, i, fill, reason)
                    cooldown_until = i + cfg.cooldown_bars
                    pos = None

        # 3) record equity (realized + unrealized mark-to-close)
        unreal = 0.0
        if pos is not None:
            unreal = pos["side"] * (c[i] - pos["entry_price"]) * pos["size"] + pos["funding"]
        equity_vals.append(balance + unreal)
        weight_vals.append(pos["lev"] if pos is not None else 0.0)
        equity_idx.append(ts[i])

        # 4) evaluate entry signal at this bar (for next-bar open), if flat
        if pos is None and i + 1 < hi and i >= cooldown_until:
            want_long = (cfg.direction in ("long", "both") and ind["upper"][i]
                         and ind["ulcer_ok"][i] and ind["trend_long"][i])
            want_short = (cfg.direction in ("short", "both") and ind["lower"][i]
                          and ind["ulcer_ok"][i] and ind["trend_short"][i])
            side = 0
            if want_long and not want_short:
                side = 1
            elif want_short and not want_long:
                side = -1
            elif want_long and want_short:
                side = 1  # rare same-bar both-band break: prefer long
            if side != 0:
                d = ind["atr"][i] * cfg.atr_volatility_factor
                if d > 0 and np.isfinite(d):
                    pending_side = side
                    pending_stop_distance = d  # noqa: F841 (used next iteration)

    idx = pd.DatetimeIndex(equity_idx)
    eq = pd.Series(equity_vals, index=idx, name="equity")
    w = pd.Series(weight_vals, index=idx, name="weight")
    return Result(trades=trades, equity=eq, stats=compute_stats(eq, trades, cfg), weights=w)


def target_weights(df: pd.DataFrame, cfg: Config) -> pd.Series:
    """Per-bar target leverage series for one symbol (0 when flat). The live
    signal reads the last value to decide the current target exposure."""
    return run(df, cfg).weights


def config_from_params(params: dict) -> Config:
    """Build an execution Config from a strategy params dict (DEFAULT_PARAMS /
    backtest_ref params). bps cost fields are converted to fractions."""
    return Config(
        kc_window=int(params.get("kc_window", 10)),
        kc_window_atr=int(params.get("kc_window_atr", 27)),
        kc_multiplier=float(params.get("kc_multiplier", 1.7536)),
        ulcer_window=int(params.get("ulcer_window", 39)),
        ulcer_threshold=float(params.get("ulcer_threshold", 6.1425)),
        atr_period=int(params.get("atr_period", 14)),
        atr_volatility_factor=float(params.get("atr_volatility_factor", 2.0)),
        reward_factor=float(params.get("reward_factor", 2.59)),
        max_risk_per_trade=float(params.get("max_risk_per_trade", 0.0397)),
        cooldown_bars=int(params.get("cooldown_bars", 24)),
        max_hold_bars=int(params.get("max_hold_bars", 1000)),
        fee_pct=float(params.get("fee_bps", 9.5)) / 1e4,
        slippage_pct=float(params.get("slippage_bps", 5.0)) / 1e4,
        initial_balance=float(params.get("initial_balance", 10_000.0)),
        max_leverage=float(params.get("max_leverage", 5.0)),
        direction="long",
        include_funding=bool(params.get("include_funding", True)),
        trend_filter=str(params.get("trend_filter", "ema_above_rising")),
        trend_window=int(params.get("trend_window", 100)),
        trend_slope_lookback=int(params.get("trend_slope_lookback", 24)),
        exit_execution=str(params.get("exit_execution", "next_open")),
    )



def compute_stats(equity: pd.Series, trades: list[Trade], cfg: Config) -> dict:
    ppy = 24 * 365
    rets = equity.pct_change().dropna()
    n = len(equity)
    years = n / ppy if n else 0.0
    final, init = float(equity.iloc[-1]), float(equity.iloc[0])
    total_return = final / init - 1 if init else 0.0
    cagr = (final / init) ** (1 / years) - 1 if years > 0 and final > 0 and init > 0 else 0.0
    std = rets.std()
    sharpe = (rets.mean() / std * np.sqrt(ppy)) if std and std > 0 else 0.0
    downside = rets[rets < 0].std()
    sortino = (rets.mean() / downside * np.sqrt(ppy)) if downside and downside > 0 else 0.0
    cummax = equity.cummax()
    dd = (equity / cummax - 1.0)
    max_dd = float(dd.min()) if len(dd) else 0.0
    calmar = (cagr / abs(max_dd)) if max_dd < 0 else 0.0
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": (len(wins) / len(trades) * 100) if trades else 0.0,
        "total_return_pct": total_return * 100,
        "cagr_pct": cagr * 100,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "max_drawdown_pct": max_dd * 100,
        "profit_factor": pf,
        "final_equity": final,
        "total_fees": sum(t.fees for t in trades),
        "total_funding": sum(t.funding for t in trades),
        "avg_bars_held": (np.mean([t.bars_held for t in trades]) if trades else 0.0),
        "long_trades": sum(1 for t in trades if t.side > 0),
        "short_trades": sum(1 for t in trades if t.side < 0),
    }
