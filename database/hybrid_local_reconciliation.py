#!/usr/bin/env python3
"""Reconcile local host state after Controller -> Hybrid promotion.

Database identity/topology promotion is intentionally committed before this module
runs. Local reconciliation is idempotent and safe to retry: it updates only the
known Agent identity fields in ``config/agent.conf`` and refreshes the local
runtime inventory/heartbeat for the already-persisted Agent.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import socket
from pathlib import Path
from typing import Any, Callable

from agent_runtime_repository import AgentRuntimeRepository
from registry_repository import RegistryRepository


class HybridLocalReconciliationError(RuntimeError):
    """Raised when local Hybrid state cannot be reconciled safely."""


def _escape_shell_value(value: str) -> str:
    if "\n" in value or "\r" in value or '"' in value:
        raise HybridLocalReconciliationError("unsafe value for agent.conf")
    return value.replace("\\", "\\\\")


def _set_shell_value(text: str, key: str, value: str) -> str:
    rendered = f'{key}="{_escape_shell_value(value)}"'
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(rendered, text)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + rendered + "\n"


def reconcile_agent_conf(
    root: Path,
    *,
    node_id: str,
    agent_id: str,
    agent_name: str,
    agent_status: str,
    hostname: str,
) -> dict[str, Any]:
    """Atomically reconcile the local shell config without touching secrets."""
    config = root / "config" / "agent.conf"
    if not config.is_file():
        raise HybridLocalReconciliationError(f"agent.conf not found: {config}")

    original = config.read_text(encoding="utf-8")
    updated = original
    for key, value in (
        ("AGENT_ID", agent_id),
        ("AGENT_NAME", agent_name),
        ("AGENT_STATUS", agent_status),
        ("DSM_NODE_ID", node_id),
        ("DSM_NODE_ROLE", "hybrid"),
        ("HOSTNAME", hostname),
    ):
        updated = _set_shell_value(updated, key, str(value))

    changed = updated != original
    if changed:
        temporary = config.with_suffix(config.suffix + ".tmp")
        temporary.write_text(updated, encoding="utf-8")
        os.chmod(temporary, config.stat().st_mode & 0o777)
        os.replace(temporary, config)

    return {"config_path": str(config), "config_changed": changed}


def _default_inventory(root: Path, *, hostname: str) -> dict[str, Any]:
    disk = shutil.disk_usage(root if root.exists() else Path("/"))
    version_path = root / "version"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        version = "unknown"

    # Keep capability detection dependency-light here. The dedicated Agent runtime
    # may enrich this snapshot later; these primitives are enough for placement
    # health to distinguish a live local Hybrid Agent from an unreported Agent.
    return {
        "hostname": hostname,
        "os_name": platform.system().lower(),
        "architecture": platform.machine(),
        "capivara_version": version,
        "capabilities": {"native-linux": platform.system().lower() == "linux"},
        "cpu": {"logical_cores": os.cpu_count(), "machine": platform.machine()},
        "ram_total_bytes": None,
        "storage": {
            "root_total_bytes": disk.total,
            "root_free_bytes": disk.free,
        },
        "network": {},
    }


def reconcile_local_hybrid_runtime(
    repository: RegistryRepository,
    root: Path,
    *,
    node_id: str,
    agent_id: str,
    hostname: str | None = None,
    inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile config + runtime for an Agent already bound to this local Node."""
    hostname = str(hostname or socket.gethostname()).strip() or node_id
    repository.initialize()
    ph = repository.dialect.placeholder
    with repository.transaction() as session:
        row = session.execute(
            f"SELECT id,node_id,name,status FROM agents WHERE id={ph}",
            (agent_id,),
        ).fetchone()
        if row is None:
            raise HybridLocalReconciliationError(f"Agent {agent_id} does not exist")
        agent = dict(row)
        if str(agent["node_id"]) != node_id:
            raise HybridLocalReconciliationError(
                f"Agent {agent_id} belongs to node {agent['node_id']}"
            )

    config_result = reconcile_agent_conf(
        root,
        node_id=node_id,
        agent_id=agent_id,
        agent_name=str(agent["name"]),
        agent_status=str(agent["status"]),
        hostname=hostname,
    )

    runtime = AgentRuntimeRepository(repository.backend)
    facts = dict(inventory or _default_inventory(root, hostname=hostname))
    runtime.upsert_inventory(
        agent_id=agent_id,
        hostname=facts.get("hostname", hostname),
        os_name=facts.get("os_name"),
        architecture=facts.get("architecture"),
        capivara_version=facts.get("capivara_version"),
        address=facts.get("address"),
        fingerprint=facts.get("fingerprint"),
        capabilities=facts.get("capabilities", {}),
        cpu=facts.get("cpu", {}),
        ram_total_bytes=facts.get("ram_total_bytes"),
        storage=facts.get("storage", {}),
        network=facts.get("network", {}),
    )
    last_seen = runtime.heartbeat(agent_id)
    snapshot = runtime.snapshot(agent_id)

    return {
        **config_result,
        "runtime_reconciled": True,
        "health_status": snapshot.get("health_status"),
        "last_seen": last_seen,
    }


__all__ = [
    "HybridLocalReconciliationError",
    "reconcile_agent_conf",
    "reconcile_local_hybrid_runtime",
]
