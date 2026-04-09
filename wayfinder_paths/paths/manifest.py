from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

import yaml
from packaging.version import InvalidVersion, Version


class PathManifestError(Exception):
    pass


_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SKILL_MAX_NAME_LENGTH = 64
_SKILL_MAX_DESCRIPTION_LENGTH = 1024
_SKILL_SOURCES = {"generated", "provided"}
_RUNTIME_MODES = {"thin", "embedded"}
_BOOTSTRAP_MODES = {"uv", "pipx", "venv"}
_DEFAULT_RUNTIME_PACKAGE = "wayfinder-paths"
_DEFAULT_RUNTIME_PYTHON = ">=3.12,<3.13"
_DEFAULT_BOOTSTRAP = "uv"
_DEFAULT_FALLBACK_BOOTSTRAP = "pipx"
_DEFAULT_API_KEY_ENV = "WAYFINDER_API_KEY"
_DEFAULT_CONFIG_PATH_ENV = "WAYFINDER_CONFIG_PATH"


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value


def _is_valid_version(version: str) -> bool:
    if not version:
        return False
    if len(version) > 32:
        return False
    try:
        Version(version)
        return True
    except InvalidVersion:
        return bool(_SEMVER_RE.fullmatch(version))


def _ensure_object(
    raw_obj: Any, *, name: str, required: bool = False
) -> dict[str, Any] | None:
    if raw_obj is None:
        if required:
            raise PathManifestError(f"{name} must be an object")
        return None
    if not isinstance(raw_obj, dict):
        raise PathManifestError(f"{name} must be an object")
    return raw_obj


def _parse_string_list(raw_obj: Any, *, name: str) -> list[str]:
    if raw_obj is None:
        return []
    if not isinstance(raw_obj, list):
        raise PathManifestError(f"{name} must be a list")
    values = [str(item).strip() for item in raw_obj if str(item).strip()]
    return values


def _parse_bool(raw_obj: Any, *, name: str) -> bool | None:
    if raw_obj is None:
        return None
    if not isinstance(raw_obj, bool):
        raise PathManifestError(f"{name} must be a boolean")
    return raw_obj


@dataclass(frozen=True)
class PathAppletConfig:
    build_dir: str
    manifest_path: str


@dataclass(frozen=True)
class PathSkillClaudeConfig:
    disable_model_invocation: bool | None
    allowed_tools: list[str]


@dataclass(frozen=True)
class PathSkillCodexConfig:
    allow_implicit_invocation: bool | None


@dataclass(frozen=True)
class PathSkillOpenClawConfig:
    user_invocable: bool | None
    disable_model_invocation: bool | None
    requires: dict[str, Any]
    install: list[dict[str, Any]]


@dataclass(frozen=True)
class PathSkillPortableConfig:
    python: str | None
    package: str | None


@dataclass(frozen=True)
class PathSkillRuntimeConfig:
    mode: str | None
    package: str | None
    version: str | None
    python: str | None
    component: str | None
    bootstrap: str | None
    fallback_bootstrap: str | None
    prefer_existing_runtime: bool | None
    require_api_key: bool | None
    api_key_env: str | None
    config_path_env: str | None


@dataclass(frozen=True)
class PathSkillConfig:
    enabled: bool
    source: str
    name: str
    description: str
    instructions_path: str | None
    claude: PathSkillClaudeConfig | None
    codex: PathSkillCodexConfig | None
    openclaw: PathSkillOpenClawConfig | None
    runtime: PathSkillRuntimeConfig | None
    portable: PathSkillPortableConfig | None
    uses_portable_alias: bool
    raw: dict[str, Any]


def _parse_claude_skill_config(raw_obj: Any) -> PathSkillClaudeConfig | None:
    obj = _ensure_object(raw_obj, name="wfpath.yaml skill.claude")
    if obj is None:
        return None
    return PathSkillClaudeConfig(
        disable_model_invocation=_parse_bool(
            obj.get("disable_model_invocation"),
            name="wfpath.yaml skill.claude.disable_model_invocation",
        ),
        allowed_tools=_parse_string_list(
            obj.get("allowed_tools"),
            name="wfpath.yaml skill.claude.allowed_tools",
        ),
    )


def _parse_codex_skill_config(raw_obj: Any) -> PathSkillCodexConfig | None:
    obj = _ensure_object(raw_obj, name="wfpath.yaml skill.codex")
    if obj is None:
        return None
    return PathSkillCodexConfig(
        allow_implicit_invocation=_parse_bool(
            obj.get("allow_implicit_invocation"),
            name="wfpath.yaml skill.codex.allow_implicit_invocation",
        )
    )


def _parse_openclaw_skill_config(raw_obj: Any) -> PathSkillOpenClawConfig | None:
    obj = _ensure_object(raw_obj, name="wfpath.yaml skill.openclaw")
    if obj is None:
        return None

    requires = (
        _ensure_object(
            obj.get("requires"),
            name="wfpath.yaml skill.openclaw.requires",
        )
        or {}
    )

    install_raw = obj.get("install") or []
    if not isinstance(install_raw, list):
        raise PathManifestError("wfpath.yaml skill.openclaw.install must be a list")
    install: list[dict[str, Any]] = []
    for idx, item in enumerate(install_raw):
        if not isinstance(item, dict):
            raise PathManifestError(
                f"wfpath.yaml skill.openclaw.install[{idx}] must be an object"
            )
        install.append(dict(item))

    return PathSkillOpenClawConfig(
        user_invocable=_parse_bool(
            obj.get("user_invocable"),
            name="wfpath.yaml skill.openclaw.user_invocable",
        ),
        disable_model_invocation=_parse_bool(
            obj.get("disable_model_invocation"),
            name="wfpath.yaml skill.openclaw.disable_model_invocation",
        ),
        requires=dict(requires),
        install=install,
    )


def _parse_portable_skill_config(raw_obj: Any) -> PathSkillPortableConfig | None:
    obj = _ensure_object(raw_obj, name="wfpath.yaml skill.portable")
    if obj is None:
        return None
    python = str(obj.get("python", "")).strip() or None
    package = str(obj.get("package", "")).strip() or None
    return PathSkillPortableConfig(python=python, package=package)


def _parse_runtime_skill_config(raw_obj: Any) -> PathSkillRuntimeConfig | None:
    obj = _ensure_object(raw_obj, name="wfpath.yaml skill.runtime")
    if obj is None:
        return None

    mode = str(obj.get("mode", "")).strip() or None
    if mode is not None and mode not in _RUNTIME_MODES:
        raise PathManifestError(
            "wfpath.yaml skill.runtime.mode must be one of: thin, embedded"
        )

    bootstrap = str(obj.get("bootstrap", "")).strip() or None
    if bootstrap is not None and bootstrap not in _BOOTSTRAP_MODES:
        raise PathManifestError(
            "wfpath.yaml skill.runtime.bootstrap must be one of: uv, pipx, venv"
        )

    fallback_bootstrap = str(obj.get("fallback_bootstrap", "")).strip() or None
    if fallback_bootstrap is not None and fallback_bootstrap not in _BOOTSTRAP_MODES:
        raise PathManifestError(
            "wfpath.yaml skill.runtime.fallback_bootstrap must be one of: uv, pipx, venv"
        )

    return PathSkillRuntimeConfig(
        mode=mode,
        package=str(obj.get("package", "")).strip() or None,
        version=str(obj.get("version", "")).strip() or None,
        python=str(obj.get("python", "")).strip() or None,
        component=str(obj.get("component", "")).strip() or None,
        bootstrap=bootstrap,
        fallback_bootstrap=fallback_bootstrap,
        prefer_existing_runtime=_parse_bool(
            obj.get("prefer_existing_runtime"),
            name="wfpath.yaml skill.runtime.prefer_existing_runtime",
        ),
        require_api_key=_parse_bool(
            obj.get("require_api_key"),
            name="wfpath.yaml skill.runtime.require_api_key",
        ),
        api_key_env=str(obj.get("api_key_env", "")).strip() or None,
        config_path_env=str(obj.get("config_path_env", "")).strip() or None,
    )


def _runtime_from_portable_config(
    portable: PathSkillPortableConfig | None,
) -> PathSkillRuntimeConfig | None:
    if portable is None:
        return None
    return PathSkillRuntimeConfig(
        mode="thin",
        package=portable.package,
        version=None,
        python=portable.python,
        component=None,
        bootstrap=None,
        fallback_bootstrap=None,
        prefer_existing_runtime=None,
        require_api_key=None,
        api_key_env=None,
        config_path_env=None,
    )


def _parse_skill_config(raw_obj: Any) -> PathSkillConfig | None:
    obj = _ensure_object(raw_obj, name="wfpath.yaml skill")
    if obj is None:
        return None

    enabled = _parse_bool(obj.get("enabled"), name="wfpath.yaml skill.enabled")
    enabled = bool(enabled)

    source = str(obj.get("source", "")).strip()
    name = str(obj.get("name", "")).strip()
    description = str(obj.get("description", "")).strip()
    instructions_path = str(obj.get("instructions", "")).strip() or None
    portable = _parse_portable_skill_config(obj.get("portable"))
    runtime = _parse_runtime_skill_config(obj.get("runtime"))
    uses_portable_alias = runtime is None and portable is not None
    if runtime is None:
        runtime = _runtime_from_portable_config(portable)

    if enabled:
        if source not in _SKILL_SOURCES:
            raise PathManifestError(
                "wfpath.yaml skill.source must be one of: generated, provided"
            )
        if not name:
            raise PathManifestError("wfpath.yaml skill.name is required")
        if len(name) > _SKILL_MAX_NAME_LENGTH or not _SKILL_NAME_RE.fullmatch(name):
            raise PathManifestError(
                "wfpath.yaml skill.name must be lowercase letters/numbers/hyphens and <= 64 chars"
            )
        if not description:
            raise PathManifestError("wfpath.yaml skill.description is required")
        if len(description) > _SKILL_MAX_DESCRIPTION_LENGTH:
            raise PathManifestError(
                "wfpath.yaml skill.description must be <= 1024 chars"
            )
        if source == "generated" and not instructions_path:
            raise PathManifestError(
                "wfpath.yaml skill.instructions is required for generated skills"
            )

    elif source and source not in _SKILL_SOURCES:
        raise PathManifestError(
            "wfpath.yaml skill.source must be one of: generated, provided"
        )

    return PathSkillConfig(
        enabled=enabled,
        source=source or "generated",
        name=name,
        description=description,
        instructions_path=instructions_path,
        claude=_parse_claude_skill_config(obj.get("claude")),
        codex=_parse_codex_skill_config(obj.get("codex")),
        openclaw=_parse_openclaw_skill_config(obj.get("openclaw")),
        runtime=runtime,
        portable=portable,
        uses_portable_alias=uses_portable_alias,
        raw=dict(obj),
    )


@dataclass(frozen=True)
class PathManifest:
    schema_version: str
    slug: str
    name: str
    version: str
    summary: str
    primary_kind: str
    tags: list[str]
    applet: PathAppletConfig | None
    skill: PathSkillConfig | None
    raw: dict[str, Any]

    @property
    def components(self) -> list[dict[str, Any]]:
        raw_components = self.raw.get("components")
        if not isinstance(raw_components, list):
            return []
        return [item for item in raw_components if isinstance(item, dict)]

    def resolve_component(self, component_id: str | None = None) -> dict[str, Any]:
        components = self.components
        if not components:
            raise PathManifestError("wfpath.yaml must define at least one component")

        if component_id is None:
            first = components[0]
            if not str(first.get("path") or "").strip():
                raise PathManifestError("wfpath.yaml first component is missing path")
            return first

        needle = str(component_id).strip()
        for component in components:
            if str(component.get("id") or "").strip() == needle:
                if not str(component.get("path") or "").strip():
                    raise PathManifestError(
                        f"wfpath.yaml component '{needle}' is missing path"
                    )
                return component

        raise PathManifestError(f"wfpath.yaml component not found: {needle}")

    def default_component_id(self) -> str:
        if self.skill and self.skill.runtime and self.skill.runtime.component:
            return self.skill.runtime.component

        component = self.resolve_component()
        component_id = str(component.get("id") or "").strip()
        if component_id:
            return component_id
        return "main"

    @staticmethod
    def load(path: Path) -> PathManifest:
        try:
            raw_obj = yaml.safe_load(path.read_text()) or {}
        except Exception as exc:
            raise PathManifestError(f"Failed to parse {path.name}") from exc

        if not isinstance(raw_obj, dict):
            raise PathManifestError(f"{path.name} must be an object")

        schema_version = str(raw_obj.get("schema_version", "")).strip() or "0.1"

        slug = str(raw_obj.get("slug", "")).strip()
        if not slug:
            raise PathManifestError("wfpath.yaml missing required field: slug")
        if _slugify(slug) != slug or not _SLUG_RE.fullmatch(slug):
            raise PathManifestError("wfpath.yaml slug must be URL-safe (slugified)")

        name = str(raw_obj.get("name", "")).strip()
        if not name:
            raise PathManifestError("wfpath.yaml missing required field: name")

        version = str(raw_obj.get("version", "")).strip()
        if not version:
            raise PathManifestError("wfpath.yaml missing required field: version")
        if not _is_valid_version(version):
            raise PathManifestError(
                "wfpath.yaml version must be a valid semver/PEP 440 version string"
            )

        summary = str(raw_obj.get("summary", "")).strip()
        primary_kind = str(raw_obj.get("primary_kind", "bundle")).strip() or "bundle"

        tags_raw = raw_obj.get("tags", []) or []
        if not isinstance(tags_raw, list):
            raise PathManifestError("wfpath.yaml tags must be a list")
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]

        applet_obj = raw_obj.get("applet") or None
        applet: PathAppletConfig | None = None
        if applet_obj is not None:
            if not isinstance(applet_obj, dict):
                raise PathManifestError("wfpath.yaml applet must be an object")
            build_dir = str(applet_obj.get("build_dir", "")).strip()
            if not build_dir:
                raise PathManifestError(
                    "wfpath.yaml applet.build_dir is required when applet is present"
                )
            manifest_path = str(
                applet_obj.get("manifest", "applet/applet.manifest.json")
            ).strip()
            applet = PathAppletConfig(build_dir=build_dir, manifest_path=manifest_path)

        skill = _parse_skill_config(raw_obj.get("skill"))

        return PathManifest(
            schema_version=schema_version,
            slug=slug,
            name=name,
            version=version,
            summary=summary,
            primary_kind=primary_kind,
            tags=tags,
            applet=applet,
            skill=skill,
            raw=raw_obj,
        )


def _package_version_or_default(package: str) -> str:
    try:
        return importlib_metadata.version(package)
    except importlib_metadata.PackageNotFoundError:
        return "0.0.0"


def resolve_skill_runtime(manifest: PathManifest) -> PathSkillRuntimeConfig:
    skill = manifest.skill
    runtime = skill.runtime if skill else None
    package = (
        runtime.package if runtime and runtime.package else _DEFAULT_RUNTIME_PACKAGE
    )
    return PathSkillRuntimeConfig(
        mode=runtime.mode if runtime and runtime.mode else "thin",
        package=package,
        version=runtime.version
        if runtime and runtime.version
        else _package_version_or_default(package),
        python=runtime.python
        if runtime and runtime.python
        else _DEFAULT_RUNTIME_PYTHON,
        component=runtime.component
        if runtime and runtime.component
        else manifest.default_component_id(),
        bootstrap=runtime.bootstrap
        if runtime and runtime.bootstrap
        else _DEFAULT_BOOTSTRAP,
        fallback_bootstrap=(
            runtime.fallback_bootstrap
            if runtime and runtime.fallback_bootstrap
            else _DEFAULT_FALLBACK_BOOTSTRAP
        ),
        prefer_existing_runtime=(
            runtime.prefer_existing_runtime
            if runtime and runtime.prefer_existing_runtime is not None
            else True
        ),
        require_api_key=(
            runtime.require_api_key
            if runtime and runtime.require_api_key is not None
            else False
        ),
        api_key_env=runtime.api_key_env
        if runtime and runtime.api_key_env
        else _DEFAULT_API_KEY_ENV,
        config_path_env=(
            runtime.config_path_env
            if runtime and runtime.config_path_env
            else _DEFAULT_CONFIG_PATH_ENV
        ),
    )
