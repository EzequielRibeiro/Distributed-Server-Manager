"""DSM #928: real Linux Agent Python process -> authenticated Controller HTTP.

Two separate short-lived processes import the real agents/linux/runtime/agent.py,
load a strictly disposable agent config, and call its real heartbeat() and
urllib _post(). The host inventory is stubbed to prevent machine/instance
discovery, so this is *not* an Agent run_forever() or real-game test.

No installed DSM, systemd unit or production endpoint is ever accessed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from update_game_uptime_sqlite_http_integration_test import (
    ActualDispatcherSqliteHttpTests,
)

ROOT = Path(__file__).resolve().parents[1]


# A fresh interpreter per invocation, not an in-process mock of HTTP calls.
# The actual Linux Agent imports/configuration/heartbeat/urllib protocol run.
_CHILD = r'''
import json
from contextlib import ExitStack
from pathlib import Path
import sys
from unittest.mock import patch

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "agents/linux/runtime"))
import agent as linux_agent
from game_uptime_agent_wire import build_probe

config = linux_agent._load_config()
agent_id = config["agent_id"]
payload = {
    "agent_id": agent_id,
    "hostname": "dsm928-agent-fixture",
    "os": "linux",
    "architecture": "x86_64",
    "capivara_version": "2.0.132",
    "fingerprint": config["fingerprint"],
    "heartbeat_interval_seconds": 30,
    "degraded_after_seconds": 60,
    "offline_after_seconds": 120,
}
if sys.argv[2] == "diagnostic":
    payload["no_drain_compatibility_probe"] = build_probe(agent_id)
elif sys.argv[2] != "legacy":
    raise ValueError("unknown fixture mode")

# Production inventory, command activation and game operations must never run.
# The fixture keeps the real Agent heartbeat protocol, HTTP client and
# config path handling. A command unexpectedly included in the response
# makes this CI case fail rather than operating on the test runner.
def forbid(*_a, **_k):
    raise AssertionError("unexpected game/update command in DSM928 fixture")

actions = (
    "stage_update_request", "stage_provisioning_command",
    "stage_storage_pool_migration", "stage_game_data_command",
    "handle_instance_command", "handle_console_command",
    "handle_file_command", "handle_artifact_command",
    "handle_native_restart_command", "handle_dayz_operation_command",
    "handle_yarax_admin_command", "handle_doctor_command",
    "handle_uninstall_command", "apply_content_commands",
    "apply_backup_commands", "apply_broadcast_commands",
    "apply_configuration_commands",
)
with ExitStack() as stack:
    stack.enter_context(patch.object(linux_agent, "_inventory", return_value=payload))
    for action in actions:
        stack.enter_context(patch.object(linux_agent, action, side_effect=forbid))
    # The real Controller may acknowledge an empty batch of telemetry events.
    # Only that no-op is allowed; any nonempty ACK is unsafe in this fixture.
    stack.enter_context(patch.object(
        linux_agent, "acknowledge_runtime_events",
        side_effect=lambda _state, ids: None if ids == [] else forbid(),
    ))
    result = linux_agent.heartbeat(config)

diagnostic = result.get("no_drain_wire_diagnostic")
if sys.argv[2] == "diagnostic":
    assert isinstance(diagnostic, dict), "missing real Agent diagnostic"
    assert diagnostic.get("wire_compatible") is True, diagnostic
    assert diagnostic.get("live_no_drain_authorized") is False, diagnostic
else:
    assert diagnostic is None, "legacy heartbeat received unexpected diagnostic"
assert result.get("health_status") == "online", result
assert result.get("agent_id") == agent_id, result
assert "update" not in result and "instance_command" not in result, result

saved = linux_agent._load_config()
assert saved["agent_id"] == agent_id
print(json.dumps({
    "wire_compatible": bool(diagnostic and diagnostic["wire_compatible"]),
    "live_no_drain_authorized": False,
    "health_status": result["health_status"],
    "agent_id": result["agent_id"],
    "controller_location_persisted":
        isinstance(saved.get("controller_location"), dict),
}, sort_keys=True))
'''


class LinuxAgentProcessHeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.controller = ActualDispatcherSqliteHttpTests(
            "test_credentialed_sqlite_controller_survives_restart_and_new_nonce")
        self.addCleanup(self.controller.doCleanups)
        self.controller.setUp()
        self.temp = tempfile.TemporaryDirectory(prefix="dsm928-agent-restart-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "agent.json"
        self.state = self.root / "runtime"
        self.state.mkdir(mode=0o700)

    def invoke(self, mode="diagnostic", *, invalid_secret=False):
        cfg = {
            "controller_url": self.controller.url.rsplit("/api/agent/heartbeat", 1)[0],
            "agent_id": self.controller.agent_id,
            "fingerprint": self.controller.fingerprint,
            "credential_id": self.controller.identity.credential_id,
            "credential_secret": (
                "wrong-agent-credential" if invalid_secret else
                self.controller.identity.credential_secret
            ),
        }
        self.config.write_text(json.dumps(cfg), encoding="utf-8")
        self.config.chmod(0o600)
        env = {
            **os.environ,
            "CAPIVARA_AGENT_CONFIG": str(self.config),
            "CAPIVARA_AGENT_STATE_DIR": str(self.state),
            "CAPIVARA_AGENT_HOST_IDENTITY": str(self.root / "host-identity"),
            "DSM928_COMPAT_DIAGNOSTIC": "1" if mode == "diagnostic" else "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        result = subprocess.run(
            [sys.executable, "-c", _CHILD, str(ROOT), mode],
            cwd=self.root, env=env,
            capture_output=True, text=True, timeout=25, check=False)
        return result

    def test_real_agent_process_reconnects_to_restarted_controller(self):
        first = self.invoke()
        self.assertEqual(first.returncode, 0, first.stderr[-1400:])
        a = json.loads(first.stdout.strip().splitlines()[-1])
        self.assertTrue(a["wire_compatible"])
        self.assertFalse(a["live_no_drain_authorized"])

        old_backend = self.controller.backend
        self.controller._restart_controller_dispatcher()
        self.assertIsNot(self.controller.backend, old_backend)
        second = self.invoke()
        self.assertEqual(second.returncode, 0, second.stderr[-1400:])
        b = json.loads(second.stdout.strip().splitlines()[-1])
        self.assertEqual(b["agent_id"], a["agent_id"])
        self.assertEqual(b["health_status"], "online")
        self.assertTrue(b["wire_compatible"])
        self.assertFalse(b["live_no_drain_authorized"])
        with sqlite3.connect(self.controller.db_path) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM agent_runtime_inventory WHERE agent_id=?",
                (self.controller.agent_id,),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_agent_legacy_mode_and_rejected_credential_fail_closed(self):
        result = self.invoke("legacy")
        self.assertEqual(result.returncode, 0, result.stderr[-1400:])
        value = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertFalse(value["wire_compatible"])
        denied = self.invoke("diagnostic", invalid_secret=True)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("Controller rejected request (401)", denied.stderr)
        self.assertNotIn("wire_compatible", denied.stdout)


if __name__ == "__main__":
    unittest.main()
