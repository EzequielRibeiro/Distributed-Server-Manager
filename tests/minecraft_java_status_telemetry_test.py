#!/usr/bin/env python3
"""Minecraft Java gameplay status, Agent routing and unknown-vs-zero regression."""
from __future__ import annotations

import importlib.util
import json
import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (
    ROOT / "agents" / "common",
    ROOT / "agents" / "linux" / "runtime",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import minecraft_java_status as status
import instance_telemetry as linux

WINDOWS_PATH = ROOT / "agents" / "windows" / "runtime" / "instance_telemetry.py"
SPEC = importlib.util.spec_from_file_location("windows_instance_telemetry_java_status", WINDOWS_PATH)
windows = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(windows)


class FakeStatusSocket:
    def __init__(self, payload):
        self.payload = payload
        self.sent = []
        self.timeout = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def settimeout(self, seconds):
        self.timeout = seconds

    def sendall(self, packet):
        self.sent.append(packet)

    def recv(self, size):
        if not self.payload:
            return b""
        # Deliberately fragment reads to check exact length handling.
        actual = min(size, 3)
        result, self.payload = self.payload[:actual], self.payload[actual:]
        return result


def response(players=None):
    if players is None:
        players = {"online": 1, "max": 20, "sample": [{"name": "private"}]}
    body = json.dumps({"players": players}).encode("utf-8")
    packet = status._varint(0) + status._varint(len(body)) + body
    return status._varint(len(packet)) + packet


class MinecraftJavaStatusTelemetryTest(unittest.TestCase):
    def test_protocol_reads_online_and_max_without_player_identity(self):
        fake = FakeStatusSocket(response())
        with patch.object(status.socket, "create_connection", return_value=fake) as connect:
            result = status.query_java_status(24008, 2)
        self.assertEqual(result["players_online"], 1)
        self.assertEqual(result["players_max"], 20)
        self.assertIsInstance(result["latency_ms"], float)
        self.assertNotIn("sample", result)
        connect.assert_called_once_with(("127.0.0.1", 24008), timeout=2)
        self.assertTrue(fake.sent[0].endswith(b"\x01\x00"))

    def test_zero_is_real_and_missing_or_broken_response_is_unknown(self):
        with patch.object(status.socket, "create_connection", return_value=FakeStatusSocket(
            response({"online": 0, "max": 20})
        )):
            self.assertEqual(status.query_java_status(24008)["players_online"], 0)
        for value in (b"", b"\xff\xff", response({"max": 20}), response({"online": -1, "max": 20})):
            with self.subTest(value=value), patch.object(
                status.socket, "create_connection", return_value=FakeStatusSocket(value),
            ):
                self.assertEqual(status.query_java_status(24008), {})
        with patch.object(status.socket, "create_connection", side_effect=socket.timeout):
            self.assertEqual(status.query_java_status(24008), {})

    def test_only_reserved_tcp_game_binding_is_queried(self):
        with patch.object(status, "query_java_status", return_value={"players_online": 3}) as ping:
            self.assertEqual(status.query_reserved_java_game_port(
                {"ports": {"game": {"port": 24008, "protocol": "tcp"}}}, {},
            ), {"players_online": 3})
            ping.assert_called_once_with(24008, 2)
            self.assertEqual(status.query_reserved_java_game_port(
                {"ports": {"rcon": {"port": 24009, "protocol": "tcp"}}}, {},
            ), {})
            self.assertEqual(status.query_reserved_java_game_port(
                {"ports": {"game": {"port": 24008, "protocol": "udp"}}}, {},
            ), {})
            ping.assert_called_once()

    def test_linux_collects_java_status_from_game_binding(self):
        record = {
            "instance_id": "mc-001", "game_id": "minecraft",
            "environment_id": "minecraft.java.vanilla", "adapter": "systemd",
            "ports": {"game": {"port": 24008, "protocol": "tcp"}},
        }
        with (
            patch.object(linux.instance_runtime, "list_instances", return_value=[record]),
            patch.object(linux.instance_runtime, "get_instance", return_value=record),
            patch.object(linux.instance_runtime, "status", return_value={"observed_state": "running"}),
            patch.object(linux, "_systemd_main_pid", return_value=None),
            patch.object(linux, "_systemd_resources", return_value=(None, None)),
            patch.object(linux, "_systemd_network", return_value=(None, None)),
            patch.object(linux, "_network", return_value=(None, None)),
            patch.object(linux, "_storage_used", return_value=None),
            patch.object(linux, "query_reserved_java_game_port",
                         return_value={"players_online": 1, "players_max": 20, "latency_ms": 4.2}) as ping,
        ):
            samples = linux.collect_instance_telemetry({"agent_id": "agent-test"})
        self.assertEqual(samples[0]["players_online"], 1)
        self.assertEqual(samples[0]["players_max"], 20)
        self.assertEqual(samples[0]["latency_ms"], 4.2)
        ping.assert_called_once_with(record, {})

    def test_windows_java_uses_same_protocol_and_does_not_probe_other_games(self):
        record = {
            "instance_id": "mc-001", "game_id": "minecraft",
            "environment_id": "minecraft.java.vanilla", "adapter": "windows-process",
            "ports": {"game": {"port": 24008, "protocol": "tcp"}},
        }
        with (
            patch.object(windows.instance_runtime, "list_instances", return_value=[record]),
            patch.object(windows.instance_runtime, "get_instance", return_value=record),
            patch.object(windows.instance_runtime, "status", return_value={"observed_state": "running"}),
            patch.object(windows, "_process_pid", return_value=None),
            patch.object(windows, "_process_values", return_value=(None, None, None)),
            patch.object(windows, "_storage_used", return_value=None),
            patch.object(windows, "query_reserved_java_game_port",
                         return_value={"players_online": 0, "players_max": 20}) as ping,
        ):
            samples = windows.collect_instance_telemetry({"agent_id": "agent-test"})
        self.assertEqual(samples[0]["players_online"], 0)
        self.assertEqual(samples[0]["players_max"], 20)
        ping.assert_called_once_with(record, {})
        record["game_id"] = "dayz"
        with (
            patch.object(windows.instance_runtime, "list_instances", return_value=[record]),
            patch.object(windows.instance_runtime, "get_instance", return_value=record),
            patch.object(windows.instance_runtime, "status", return_value={"observed_state": "running"}),
            patch.object(windows, "_process_pid", return_value=None),
            patch.object(windows, "_process_values", return_value=(None, None, None)),
            patch.object(windows, "_storage_used", return_value=None),
            patch.object(windows, "_query", return_value={"players_online": 7}) as other,
            patch.object(windows, "query_reserved_java_game_port") as java,
        ):
            self.assertEqual(windows.collect_instance_telemetry({})[0]["players_online"], 7)
        java.assert_not_called()
        other.assert_called_once()


if __name__ == "__main__":
    unittest.main()
