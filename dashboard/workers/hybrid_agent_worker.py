#!/usr/bin/env python3
"""Persistent local Hybrid Agent inventory/heartbeat worker."""

from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("DSM_ROOT", Path(__file__).resolve().parents[2])).resolve()
DATABASE = ROOT / "database"
DASHBOARD = ROOT / "dashboard"
for path in (ROOT, DATABASE, DASHBOARD):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from hybrid_console_client import process_hybrid_console_cycle
from hybrid_configuration_client import process_hybrid_configuration_cycle
from hybrid_game_data_client import process_hybrid_game_data_cycle
from hybrid_instance_provisioning_client import process_hybrid_instance_provisioning_cycle
from hybrid_instance_files_client import process_hybrid_instance_files_cycle
from hybrid_instance_runtime_client import process_hybrid_instance_runtime_cycle
from hybrid_runtime_reconciliation_client import process_hybrid_runtime_reconciliation_cycle
from hybrid_local_reconciliation import reconcile_local_hybrid_runtime
from registry_repository import RegistryRepository
from runtime_backend import backend_from_environment

INTERVAL_SECONDS = max(
    10,
    int(os.environ.get("DSM_HYBRID_HEARTBEAT_SECONDS", "30")),
)
INTERACTIVE_INTERVAL_SECONDS = max(
    1,
    int(os.environ.get("DSM_HYBRID_INTERACTIVE_SECONDS", "1")),
)
_ALLOWED_DB_KEYS = {
    "DSM_DATABASE_DRIVER",
    "DSM_DATABASE",
    "DSM_DATABASE_HOST",
    "DSM_DATABASE_PORT",
    "DSM_DATABASE_NAME",
    "DSM_DATABASE_USER",
    "DSM_DATABASE_PASSWORD_FILE",
    "DSM_DATABASE_TLS",
}


def _read_shell_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    pattern = re.compile(r'^([A-Z0-9_]+)=(?:"([^"]*)"|\'([^\']*)\'|([^#\s]*))\s*$')
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            continue
        result[match.group(1)] = next((v for v in match.groups()[1:] if v is not None), "")
    return result


def _database_environment(root: Path) -> dict[str, str]:
    environment = dict(os.environ)
    for key, value in _read_shell_values(root / "config" / "dsm.conf").items():
        if key in _ALLOWED_DB_KEYS and key not in environment:
            environment[key] = value
    environment.setdefault("DSM_ROOT", str(root))
    return environment


def _collect_and_store_instance_telemetry(
    root: Path,
    agent_id: str,
    backend,
) -> dict[str, Any]:
    """Collect and persist per-instance telemetry for the local Hybrid Agent."""
    state_dir = root / "runtime" / "hybrid-agent-state"
    config_path = state_dir / "agent.json"
    runtime_dir = root / "agents" / "linux" / "runtime"

    if str(runtime_dir) not in sys.path:
        sys.path.insert(0, str(runtime_dir))

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "samples": 0,
            "accepted": 0,
            "error": "hybrid Agent runtime config is unavailable",
        }

    config = raw if isinstance(raw, dict) else {}
    config["agent_id"] = agent_id

    old_state = os.environ.get("CAPIVARA_AGENT_STATE_DIR")
    old_config = os.environ.get("CAPIVARA_AGENT_CONFIG")

    os.environ["CAPIVARA_AGENT_STATE_DIR"] = str(state_dir)
    os.environ["CAPIVARA_AGENT_CONFIG"] = str(config_path)

    try:
        from instance_telemetry import collect_instance_telemetry
        from agent_heartbeat_api import _store_instance_telemetry

        samples = collect_instance_telemetry(config)

        accepted = _store_instance_telemetry(
            agent_id,
            {"instance_telemetry": samples},
            backend=backend,
        )

        return {
            "samples": len(samples),
            "accepted": accepted,
        }
    finally:
        if old_state is None:
            os.environ.pop("CAPIVARA_AGENT_STATE_DIR", None)
        else:
            os.environ["CAPIVARA_AGENT_STATE_DIR"] = old_state

        if old_config is None:
            os.environ.pop("CAPIVARA_AGENT_CONFIG", None)
        else:
            os.environ["CAPIVARA_AGENT_CONFIG"] = old_config


def _hybrid_context(root: Path, backend=None):
    config = _read_shell_values(root / "config" / "agent.conf")

    if str(config.get("DSM_NODE_ROLE", "")).strip().lower() != "hybrid":
        return None, None, None, None, {
            "active": False,
            "reason": "not_hybrid",
        }

    node_id = str(config.get("DSM_NODE_ID", "")).strip()
    agent_id = str(config.get("AGENT_ID", "")).strip()

    if not node_id or not agent_id:
        return None, None, None, None, {
            "active": False,
            "reason": "identity_incomplete",
        }

    effective_backend = backend or backend_from_environment(
        _database_environment(root)
    )

    return config, node_id, agent_id, effective_backend, None


def heartbeat_cycle(
    root: Path = ROOT,
    *,
    backend=None,
) -> dict[str, Any]:
    (
        config,
        node_id,
        agent_id,
        effective_backend,
        inactive,
    ) = _hybrid_context(root, backend)

    if inactive is not None:
        return inactive

    result = reconcile_local_hybrid_runtime(
        RegistryRepository(effective_backend),
        root,
        node_id=node_id,
        agent_id=agent_id,
        hostname=socket.gethostname(),
    )

    provisioning = process_hybrid_instance_provisioning_cycle(
        effective_backend,
        root,
        agent_id,
    )

    game_data = process_hybrid_game_data_cycle(
        effective_backend,
        root,
        agent_id,
    )
    runtime_reconciliation = process_hybrid_runtime_reconciliation_cycle(
        root,
        agent_id,
    )

    configuration = process_hybrid_configuration_cycle(
        effective_backend,
        root,
        agent_id,
    )

    instance_telemetry = _collect_and_store_instance_telemetry(
        root,
        agent_id,
        effective_backend,
    )

    return {
        "active": True,
        "agent_id": agent_id,
        "provisioning": provisioning,
        "game_data": game_data,
        "runtime_reconciliation": runtime_reconciliation,
        "configuration": configuration,
        "instance_telemetry": instance_telemetry,
        **result,
    }


def interactive_cycle(
    root: Path = ROOT,
    *,
    backend=None,
) -> dict[str, Any]:
    (
        config,
        node_id,
        agent_id,
        effective_backend,
        inactive,
    ) = _hybrid_context(root, backend)

    if inactive is not None:
        return inactive

    instance_runtime = process_hybrid_instance_runtime_cycle(
        effective_backend,
        root,
        agent_id,
    )

    instance_files = process_hybrid_instance_files_cycle(
        effective_backend,
        root,
        agent_id,
    )

    console = process_hybrid_console_cycle(
        effective_backend,
        root,
        agent_id,
    )

    return {
        "active": True,
        "agent_id": agent_id,
        "instance_runtime": instance_runtime,
        "instance_files": instance_files,
        "console": console,
    }


def full_cycle(
    root: Path = ROOT,
    *,
    backend=None,
) -> dict[str, Any]:
    slow = heartbeat_cycle(root, backend=backend)

    if not slow.get("active"):
        return slow

    interactive = interactive_cycle(root, backend=backend)

    if not interactive.get("active"):
        return interactive

    return {
        **slow,
        "instance_runtime": interactive.get("instance_runtime"),
        "instance_files": interactive.get("instance_files"),
        "console": interactive.get("console"),
    }


def run_forever(root: Path = ROOT) -> None:
    next_heartbeat = 0.0

    while True:
        now = time.monotonic()

        if now >= next_heartbeat:
            try:
                result = heartbeat_cycle(root)

                if result.get("active"):
                    game_data = (
                        result.get("game_data")
                        if isinstance(result.get("game_data"), dict)
                        else {}
                    )
                    state = (
                        game_data.get("state")
                        if isinstance(game_data.get("state"), dict)
                        else {}
                    )

                    print(
                        "hybrid heartbeat ok "
                        f"agent={result.get('agent_id')} "
                        f"health={result.get('health_status')} "
                        f"game_data={state.get('status', 'idle')}",
                        flush=True,
                    )

            except Exception as exc:
                print(
                    f"hybrid heartbeat failed: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

            next_heartbeat = time.monotonic() + INTERVAL_SECONDS

        try:
            interactive_cycle(root)
        except Exception as exc:
            print(
                f"hybrid interactive cycle failed: {exc}",
                file=sys.stderr,
                flush=True,
            )

        time.sleep(INTERACTIVE_INTERVAL_SECONDS)

def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "once":
        result = full_cycle(ROOT)
        print(result)
        return 0
    run_forever(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
