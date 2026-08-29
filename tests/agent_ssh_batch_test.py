#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


batch = load_module("agent_batch_targets_tested", ROOT / "database" / "agent_batch_targets.py")


class BatchTargetParserTest(unittest.TestCase):
    def csv(self, content: str) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".csv", encoding="utf-8", delete=False)
        handle.write(content)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)

    def test_minimal_csv_uses_global_defaults(self):
        targets = batch.load_csv_targets(
            self.csv("host,name\n192.0.2.10,Node-01\n192.0.2.11,Node-02\n"),
            defaults={"ssh_user": "admin", "ssh_port": 2222, "identity_file": "/keys/dc.key"},
        )
        self.assertEqual([x.host for x in targets], ["192.0.2.10", "192.0.2.11"])
        self.assertEqual(targets[0].ssh_user, "admin")
        self.assertEqual(targets[0].ssh_port, 2222)
        self.assertEqual(targets[0].identity_file, "/keys/dc.key")
        self.assertIsNone(targets[0].password_file)

    def test_row_password_replaces_global_identity(self):
        targets = batch.load_csv_targets(
            self.csv("host,user,password_file,identity_file\n192.0.2.10,admin,/secrets/one.secret,\n"),
            defaults={"ssh_user": "default", "identity_file": "/keys/global.key"},
        )
        self.assertEqual(targets[0].password_file, "/secrets/one.secret")
        self.assertIsNone(targets[0].identity_file)

    def test_row_identity_replaces_global_password(self):
        targets = batch.load_csv_targets(
            self.csv("host,user,password_file,identity_file\n192.0.2.10,admin,,/keys/one.key\n"),
            defaults={"ssh_user": "default", "password_file": "/secrets/global.secret"},
        )
        self.assertEqual(targets[0].identity_file, "/keys/one.key")
        self.assertIsNone(targets[0].password_file)

    def test_raw_password_column_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "never contain raw passwords"):
            batch.load_csv_targets(self.csv("host,user,password\n192.0.2.10,admin,secret\n"))

    def test_conflicting_row_auth_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "either password_file or identity_file"):
            batch.load_csv_targets(
                self.csv("host,user,password_file,identity_file\n192.0.2.10,admin,/s,/k\n")
            )

    def test_duplicate_host_and_port_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate host/port"):
            batch.load_csv_targets(
                self.csv("host,user,port\n192.0.2.10,admin,22\n192.0.2.10,root,22\n")
            )

    def test_concurrency_is_bounded(self):
        self.assertEqual(batch.normalize_concurrency(1), 1)
        self.assertEqual(batch.normalize_concurrency(20), 20)
        with self.assertRaises(ValueError):
            batch.normalize_concurrency(0)
        with self.assertRaises(ValueError):
            batch.normalize_concurrency(21)


class DashboardContractTest(unittest.TestCase):
    def test_linux_and_windows_offer_batch_and_both_auth_methods(self):
        for relative in ("dashboard/web/add-agent-linux.html", "dashboard/web/add-agent-windows.html"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn('name="agent-ssh-mode" value="single"', text)
            self.assertIn('name="agent-ssh-mode" value="batch"', text)
            self.assertIn('name="agent-ssh-auth" value="password"', text)
            self.assertIn('name="agent-ssh-auth" value="key"', text)
            self.assertIn('id="agent-ssh-csv"', text)
            self.assertIn('id="agent-identity-file"', text)
            self.assertIn('id="agent-password-file"', text)

    def test_wizard_uses_batch_preflight_and_deploy_endpoints(self):
        text = (ROOT / "dashboard/web/agent-installation-wizard.js").read_text(encoding="utf-8")
        self.assertIn('/agents/installations/test-connections', text)
        self.assertIn('/agents/installations/batch', text)
        self.assertIn("Testar todos", text)
        self.assertIn("batchReadyTargets", text)

    def test_http_layer_exposes_batch_paths(self):
        text = (ROOT / "dashboard/agent_installation_http.py").read_text(encoding="utf-8")
        self.assertIn('AGENT_INSTALLATIONS_BATCH_PATH = "/api/agents/installations/batch"', text)
        self.assertIn('AGENT_INSTALLATION_TEST_BATCH_PATH = "/api/agents/installations/test-connections"', text)
        server = (ROOT / "dashboard/server_part12.py").read_text(encoding="utf-8")
        self.assertIn("AGENT_INSTALLATIONS_BATCH_PATH", server)
        self.assertIn("AGENT_INSTALLATION_TEST_BATCH_PATH", server)

    def test_documentation_has_cli_and_csv_examples(self):
        text = (ROOT / "docs/agents/remote-deployment/ssh-batch.md").read_text(encoding="utf-8")
        self.assertIn("cap agent test-connection", text)
        self.assertIn("cap agent deploy", text)
        self.assertIn("--hosts-file hosts.csv", text)
        self.assertIn("host,name,user,port", text)
        self.assertIn("--password-file", text)
        self.assertIn("--identity-file", text)


if __name__ == "__main__":
    unittest.main()
