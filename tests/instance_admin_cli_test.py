#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from instance_admin_cli import _content_selection, _remote_occupied_ports, _runtime_definition


class InstanceAdminCliTest(unittest.TestCase):
    def test_dayz_runtime_is_selected_when_it_is_the_only_registered_variant(self):
        definition = _runtime_definition("dayz", None)
        self.assertEqual(definition["id"], "dayz.stable")
        self.assertEqual(definition["game"], "dayz")

    def test_dayz_content_selection_preserves_required_steam_auth_and_package(self):
        selection = _content_selection(_runtime_definition("dayz", "dayz.stable"))
        self.assertEqual(selection["provider"], "steam")
        self.assertEqual(selection["auth"], "required")
        self.assertEqual(selection["install"]["package_id"], "223350")

    def test_remote_port_provider_uses_agent_heartbeat_socket_inventory(self):
        provider = _remote_occupied_ports({
            "network": {
                "source": "ss",
                "tcp_listen": [22, 8080],
                "udp_listen": [2302, 2304, 27016],
            }
        })
        self.assertEqual(provider("agent", "node", "udp", 2300, 2310), {2302, 2304})
        self.assertEqual(provider("agent", "node", "tcp", 8000, 9000), {8080})


if __name__ == "__main__":
    unittest.main()
