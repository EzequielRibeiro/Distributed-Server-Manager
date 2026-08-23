#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import local_cli


class AgentLocalCliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp.name) / "agent.json"
        self.config = {
            "agent_id": "agent-one",
            "node_id": "node-one",
            "name": "Agent One",
            "controller_id": "controller-one",
            "controller_url": "https://controller.example",
            "credential_id": "cred-one",
            "credential_secret": "must-never-be-returned",
            "credential_type": "opaque-v1",
            "fingerprint": "sha256:test",
            "capivara_version": "1.0.0",
            "heartbeat_interval_seconds": 30,
            "degraded_after_seconds": 60,
            "offline_after_seconds": 120,
        }
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        self.original_config = local_cli.CONFIG_PATH
        local_cli.CONFIG_PATH = self.config_path

    def tearDown(self):
        local_cli.CONFIG_PATH = self.original_config
        self.temp.cleanup()

    def test_identity_never_exposes_credential_secret(self):
        identity = local_cli._identity(self.config)
        self.assertTrue(identity["enrolled"])
        self.assertNotIn("credential_secret", identity)
        self.assertNotIn("credential_id", identity)

    def test_local_doctor_is_healthy_without_game_or_port_cache(self):
        with patch.object(local_cli, "_service_state", return_value={
            "service": "capivara-agent.service",
            "available": True,
            "load_state": "loaded",
            "active_state": "active",
            "sub_state": "running",
            "healthy": True,
        }), patch.object(local_cli, "_controller_probe", return_value={
            "configured": True,
            "reachable": True,
            "status_code": 200,
        }), patch.object(local_cli, "detect_capabilities", return_value={"native-linux": True}), patch.object(
            local_cli,
            "collect_network_inventory",
            return_value={"source": "ss", "tcp_listen": [], "udp_listen": []},
        ), patch.object(local_cli, "_host", return_value={
            "hostname": "agent-one",
            "os": "linux",
            "architecture": "x86_64",
            "cpu_logical_cores": 4,
            "ram_total_bytes": 8 * 1024**3,
            "storage_root_total_bytes": 100 * 1024**3,
            "storage_root_free_bytes": 50 * 1024**3,
        }):
            result = local_cli._doctor(self.config)
        self.assertEqual(result["status"], "healthy")
        self.assertTrue(result["ready"])
        self.assertEqual(result["kind"], "CapivaraAgentDoctor")
        self.assertEqual(
            {item["code"] for item in result["findings"]},
            {"port_ranges_not_cached"},
        )

    def test_ports_check_reports_observed_socket_overlap(self):
        config = self.config | {
            "port_ranges": [
                {"protocol": "udp", "start_port": 24000, "end_port": 24999}
            ]
        }
        with patch.object(
            local_cli,
            "collect_network_inventory",
            return_value={"source": "ss", "tcp_listen": [], "udp_listen": [2302, 24005, 27016]},
        ):
            result = local_cli._ports(config)
        self.assertTrue(result["configured"])
        self.assertEqual(result["conflict_count"], 1)
        self.assertEqual(result["conflicts"][0]["occupied"], [24005])

    def test_cap_agent_status_json_uses_local_runtime(self):
        with patch.object(local_cli, "_service_state", return_value={"active_state": "active"}), patch.object(
            local_cli,
            "_controller_probe",
            return_value={"reachable": True},
        ):
            output = StringIO()
            with redirect_stdout(output):
                code = local_cli.main(["agent", "status", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["agent_id"], "agent-one")
        self.assertTrue(payload["controller_reachable"])


    def test_human_emit_formats_nested_structures(self):
        payload = {
            "identity": {
                "agent_id": "agent-one",
                "enrolled": True,
            },
            "ports": [
                {
                    "protocol": "udp",
                    "start_port": 24000,
                    "end_port": 24999,
                    "occupied": [24005, 24006],
                }
            ],
            "note": None,
        }

        output = StringIO()
        with redirect_stdout(output):
            local_cli._emit(payload, as_json=False)

        rendered = output.getvalue()

        self.assertIn("identity:\n", rendered)
        self.assertIn("  agent_id: agent-one\n", rendered)
        self.assertIn("  enrolled: true\n", rendered)
        self.assertIn("ports:\n", rendered)
        self.assertIn("  -\n", rendered)
        self.assertIn("    protocol: udp\n", rendered)
        self.assertIn("    occupied:\n", rendered)
        self.assertIn("      - 24005\n", rendered)
        self.assertIn("      - 24006\n", rendered)
        self.assertIn("note: -\n", rendered)

        self.assertNotIn('{"agent_id":', rendered)
        self.assertNotIn('[{"protocol":', rendered)

    def test_human_emit_logs_are_printed_as_terminal_lines(self):
        payload = {
            "service": "capivara-agent.service",
            "ok": True,
            "lines": [
                "2026-08-22T03:48:51+00:00 Node1 systemd[1]: Started capivara-agent.service",
                "2026-08-22T03:48:52+00:00 Node1 python3[6097]: heartbeat ok",
            ],
        }

        output = StringIO()
        with redirect_stdout(output):
            local_cli._emit(payload, as_json=False)

        rendered = output.getvalue()

        self.assertEqual(
            rendered,
            "service: capivara-agent.service\n"
            "ok: true\n"
            "\n"
            "2026-08-22T03:48:51+00:00 Node1 systemd[1]: Started capivara-agent.service\n"
            "2026-08-22T03:48:52+00:00 Node1 python3[6097]: heartbeat ok\n",
        )
        self.assertNotIn("lines:", rendered)
        self.assertNotIn('["2026-', rendered)

    def test_json_emit_preserves_structured_payload(self):
        payload = {
            "service": "capivara-agent.service",
            "ok": True,
            "lines": ["line-one", "line-two"],
        }

        output = StringIO()
        with redirect_stdout(output):
            local_cli._emit(payload, as_json=True)

        rendered = json.loads(output.getvalue())

        self.assertEqual(rendered, payload)

if __name__ == "__main__":
    unittest.main()
