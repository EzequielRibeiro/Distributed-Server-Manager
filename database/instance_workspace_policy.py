#!/usr/bin/env python3
"""Universal policy contract shared by Controller persistence and Dashboard."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

INSTANCE_PERMISSIONS = frozenset({
    "instance.view", "instance.start", "instance.stop", "instance.restart", "instance.delete",
    "console.read", "console.execute",
    "files.read", "files.download", "files.upload", "files.edit", "files.delete", "files.move", "files.extract",
    "backup.read", "backup.create", "backup.download", "backup.restore", "backup.delete",
    "startup.read", "startup.write",
    "content.read", "content.install", "content.remove",
    "team.read", "team.manage",
    "contract.read", "contract.upgrade",
    "activity.read",
})

PERMISSION_PRESETS = {
    "viewer": frozenset({
        "instance.view", "console.read", "files.read", "files.download", "backup.read",
        "startup.read", "content.read", "team.read", "contract.read", "activity.read",
    }),
    "operator": frozenset({
        "instance.view", "instance.start", "instance.stop", "instance.restart", "console.read",
        "files.read", "files.download", "files.upload", "files.edit", "backup.read", "backup.create",
        "backup.download", "startup.read", "content.read", "content.install", "content.remove",
        "team.read", "contract.read", "activity.read",
    }),
    "manager": INSTANCE_PERMISSIONS,
}

FILE_ACTION_PERMISSION = {
    "list": "files.read", "read": "files.read", "download": "files.download",
    "upload": "files.upload", "edit": "files.edit", "delete": "files.delete",
    "move": "files.move", "rename": "files.move", "mkdir": "files.upload", "extract": "files.extract",
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


def effective_content_policy(contract_entitlements: dict[str, Any] | None, runtime_capabilities: dict[str, Any] | None) -> EffectiveContentPolicy:
    entitlement = contract_entitlements or {}; capability = runtime_capabilities or {}
    def enabled(feature: str, entitlement_default: bool = False) -> bool:
        return bool(entitlement.get(feature, entitlement_default)) and bool(capability.get(feature, False))
    mods = enabled("mods"); plugins = enabled("plugins"); workshop = enabled("workshop")
    return EffectiveContentPolicy(
        modifications_allowed=bool(mods or plugins or workshop),
        mods_allowed=mods,
        plugins_allowed=plugins,
        workshop_allowed=workshop,
        external_upload_allowed=enabled("external_upload", True),
        custom_runtime_allowed=enabled("custom_runtime"),
    )


def content_ui_sections(policy: EffectiveContentPolicy) -> list[str]:
    result = []
    if policy.mods_allowed: result.append("mods")
    if policy.plugins_allowed: result.append("plugins")
    if policy.workshop_allowed: result.append("workshop")
    return result


def validate_startup_values(values: dict[str, Any] | None, declaration: dict[str, Any] | None) -> dict[str, Any]:
    supplied = values if isinstance(values, dict) else {}; declared = declaration if isinstance(declaration, dict) else {}; normalized = {}
    for key, value in supplied.items():
        spec = declared.get(key)
        if not isinstance(spec, dict) or not bool(spec.get("customer_editable")):
            raise PermissionError(f"startup parameter is not customer editable: {key}")
        kind = str(spec.get("type") or "string").lower()
        if kind == "select":
            if value not in list(spec.get("allowed") or []): raise ValueError(f"invalid value for startup parameter: {key}")
        elif kind == "integer":
            try: value = int(value)
            except (TypeError, ValueError) as exc: raise ValueError(f"startup parameter must be an integer: {key}") from exc
            if spec.get("min") is not None and value < int(spec["min"]): raise ValueError(f"startup parameter below minimum: {key}")
            if spec.get("max") is not None and value > int(spec["max"]): raise ValueError(f"startup parameter above maximum: {key}")
        elif kind == "boolean": value = bool(value)
        elif kind == "string":
            value = str(value)
            if len(value) > int(spec.get("max_length") or 256): raise ValueError(f"startup parameter too long: {key}")
        else: raise ValueError(f"unsupported startup parameter type: {kind}")
        normalized[str(key)] = value
    return normalized


def normalized_instance_relative_path(value: str) -> str:
    path = PurePosixPath(str(value or "").replace("\\", "/").strip() or ".")
    if path.is_absolute() or ".." in path.parts: raise ValueError("path must stay inside the instance")
    return path.as_posix()


def enforce_content_upload(relative_path: str, *, policy: EffectiveContentPolicy, runtime_rules: dict[str, Any] | None = None) -> None:
    path = normalized_instance_relative_path(relative_path).lower(); rules = runtime_rules if isinstance(runtime_rules, dict) else {}
    protected = [str(item).strip("/").lower() for item in rules.get("protected_paths", []) if str(item).strip()]
    if any(path == item or path.startswith(item + "/") for item in protected): raise PermissionError("managed runtime path cannot be modified by customer")
    for rule_name, allowed, error in (
        ("mod_paths", policy.mods_allowed, "mods are not allowed by this contract"),
        ("plugin_paths", policy.plugins_allowed, "plugins are not allowed by this contract"),
        ("workshop_paths", policy.workshop_allowed, "workshop content is not allowed by this contract"),
    ):
        candidates = [str(item).strip("/").lower() for item in rules.get(rule_name, []) if str(item).strip()]
        if candidates and any(path == item or path.startswith(item + "/") for item in candidates) and not allowed: raise PermissionError(error)
    if PurePosixPath(path).suffix.lower() in {str(x).lower() for x in rules.get("runtime_extensions", [])} and not policy.custom_runtime_allowed:
        raise PermissionError("custom runtime artifacts are not allowed by this contract")
    if not policy.external_upload_allowed: raise PermissionError("external file upload is not allowed by this contract")


__all__ = [
    "CONTENT_FEATURES", "EffectiveContentPolicy", "FILE_ACTION_PERMISSION", "INSTANCE_PERMISSIONS", "PERMISSION_PRESETS",
    "content_ui_sections", "effective_content_policy", "effective_permissions", "enforce_content_upload",
    "normalized_instance_relative_path", "permissions_for_profile", "require_permission", "validate_startup_values",
]
