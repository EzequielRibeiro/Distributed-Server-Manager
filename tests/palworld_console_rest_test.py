#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import console_client
import palworld_rest_console as console
from runtime_workspace_catalog import runtime_workspace_capabilities


class _Response:
    def __init__(self, status=200, payload=b""):
        self.status = status
        self.payload = payload

    def read(self, limit):
        return self.payload[:limit]


class _Connection:
    instances = []

    def __init__(self, host, port, timeout):
        self.host = host; self.port = port; self.timeout = timeout; self.request_data = None
        self.__class__.instances.append(self)

    def request(self, method, path, body=None, headers=None):
        self.request_data = (method, path, body, dict(headers or {}))

    def getresponse(self):
        return _Response(200, b'{"servername":"Capivara Palworld"}')

    def close(self):
        pass


class PalworldRestConsoleTest(unittest.TestCase):
    def setUp(self):
        _Connection.instances.clear()
        self.tmp = tempfile.TemporaryDirectory()
        state = Path(self.tmp.name) / "instance"
        config = state / "Pal" / "Saved" / "Config" / "LinuxServer"
        config.mkdir(parents=True)
        self.settings = config / "PalWorldSettings.ini"
        self.settings.write_text(
            '[/Script/Pal.PalGameWorldSettings]\nOptionSettings=(AdminPassword="secret-value",RESTAPIEnabled=True,RESTAPIPort=24012)\n',
            encoding="utf-8",
        )
        self.record = {
            "game_id": "palworld",
            "instance_state_root": str(state),
            "configuration_root": str(config),
            "ports": {"rest_api": {"port": 24012, "protocol": "tcp"}},
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_workspace_declares_palworld_console_support(self):
        capabilities = runtime_workspace_capabilities(ROOT, "palworld", "palworld.stable")
        self.assertTrue(capabilities["console"]["supported"])

    def test_info_uses_localhost_rest_api_and_never_returns_password(self):
        with patch("palworld_rest_console.http.client.HTTPConnection", _Connection):
            output = console.execute(self.record, "/Info")
        connection = _Connection.instances[-1]
        self.assertEqual("127.0.0.1", connection.host)
        self.assertEqual(24012, connection.port)
        method, path, body, headers = connection.request_data
        self.assertEqual(("GET", "/v1/api/info", None), (method, path, body))
        self.assertTrue(headers["Authorization"].startswith("Basic "))
        self.assertNotIn("secret-value", "\n".join(output))
        self.assertIn("Capivara Palworld", "\n".join(output))

    def test_generic_console_client_dispatches_palworld_rest_transport(self):
        record = {**self.record, "instance_id": "pal-1", "agent_id": "agent-1", "console": {"supported": True, "transport": "palworld-rest"}}
        with patch("console_client.instance_runtime.get_instance", return_value=record), patch("palworld_rest_console.execute", return_value=["ok"]) as execute:
            result = console_client.execute({"agent_id": "agent-1"}, "pal-1", "/Info")
        self.assertEqual(["ok"], result)
        execute.assert_called_once_with(record, "/Info")

    def test_show_players_does_not_expose_ip_or_location(self):
        payload = {"players": [{"name": "Alice", "userId": "steam_1", "ip": "203.0.113.8", "location_x": 10, "location_y": 20, "level": 5, "ping": 12.5}]}
        with patch("palworld_rest_console._request", return_value=payload):
            output = console.execute(self.record, "/ShowPlayers")
        text = "\n".join(output)
        self.assertIn("Alice", text);self.assertIn("steam_1", text)
        self.assertNotIn("203.0.113.8", text);self.assertNotIn("location", text.lower())

    def test_broadcast_maps_to_announce_json(self):
        with patch("palworld_rest_console.http.client.HTTPConnection", _Connection):
            console.execute(self.record, "/Broadcast Manutenção em 10 minutos")
        method, path, body, _headers = _Connection.instances[-1].request_data
        self.assertEqual(("POST", "/v1/api/announce"), (method, path))
        self.assertEqual({"message": "Manutenção em 10 minutos"}, json.loads(body.decode("utf-8")))

    def test_admin_password_command_is_blocked_before_transport(self):
        with self.assertRaisesRegex(console.PalworldConsoleError, "blocked"):
            console.execute(self.record, "/AdminPassword dont-store-this")

    def test_missing_admin_password_is_actionable(self):
        self.settings.write_text("OptionSettings=(AdminPassword=\"\",RESTAPIEnabled=True,RESTAPIPort=24012)\n", encoding="utf-8")
        with self.assertRaisesRegex(console.PalworldConsoleError, "AdminPassword is not configured"):
            console.execute(self.record, "/Save")

    def test_disabled_rest_api_is_actionable(self):
        self.settings.write_text('OptionSettings=(AdminPassword="secret-value",RESTAPIEnabled=False,RESTAPIPort=24012)\n', encoding="utf-8")
        with self.assertRaisesRegex(console.PalworldConsoleError, "REST API is disabled"):
            console.execute(self.record, "/Save")

    def test_shutdown_commands_do_not_bypass_capivara_desired_state(self):
        for command in ("/Shutdown 10 maintenance", "/DoExit"):
            with self.subTest(command=command), self.assertRaisesRegex(console.PalworldConsoleError, "lifecycle management"):
                console.execute(self.record, command)

    def test_player_context_only_commands_fail_closed(self):
        with self.assertRaisesRegex(console.PalworldConsoleError, "in-game administrator context"):
            console.execute(self.record, "/TeleportToMe steam_123")


if __name__ == "__main__":
    unittest.main()
