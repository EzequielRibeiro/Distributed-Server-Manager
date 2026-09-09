#!/usr/bin/env python3
from __future__ import annotations

import socket
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
DASHBOARD = ROOT / "dashboard"
for path in (RUNTIME, DASHBOARD):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import instance_telemetry as telemetry
from materializers import systemd as systemd_materializer
from customer_instance_workspace_service import CustomerInstanceWorkspaceService


class _FakeSocket:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def settimeout(self, value):
        self.timeout = value

    def sendto(self, payload, address):
        self.sent.append((payload, address))
        return len(payload)

    def recvfrom(self, _size):
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response, ("127.0.0.1", 27016)


class _ContentPolicy:
    def as_dict(self):
        return {}


class InstanceRuntimeTelemetryTest(unittest.TestCase):
    @staticmethod
    def _a2s_info_payload(players=7, players_max=60):
        return (
            b"\xff\xff\xff\xffI"
            + bytes([17])
            + b"Capivara DayZ\x00chernarusplus\x00dayz\x00DayZ\x00"
            + (1234).to_bytes(2, "little")
            + bytes([players, players_max, 0])
        )

    def test_systemd_unit_enables_ip_accounting(self):
        spec = {
            "instance_id": "dayz-001",
            "agent_id": "agent-001",
            "runtime_id": "runtime-001",
            "user": "capivara-instance",
            "executable": "/opt/dayz/DayZServer",
            "arguments": [],
            "working_directory": "/opt/dayz",
            "instance_state_root": "/var/lib/capivara-instances/dayz-001",
        }
        rendered = systemd_materializer.render_unit(spec)
        self.assertIn("\nIPAccounting=yes\n", rendered)

    def test_systemd_network_returns_instance_counters(self):
        completed = SimpleNamespace(
            returncode=0,
            stdout="IPIngressBytes=123456\nIPEgressBytes=654321\n",
        )
        with patch.object(telemetry.subprocess, "run", return_value=completed) as run:
            self.assertEqual(telemetry._systemd_network("dayz-001"), (123456, 654321))
        command = run.call_args.args[0]
        self.assertIn("capivara-instance-dayz-001.service", command)
        self.assertIn("--property=IPIngressBytes", command)
        self.assertIn("--property=IPEgressBytes", command)

    def test_unavailable_systemd_network_is_unknown_not_zero(self):
        completed = SimpleNamespace(
            returncode=0,
            stdout="IPIngressBytes=[not set]\nIPEgressBytes=\n",
        )
        with patch.object(telemetry.subprocess, "run", return_value=completed):
            self.assertEqual(telemetry._systemd_network("dayz-001"), (None, None))

    def test_dayz_uses_reserved_steam_query_port(self):
        record = {"ports": {"steam_query": {"port": 27123, "protocol": "udp"}}}
        with patch.object(
            telemetry,
            "_a2s_info",
            return_value={"players_online": 5, "players_max": 60},
        ) as query:
            result = telemetry._dayz_query(record, {})
        self.assertEqual(result["players_online"], 5)
        query.assert_called_once_with("127.0.0.1", 27123, 2)

    def test_native_a2s_info_parses_players(self):
        fake = _FakeSocket([self._a2s_info_payload(players=11, players_max=64)])
        with patch.object(telemetry.socket, "socket", return_value=fake):
            result = telemetry._a2s_info("127.0.0.1", 27016, 1)
        self.assertEqual(result["players_online"], 11)
        self.assertEqual(result["players_max"], 64)
        self.assertIsInstance(result["latency_ms"], float)
        self.assertEqual(fake.sent[0][0], telemetry._A2S_INFO_REQUEST)

    def test_native_a2s_info_handles_challenge(self):
        challenge = b"\x01\x02\x03\x04"
        fake = _FakeSocket([
            b"\xff\xff\xff\xffA" + challenge,
            self._a2s_info_payload(players=3, players_max=50),
        ])
        with patch.object(telemetry.socket, "socket", return_value=fake):
            result = telemetry._a2s_info("127.0.0.1", 27016, 1)
        self.assertEqual(result["players_online"], 3)
        self.assertEqual(len(fake.sent), 2)
        self.assertEqual(fake.sent[1][0], telemetry._A2S_INFO_REQUEST + challenge)

    def test_native_a2s_failure_is_unknown(self):
        malformed = _FakeSocket([b"not-a2s"])
        with patch.object(telemetry.socket, "socket", return_value=malformed):
            self.assertEqual(telemetry._a2s_info("127.0.0.1", 27016, 1), {})
        timed_out = _FakeSocket([socket.timeout("timeout")])
        with patch.object(telemetry.socket, "socket", return_value=timed_out):
            self.assertEqual(telemetry._a2s_info("127.0.0.1", 27016, 1), {})

    def test_storage_zero_only_for_measurable_empty_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(telemetry._storage_used(directory), 0)
            Path(directory, "data.bin").write_bytes(b"abc")
            self.assertEqual(telemetry._storage_used(directory), 3)
            self.assertIsNone(telemetry._storage_used(directory, max_entries=0))
        self.assertIsNone(telemetry._storage_used("/path/that/does/not/exist"))
        self.assertIsNone(telemetry._storage_used(None))

    def test_storage_scan_error_is_unknown_not_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(telemetry.os, "walk", side_effect=OSError("denied")):
                self.assertIsNone(telemetry._storage_used(directory))

    def test_workspace_keeps_usage_separate_from_quota(self):
        service = object.__new__(CustomerInstanceWorkspaceService)
        service.repo = SimpleNamespace(
            workspace_policy=lambda _instance_id: {"storage_limit_bytes": 10_000},
            telemetry=lambda _instance_id, _limit: [{"storage_used_bytes": None}],
        )
        service.provisioning = SimpleNamespace(latest_for_instance=lambda _instance_id: None)
        service.require = lambda _user, _instance_id, _permission: {
            "id": "dayz-001",
            "name": "DayZ",
            "game_id": "dayz",
            "runtime_id": "dayz-runtime",
            "agent_id": "agent-001",
            "instance_metadata": {},
            "contract_metadata": {},
        }
        service.permissions = lambda _user, _instance_id: {"instance.view"}
        service._location = lambda _agent_id: {}
        service._ports = lambda _instance_id: []
        service._contract_policy = lambda _context, _policy: ({}, _ContentPolicy())

        result = service.overview({"role": "customer"}, "dayz-001")

        self.assertIsNone(result["storage"]["used_bytes"])
        self.assertEqual(result["storage"]["limit_bytes"], 10_000)
        self.assertIsNone(result["storage"]["percent"])
        self.assertIsNone(result["telemetry"]["storage_used_bytes"])


if __name__ == "__main__":
    unittest.main()
