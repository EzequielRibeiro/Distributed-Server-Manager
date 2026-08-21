#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core", ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_deploy_cli import _preconfiguration_from_args, build_parser
from agent_installation_preconfiguration import normalize_preconfiguration


class AgentDeployPreconfigurationTest(unittest.TestCase):
    def parse(self, *extra: str):
        return build_parser().parse_args([
            "192.168.15.55",
            "--ssh-user",
            "usuario",
            *extra,
        ])

    def test_full_preconfiguration_contract(self):
        args = self.parse(
            "--name", "Agent Limeira 01",
            "--region-id", "br-se",
            "--datacenter-id", "limeira",
            "--port-range", "24000-24999",
            "--port-protocol", "both",
        )
        self.assertEqual(args.name, "Agent Limeira 01")
        self.assertEqual(args.region_id, "br-se")
        self.assertEqual(args.datacenter_id, "limeira")
        self.assertEqual(
            _preconfiguration_from_args(args),
            {
                "agent_name": "Agent Limeira 01",
                "port_protocol": "both",
                "port_start": 24000,
                "port_end": 24999,
            },
        )

    def test_port_protocol_defaults_to_both(self):
        settings = _preconfiguration_from_args(
            self.parse("--port-range", "24000-24999")
        )
        self.assertEqual(settings["port_protocol"], "both")

    def test_protocol_without_range_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "requires --port-range"):
            _preconfiguration_from_args(self.parse("--port-protocol", "udp"))

    def test_invalid_ranges_are_rejected_before_pairing(self):
        for value in ("24999-24000", "0-1000", "24000-70000", "abc-def", "24000"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _preconfiguration_from_args(self.parse("--port-range", value))

    def test_cli_uses_same_normalization_contract_as_dashboard(self):
        cli = _preconfiguration_from_args(
            self.parse(
                "--name", "Node 01",
                "--port-range", "25000-25999",
                "--port-protocol", "udp",
            )
        )
        dashboard_equivalent = normalize_preconfiguration({
            "agent_name": "Node 01",
            "port_start": 25000,
            "port_end": 25999,
            "port_protocol": "udp",
        })
        self.assertEqual(cli, dashboard_equivalent)


if __name__ == "__main__":
    unittest.main()
