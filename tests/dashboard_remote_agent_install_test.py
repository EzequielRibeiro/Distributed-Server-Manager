#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core", ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_installation_api import create_agent_installation_for_user, agent_installation_status_for_user
from agent_remote_http import dispatch_enroll
from agent_ssh_deploy import SSHResult
from backend import DatabaseConfig
from backend_factory import create_backend
from location_admin_api import upsert_datacenter_for_user, upsert_region_for_user
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class DashboardRemoteAgentInstallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        identity = installation_profile_identity(
            RegistryRepository(self.backend), profile="controller", hostname="remote-install-controller"
        )
        self.controller_id = identity["controller_id"]
        self.admin = {"role": "admin", "username": "admin"}
        self.controller = {
            "role": "controller",
            "scope_id": self.controller_id,
            "username": "controller",
        }
        upsert_region_for_user(
            self.admin,
            self.backend,
            {"id": "br-se", "name": "Brasil Sudeste", "country_code": "BR"},
        )
        upsert_datacenter_for_user(
            self.admin,
            self.backend,
            {"id": "dc-one", "region_id": "br-se", "name": "DC One"},
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def pairing_count(self):
        with self.backend.connect() as connection:
            return connection.execute("SELECT COUNT(*) AS total FROM agent_pairing_tokens").fetchone()["total"]

    def test_ssh_preflight_happens_before_pairing_and_remote_result_has_no_secret(self):
        calls = []

        def runner(argv, stdin_text, timeout):
            calls.append((list(argv), stdin_text, timeout))
            remote_command = argv[-1]
            if "CAPIVARA_PREFLIGHT_OK" in remote_command:
                return SSHResult(0, "CAPIVARA_PREFLIGHT_OK\nx86_64\n", "")
            if remote_command.startswith("test -f /var/lib/capivara-agent"):
                return SSHResult(1, "", "")
            if remote_command == "sudo -n python3 -":
                return SSHResult(0, "bootstrap ok", "")
            return SSHResult(1, "", "unexpected")

        result = create_agent_installation_for_user(
            self.controller,
            self.backend,
            {
                "platform": "linux",
                "method": "ssh",
                "region_id": "br-se",
                "datacenter_id": "dc-one",
                "controller_url": "https://controller.example",
                "ssh_host": "192.0.2.55",
                "ssh_user": "capadmin",
                "ssh_port": 22,
                "agent_name": "Remote Node",
                "port_protocol": "both",
                "port_start": 24000,
                "port_end": 24999,
            },
            ssh_runner=runner,
        )

        self.assertEqual(result["method"], "ssh")
        self.assertIsNone(result["instruction"])
        self.assertEqual(result["remote_bootstrap"]["state"], "completed")
        self.assertEqual(self.pairing_count(), 1)
        self.assertEqual(len(calls), 3)
        serialized = repr(result)
        self.assertNotIn("pairing-", serialized.lower())
        self.assertNotIn("token", serialized.lower())
        # The secret is carried only inside encrypted SSH stdin for bootstrap.
        self.assertIsNotNone(calls[2][1])
        self.assertNotIn("--pairing-token", " ".join(calls[2][0]))

    def test_failed_preflight_does_not_issue_pairing_token(self):
        def runner(argv, stdin_text, timeout):
            return SSHResult(1, "", "Permission denied (publickey)")

        with self.assertRaisesRegex(ValueError, "SSH preflight failed"):
            create_agent_installation_for_user(
                self.controller,
                self.backend,
                {
                    "platform": "linux",
                    "method": "ssh",
                    "region_id": "br-se",
                    "datacenter_id": "dc-one",
                    "controller_url": "https://controller.example",
                    "ssh_host": "192.0.2.55",
                    "ssh_user": "capadmin",
                },
                ssh_runner=runner,
            )
        self.assertEqual(self.pairing_count(), 0)

    def test_dashboard_rejects_ssh_password_without_issuing_token(self):
        with self.assertRaisesRegex(ValueError, "passwords are not accepted"):
            create_agent_installation_for_user(
                self.controller,
                self.backend,
                {
                    "platform": "linux",
                    "method": "ssh",
                    "region_id": "br-se",
                    "datacenter_id": "dc-one",
                    "controller_url": "https://controller.example",
                    "ssh_host": "192.0.2.55",
                    "ssh_user": "capadmin",
                    "ssh_password": "must-not-be-used",
                },
            )
        self.assertEqual(self.pairing_count(), 0)

    def test_port_range_and_name_are_applied_only_after_enrollment(self):
        installation = create_agent_installation_for_user(
            self.controller,
            self.backend,
            {
                "platform": "linux",
                "method": "github",
                "region_id": "br-se",
                "datacenter_id": "dc-one",
                "controller_url": "https://controller.example",
                "agent_name": "Prepared Node",
                "port_protocol": "udp",
                "port_start": 25000,
                "port_end": 25999,
            },
        )
        with self.backend.connect() as connection:
            before = connection.execute("SELECT COUNT(*) AS total FROM agent_port_ranges").fetchone()["total"]
        self.assertEqual(before, 0)

        token = installation["instruction"].split("--pairing-token ", 1)[1].split()[0]
        code, enrolled = dispatch_enroll(
            {
                "pairing_token": token,
                "agent_id": "agent-prepared",
                "node_id": "node-prepared",
                "name": "Generated Host Name",
                "fingerprint": "sha256:prepared",
                "hostname": "prepared",
                "os": "linux",
                "architecture": "x86_64",
            },
            backend=self.backend,
        )
        self.assertEqual(code, 201)
        self.assertTrue(enrolled["installation_tracking_bound"])

        with self.backend.connect() as connection:
            agent = connection.execute(
                "SELECT name FROM agents WHERE id='agent-prepared'"
            ).fetchone()
            ranges = connection.execute(
                "SELECT protocol,start_port,end_port FROM agent_port_ranges WHERE agent_id='agent-prepared'"
            ).fetchall()
        self.assertEqual(agent["name"], "Prepared Node")
        self.assertEqual([(r["protocol"], r["start_port"], r["end_port"]) for r in ranges], [("udp", 25000, 25999)])

        status = agent_installation_status_for_user(
            self.controller, self.backend, installation["installation_id"]
        )
        self.assertIsNotNone(status["preconfiguration"]["applied_at"])
        self.assertIsNone(status["preconfiguration"]["apply_error"])

    def test_ui_exposes_ssh_and_preconfiguration_without_password_field(self):
        html = (ROOT / "dashboard/web/agents.html").read_text(encoding="utf-8")
        js = (ROOT / "dashboard/web/agent-installation.js").read_text(encoding="utf-8")
        self.assertIn('value="ssh"', html)
        self.assertIn('id="agent-preconfig-port-start"', html)
        self.assertIn('id="agent-preconfig-port-end"', html)
        self.assertIn('id="agent-ssh-host"', html)
        self.assertNotIn('type="password"', html)
        self.assertIn("remote_bootstrap", js)
        self.assertIn("port_protocol", js)


if __name__ == "__main__":
    unittest.main()
