#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import cap_dispatch  # noqa: E402
import local_cli  # noqa: E402


class HybridAgentHealthParityTest(unittest.TestCase):
    def test_hybrid_health_uses_embedded_transport_without_controller_ping(self) -> None:
        with (
            patch.object(cap_dispatch, "_hybrid_identity", return_value=({}, "agent-hybrid", "node-hybrid")),
            patch.object(local_cli, "_service_state", return_value={"healthy": True, "active_state": "active"}),
            patch.object(local_cli, "_controller_probe", side_effect=AssertionError("Hybrid health must not call /ping")),
        ):
            payload = cap_dispatch._hybrid_health()

        self.assertTrue(payload["healthy"])
        self.assertEqual(payload["mode"], "hybrid")
        self.assertEqual(payload["controller"]["transport"], "embedded-database")
        self.assertTrue(payload["controller"]["reachable"])

    def test_standalone_health_keeps_controller_probe(self) -> None:
        controller = {"configured": True, "reachable": True, "status_code": 200}
        output = io.StringIO()
        with (
            patch.object(local_cli, "_read_config", return_value={"controller_url": "https://controller.example"}),
            patch.object(local_cli, "_service_state", return_value={"healthy": True, "active_state": "active"}),
            patch.object(local_cli, "_controller_probe", return_value=controller) as probe,
            redirect_stdout(output),
        ):
            code = local_cli.main(["health", "--json"])

        self.assertEqual(code, 0)
        probe.assert_called_once()
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["controller"], controller)


if __name__ == "__main__":
    unittest.main()
