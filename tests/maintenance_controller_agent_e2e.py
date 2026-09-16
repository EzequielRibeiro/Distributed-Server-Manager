#!/usr/bin/env python3
"""M5 E2E: Controller maintenance -> heartbeat -> Linux Agent -> readiness."""
from __future__ import annotations

import json
import os
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "dashboard" / "workers", ROOT / "tests"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from backend import DatabaseConfig
from backend_factory import create_backend
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from agent_pairing_repository import AgentPairingRepository
from maintenance_repository import MaintenanceRepository
from maintenance_worker import MaintenanceWorker
from external_controller_agent_network_e2e import ControllerHandler, _catalog_policy

AGENT_ID = "agent-m5-e2e"
NODE_ID = "node-m5-e2e"
CONTROLLER_ID = "controller-m5-e2e"
INSTANCE_ID = "m5-instance"


def _certificate(root: Path) -> tuple[Path, Path]:
    cert = root / "controller.crt"
    key = root / "controller.key"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "1",
            "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost",
            "-keyout", str(key), "-out", str(cert),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return cert, key


def _seed_controller(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO nodes(id,name,role,status,metadata_json) VALUES (?,?,?,?,?)",
            ("controller-m5-node", "M5 Controller", "controller", "active", "{}"),
        )
        connection.execute(
            "INSERT INTO controllers(id,node_id,name,status,metadata_json) VALUES (?,?,?,?,?)",
            (CONTROLLER_ID, "controller-m5-node", "M5 Controller", "active", "{}"),
        )
        connection.commit()


def _seed_instance(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",
            (1, CONTROLLER_ID, "M5 E2E Customer", "active"),
        )
        connection.execute(
            "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (INSTANCE_ID, NODE_ID, "external-e2e", "external-e2e-runtime", "M5 E2E", "active", CONTROLLER_ID, AGENT_ID, 1),
        )
        connection.execute(
            "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port) VALUES (?,?,?,?,?)",
            (INSTANCE_ID, NODE_ID, "game", "udp", 24210),
        )
        connection.execute(
            "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port) VALUES (?,?,?,?,?)",
            (INSTANCE_ID, NODE_ID, "admin", "tcp", 24211),
        )
        connection.commit()


def _force_due(database: Path, when: datetime) -> None:
    stamp = (when - timedelta(seconds=1)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE instance_maintenance_state SET next_due_at=? WHERE instance_id=?",
            (stamp, INSTANCE_ID),
        )
        connection.commit()


def _runtime_spec(root: Path) -> dict:
    binary = root / "server-bin"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    policy = _catalog_policy()
    return {
        "instance_id": INSTANCE_ID,
        "agent_id": AGENT_ID,
        "runtime_id": "external-e2e-runtime",
        "game_id": "external-e2e",
        "environment_id": "external-e2e-runtime",
        "adapter": "systemd",
        "profile": "m5-e2e",
        "profile_version": 1,
        "working_directory": str(root / "instance"),
        "executable": str(binary),
        "arguments": [],
        "environment": {},
        "user": "capivara-instance",
        "desired_state": "running",
        "ports": {
            "game": {"name": "game", "protocol": "udp", "port": 24210},
            "admin": {"name": "admin", "protocol": "tcp", "port": 24211},
        },
        "catalog_runtime_policy": policy,
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="capivara-m5-e2e-") as temporary:
        root = Path(temporary)
        state = root / "agent-state"
        config_path = root / "agent.json"
        database = root / "capivara.db"
        cert, key = _certificate(root)
        os.environ["CAPIVARA_AGENT_STATE_DIR"] = str(state)
        os.environ["CAPIVARA_AGENT_CONFIG"] = str(config_path)
        os.environ["SSL_CERT_FILE"] = str(cert)

        backend = create_backend(DatabaseConfig(driver="sqlite", database=str(database)))
        backend.initialize()
        _seed_controller(database)
        pairing = AgentPairingRepository(backend).issue_token(controller_id=CONTROLLER_ID)

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        config = {
            "agent_id": AGENT_ID,
            "node_id": NODE_ID,
            "name": "M5 Linux Agent",
            "hostname": "m5-agent",
            "fingerprint": "sha256:m5-e2e",
            "controller_url": f"https://localhost:{port}",
            "pairing_token": pairing.token,
            "capivara_version": "2.0.63-m5-e2e",
            "heartbeat_interval_seconds": 1,
            "degraded_after_seconds": 10,
            "offline_after_seconds": 30,
        }
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        ControllerHandler.backend = backend
        ControllerHandler.before_heartbeat = None
        server = HTTPServer(("127.0.0.1", port), ControllerHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert), str(key))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            runtime_path = ROOT / "agents" / "linux" / "runtime"
            if str(runtime_path) not in sys.path:
                sys.path.insert(0, str(runtime_path))
            import agent as linux_agent
            from external_agent_network_probe import _RuntimeContractHarness

            enrolled = linux_agent.enroll(linux_agent._load_config())
            if not enrolled.get("credential_id") or enrolled.get("pairing_token"):
                raise AssertionError("Agent enrollment did not exchange pairing token for credential")
            _seed_instance(database)

            harness = _RuntimeContractHarness(enrolled, INSTANCE_ID, "unused-instance")
            spec = _runtime_spec(root)
            harness.materialization.materialize(enrolled, spec)
            harness.firewall.reconcile(spec)
            harness.runtime_state[INSTANCE_ID] = "running"

            maintenance = MaintenanceRepository(backend)
            maintenance.initialize()
            now = datetime.now(timezone.utc).replace(microsecond=0)
            maintenance.set_policy(
                INSTANCE_ID,
                {
                    "enabled": True,
                    "schedule_mode": "fixed",
                    "timezone": "UTC",
                    "weekdays": list(range(7)),
                    "start_time": "04:00",
                    "warning_offsets_seconds": [],
                    "broadcast_enabled": False,
                    "coalesce_updates": False,
                },
                requested_by="m5-e2e",
                now=now,
            )
            _force_due(database, now)
            worker = MaintenanceWorker(
                backend,
                ROOT,
                capability_resolver=lambda _: {"scheduled_restart": True},
            )

            completed = None
            for step in range(80):
                tick_at = now + timedelta(seconds=step)
                worker.tick(now=tick_at)
                linux_agent.heartbeat(enrolled)
                worker.tick(now=tick_at)
                snapshot = maintenance.snapshot(INSTANCE_ID)
                runs = snapshot.get("runs") or []
                if runs and str(runs[0].get("status") or "") in {"completed", "failed"}:
                    completed = runs[0]
                    break
            if completed is None:
                raise AssertionError("maintenance run did not finish through Controller-Agent heartbeat")
            if completed.get("status") != "completed":
                raise AssertionError(f"maintenance run failed: {completed}")

            lifecycle = AgentInstanceRuntimeRepository(backend)
            lifecycle.initialize()
            command_columns = (
                "preflight_command_id", "stop_command_id", "start_command_id", "readiness_command_id"
            )
            states = [lifecycle.snapshot(str(completed[name])) for name in command_columns]
            actions = [str(state.get("action") or "") for state in states]
            if actions != ["status", "stop", "start", "doctor"]:
                raise AssertionError(f"unexpected M5 lifecycle sequence: {actions}")
            if any(str(state.get("status") or "") != "completed" for state in states):
                raise AssertionError(f"M5 lifecycle command did not complete: {states}")
            if harness.runtime_state.get(INSTANCE_ID) != "running":
                raise AssertionError("instance did not return to running state")
            adapter_events = [
                event["stage"] for event in harness.events
                if event.get("instance_id") == INSTANCE_ID and event.get("stage") in {"adapter_stop", "adapter_start"}
            ]
            if adapter_events[-2:] != ["adapter_stop", "adapter_start"]:
                raise AssertionError(f"Agent did not execute stop/start in order: {adapter_events}")

            print(json.dumps({
                "status": "passed",
                "path": "Controller -> heartbeat -> Linux Agent -> stop/start -> Doctor -> readiness",
                "actions": actions,
                "run_id": completed.get("run_id"),
                "final_state": harness.runtime_state.get(INSTANCE_ID),
                "ready": True,
            }, indent=2))
            return 0
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
