from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from wayfinder_paths.core.config import CONFIG
from wayfinder_paths.packs.client import PacksApiClient, PacksApiError

_LOCKFILE_NAME = "packs.lock.json"
_STATE_FILENAME = "packs-heartbeat.json"
_DEFAULT_COOLDOWN = timedelta(hours=24)


@dataclass(frozen=True)
class PackHeartbeatResult:
    status: str
    reason: str
    attempted: int = 0
    sent: int = 0
    trigger: str = ""


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _find_wayfinder_dir(*, start: Path | None = None) -> Path | None:
    cur = (start or Path.cwd()).resolve()
    for parent in [cur, *cur.parents]:
        state_dir = parent / ".wayfinder"
        if (state_dir / _LOCKFILE_NAME).exists():
            return state_dir
    return None


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text()) or {}
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _has_explicit_packs_api_target() -> bool:
    system = CONFIG.get("system", {}) if isinstance(CONFIG, dict) else {}
    return bool(
        os.environ.get("WAYFINDER_PACKS_API_URL")
        or system.get("packs_api_base_url")
        or system.get("api_base_url")
    )


def _collect_installed_pack_heartbeats(lock: dict[str, Any]) -> list[dict[str, str]]:
    packs = lock.get("packs")
    if not isinstance(packs, dict):
        return []

    heartbeats: list[dict[str, str]] = []
    for slug, entry in packs.items():
        if not isinstance(entry, dict):
            continue
        installation_id = str(entry.get("installation_id") or "").strip()
        heartbeat_token = str(entry.get("heartbeat_token") or "").strip()
        if not installation_id or not heartbeat_token:
            continue
        heartbeats.append(
            {
                "slug": str(slug).strip(),
                "installation_id": installation_id,
                "heartbeat_token": heartbeat_token,
                "status": "active",
            }
        )
    return heartbeats


def maybe_heartbeat_installed_packs(
    *,
    trigger: str,
    cwd: Path | None = None,
    cooldown: timedelta = _DEFAULT_COOLDOWN,
    client: PacksApiClient | None = None,
    now: datetime | None = None,
) -> PackHeartbeatResult:
    if not _has_explicit_packs_api_target():
        return PackHeartbeatResult(status="skipped", reason="packs_api_not_configured")

    state_dir = _find_wayfinder_dir(start=cwd)
    if state_dir is None:
        return PackHeartbeatResult(status="skipped", reason="lockfile_not_found")

    lock = _load_json(state_dir / _LOCKFILE_NAME)
    heartbeats = _collect_installed_pack_heartbeats(lock)
    if not heartbeats:
        return PackHeartbeatResult(status="skipped", reason="no_installations")

    current_time = now or _now_utc()
    state_path = state_dir / _STATE_FILENAME
    state = _load_json(state_path)
    last_success_at = _parse_timestamp(state.get("last_success_at"))
    if last_success_at and (current_time - last_success_at) < cooldown:
        return PackHeartbeatResult(
            status="skipped",
            reason="cooldown_active",
            attempted=len(heartbeats),
            trigger=trigger,
        )

    batch_client = client or PacksApiClient()
    try:
        response = batch_client.submit_batch_install_heartbeats(
            heartbeats=heartbeats,
            source=trigger,
        )
    except PacksApiError as exc:
        logger.debug("Installed-pack heartbeat skipped after API error: {}", exc)
        return PackHeartbeatResult(
            status="error",
            reason="request_failed",
            attempted=len(heartbeats),
            trigger=trigger,
        )

    results = response.get("results")
    sent = 0
    if isinstance(results, list):
        sent = sum(
            1
            for item in results
            if isinstance(item, dict) and item.get("status") == "recorded"
        )

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": "0.1",
                "last_success_at": current_time.isoformat(),
                "last_trigger": trigger,
                "attempted": len(heartbeats),
                "sent": sent,
            },
            indent=2,
        )
        + "\n"
    )
    return PackHeartbeatResult(
        status="recorded",
        reason="sent",
        attempted=len(heartbeats),
        sent=sent,
        trigger=trigger,
    )
