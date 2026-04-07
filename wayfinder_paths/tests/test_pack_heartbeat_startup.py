from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wayfinder_paths.packs.heartbeat import maybe_heartbeat_installed_packs


def _write_lockfile(root: Path) -> None:
    state_dir = root / ".wayfinder"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "packs.lock.json").write_text(
        json.dumps(
            {
                "schemaVersion": "0.1",
                "packs": {
                    "demo-pack": {
                        "installation_id": "install-123",
                        "heartbeat_token": "heartbeat-secret",
                    }
                },
            }
        )
        + "\n"
    )


def test_maybe_heartbeat_installed_packs_sends_and_writes_state(
    tmp_path: Path, monkeypatch
) -> None:
    _write_lockfile(tmp_path)
    monkeypatch.setenv("WAYFINDER_PACKS_API_URL", "https://packs.example")

    class FakeClient:
        calls: list[dict[str, object]] = []

        def submit_batch_install_heartbeats(self, **kwargs):
            self.__class__.calls.append(kwargs)
            return {
                "results": [{"installation_id": "install-123", "status": "recorded"}]
            }

    now = datetime(2026, 4, 7, 12, 0, tzinfo=UTC)
    result = maybe_heartbeat_installed_packs(
        trigger="mcp-cli",
        cwd=tmp_path,
        client=FakeClient(),
        now=now,
    )

    assert result.status == "recorded"
    assert result.sent == 1
    assert FakeClient.calls == [
        {
            "heartbeats": [
                {
                    "slug": "demo-pack",
                    "installation_id": "install-123",
                    "heartbeat_token": "heartbeat-secret",
                    "status": "active",
                }
            ],
            "source": "mcp-cli",
        }
    ]

    state = json.loads((tmp_path / ".wayfinder" / "packs-heartbeat.json").read_text())
    assert state["last_trigger"] == "mcp-cli"
    assert state["sent"] == 1


def test_maybe_heartbeat_installed_packs_respects_cooldown(
    tmp_path: Path, monkeypatch
) -> None:
    _write_lockfile(tmp_path)
    monkeypatch.setenv("WAYFINDER_PACKS_API_URL", "https://packs.example")
    state_path = tmp_path / ".wayfinder" / "packs-heartbeat.json"
    state_path.write_text(
        json.dumps(
            {
                "schemaVersion": "0.1",
                "last_success_at": datetime(2026, 4, 7, 10, 0, tzinfo=UTC).isoformat(),
                "last_trigger": "mcp-server",
            }
        )
        + "\n"
    )

    class FakeClient:
        def submit_batch_install_heartbeats(self, **kwargs):
            raise AssertionError("batch heartbeat should not be called during cooldown")

    result = maybe_heartbeat_installed_packs(
        trigger="mcp-cli",
        cwd=tmp_path,
        client=FakeClient(),
        now=datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
        cooldown=timedelta(hours=24),
    )

    assert result.status == "skipped"
    assert result.reason == "cooldown_active"
