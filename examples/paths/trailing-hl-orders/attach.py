"""Register a trailing-order config and ensure the background monitor runs.

The skill invokes this via `mcp__wayfinder__run_script` immediately after the
user's entry order fires. It appends the config to library storage, registers
a runner job if needed, and prints a one-line confirmation back to Claude.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from controller import TrailingConfig  # noqa: E402
from state import add_config  # noqa: E402

RUNNER_JOB_NAME = "trailing-hl-monitor"
DEFAULT_INTERVAL = 300  # seconds


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Attach a trailing order to a Hyperliquid position"
    )
    parser.add_argument("--wallet", default="main")
    parser.add_argument("--coin", required=True)
    parser.add_argument("--side", required=True, choices=("long", "short"))
    parser.add_argument(
        "--kind",
        required=True,
        choices=("trailing_sl", "trailing_tp", "trailing_entry"),
    )
    parser.add_argument("--offset-pct", required=True, type=float)
    parser.add_argument("--mode", choices=("resting", "monitor"), default="resting")
    parser.add_argument("--activation-pct", type=float, default=None)
    parser.add_argument("--oco-peer", default=None)
    parser.add_argument(
        "--position-id",
        required=True,
        help="Unique tag for this position (entry cloid or user-supplied id).",
    )
    parser.add_argument(
        "--entry-size",
        type=float,
        default=None,
        help="Coin units to buy/sell on FIRE_ENTRY (trailing_entry only).",
    )
    parser.add_argument("--cadence", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument(
        "--skip-runner",
        action="store_true",
        help="Only write the config; don't register or start the runner.",
    )
    return parser.parse_args()


def _runner_cmd() -> list[str] | None:
    wf = shutil.which("wayfinder")
    if wf:
        return [wf]
    poetry = shutil.which("poetry")
    if poetry:
        return [poetry, "run", "wayfinder"]
    return None


def _runner(args: list[str]) -> tuple[int, str, str]:
    cmd = _runner_cmd()
    if cmd is None:
        return 127, "", "wayfinder CLI not found on PATH"
    proc = subprocess.run([*cmd, *args], capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def _ensure_runner_job(script_path: Path, interval: int) -> str:
    # Idempotent: start the daemon (no-op if already running), add the job if missing.
    code, out, err = _runner(["runner", "start"])
    if code not in (0,):
        return f"runner start returned {code}: {err.strip() or out.strip()}"

    code, out, err = _runner(["runner", "status"])
    already_registered = False
    if code == 0:
        try:
            parsed = json.loads(out)
            jobs = parsed.get("jobs") or parsed.get("result", {}).get("jobs") or []
            already_registered = any(
                str(j.get("name")) == RUNNER_JOB_NAME
                for j in jobs
                if isinstance(j, dict)
            )
        except json.JSONDecodeError:
            already_registered = RUNNER_JOB_NAME in out

    if already_registered:
        return "runner job already registered"

    code, out, err = _runner(
        [
            "runner",
            "add-job",
            "--name",
            RUNNER_JOB_NAME,
            "--type",
            "script",
            "--script-path",
            str(script_path),
            "--interval",
            str(interval),
        ]
    )
    if code != 0:
        return f"add-job failed ({code}): {err.strip() or out.strip()}"
    return "runner job registered"


def main() -> int:
    args = _parse_args()
    cfg = TrailingConfig(
        coin=args.coin,
        side=args.side,
        kind=args.kind,
        offset_pct=args.offset_pct,
        mode=args.mode,
        activation_pct=args.activation_pct,
        oco_peer=args.oco_peer,
    )
    key = add_config(args.wallet, args.coin, args.position_id, cfg)
    # Entry-size metadata lives alongside the config (only meaningful for trailing_entry).
    if args.entry_size is not None:
        from state import load_configs, save_configs

        all_cfgs = load_configs()
        entry = all_cfgs.get(key, {})
        entry["entry_size"] = args.entry_size
        all_cfgs[key] = entry
        save_configs(all_cfgs)

    monitor_path = Path(__file__).resolve().parent / "monitor.py"
    runner_note = (
        "skipped (--skip-runner)"
        if args.skip_runner
        else _ensure_runner_job(monitor_path, args.cadence)
    )

    print(
        json.dumps(
            {
                "status": "attached",
                "key": key,
                "config": {
                    "coin": args.coin,
                    "side": args.side,
                    "kind": args.kind,
                    "offset_pct": args.offset_pct,
                    "mode": args.mode,
                    "activation_pct": args.activation_pct,
                    "oco_peer": args.oco_peer,
                    "cadence_s": args.cadence,
                },
                "runner": runner_note,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
