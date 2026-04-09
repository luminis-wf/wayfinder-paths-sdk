from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from wayfinder_paths.paths.manifest import PathManifest, PathManifestError
from wayfinder_paths.paths.renderer import PathSkillRenderError, render_skill_exports


class PathFormatError(Exception):
    pass


@dataclass(frozen=True)
class PathFormatReport:
    changed_files: list[str]


def _write_if_changed(path: Path, content: str) -> bool:
    normalized = content.rstrip() + "\n"
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if current == normalized:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalized, encoding="utf-8")
    return True


def _skill_dict(manifest: PathManifest) -> dict[str, Any] | None:
    skill = manifest.skill
    if not skill:
        return None

    data: dict[str, Any] = {
        "enabled": skill.enabled,
        "source": skill.source,
    }
    if skill.enabled:
        data["name"] = skill.name
        data["description"] = skill.description
        if skill.source == "generated" and skill.instructions_path:
            data["instructions"] = skill.instructions_path

    if skill.claude:
        claude: dict[str, Any] = {}
        if skill.claude.disable_model_invocation is not None:
            claude["disable_model_invocation"] = skill.claude.disable_model_invocation
        if skill.claude.allowed_tools:
            claude["allowed_tools"] = skill.claude.allowed_tools
        if claude:
            data["claude"] = claude

    if skill.codex:
        codex: dict[str, Any] = {}
        if skill.codex.allow_implicit_invocation is not None:
            codex["allow_implicit_invocation"] = skill.codex.allow_implicit_invocation
        if codex:
            data["codex"] = codex

    if skill.openclaw:
        openclaw: dict[str, Any] = {}
        if skill.openclaw.user_invocable is not None:
            openclaw["user_invocable"] = skill.openclaw.user_invocable
        if skill.openclaw.disable_model_invocation is not None:
            openclaw["disable_model_invocation"] = (
                skill.openclaw.disable_model_invocation
            )
        if skill.openclaw.requires:
            openclaw["requires"] = skill.openclaw.requires
        if skill.openclaw.install:
            openclaw["install"] = skill.openclaw.install
        if openclaw:
            data["openclaw"] = openclaw

    if skill.runtime:
        runtime: dict[str, Any] = {}
        if skill.runtime.mode:
            runtime["mode"] = skill.runtime.mode
        if skill.runtime.package:
            runtime["package"] = skill.runtime.package
        if skill.runtime.version:
            runtime["version"] = skill.runtime.version
        if skill.runtime.python:
            runtime["python"] = skill.runtime.python
        if skill.runtime.component:
            runtime["component"] = skill.runtime.component
        if skill.runtime.bootstrap:
            runtime["bootstrap"] = skill.runtime.bootstrap
        if skill.runtime.fallback_bootstrap:
            runtime["fallback_bootstrap"] = skill.runtime.fallback_bootstrap
        if skill.runtime.prefer_existing_runtime is not None:
            runtime["prefer_existing_runtime"] = skill.runtime.prefer_existing_runtime
        if skill.runtime.require_api_key is not None:
            runtime["require_api_key"] = skill.runtime.require_api_key
        if skill.runtime.api_key_env:
            runtime["api_key_env"] = skill.runtime.api_key_env
        if skill.runtime.config_path_env:
            runtime["config_path_env"] = skill.runtime.config_path_env
        if runtime:
            data["runtime"] = runtime
    elif skill.portable:
        portable: dict[str, Any] = {}
        if skill.portable.python:
            portable["python"] = skill.portable.python
        if skill.portable.package:
            portable["package"] = skill.portable.package
        if portable:
            data["portable"] = portable

    return data


def _manifest_dict(manifest: PathManifest) -> dict[str, Any]:
    raw = dict(manifest.raw)
    ordered: dict[str, Any] = {
        "schema_version": manifest.schema_version,
        "slug": manifest.slug,
        "name": manifest.name,
        "version": manifest.version,
    }
    if manifest.summary:
        ordered["summary"] = manifest.summary
    ordered["primary_kind"] = manifest.primary_kind
    ordered["tags"] = manifest.tags

    components = raw.get("components")
    if components is not None:
        ordered["components"] = components

    if manifest.applet:
        ordered["applet"] = {
            "build_dir": manifest.applet.build_dir,
            "manifest": manifest.applet.manifest_path,
        }

    skill = _skill_dict(manifest)
    if skill is not None:
        ordered["skill"] = skill

    for key, value in raw.items():
        if key not in ordered:
            ordered[key] = value

    return ordered


def format_path(*, path_dir: Path) -> PathFormatReport:
    path_dir = path_dir.resolve()
    manifest_path = path_dir / "wfpath.yaml"
    if not manifest_path.exists():
        raise PathFormatError(f"Missing wfpath.yaml in {path_dir}")

    try:
        manifest = PathManifest.load(manifest_path)
    except PathManifestError as exc:
        raise PathFormatError(str(exc)) from exc

    changed: list[str] = []

    manifest_text = yaml.safe_dump(
        _manifest_dict(manifest),
        sort_keys=False,
        allow_unicode=False,
    )
    if _write_if_changed(manifest_path, manifest_text):
        changed.append("wfpath.yaml")

    if manifest.applet:
        applet_manifest_path = path_dir / manifest.applet.manifest_path
        if applet_manifest_path.exists():
            parsed = json.loads(applet_manifest_path.read_text(encoding="utf-8"))
            formatted = json.dumps(parsed, indent=2, sort_keys=False) + "\n"
            if _write_if_changed(applet_manifest_path, formatted):
                changed.append(manifest.applet.manifest_path)

    try:
        render_report = render_skill_exports(path_dir=path_dir)
    except PathSkillRenderError as exc:
        raise PathFormatError(str(exc)) from exc
    changed.extend(render_report.written_files)

    return PathFormatReport(changed_files=sorted(set(changed)))
