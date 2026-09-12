#!/usr/bin/env python3
"""Native Linux proof that public Steam query exposure is externally reachable.

Runs an A2S_INFO fixture on the host, sends the production A2S client from an
isolated network namespace, and crosses the production Capivara UFW reconciler.
The proof is deliberately fail-closed: the external query must fail before the
owned rule exists, succeed after reconcile, and fail again after teardown.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import threading
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LINUX_RUNTIME = ROOT / "agents" / "linux" / "runtime"
LINUX_PRIVILEGED = ROOT / "agents" / "linux" / "privileged" / "reconcile_firewall.py"
sys.path.insert(0, str(LINUX_RUNTIME))
import privileged_firewall  # noqa: E402

HOST_IP = "10.254.239.1"
CLIENT_IP = "10.254.239.2"
QUERY_PORT = 40313
NS = "capivara-broadcast-e2e"
HOST_IF = "cap-br-host"
CLIENT_IF = "cap-br-client"
_A2S_REQUEST = b"\xff\xff\xff\xffTSource Engine Query\x00"


def _run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), text=True, capture_output=True, check=check, timeout=15)


def _load_reconciler():
    spec = importlib.util.spec_from_file_location("capivara_broadcast_reconciler", LINUX_PRIVILEGED)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Linux privileged firewall reconciler")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reconciler = _load_reconciler()


def _instance_id() -> str:
    run_id = "".join(ch for ch in os.environ.get("GITHUB_RUN_ID", "local") if ch.isalnum())
    attempt = "".join(ch for ch in os.environ.get("GITHUB_RUN_ATTEMPT", "1") if ch.isalnum())
    return f"ci-broadcast-{run_id or 'local'}-{attempt or '1'}"


def _network_setup() -> None:
    _network_cleanup()
    _run("ip", "netns", "add", NS)
    _run("ip", "link", "add", HOST_IF, "type", "veth", "peer", "name", CLIENT_IF)
    _run("ip", "link", "set", CLIENT_IF, "netns", NS)
    _run("ip", "addr", "add", f"{HOST_IP}/24", "dev", HOST_IF)
    _run("ip", "link", "set", HOST_IF, "up")
    _run("ip", "netns", "exec", NS, "ip", "addr", "add", f"{CLIENT_IP}/24", "dev", CLIENT_IF)
    _run("ip", "netns", "exec", NS, "ip", "link", "set", CLIENT_IF, "up")
    _run("ip", "netns", "exec", NS, "ip", "link", "set", "lo", "up")


def _network_cleanup() -> None:
    subprocess.run(["ip", "netns", "del", NS], check=False, capture_output=True)
    subprocess.run(["ip", "link", "del", HOST_IF], check=False, capture_output=True)


class A2SServer(threading.Thread):
    daemon = True

    def __init__(self):
        super().__init__()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((HOST_IP, QUERY_PORT))
        self.sock.settimeout(0.2)
        self.stop_event = threading.Event()

    @staticmethod
    def _response() -> bytes:
        return (
            b"\xff\xff\xff\xff\x49\x11"
            b"Capivara Broadcast E2E\x00"
            b"chernarusplus\x00"
            b"dayz\x00"
            b"DayZ\x00"
            + struct.pack("<H", 1234)
            + bytes((3, 60, 0))
        )

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                payload, peer = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            if payload.startswith(_A2S_REQUEST):
                self.sock.sendto(self._response(), peer)

    def close(self) -> None:
        self.stop_event.set()
        self.join(timeout=2)
        self.sock.close()


def _external_query() -> dict[str, Any]:
    code = (
        "import json,sys; "
        f"sys.path.insert(0,{str(LINUX_RUNTIME)!r}); "
        "import instance_telemetry; "
        f"print(json.dumps(instance_telemetry._a2s_info({HOST_IP!r},{QUERY_PORT},1)))"
    )
    completed = _run("ip", "netns", "exec", NS, "python3", "-c", code)
    raw = completed.stdout.strip().splitlines()
    return json.loads(raw[-1]) if raw else {}


def _spec(instance_id: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "catalog_runtime_policy": {
            "network_exposure": [
                {"name": "game", "protocol": "udp", "exposure": "public"},
                {"name": "steam_query", "protocol": "udp", "exposure": "public"},
                {"name": "admin", "protocol": "tcp", "exposure": "private"},
            ]
        },
        "ports": {
            "game": {"port": QUERY_PORT - 3, "protocol": "udp"},
            "steam_query": {"port": QUERY_PORT, "protocol": "udp"},
            "admin": {"port": QUERY_PORT + 1, "protocol": "tcp"},
        },
    }


def main() -> int:
    if os.geteuid() != 0:
        raise SystemExit("native Linux broadcast E2E must run as root")

    instance_id = _instance_id()
    desired = reconciler._validate_rules(instance_id, privileged_firewall.public_rules(_spec(instance_id)))
    query_rules = [rule for rule in desired if rule.get("name") == "steam_query"]
    if len(query_rules) != 1 or query_rules[0].get("port") != QUERY_PORT:
        raise AssertionError(f"steam_query exposure did not resolve correctly: {desired!r}")

    _network_setup()
    server = A2SServer()
    server.start()
    reconciler.reconcile_ufw(instance_id, [])
    try:
        before = _external_query()
        if before:
            raise AssertionError(f"A2S was externally reachable before managed exposure: {before!r}")

        result = reconciler.reconcile_ufw(instance_id, desired)
        if result.get("backend") != "ufw" or not result.get("changed"):
            raise AssertionError(f"managed UFW exposure was not created: {result!r}")

        after = _external_query()
        if after.get("players_online") != 3 or after.get("players_max") != 60:
            raise AssertionError(f"external A2S query did not cross managed firewall: {after!r}")
        if after.get("latency_ms") is None:
            raise AssertionError(f"external A2S query did not report latency: {after!r}")

        removed = reconciler.reconcile_ufw(instance_id, [])
        if not removed.get("changed"):
            raise AssertionError(f"managed query exposure was not removed: {removed!r}")
        final = _external_query()
        if final:
            raise AssertionError(f"A2S remained externally reachable after teardown: {final!r}")

        print(json.dumps({
            "status": "passed",
            "protocol": "A2S_INFO/udp",
            "query_port": QUERY_PORT,
            "players_online": after["players_online"],
            "players_max": after["players_max"],
            "latency_ms": after["latency_ms"],
            "blocked_before_reconcile": True,
            "reachable_after_reconcile": True,
            "blocked_after_teardown": True,
        }, indent=2))
        return 0
    finally:
        try:
            reconciler.reconcile_ufw(instance_id, [])
        finally:
            server.close()
            _network_cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
