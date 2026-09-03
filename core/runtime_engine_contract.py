"""Canonical Runtime/Engine contract for Capivara DSM.

P0-A deliberately separates logical runtime identity from the execution engine.
Installation policy remains outside this module and is handled by later stages.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

CONTRACT_VERSION = 1
KIND = "RuntimeEngineContract"
SUPPORTED_ENGINE_KINDS = {"java", "native", "launcher"}


class RuntimeEngineContractError(ValueError):
    """Raised when a canonical runtime/engine contract is invalid."""


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RuntimeEngineContractError(f"{field} is required")
    return text


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value:
        raise RuntimeEngineContractError(f"{field} must be a non-empty list")
    result = [str(item).strip().lower() for item in value if str(item).strip()]
    if not result:
        raise RuntimeEngineContractError(f"{field} must be a non-empty list")
    return result


def validate_runtime_engine_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a defensive copy of a canonical contract."""
    if not isinstance(contract, Mapping):
        raise RuntimeEngineContractError("contract must be an object")
    if contract.get("contract_version") != CONTRACT_VERSION:
        raise RuntimeEngineContractError("unsupported contract_version")
    if contract.get("kind") != KIND:
        raise RuntimeEngineContractError("kind must be RuntimeEngineContract")

    runtime = contract.get("runtime")
    engine = contract.get("engine")
    if not isinstance(runtime, Mapping):
        raise RuntimeEngineContractError("runtime must be an object")
    if not isinstance(engine, Mapping):
        raise RuntimeEngineContractError("engine must be an object")

    for field in ("id", "game", "edition", "variant"):
        _text(runtime.get(field), f"runtime.{field}")

    version = runtime.get("version")
    if not isinstance(version, Mapping):
        raise RuntimeEngineContractError("runtime.version must be an object")
    strategy = _text(version.get("strategy"), "runtime.version.strategy").lower()
    if strategy not in {"static", "dynamic"}:
        raise RuntimeEngineContractError("runtime.version.strategy must be static or dynamic")

    _text(engine.get("id"), "engine.id")
    engine_kind = _text(engine.get("kind"), "engine.kind").lower()
    if engine_kind not in SUPPORTED_ENGINE_KINDS:
        raise RuntimeEngineContractError("unsupported engine.kind")

    requirements = engine.get("requirements")
    if not isinstance(requirements, Mapping):
        raise RuntimeEngineContractError("engine.requirements must be an object")
    _string_list(requirements.get("os"), "engine.requirements.os")
    _string_list(requirements.get("architectures"), "engine.requirements.architectures")

    launch = contract.get("launch")
    if not isinstance(launch, Mapping):
        raise RuntimeEngineContractError("launch must be an object")
    _text(launch.get("executable"), "launch.executable")

    # Canonical launch/install semantics must not require an OS-specific absolute
    # installation directory. P0-B will resolve physical layout later.
    if "directory" in contract or "installation" in contract:
        raise RuntimeEngineContractError(
            "installation layout is not part of the canonical Runtime/Engine contract"
        )

    return deepcopy(dict(contract))


def canonical_from_runtime_v2(runtime_v2: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize a legacy Catalog v2 RuntimeDefinition into the P0-A contract.

    The legacy absolute ``installation.directory`` is intentionally not copied:
    it is physical placement information and therefore belongs to P0-B.
    ``artifact.provider`` is preserved as artifact metadata and never promoted to
    an execution engine identity (for example Steam/SteamCMD remains an installer
    concern, while the resulting server process can still be a native engine).
    """
    if not isinstance(runtime_v2, Mapping):
        raise RuntimeEngineContractError("RuntimeDefinition v2 must be an object")
    if runtime_v2.get("kind") != "RuntimeDefinition" or runtime_v2.get("schema_version") != 2:
        raise RuntimeEngineContractError("expected RuntimeDefinition schema_version 2")

    process = runtime_v2.get("process") or {}
    requirements = runtime_v2.get("requirements") or {}
    version = runtime_v2.get("version") or {}
    artifact = runtime_v2.get("artifact") or {}

    legacy_engine = _text(process.get("engine"), "process.engine").lower()
    engine_kind = legacy_engine if legacy_engine in {"java", "native"} else "launcher"

    engine_requirements: dict[str, Any] = {
        "os": _string_list(requirements.get("os"), "requirements.os"),
        "architectures": _string_list(
            requirements.get("architectures"), "requirements.architectures"
        ),
    }
    if isinstance(requirements.get("java"), Mapping):
        engine_requirements["java"] = deepcopy(dict(requirements["java"]))

    canonical: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "kind": KIND,
        "runtime": {
            "id": _text(runtime_v2.get("id"), "id"),
            "game": _text(runtime_v2.get("game"), "game"),
            "edition": _text(runtime_v2.get("edition"), "edition"),
            "variant": _text(runtime_v2.get("variant"), "variant"),
            "version": {
                "strategy": _text(version.get("strategy"), "version.strategy").lower(),
                "resolver": version.get("resolver"),
                "value": version.get("value"),
                "build": version.get("build"),
            },
        },
        "engine": {
            "id": legacy_engine,
            "kind": engine_kind,
            "requirements": engine_requirements,
        },
        "launch": {
            "executable": _text(process.get("executable"), "process.executable"),
            "artifact_mode": process.get("artifact_mode", "executable"),
            "args": deepcopy(process.get("args", [])),
        },
        "artifact": deepcopy(dict(artifact)),
        "compatibility": {
            "source_kind": "RuntimeDefinition",
            "source_schema_version": 2,
        },
    }

    return validate_runtime_engine_contract(canonical)


def supports_agent(contract: Mapping[str, Any], *, os_name: str, architecture: str) -> bool:
    """Return whether an Agent platform can host the engine contract."""
    checked = validate_runtime_engine_contract(contract)
    requirements = checked["engine"]["requirements"]
    os_value = str(os_name).strip().lower()
    arch_value = str(architecture).strip().lower()
    return os_value in requirements["os"] and arch_value in requirements["architectures"]
