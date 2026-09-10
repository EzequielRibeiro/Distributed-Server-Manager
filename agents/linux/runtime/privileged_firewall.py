#!/usr/bin/env python3
"""Bridge the unprivileged Linux Agent to the root-owned firewall reconciler."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any

import instance_runtime


_ALLOWED_PROTOCOLS = {"tcp", "udp"}
_ALLOWED_EXPOSURE = {"public", "private", "none"}


def _request_root() -> Path:
    return Path(instance_runtime.STATE_DIR) / "privileged-firewall"


def _token(value: Any, label: str = "instance_id", max_length: int = 191) -> str:
    text = str(value or "").strip()
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
    if not text or len(text) > max_length or any(ch not in allowed for ch in text):
        raise ValueError(f"invalid {label}")
    return text


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temp, 0o600)
    os.replace(temp, path)


def _hybrid_catalog_exposure(spec: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Recover exposure for pre-firewall Hybrid RuntimeSpecs from the local catalog.

    RuntimeSpecs created before managed firewall support can contain a valid
    catalog_runtime_policy and resolved ports while lacking network_exposure.
    Hybrid nodes have the canonical catalog locally, so use it only as a
    compatibility fallback. New RuntimeSpecs continue to use their persisted
    Controller-resolved policy.
    """
    if os.environ.get("CAPIVARA_AGENT_MODE") != "hybrid":
        return None

    root_value = str(os.environ.get("CAPIVARA_DSM_ROOT") or "").strip()
    if not root_value:
        return None

    game_id = _token(spec.get("game_id"), "game_id", 64).lower()
    runtime_id = _token(spec.get("runtime_id"), "runtime_id", 191)
    runtime_root = Path(root_value) / "catalog" / "v2" / "games" / game_id / "runtimes"
    if not runtime_root.is_dir():
        raise ValueError(f"catalog runtime directory is unavailable for {runtime_id}")

    definition: dict[str, Any] | None = None
    for path in sorted(runtime_root.glob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(value, dict) and str(value.get("id") or "").strip() == runtime_id:
            definition = value
            break

    if definition is None:
        raise ValueError(f"catalog runtime definition is unavailable for {runtime_id}")

    network = definition.get("network")
    raw_ports = network.get("ports") if isinstance(network, dict) else None
    if not isinstance(raw_ports, list):
        raise ValueError(f"catalog network ports are unavailable for {runtime_id}")

    exposure: list[dict[str, Any]] = []
    for raw in raw_ports:
        if not isinstance(raw, dict):
            raise ValueError(f"invalid catalog network port for {runtime_id}")
        exposure.append(
            {
                "name": raw.get("name"),
                "protocol": raw.get("protocol"),
                "exposure": raw.get("exposure", "none"),
            }
        )
    return exposure


def public_rules(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve explicit public Catalog exposure against reserved RuntimeSpec ports."""
    policy = spec.get("catalog_runtime_policy")
    if not isinstance(policy, dict):
        raise ValueError("catalog runtime policy is required for managed firewall")

    exposure = policy.get("network_exposure")
    if not isinstance(exposure, list):
        exposure = _hybrid_catalog_exposure(spec)
    if not isinstance(exposure, list):
        raise ValueError("catalog network exposure is required for managed firewall")

    ports = spec.get("ports")
    if not isinstance(ports, dict):
        raise ValueError("runtime ports are required for managed firewall")

    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in exposure:
        if not isinstance(raw, dict):
            raise ValueError("invalid catalog network exposure entry")

        name = _token(raw.get("name"), "port name", 64)
        protocol = str(raw.get("protocol") or "").strip().lower()
        scope = str(raw.get("exposure") or "none").strip().lower()

        if name in seen:
            raise ValueError(f"duplicate catalog network exposure: {name}")
        seen.add(name)

        if protocol not in _ALLOWED_PROTOCOLS:
            raise ValueError(f"invalid protocol for {name}")
        if scope not in _ALLOWED_EXPOSURE:
            raise ValueError(f"invalid exposure for {name}")

        binding = ports.get(name)
        if not isinstance(binding, dict):
            raise ValueError(f"resolved port is unavailable for {name}")

        try:
            port = int(binding.get("port"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid resolved port for {name}") from exc

        if not 1 <= port <= 65535:
            raise ValueError(f"resolved port outside TCP/UDP range for {name}")

        resolved_protocol = str(binding.get("protocol") or "").strip().lower()
        if resolved_protocol != protocol:
            raise ValueError(
                f"resolved protocol mismatch for {name}: "
                f"catalog={protocol} resolved={resolved_protocol}"
            )

        if scope == "public":
            result.append(
                {
                    "name": name,
                    "protocol": protocol,
                    "port": port,
                }
            )

    return result


def reconcile(spec: dict[str, Any], *, rules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    instance_id = _token(spec.get("instance_id"))
    desired = public_rules(spec) if rules is None else list(rules)

    root = _request_root()
    request_path = root / f"{instance_id}.request.json"
    result_path = root / f"{instance_id}.result.json"

    try:
        result_path.unlink()
    except FileNotFoundError:
        pass

    _atomic_json(
        request_path,
        {
            "schema_version": 1,
            "kind": "CapivaraPrivilegedFirewallRequest",
            "instance_id": instance_id,
            "rules": desired,
        },
    )

    default_unit = (
        "dsm-hybrid-agent-firewall@{instance_id}.service"
        if os.environ.get("CAPIVARA_AGENT_MODE") == "hybrid"
        else "capivara-agent-firewall@{instance_id}.service"
    )
    unit = os.environ.get("CAPIVARA_FIREWALL_UNIT_TEMPLATE", default_unit).format(
        instance_id=instance_id
    )

    completed = subprocess.run(
        ["systemctl", "start", unit, "--no-pager"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            (
                completed.stderr
                or completed.stdout
                or "privileged firewall helper failed"
            )[:2000]
        )

    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"privileged firewall returned no valid result: {exc}"
        ) from exc

    if not isinstance(result, dict) or result.get("status") != "completed":
        raise RuntimeError(
            str((result or {}).get("error") or "privileged firewall failed")[:2000]
        )

    operation = result.get("operation")
    if not isinstance(operation, dict):
        raise RuntimeError("privileged firewall returned invalid operation")

    return operation


def remove(spec: dict[str, Any]) -> dict[str, Any]:
    return reconcile(spec, rules=[])


__all__ = ["public_rules", "reconcile", "remove"]
