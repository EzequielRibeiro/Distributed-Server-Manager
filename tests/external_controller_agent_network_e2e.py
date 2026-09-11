#!/usr/bin/env python3
"""External Controller↔Agent E2E for network recovery plus a complete instance lifecycle."""
from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from backend import DatabaseConfig
from backend_factory import create_backend
from agent_admin_repository import AgentAdminRepository
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_enroll, dispatch_heartbeat
from agent_runtime_repository import AgentRuntimeRepository
from catalog_controller_runtime_policy import default_policy

NS = "capivara-p4"
HOST_IF = "cap-p4-host"
AGENT_IF = "cap-p4-agent"
HOST_IP = "10.203.0.1"
AGENT_IP = "10.203.0.2"
DNS_NAME = "controller.p4.test"
INTERNAL_PORT = 18443
EXTERNAL_PORT = 18080
INSTANCE_A = "p4-instance-a"
INSTANCE_B = "p4-instance-b"
AGENT_ID = "agent-p4-external"


def run(*args: str, check: bool = True, capture: bool = True, env=None):
    return subprocess.run(list(args), check=check, text=True, capture_output=capture, env=env)


class InstanceCycleOrchestrator:
    """Queue exactly one lifecycle action after the previous one is acknowledged."""

    def __init__(self, backend, provisioning_ids: list[str]):
        self.backend = backend
        self.provisioning = AgentInstanceProvisioningRepository(backend)
        self.runtime = AgentInstanceRuntimeRepository(backend)
        self.provisioning_ids = list(provisioning_ids)
        self.actions = [
            (INSTANCE_A, "start"),
            (INSTANCE_A, "start"),
            (INSTANCE_B, "start"),
            (INSTANCE_A, "restart"),
            (INSTANCE_A, "stop"),
            (INSTANCE_A, "stop"),
            (INSTANCE_A, "remove"),
            (INSTANCE_B, "status"),
            (INSTANCE_B, "stop"),
            (INSTANCE_B, "remove"),
        ]
        self.index = 0
        self.current: dict | None = None
        self.command_ids: list[str] = []
        self.completed: list[dict] = []
        self.finished = False
        self.provisioning_finished = False
        self.remove_idempotent = False

    def _provisioning_complete(self) -> bool:
        if self.provisioning_finished:
            return True
        states = [self.provisioning.snapshot(provisioning_id) for provisioning_id in self.provisioning_ids]
        failures = [state for state in states if str(state.get("status") or "").lower() == "failed"]
        if failures:
            raise AssertionError(f"provisioning failed before lifecycle: {failures}")
        self.provisioning_finished = all(
            str(state.get("status") or "").lower() == "completed"
            for state in states
        )
        return self.provisioning_finished

    def _complete_current_if_ready(self) -> None:
        if self.current is None:
            return
        try:
            state = self.runtime.snapshot(str(self.current["command_id"]))
        except KeyError:
            if self.current["action"] != "remove":
                raise
            self.completed.append({**self.current, "status": "completed", "deleted_with_instance": True})
            self.current = None
            self.index += 1
            return

        status = str(state.get("status") or "").lower()
        if status == "failed":
            raise AssertionError(f"lifecycle command failed: {state}")
        if status != "completed":
            return
        self.completed.append(state)
        self.current = None
        self.index += 1

    def before_heartbeat(self, payload: dict) -> None:
        if self.finished or not self._provisioning_complete():
            return
        self._complete_current_if_ready()
        if self.current is not None:
            return
        if self.index >= len(self.actions):
            self.finished = True
            return

        instance_id, action = self.actions[self.index]
        created = self.runtime.enqueue(
            agent_id=AGENT_ID,
            instance_id=instance_id,
            action=action,
            requested_by="external-e2e",
        )
        if action == "remove":
            duplicate = self.runtime.enqueue(
                agent_id=AGENT_ID,
                instance_id=instance_id,
                action=action,
                requested_by="external-e2e",
            )
            if duplicate["command_id"] != created["command_id"]:
                raise AssertionError("remove enqueue is not idempotent")
            self.remove_idempotent = True
        self.current = {
            "command_id": created["command_id"],
            "instance_id": instance_id,
            "action": action,
        }
        self.command_ids.append(str(created["command_id"]))

    def status_b_was_running(self) -> bool:
        for state in self.completed:
            if state.get("instance_id") != INSTANCE_B or state.get("action") != "status":
                continue
            report = state.get("result") if isinstance(state.get("result"), dict) else {}
            payload = report.get("result") if isinstance(report.get("result"), dict) else {}
            return str(payload.get("observed_state") or "").lower() == "running"
        return False


class ControllerHandler(BaseHTTPRequestHandler):
    backend = None
    before_heartbeat = None

    def log_message(self, fmt, *args):
        return

    def _json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _reply(self, status: int, payload: dict):
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._reply(200, {"status": "ok"}) if self.path == "/ping" else self._reply(404, {"error": "not_found"})

    def do_POST(self):
        payload = self._json_body()
        try:
            if self.path == "/api/agent/enroll":
                status, result = dispatch_enroll(payload, backend=self.backend)
            elif self.path == "/api/agent/heartbeat":
                if callable(self.before_heartbeat):
                    self.before_heartbeat(payload)
                status, result = dispatch_heartbeat(payload, headers=self.headers, backend=self.backend)
            else:
                status, result = 404, {"error": "not_found"}
        except Exception as exc:
            status, result = 500, {"error": "external_e2e_orchestration_failed", "message": str(exc)}
        self._reply(status, result)


class TinyDns(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((HOST_IP, 53))
        self.stop_event = threading.Event()

    @staticmethod
    def _question_name(packet: bytes, offset: int = 12):
        labels = []
        cursor = offset
        while cursor < len(packet):
            size = packet[cursor]
            cursor += 1
            if size == 0:
                break
            labels.append(packet[cursor:cursor + size].decode("ascii"))
            cursor += size
        return ".".join(labels), cursor + 4

    def run(self):
        self.sock.settimeout(.2)
        while not self.stop_event.is_set():
            try:
                packet, peer = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            if len(packet) < 12:
                continue
            name, end = self._question_name(packet)
            qtype, qclass = struct.unpack("!HH", packet[end - 4:end])
            question = packet[12:end]
            answer = b""
            count = 0
            if name.rstrip(".").lower() == DNS_NAME and qtype == 1 and qclass == 1:
                answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 30, 4) + socket.inet_aton(HOST_IP)
                count = 1
            header = packet[:2] + struct.pack("!HHHHH", 0x8180, 1, count, 0, 0)
            self.sock.sendto(header + question + answer, peer)

    def close(self):
        self.stop_event.set()
        self.join(timeout=2)
        self.sock.close()


def namespace_setup():
    run("ip", "netns", "add", NS)
    run("ip", "link", "add", HOST_IF, "type", "veth", "peer", "name", AGENT_IF)
    run("ip", "link", "set", AGENT_IF, "netns", NS)
    run("ip", "addr", "add", f"{HOST_IP}/24", "dev", HOST_IF)
    run("ip", "link", "set", HOST_IF, "up")
    run("ip", "netns", "exec", NS, "ip", "addr", "add", f"{AGENT_IP}/24", "dev", AGENT_IF)
    run("ip", "netns", "exec", NS, "ip", "link", "set", AGENT_IF, "up")
    run("ip", "netns", "exec", NS, "ip", "link", "set", "lo", "up")
    directory = Path("/etc/netns") / NS
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "resolv.conf").write_text(
        f"nameserver {HOST_IP}\noptions timeout:1 attempts:1\n",
        encoding="utf-8",
    )


def nat_rule(add: bool):
    run(
        "iptables",
        "-t",
        "nat",
        "-A" if add else "-D",
        "PREROUTING",
        "-i",
        HOST_IF,
        "-p",
        "tcp",
        "--dport",
        str(EXTERNAL_PORT),
        "-j",
        "REDIRECT",
        "--to-ports",
        str(INTERNAL_PORT),
        check=add,
    )


def cleanup():
    try:
        nat_rule(False)
    except Exception:
        pass
    subprocess.run(["ip", "netns", "del", NS], check=False, capture_output=True)
    subprocess.run(["ip", "link", "del", HOST_IF], check=False, capture_output=True)
    shutil.rmtree(Path("/etc/netns") / NS, ignore_errors=True)


def create_cert(root: Path):
    cert = root / "controller.crt"
    key = root / "controller.key"
    run(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-sha256",
        "-days",
        "1",
        "-subj",
        f"/CN={DNS_NAME}",
        "-addext",
        f"subjectAltName=DNS:{DNS_NAME}",
        "-keyout",
        str(key),
        "-out",
        str(cert),
    )
    return cert, key


def agent_probe(action: str, config_path: Path, state_dir: Path, ca_file: Path, *extra: str, expect_success: bool = True):
    env = os.environ.copy()
    env.update(
        {
            "CAPIVARA_AGENT_CONFIG": str(config_path),
            "CAPIVARA_AGENT_STATE_DIR": str(state_dir),
            "SSL_CERT_FILE": str(ca_file),
        }
    )
    cmd = [
        "ip",
        "netns",
        "exec",
        NS,
        "env",
        f"CAPIVARA_AGENT_CONFIG={config_path}",
        f"CAPIVARA_AGENT_STATE_DIR={state_dir}",
        f"SSL_CERT_FILE={ca_file}",
        "python3",
        str(ROOT / "tests" / "external_agent_network_probe.py"),
        action,
        *extra,
    ]
    completed = run(*cmd, check=False, env=env)
    if expect_success and completed.returncode != 0:
        raise AssertionError(f"Agent probe failed ({action}): {completed.stderr or completed.stdout}")
    if not expect_success and completed.returncode == 0:
        raise AssertionError(f"Agent probe unexpectedly succeeded ({action}): {completed.stdout}")
    return completed


def parsed_last_seen(value: str) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _catalog_policy() -> dict:
    return default_policy(
        {
            "id": "external-e2e-runtime",
            "process": {"executable": "server-bin", "args": []},
            "network": {
                "ports": [
                    {"name": "game", "protocol": "udp", "exposure": "public"},
                    {"name": "admin", "protocol": "tcp", "exposure": "private"},
                ],
                "apply": [],
            },
        }
    )


def _seed_instances(database_path: Path, controller_id: str, storage_root: Path) -> None:
    storage_root.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE agents SET metadata_json=? WHERE id=?",
            (
                json.dumps(
                    {
                        "telemetry": {
                            "storage_pools": [
                                {
                                    "id": "default",
                                    "storage_class": "standard",
                                    "enabled": True,
                                    "default": True,
                                    "health": "online",
                                    "priority": 100,
                                    "usable_bytes": 10 * 1024 * 1024 * 1024,
                                    "free_bytes": 10 * 1024 * 1024 * 1024,
                                    "reserve_bytes": 0,
                                    "root_path": str(storage_root),
                                }
                            ]
                        }
                    }
                ),
                AGENT_ID,
            ),
        )
        connection.execute(
            "INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",
            (1, controller_id, "External E2E Customer", "active"),
        )
        for instance_id, game_port, admin_port in (
            (INSTANCE_A, 24010, 24011),
            (INSTANCE_B, 24110, 24111),
        ):
            connection.execute(
                "INSERT INTO instances(id,node_id,game_id,runtime_id,name,status,controller_id,agent_id,customer_id) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    instance_id,
                    "node-p4-external",
                    "external-e2e",
                    "external-e2e-runtime",
                    instance_id,
                    "offline",
                    controller_id,
                    AGENT_ID,
                    1,
                ),
            )
            connection.execute(
                "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port) VALUES (?,?,?,?,?)",
                (instance_id, "node-p4-external", "game", "udp", game_port),
            )
            connection.execute(
                "INSERT INTO instance_ports(instance_id,node_id,name,protocol,port) VALUES (?,?,?,?,?)",
                (instance_id, "node-p4-external", "admin", "tcp", admin_port),
            )
        connection.commit()


def _enqueue_provisioning(backend, policy: dict) -> tuple[list[str], bool]:
    jobs = AgentInstanceProvisioningRepository(backend)
    provisioning_ids: list[str] = []
    idempotent = True
    for instance_id in (INSTANCE_A, INSTANCE_B):
        arguments = {
            "agent_id": AGENT_ID,
            "instance_id": instance_id,
            "environment_id": "external-e2e.stable",
            "selector": "stable",
            "selection": {
                "game": "external-e2e",
                "provider": "fixture",
                "fixture_instance": instance_id,
            },
            "configuration": {"catalog_runtime_policy": policy},
            "desired_state": "stopped",
            "requested_by": "external-e2e",
            "storage_pool_id": "default",
        }
        first = jobs.enqueue(**arguments)
        duplicate = jobs.enqueue(**arguments)
        if duplicate["provisioning_id"] != first["provisioning_id"]:
            idempotent = False
            raise AssertionError(f"provisioning enqueue is not idempotent for {instance_id}")
        provisioning_ids.append(str(first["provisioning_id"]))
    return provisioning_ids, idempotent


def _assert_runtime_contract(cycle: dict) -> None:
    required_flags = (
        "completed",
        "private_closed",
        "reconcile_before_start_restart",
        "remove_after_stopped",
        "idempotent_start",
        "idempotent_stop",
        "isolation_between_instances",
        "firewall_empty_after_teardown",
    )
    for key in required_flags:
        if cycle.get(key) is not True:
            raise AssertionError(f"instance-cycle proof failed: {key}={cycle.get(key)!r}")

    expected_ports = {
        INSTANCE_A: {"game": ("udp", 24010), "admin": ("tcp", 24011)},
        INSTANCE_B: {"game": ("udp", 24110), "admin": ("tcp", 24111)},
    }
    for instance_id, expected in expected_ports.items():
        spec = (cycle.get("runtime_specs") or {}).get(instance_id) or {}
        ports = spec.get("ports") if isinstance(spec.get("ports"), dict) else {}
        for role, (protocol, port) in expected.items():
            binding = ports.get(role) if isinstance(ports.get(role), dict) else {}
            if (str(binding.get("protocol")), int(binding.get("port") or 0)) != (protocol, port):
                raise AssertionError(f"reserved port did not reach RuntimeSpec: {instance_id}/{role}")
        policy = spec.get("catalog_runtime_policy") if isinstance(spec.get("catalog_runtime_policy"), dict) else {}
        exposure = {
            str(item.get("name")): (str(item.get("protocol")), str(item.get("exposure")))
            for item in policy.get("network_exposure") or []
            if isinstance(item, dict)
        }
        if exposure != {"game": ("udp", "public"), "admin": ("tcp", "private")}:
            raise AssertionError(f"catalog exposure did not reach RuntimeSpec: {instance_id}: {exposure}")


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("P4 network E2E must run as root")
    cleanup()
    temporary = tempfile.TemporaryDirectory(prefix="capivara-p4-")
    backend = server = dns = None
    try:
        namespace_setup()
        root = Path(temporary.name)
        cert, key = create_cert(root)
        database_path = root / "capivara.db"
        backend = create_backend(DatabaseConfig(driver="sqlite", database=str(database_path)))
        backend.initialize()
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "INSERT INTO nodes(id,name,role,status,metadata_json) VALUES (?,?,?,?,?)",
                ("controller-p4-node", "P4 Controller", "controller", "active", "{}"),
            )
            connection.execute(
                "INSERT INTO controllers(id,node_id,name,status,metadata_json) VALUES (?,?,?,?,?)",
                ("controller-p4", "controller-p4-node", "P4 Controller", "active", "{}"),
            )
            connection.commit()

        pairing = AgentPairingRepository(backend).issue_token(controller_id="controller-p4")
        config_path = root / "agent.json"
        state_dir = root / "agent-state"
        instance_storage_root = root / "instance-storage"
        config_path.write_text(
            json.dumps(
                {
                    "agent_id": AGENT_ID,
                    "node_id": "node-p4-external",
                    "name": "P4 External Agent",
                    "hostname": "p4-agent",
                    "fingerprint": "sha256:p4-external",
                    "controller_url": f"https://{DNS_NAME}:{EXTERNAL_PORT}",
                    "pairing_token": pairing.token,
                    "capivara_version": "2.0.9-p4",
                    "heartbeat_interval_seconds": 1,
                    "degraded_after_seconds": 2,
                    "offline_after_seconds": 4,
                    "instance_storage_root": str(instance_storage_root),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        ControllerHandler.backend = backend
        ControllerHandler.before_heartbeat = None
        server = HTTPServer((HOST_IP, INTERNAL_PORT), ControllerHandler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(str(cert), str(key))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        dns = TinyDns()
        dns.start()
        nat_rule(True)

        resolution = json.loads(agent_probe("resolve", config_path, state_dir, cert, DNS_NAME).stdout.strip().splitlines()[-1])
        assert resolution["address"] == HOST_IP
        enrollment = json.loads(agent_probe("enroll", config_path, state_dir, cert).stdout.strip().splitlines()[-1])
        assert enrollment["controller_id"] == "controller-p4"
        assert enrollment["pairing_token_present"] is False
        assert enrollment["rtt_ms"] >= 0
        first = json.loads(agent_probe("heartbeat", config_path, state_dir, cert).stdout.strip().splitlines()[-1])
        assert first["health_status"] == "online" and first["rtt_ms"] >= 0

        runtime_repo = AgentRuntimeRepository(backend)
        snapshot = runtime_repo.snapshot(AGENT_ID, refresh_health=False)
        last_seen = parsed_last_seen(snapshot["last_seen"])
        nat_rule(False)
        offline = agent_probe("heartbeat", config_path, state_dir, cert, expect_success=False)
        assert offline.returncode != 0
        degraded = runtime_repo.refresh_health(now=last_seen + timedelta(seconds=3))[AGENT_ID]
        assert degraded == "degraded"
        offline_state = runtime_repo.refresh_health(now=last_seen + timedelta(seconds=5))[AGENT_ID]
        assert offline_state == "offline"

        admin = AgentAdminRepository(backend)
        queued = admin.request_doctor(AGENT_ID, requested_by="p4:e2e")
        assert str(queued.get("status") or "").lower() == "queued"
        nat_rule(True)
        delivery = json.loads(agent_probe("heartbeat", config_path, state_dir, cert).stdout.strip().splitlines()[-1])
        assert delivery["doctor_command"] or str((delivery.get("doctor_state") or {}).get("status") or "").lower() in {"queued", "running"}
        final = json.loads(agent_probe("heartbeat", config_path, state_dir, cert).stdout.strip().splitlines()[-1])
        latest = admin.latest_doctor(AGENT_ID)
        assert str((latest or {}).get("status") or "").lower() == "completed"
        recovered = runtime_repo.snapshot(AGENT_ID)
        assert recovered["health_status"] == "online"

        _seed_instances(database_path, enrollment["controller_id"], instance_storage_root)
        policy = _catalog_policy()
        provisioning_ids, provisioning_idempotent = _enqueue_provisioning(backend, policy)
        orchestrator = InstanceCycleOrchestrator(backend, provisioning_ids)
        ControllerHandler.before_heartbeat = orchestrator.before_heartbeat
        cycle = json.loads(
            agent_probe(
                "instance-cycle",
                config_path,
                state_dir,
                cert,
                INSTANCE_A,
                INSTANCE_B,
            ).stdout.strip().splitlines()[-1]
        )
        _assert_runtime_contract(cycle)
        if not orchestrator.finished:
            raise AssertionError("Controller lifecycle orchestration did not finish")
        if not orchestrator.remove_idempotent:
            raise AssertionError("remove command idempotence was not proven")
        if not orchestrator.status_b_was_running():
            raise AssertionError("instance B was not still running after instance A teardown")
        if len(orchestrator.command_ids) != len(orchestrator.actions):
            raise AssertionError("not every lifecycle action crossed the Controller→Agent queue")
        if not orchestrator.provisioning_finished:
            raise AssertionError("provisioning was not acknowledged by Controller")

        with sqlite3.connect(database_path) as connection:
            remaining = connection.execute(
                "SELECT COUNT(*) FROM instances WHERE id IN (?,?)",
                (INSTANCE_A, INSTANCE_B),
            ).fetchone()[0]
            consumed = connection.execute(
                "SELECT consumed_at FROM agent_pairing_tokens WHERE id=?",
                (pairing.token_id,),
            ).fetchone()[0]
        assert remaining == 0
        assert consumed

        print(
            json.dumps(
                {
                    "status": "passed",
                    "transport": "https",
                    "tls_minimum": "1.2",
                    "hostname_validation": DNS_NAME,
                    "dns_ms": resolution["dns_ms"],
                    "enroll_rtt_ms": enrollment["rtt_ms"],
                    "heartbeat_rtt_ms": first["rtt_ms"],
                    "reconnect_rtt_ms": final["rtt_ms"],
                    "health_transition": ["online", "degraded", "offline", "online"],
                    "queued_while_offline": True,
                    "doctor_completed_after_reconnect": True,
                    "external_port": EXTERNAL_PORT,
                    "internal_port": INTERNAL_PORT,
                    "instance_cycle": {
                        "flow": [
                            "controller",
                            "provisioning",
                            "agent",
                            "runtime_spec",
                            "catalog_runtime_policy",
                            "exposure",
                            "start",
                            "restart",
                            "stop",
                            "teardown",
                        ],
                        "ports_propagated": True,
                        "private_closed": cycle["private_closed"],
                        "reconcile_before_start_restart": cycle["reconcile_before_start_restart"],
                        "remove_after_stopped": cycle["remove_after_stopped"],
                        "provisioning_idempotent": provisioning_idempotent,
                        "start_idempotent": cycle["idempotent_start"],
                        "stop_idempotent": cycle["idempotent_stop"],
                        "remove_enqueue_idempotent": orchestrator.remove_idempotent,
                        "isolation_between_instances": cycle["isolation_between_instances"],
                        "controller_instances_removed": remaining == 0,
                        "native_firewall_gate": "separate",
                    },
                },
                indent=2,
            )
        )
        return 0
    finally:
        ControllerHandler.before_heartbeat = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if dns is not None:
            dns.close()
        if backend is not None:
            backend.close()
        cleanup()
        temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
