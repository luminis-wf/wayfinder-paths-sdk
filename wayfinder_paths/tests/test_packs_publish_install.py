from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

from click.testing import CliRunner

from wayfinder_paths.packs.builder import PackBuilder
from wayfinder_paths.packs.cli import pack_cli
from wayfinder_paths.packs.scaffold import init_pack


def test_pack_publish_uploads_rendered_skill_exports_and_bond_metadata(
    tmp_path: Path, monkeypatch
):
    pack_dir = tmp_path / "skill-demo"
    init_pack(
        pack_dir=pack_dir,
        slug="skill-demo",
        primary_kind="monitor",
        with_applet=False,
        with_skill=True,
    )

    class FakePublishClient:
        calls: list[dict[str, object]] = []

        def __init__(self, *, api_base_url=None):
            self.api_base_url = api_base_url

        def publish(self, **kwargs):
            self.__class__.calls.append(kwargs)
            return {
                "pack": {"slug": "skill-demo"},
                "version": {"version": "0.1.0"},
                "ownerLinkRequired": True,
                "effectiveRiskTier": "interactive",
                "requiredInitialBond": "1000",
                "requiredUpgradePendingBond": "1000",
                "manageUrl": "https://app.example/packs/submissions/skill-demo?version=0.1.0",
                "packId": "0xabc123",
                "contractArgs": {
                    "packId": "0xabc123",
                    "bundleHash": "0xdef456",
                    "riskTier": "interactive",
                    "requiredInitialBondWei": "1000",
                    "requiredUpgradePendingBondWei": "1000",
                },
            }

    monkeypatch.setattr("wayfinder_paths.packs.cli.PacksApiClient", FakePublishClient)

    result = CliRunner().invoke(
        pack_cli,
        [
            "publish",
            "--path",
            str(pack_dir),
            "--out",
            str(pack_dir / "dist" / "bundle.zip"),
            "--api-url",
            "https://packs.example",
            "--bonded",
            "--owner-wallet",
            "0x1234567890AbcdEF1234567890aBcdef12345678",
            "--risk-tier",
            "interactive",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(FakePublishClient.calls) == 1
    call = FakePublishClient.calls[0]

    assert call["owner_wallet"] == "0x1234567890AbcdEF1234567890aBcdef12345678"
    assert call["bonded"] is True
    assert call["risk_tier"] == "interactive"
    assert call["source_path"] is not None
    assert Path(call["source_path"]).name == "source.zip"

    exports_manifest = call["exports_manifest"]
    skill_exports = call["skill_exports"]

    assert exports_manifest is not None
    assert exports_manifest["targets"] == ["claude", "codex", "openclaw", "portable"]
    assert set(skill_exports) == {"claude", "codex", "openclaw", "portable"}

    with ZipFile(io.BytesIO(skill_exports["claude"]), "r") as zf:
        names = set(zf.namelist())
    assert "skill/SKILL.md" in names

    with ZipFile(io.BytesIO(skill_exports["codex"]), "r") as zf:
        names = set(zf.namelist())
    assert "skill/agents/openai.yaml" in names

    assert "Link owner wallet and bond at:" in result.output
    assert "https://app.example/packs/submissions/skill-demo?version=0.1.0" in result.output
    assert "Effective risk tier: interactive" in result.output
    assert "Required initial bond: 1000" in result.output
    assert "Required upgrade pending bond: 1000" in result.output
    assert "Bond contract args:" in result.output


def test_pack_build_is_deterministic(tmp_path: Path):
    pack_dir = tmp_path / "deterministic-pack"
    init_pack(
        pack_dir=pack_dir,
        slug="deterministic-pack",
        primary_kind="monitor",
        with_applet=False,
        with_skill=True,
    )

    first = PackBuilder.build(
        pack_dir=pack_dir,
        out_path=pack_dir / "dist" / "bundle-a.zip",
    )
    second = PackBuilder.build(
        pack_dir=pack_dir,
        out_path=pack_dir / "dist" / "bundle-b.zip",
    )
    source_archive = PackBuilder.build_source_archive(
        pack_dir=pack_dir,
        out_path=pack_dir / "dist" / "source.zip",
    )

    assert first.bundle_sha256 == second.bundle_sha256
    assert first.bundle_path.read_bytes() == second.bundle_path.read_bytes()
    assert source_archive.exists()


def test_pack_publish_requires_owner_wallet_for_bonded(tmp_path: Path):
    pack_dir = tmp_path / "skill-demo"
    init_pack(
        pack_dir=pack_dir,
        slug="skill-demo",
        primary_kind="monitor",
        with_applet=False,
        with_skill=True,
    )

    result = CliRunner().invoke(
        pack_cli,
        [
            "publish",
            "--path",
            str(pack_dir),
            "--bonded",
        ],
    )

    assert result.exit_code != 0
    assert "--owner-wallet is required with --bonded" in result.output


def test_pack_install_requests_intent_and_submits_receipt(tmp_path: Path, monkeypatch):
    pack_dir = tmp_path / "install-demo"
    init_pack(
        pack_dir=pack_dir,
        slug="install-demo",
        primary_kind="monitor",
        with_applet=False,
        with_skill=True,
    )
    built = PackBuilder.build(
        pack_dir=pack_dir, out_path=pack_dir / "dist" / "bundle.zip"
    )

    class FakeInstallClient:
        install_intent_calls: list[dict[str, object]] = []
        receipt_calls: list[dict[str, object]] = []

        def __init__(self, *, api_base_url=None):
            self.api_base_url = api_base_url

        def get_pack(self, *, slug: str):
            return {
                "pack": {"slug": slug, "latest_version": "0.1.0"},
                "versions": [
                    {"version": "0.1.0", "bundle_sha256": built.bundle_sha256}
                ],
            }

        def get_pack_version(self, *, slug: str, version: str):
            return {
                "version": {"version": version, "bundle_sha256": built.bundle_sha256}
            }

        def create_install_intent(self, **kwargs):
            self.__class__.install_intent_calls.append(kwargs)
            expires_at = (datetime.now(UTC) + timedelta(hours=24)).isoformat()
            return {
                "intent": {
                    "intent_id": "intent-123",
                    "pack_slug": kwargs["slug"],
                    "version": kwargs["version"],
                    "bundle_sha256": built.bundle_sha256,
                    "issued_at": datetime.now(UTC).isoformat(),
                    "expires_at": expires_at,
                    "runtime": kwargs["runtime"],
                },
                "signature": "signed-intent",
            }

        def download_bundle(self, *, slug: str, version: str, out_path: Path):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(built.bundle_path.read_bytes())
            return out_path

        def submit_install_receipt(self, **kwargs):
            self.__class__.receipt_calls.append(kwargs)
            return {
                "status": "recorded",
                "installation_id": "install-123",
                "heartbeat_token": "heartbeat-secret",
            }

        def submit_install_heartbeat(self, **kwargs):
            return {"status": "recorded", "installation_id": kwargs["installation_id"]}

    monkeypatch.setattr("wayfinder_paths.packs.cli.PacksApiClient", FakeInstallClient)

    install_root = tmp_path / ".wayfinder" / "packs"
    result = CliRunner().invoke(
        pack_cli,
        [
            "install",
            "--slug",
            "install-demo",
            "--version",
            "0.1.0",
            "--dir",
            str(install_root),
            "--api-url",
            "https://packs.example",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(FakeInstallClient.install_intent_calls) == 1
    assert len(FakeInstallClient.receipt_calls) == 1

    output = json.loads(result.output)
    assert output["result"]["install_intent_id"] == "intent-123"
    assert output["result"]["installation_id"] == "install-123"
    assert output["result"]["heartbeat_enabled"] is True
    assert output["result"]["verified_install"] is True
    assert output["result"]["warnings"] == []

    receipt = FakeInstallClient.receipt_calls[0]
    assert receipt["runtime"] == "sdk-cli"
    assert receipt["extracted_files"] > 0
    assert receipt["install_path"].endswith("install-demo/0.1.0")

    lock = json.loads((tmp_path / ".wayfinder" / "packs.lock.json").read_text())
    assert lock["packs"]["install-demo"]["installation_id"] == "install-123"
    assert lock["packs"]["install-demo"]["heartbeat_token"] == "heartbeat-secret"


def test_pack_heartbeat_install_uses_lockfile_credentials(tmp_path: Path, monkeypatch):
    lock_dir = tmp_path / ".wayfinder"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / "packs.lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "schemaVersion": "0.1",
                "packs": {
                    "install-demo": {
                        "version": "0.1.0",
                        "installation_id": "install-123",
                        "heartbeat_token": "heartbeat-secret",
                    }
                },
            }
        )
    )

    class FakeHeartbeatClient:
        heartbeat_calls: list[dict[str, object]] = []

        def __init__(self, *, api_base_url=None):
            self.api_base_url = api_base_url

        def submit_install_heartbeat(self, **kwargs):
            self.__class__.heartbeat_calls.append(kwargs)
            return {"status": "recorded", "installation_id": kwargs["installation_id"]}

    monkeypatch.setattr("wayfinder_paths.packs.cli.PacksApiClient", FakeHeartbeatClient)

    result = CliRunner().invoke(
        pack_cli,
        [
            "heartbeat-install",
            "--slug",
            "install-demo",
            "--dir",
            str(tmp_path / ".wayfinder" / "packs"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert FakeHeartbeatClient.heartbeat_calls == [
        {
            "installation_id": "install-123",
            "heartbeat_token": "heartbeat-secret",
            "status": "active",
        }
    ]
