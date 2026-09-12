#!/usr/bin/env python3
from __future__ import annotations

import json
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
DATABASE = ROOT / "database"
for path in (RUNTIME, DASHBOARD, DATABASE):
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

    def test_systemd_cgroup_returns_safe_control_group(self):
        completed = SimpleNamespace(
            returncode=0,
            stdout="/system.slice/capivara-instance-dayz-001.service\n",
        )
        with patch.object(telemetry.subprocess, "run", return_value=completed) as run:
            value = telemetry._systemd_cgroup("dayz-001")
        self.assertEqual(value, "/system.slice/capivara-instance-dayz-001.service")
        command = run.call_args.args[0]
        self.assertIn("capivara-instance-dayz-001.service", command)
        self.assertIn("--property=ControlGroup", command)

        unsafe = SimpleNamespace(returncode=0, stdout="/system.slice/../escape\n")
        with patch.object(telemetry.subprocess, "run", return_value=unsafe):
            self.assertIsNone(telemetry._systemd_cgroup("dayz-001"))

    def test_cgroup_usage_reads_aggregate_cpu_and_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group = root / "system.slice" / "capivara-instance-dayz-001.service"
            group.mkdir(parents=True)
            (group / "cpu.stat").write_text(
                "usage_usec 3456789\nuser_usec 2000000\nsystem_usec 1456789\n",
                encoding="utf-8",
            )
            (group / "memory.current").write_text("987654321\n", encoding="utf-8")
            with patch.object(telemetry, "CGROUP_ROOT", root):
                self.assertEqual(
                    telemetry._cgroup_usage("/system.slice/capivara-instance-dayz-001.service"),
                    (3456789, 987654321),
                )
                self.assertEqual(telemetry._cgroup_usage("/../escape"), (None, None))

    def test_cpu_counter_does_not_mix_proc_and_cgroup_units(self):
        with tempfile.TemporaryDirectory() as directory:
            samples = Path(directory) / "samples"
            with patch.object(telemetry, "SAMPLE_STATE_DIR", samples), patch.object(
                telemetry.time,
                "monotonic",
                side_effect=[100.0, 102.0, 104.0, 106.0],
            ):
                self.assertIsNone(
                    telemetry._cpu_percent_from_counter(
                        "dayz-001", 1_000_000, units_per_second=1_000_000, source="cgroup-v2"
                    )
                )
                self.assertEqual(
                    telemetry._cpu_percent_from_counter(
                        "dayz-001", 2_000_000, units_per_second=1_000_000, source="cgroup-v2"
                    ),
                    50.0,
                )
                self.assertIsNone(
                    telemetry._cpu_percent_from_counter(
                        "dayz-001", 100, units_per_second=100, source="proc"
                    )
                )
                self.assertEqual(
                    telemetry._cpu_percent_from_counter(
                        "dayz-001", 200, units_per_second=100, source="proc"
                    ),
                    50.0,
                )

    def test_collect_systemd_prefers_cgroup_for_cpu_and_memory(self):
        record = {
            "instance_id": "dayz-001",
            "agent_id": "agent-001",
            "adapter": "systemd",
            "game_id": "test-game",
            "instance_state_root": "/instance",
        }
        with patch.object(telemetry.instance_runtime, "list_instances", return_value=[record]), patch.object(
            telemetry.instance_runtime, "get_instance", return_value=record
        ), patch.object(telemetry.instance_runtime, "status", return_value={"observed_state": "running"}), patch.object(
            telemetry, "_systemd_main_pid", return_value=123
        ), patch.object(telemetry, "_systemd_cgroup", return_value="/system.slice/test.service"), patch.object(
            telemetry, "_cgroup_usage", return_value=(3_000_000, 987654321)
        ), patch.object(telemetry, "_cgroup_cpu_percent", return_value=72.5), patch.object(
            telemetry, "_proc_stat", return_value=(100, 0)
        ), patch.object(telemetry, "_rss_bytes") as rss, patch.object(
            telemetry, "_host_uptime", return_value=10.0
        ), patch.object(telemetry, "_systemd_network", return_value=(None, None)), patch.object(
            telemetry, "_network", return_value=(None, None)
        ), patch.object(telemetry, "_storage_used", return_value=None), patch.object(
            telemetry, "_game_query", return_value={}
        ):
            result = telemetry.collect_instance_telemetry({"agent_id": "agent-001"})[0]
        self.assertEqual(result["cpu_percent"], 72.5)
        self.assertEqual(result["memory_bytes"], 987654321)
        rss.assert_not_called()

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

    def test_effective_workspace_policy_fills_only_missing_catalog_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog = root / "catalog" / "v2" / "games" / "dayz"
            catalog.mkdir(parents=True)
            (catalog / "resource-profiles.json").write_text(
                json.dumps({
                    "schema_version": 2,
                    "kind": "GameResourceProfiles",
                    "game": "dayz",
                    "default_profile_id": "medium",
                    "profiles": [{
                        "id": "medium",
                        "name": "Medium",
                        "cpu_cores": 2,
                        "memory_mb": 4096,
                        "storage_mb": 20480,
                    }],
                }),
                encoding="utf-8",
            )
            service = object.__new__(CustomerInstanceWorkspaceService)
            service.root = root
            policy = service._effective_workspace_policy(
                {"id": "dayz-001", "game_id": "dayz"},
                {
                    "resource_profile_id": "medium",
                    "cpu_limit_cores": None,
                    "memory_limit_bytes": None,
                    "storage_limit_bytes": 999,
                },
            )
        self.assertEqual(policy["cpu_limit_cores"], 2.0)
        self.assertEqual(policy["memory_limit_bytes"], 4096 * 1024 * 1024)
        self.assertEqual(policy["storage_limit_bytes"], 999)

    def test_workspace_keeps_usage_separate_from_quota(self):
        service = object.__new__(CustomerInstanceWorkspaceService)
        service.root = ROOT
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
