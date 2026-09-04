#!/usr/bin/env python3
"""Reconcile local host state for Controller <-> Hybrid transitions."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
AGENT_RUNTIME_DIR = ROOT_DIR / "agents" / "linux" / "runtime"
if str(AGENT_RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_RUNTIME_DIR))

from capabilities import detect_capabilities
from host_telemetry import collect_host_telemetry
from network_inventory import collect_network_inventory
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


def _write_agent_conf(root: Path, values: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    config = root / "config" / "agent.conf"
    if not config.is_file():
        raise HybridLocalReconciliationError(f"agent.conf not found: {config}")

    metadata = config.stat()
    original = config.read_text(encoding="utf-8")
    updated = original
    for key, value in values:
        updated = _set_shell_value(updated, key, str(value))

    changed = updated != original
    if changed:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{config.name}.", dir=str(config.parent))
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(updated)
                handle.flush()
                os.fsync(handle.fileno())
            os.chown(temporary, metadata.st_uid, metadata.st_gid)
            os.chmod(temporary, metadata.st_mode & 0o777)
            os.replace(temporary, config)
        finally:
            if temporary.exists():
                temporary.unlink()

    return {"config_path": str(config), "config_changed": changed}


def reconcile_agent_conf(
    root: Path,
    *,
    node_id: str,
    agent_id: str,
    agent_name: str,
    agent_status: str,
    hostname: str,
) -> dict[str, Any]:
    """Atomically reconcile local Hybrid identity without touching secrets."""
    return _write_agent_conf(
        root,
        (
            ("AGENT_ID", agent_id),
            ("AGENT_NAME", agent_name),
            ("AGENT_STATUS", agent_status),
            ("DSM_NODE_ID", node_id),
            ("DSM_NODE_ROLE", "hybrid"),
            ("HOSTNAME", hostname),
        ),
    )


def reconcile_local_controller_runtime(
    root: Path,
    *,
    node_id: str,
    hostname: str | None = None,
) -> dict[str, Any]:
    """Return a former Hybrid host to Controller-only local configuration.

    Secrets and the Controller/Node identity are preserved. Clearing AGENT_ID and
    setting DSM_NODE_ROLE=controller makes the persistent Hybrid worker become
    inactive on its next cycle instead of continuing to heartbeat a decommissioned
    local Agent.
    """
    effective_hostname = str(hostname or socket.gethostname()).strip() or node_id
    result = _write_agent_conf(
        root,
        (
            ("AGENT_ID", ""),
            ("AGENT_NAME", ""),
            ("AGENT_STATUS", "pending"),
            ("DSM_NODE_ID", node_id),
            ("DSM_NODE_ROLE", "controller"),
            ("HOSTNAME", effective_hostname),
        ),
    )
    return {**result, "runtime_reconciled": True, "role": "controller"}


def _memory_total_bytes() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _hybrid_capabilities(root: Path) -> dict[str, Any]:
    """Detect capabilities using a writable Hybrid-owned SteamCMD state root."""
    state_root = root / "runtime" / "state" / "hybrid-agent"
    try:
        state_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    previous = os.environ.get("CAPIVARA_AGENT_STATE_DIR")
    os.environ["CAPIVARA_AGENT_STATE_DIR"] = str(state_root)
    try:
        capabilities = detect_capabilities()
    finally:
        if previous is None:
            os.environ.pop("CAPIVARA_AGENT_STATE_DIR", None)
        else:
            os.environ["CAPIVARA_AGENT_STATE_DIR"] = previous

    bundled_steamcmd = root / "tools" / "steamcmd" / "steamcmd.sh"
    if bundled_steamcmd.is_file() and not capabilities.get("steamcmd"):
        detail = capabilities.get("steamcmd_status")
        if not isinstance(detail, dict) or not detail.get("installed"):
            capabilities["steamcmd_status"] = {
                "schema_version": 2,
                "installed": True,
                "functional": True,
                "state": "ready",
                "path": str(bundled_steamcmd),
                "runtime_32bit": True,
                "missing_dependencies": [],
            }
            capabilities["steamcmd"] = True
    return capabilities


def _default_inventory(root: Path, *, hostname: str) -> dict[str, Any]:
    disk = shutil.disk_usage(root if root.exists() else Path("/"))
    version_path = root / "version"
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except OSError:
        version = "unknown"

    return {
        "hostname": hostname,
        "os_name": platform.system().lower(),
        "architecture": platform.machine(),
        "capivara_version": version,
        "capabilities": _hybrid_capabilities(root),
        "cpu": {"logical_cores": os.cpu_count(), "machine": platform.machine()},
        "ram_total_bytes": _memory_total_bytes(),
        "storage": {"root_total_bytes": disk.total, "root_free_bytes": disk.free},
        "network": collect_network_inventory(),
        "telemetry": collect_host_telemetry(),
    }


def _store_hybrid_telemetry(
    repository: RegistryRepository,
    agent_id: str,
    telemetry: dict[str, Any] | None,
) -> None:
    if not isinstance(telemetry, dict):
        return
    ph = repository.dialect.placeholder
    with repository.transaction() as session:
        row = session.execute(
            f"SELECT metadata_json FROM agents WHERE id={ph}",
            (agent_id,),
        ).fetchone()
        if row is None:
            return
        raw = row["metadata_json"]
        if isinstance(raw, dict):
            metadata = dict(raw)
        else:
            try:
                metadata = json.loads(raw or "{}")
            except (TypeError, ValueError):
                metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["telemetry"] = telemetry
        session.execute(
            f"UPDATE agents SET metadata_json={ph} WHERE id={ph}",
            (json.dumps(metadata, sort_keys=True, separators=(",", ":")), agent_id),
        )


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
    _store_hybrid_telemetry(repository, agent_id, facts.get("telemetry"))
    last_seen = runtime.heartbeat(agent_id)
    snapshot = runtime.snapshot(agent_id)

    return {
        **config_result,
        "runtime_reconciled": True,
        "health_status": snapshot.get("health_status"),
        "last_seen": last_seen,
        "capabilities": snapshot.get("capabilities", {}),
        "telemetry": facts.get("telemetry", {}),
        "port_ranges": snapshot.get("port_ranges", []),
    }


__all__ = [
    "HybridLocalReconciliationError",
    "reconcile_agent_conf",
    "reconcile_local_controller_runtime",
    "reconcile_local_hybrid_runtime",
]
