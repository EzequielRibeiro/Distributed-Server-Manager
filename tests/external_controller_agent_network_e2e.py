#!/usr/bin/env python3
"""P4 external Controller↔Agent E2E using an isolated network namespace and NAT.

The Controller listens internally on 8080. The Agent resolves controller.p4.test via
an isolated DNS service and connects to external port 18080, which is redirected to
8080. The test then removes the NAT rule, queues a Doctor request while the Agent is
offline, restores connectivity, and proves command delivery/result recovery.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from backend import DatabaseConfig
from backend_factory import create_backend
from agent_admin_repository import AgentAdminRepository
from agent_pairing_repository import AgentPairingRepository
from agent_remote_http import dispatch_enroll, dispatch_heartbeat

NS = "capivara-p4"
HOST_IF = "cap-p4-host"
AGENT_IF = "cap-p4-agent"
HOST_IP = "10.203.0.1"
AGENT_IP = "10.203.0.2"
DNS_NAME = "controller.p4.test"
INTERNAL_PORT = 8080
EXTERNAL_PORT = 18080


def run(*args: str, check: bool = True, capture: bool = True, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args),
        check=check,
        text=True,
        capture_output=capture,
        env=env,
    )


class ControllerHandler(BaseHTTPRequestHandler):
    backend = None

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
        if self.path == "/ping":
            self._reply(200, {"status": "ok"})
            return
        self._reply(404, {"error": "not_found"})

    def do_POST(self):
        payload = self._json_body()
        if self.path == "/api/agent/enroll":
            status, result = dispatch_enroll(payload, backend=self.backend)
        elif self.path == "/api/agent/heartbeat":
            status, result = dispatch_heartbeat(payload, headers=self.headers, backend=self.backend)
        else:
            status, result = 404, {"error": "not_found"}
        self._reply(status, result)


class TinyDns(threading.Thread):
    """Minimal authoritative A-record DNS server sufficient for the E2E hostname."""

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
            labels.append(packet[cursor : cursor + size].decode("ascii"))
            cursor += size
        return ".".join(labels), cursor + 4

    def run(self):
        self.sock.settimeout(0.2)
        while not self.stop_event.is_set():
            try:
                packet, peer = self.sock.recvfrom(2048)
            except socket.timeout:
                continue
            if len(packet) < 12:
                continue
            name, question_end = self._question_name(packet)
            qtype, qclass = struct.unpack("!HH", packet[question_end - 4 : question_end])
            question = packet[12:question_end]
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
    netns_dir = Path("/etc/netns") / NS
    netns_dir.mkdir(parents=True, exist_ok=True)
    (netns_dir / "resolv.conf").write_text(f"nameserver {HOST_IP}\noptions timeout:1 attempts:1\n", encoding="utf-8")


def nat_rule(add: bool):
    action = "-A" if add else "-D"
    run(
        "iptables", "-t", "nat", action, "PREROUTING", "-i", HOST_IF,
        "-p", "tcp", "--dport", str(EXTERNAL_PORT), "-j", "REDIRECT",
        "--to-ports", str(INTERNAL_PORT), check=add,
    )


def cleanup():
    try:
        nat_rule(False)
    except Exception:
        pass
    subprocess.run(["ip", "netns", "del", NS], check=False, capture_output=True)
    subprocess.run(["ip", "link", "del", HOST_IF], check=False, capture_output=True)
    shutil.rmtree(Path("/etc/netns") / NS, ignore_errors=True)


def agent_probe(action: str, config_path: Path, state_dir: Path, *extra: str, expect_success: bool = True):
    env = os.environ.copy()
    env["CAPIVARA_AGENT_CONFIG"] = str(config_path)
    env["CAPIVARA_AGENT_STATE_DIR"] = str(state_dir)
    command = [
        "ip", "netns", "exec", NS, "env",
        f"CAPIVARA_AGENT_CONFIG={config_path}",
        f"CAPIVARA_AGENT_STATE_DIR={state_dir}",
        "python3", str(ROOT / "tests" / "external_agent_network_probe.py"), action, *extra,
    ]
    completed = run(*command, check=False, env=env)
    if expect_success and completed.returncode != 0:
        raise AssertionError(f"Agent probe failed ({action}): {completed.stderr or completed.stdout}")
    if not expect_success and completed.returncode == 0:
        raise AssertionError(f"Agent probe unexpectedly succeeded ({action}): {completed.stdout}")
    return completed


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("P4 network E2E must run as root (network namespace, DNS :53 and NAT required)")
    cleanup()
    temporary = tempfile.TemporaryDirectory(prefix="capivara-p4-")
    backend = None
    server = None
    dns = None
    try:
        namespace_setup()
        database_path = Path(temporary.name) / "capivara.db"
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
        config_path = Path(temporary.name) / "agent.json"
        state_dir = Path(temporary.name) / "agent-state"
        config_path.write_text(
            json.dumps(
                {
                    "agent_id": "agent-p4-external",
                    "node_id": "node-p4-external",
                    "name": "P4 External Agent",
                    "hostname": "p4-agent",
                    "fingerprint": "sha256:p4-external",
                    "controller_url": f"http://{DNS_NAME}:{EXTERNAL_PORT}",
                    "pairing_token": pairing.token,
                    "capivara_version": "2.0.9-p4",
                    "heartbeat_interval_seconds": 10,
                    "degraded_after_seconds": 2,
                    "offline_after_seconds": 4,
                },
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        ControllerHandler.backend = backend
        server = HTTPServer((HOST_IP, INTERNAL_PORT), ControllerHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        dns = TinyDns()
        dns.start()
        nat_rule(True)

        resolved = agent_probe("resolve", config_path, state_dir, DNS_NAME)
        resolution = json.loads(resolved.stdout.strip().splitlines()[-1])
        assert resolution["address"] == HOST_IP, resolution

        enrolled = agent_probe("enroll", config_path, state_dir)
        enrollment = json.loads(enrolled.stdout.strip().splitlines()[-1])
        assert enrollment["agent_id"] == "agent-p4-external"
        assert enrollment["controller_id"] == "controller-p4"
        assert enrollment["pairing_token_present"] is False

        first = agent_probe("heartbeat", config_path, state_dir)
        first_result = json.loads(first.stdout.strip().splitlines()[-1])
        assert first_result["health_status"] == "online", first_result

        # Simulate loss of the public NAT forwarding while the internal Controller remains healthy.
        nat_rule(False)
        offline = agent_probe("heartbeat", config_path, state_dir, expect_success=False)
        offline_text = (offline.stderr or offline.stdout).lower()
        assert "refused" in offline_text or "unavailable" in offline_text or "urlopen" in offline_text, offline_text

        admin = AgentAdminRepository(backend)
        queued = admin.request_doctor("agent-p4-external", requested_by="p4:e2e")
        assert str(queued.get("status") or "").lower() == "queued", queued
        queued_before_reconnect = admin.latest_doctor("agent-p4-external")
        assert str((queued_before_reconnect or {}).get("status") or "").lower() == "queued"

        nat_rule(True)
        delivery = agent_probe("heartbeat", config_path, state_dir)
        delivery_result = json.loads(delivery.stdout.strip().splitlines()[-1])
        assert delivery_result["doctor_command"] is True or str((delivery_result.get("doctor_state") or {}).get("status") or "").lower() in {"queued", "running"}

        completion = agent_probe("heartbeat", config_path, state_dir)
        completion_result = json.loads(completion.stdout.strip().splitlines()[-1])
        latest = admin.latest_doctor("agent-p4-external")
        assert str((latest or {}).get("status") or "").lower() == "completed", latest

        with sqlite3.connect(database_path) as connection:
            runtime = connection.execute(
                "SELECT health_status,last_seen FROM agent_runtime_inventory WHERE agent_id=?",
                ("agent-p4-external",),
            ).fetchone()
            consumed = connection.execute(
                "SELECT consumed_at FROM agent_pairing_tokens WHERE id=?",
                (pairing.token_id,),
            ).fetchone()[0]
        assert runtime and runtime[0] == "online" and runtime[1]
        assert consumed

        print(json.dumps({
            "status": "passed",
            "dns": {"hostname": DNS_NAME, "resolved": HOST_IP},
            "nat": {"external_port": EXTERNAL_PORT, "internal_port": INTERNAL_PORT},
            "enrollment": "permanent-credential",
            "offline_probe": "failed-as-expected",
            "queued_while_offline": True,
            "reconnected": True,
            "doctor_completed_after_reconnect": True,
            "controller_runtime_health": runtime[0],
        }, indent=2))
        return 0
    finally:
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
