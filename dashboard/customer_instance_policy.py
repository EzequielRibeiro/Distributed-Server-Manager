#!/usr/bin/env python3
"""Universal policy model for the customer instance workspace.

Nothing in this module is game-specific. A contract exposes entitlements, a
runtime exposes capabilities, and the effective policy is the intersection of
both. UI visibility is only a convenience; these helpers are intended to be
used by Controller-side enforcement as well.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

INSTANCE_PERMISSIONS = frozenset({
    "instance.view",
    "instance.start",
    "instance.stop",
    "instance.restart",
    "instance.delete",
    "console.read",
    "console.execute",
    "files.read",
    "files.download",
    "files.upload",
    "files.edit",
    "files.delete",
    "files.move",
    "files.extract",
    "backup.read",
    "backup.create",
    "backup.download",
    "backup.restore",
    "backup.delete",
    "startup.read",
    "startup.write",
    "content.read",
    "content.install",
    "content.remove",
    "team.read",
    "team.manage",
    "contract.read",
    "contract.upgrade",
})

PERMISSION_PRESETS = {
    "viewer": frozenset({
        "instance.view", "console.read", "files.read", "files.download",
        "backup.read", "startup.read", "content.read", "team.read",
        "contract.read",
    }),
    "operator": frozenset({
        "instance.view", "instance.start", "instance.stop", "instance.restart",
        "console.read", "files.read", "files.download", "files.upload",
        "files.edit", "backup.read", "backup.create", "backup.download",
        "startup.read", "content.read", "content.install", "content.remove",
        "team.read", "contract.read",
    }),
    "manager": INSTANCE_PERMISSIONS,
}

FILE_ACTION_PERMISSION = {
    "list": "files.read",
    "read": "files.read",
    "download": "files.download",
    "upload": "files.upload",
    "edit": "files.edit",
    "delete": "files.delete",
    "move": "files.move",
    "rename": "files.move",
    "mkdir": "files.upload",
    "extract": "files.extract",
}

CONTENT_FEATURES = frozenset({"mods", "plugins", "workshop", "external_upload", "custom_runtime"})


@dataclass(frozen=True)
class EffectiveContentPolicy:
    modifications_allowed: bool
    mods_allowed: bool
    plugins_allowed: bool
    workshop_allowed: bool
    external_upload_allowed: bool
    custom_runtime_allowed: bool

    def as_dict(self) -> dict[str, bool]:
        return {
            "modifications_allowed": self.modifications_allowed,
            "mods_allowed": self.mods_allowed,
            "plugins_allowed": self.plugins_allowed,
            "workshop_allowed": self.workshop_allowed,
            "external_upload_allowed": self.external_upload_allowed,
            "custom_runtime_allowed": self.custom_runtime_allowed,
        }


def permissions_for_profile(profile: str | None) -> set[str]:
    return set(PERMISSION_PRESETS.get(str(profile or "viewer").strip().lower(), PERMISSION_PRESETS["viewer"]))


def effective_permissions(profile: str | None, grants: dict[str, bool] | None = None) -> set[str]:
    result = permissions_for_profile(profile)
    for permission, allowed in (grants or {}).items():
        if permission not in INSTANCE_PERMISSIONS:
            continue
        if allowed:
            result.add(permission)
        else:
            result.discard(permission)
    return result


def require_permission(permissions: Iterable[str], permission: str) -> None:
    if permission not in INSTANCE_PERMISSIONS:
        raise ValueError("unknown instance permission")
    if permission not in set(permissions):
        raise PermissionError(f"{permission} permission required")


def effective_content_policy(
    contract_entitlements: dict[str, Any] | None,
    runtime_capabilities: dict[str, Any] | None,
) -> EffectiveContentPolicy:
    entitlement = contract_entitlements or {}
    capability = runtime_capabilities or {}

    def enabled(feature: str, *, entitlement_default: bool = False) -> bool:
        contract_value = bool(entitlement.get(feature, entitlement_default))
        runtime_value = bool(capability.get(feature, False))
        return contract_value and runtime_value

    mods = enabled("mods")
    plugins = enabled("plugins")
    workshop = enabled("workshop")
    external = enabled("external_upload", entitlement_default=True)
    custom_runtime = enabled("custom_runtime")
    modifications = bool(mods or plugins or workshop)
    return EffectiveContentPolicy(
        modifications_allowed=modifications,
        mods_allowed=mods,
        plugins_allowed=plugins,
        workshop_allowed=workshop,
        external_upload_allowed=external,
        custom_runtime_allowed=custom_runtime,
    )


def content_ui_sections(policy: EffectiveContentPolicy) -> list[str]:
    sections: list[str] = []
    if policy.mods_allowed:
        sections.append("mods")
    if policy.plugins_allowed:
        sections.append("plugins")
    if policy.workshop_allowed:
        sections.append("workshop")
    return sections


def validate_startup_values(
    values: dict[str, Any] | None,
    declaration: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate customer-editable startup values against catalog declaration.

    The browser never supplies a raw command line. Every key must be declared
    by the runtime and marked customer_editable. Contract-owned CPU/RAM/storage
    therefore cannot be overridden by crafting a direct request.
    """
    supplied = values if isinstance(values, dict) else {}
    declared = declaration if isinstance(declaration, dict) else {}
    normalized: dict[str, Any] = {}
    for key, value in supplied.items():
        spec = declared.get(key)
        if not isinstance(spec, dict) or not bool(spec.get("customer_editable")):
            raise PermissionError(f"startup parameter is not customer editable: {key}")
        kind = str(spec.get("type") or "string").lower()
        if kind == "select":
            allowed = list(spec.get("allowed") or [])
            if value not in allowed:
                raise ValueError(f"invalid value for startup parameter: {key}")
        elif kind == "integer":
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"startup parameter must be an integer: {key}") from exc
            if spec.get("min") is not None and value < int(spec["min"]):
                raise ValueError(f"startup parameter below minimum: {key}")
            if spec.get("max") is not None and value > int(spec["max"]):
                raise ValueError(f"startup parameter above maximum: {key}")
        elif kind == "boolean":
            value = bool(value)
        elif kind == "string":
            value = str(value)
            max_length = int(spec.get("max_length") or 256)
            if len(value) > max_length:
                raise ValueError(f"startup parameter too long: {key}")
        else:
            raise ValueError(f"unsupported startup parameter type: {kind}")
        normalized[str(key)] = value
    return normalized


def normalized_instance_relative_path(value: str) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    path = PurePosixPath(raw or ".")
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path must stay inside the instance")
    return path.as_posix()


def enforce_content_upload(
    relative_path: str,
    *,
    policy: EffectiveContentPolicy,
    runtime_rules: dict[str, Any] | None = None,
) -> None:
    """Reject content/runtime bypasses in File Manager operations.

    Runtime rules describe managed/protected paths. This is deliberately
    declarative so DayZ Workshop folders, Minecraft plugin directories and any
    future game can use the same guard.
    """
    path = normalized_instance_relative_path(relative_path).lower()
    rules = runtime_rules if isinstance(runtime_rules, dict) else {}
    protected = [str(item).strip("/").lower() for item in rules.get("protected_paths", []) if str(item).strip()]
    if any(path == item or path.startswith(item + "/") for item in protected):
        raise PermissionError("managed runtime path cannot be modified by customer")

    groups = (
        ("mod_paths", policy.mods_allowed, "mods are not allowed by this contract"),
        ("plugin_paths", policy.plugins_allowed, "plugins are not allowed by this contract"),
        ("workshop_paths", policy.workshop_allowed, "workshop content is not allowed by this contract"),
    )
    for rule_name, allowed, error in groups:
        candidates = [str(item).strip("/").lower() for item in rules.get(rule_name, []) if str(item).strip()]
        if candidates and any(path == item or path.startswith(item + "/") for item in candidates) and not allowed:
            raise PermissionError(error)

    executable_extensions = {str(x).lower() for x in rules.get("runtime_extensions", [])}
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in executable_extensions and not policy.custom_runtime_allowed:
        raise PermissionError("custom runtime artifacts are not allowed by this contract")
    if not policy.external_upload_allowed:
        raise PermissionError("external file upload is not allowed by this contract")


__all__ = [
    "CONTENT_FEATURES",
    "EffectiveContentPolicy",
    "FILE_ACTION_PERMISSION",
    "INSTANCE_PERMISSIONS",
    "PERMISSION_PRESETS",
    "content_ui_sections",
    "effective_content_policy",
    "effective_permissions",
    "enforce_content_upload",
    "normalized_instance_relative_path",
    "permissions_for_profile",
    "require_permission",
    "validate_startup_values",
]
