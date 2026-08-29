#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
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


class ExistingAgentProtectionContractTest(unittest.TestCase):
    def test_linux_presence_detector_uses_current_and_legacy_markers(self):
        text = (ROOT / "core/agent_ssh_deploy.py").read_text(encoding="utf-8")

        for marker in (
            "/etc/capivara-agent/agent.json",
            "/var/lib/capivara-agent/identity.json",
            "/etc/capivara-agent/agent.conf",
            "/etc/systemd/system/capivara-agent.service",
            "/opt/capivara-agent/runtime/agent.py",
        ):
            self.assertIn(marker, text)


class LinuxPackageManagerPreflightContractTest(unittest.TestCase):
    def test_linux_preflight_checks_dpkg_state(self):
        text = (ROOT / "core/agent_ssh_deploy.py").read_text(encoding="utf-8")
        self.assertIn("dpkg --audit", text)
        self.assertIn("/var/lib/dpkg/updates", text)
        self.assertIn("CAPIVARA_PACKAGE_MANAGER_NOT_READY", text)
        self.assertIn("dpkg --configure -a", text)


class LinuxPackageManagerPreflightBehaviorTest(unittest.TestCase):
    def test_broken_dpkg_state_is_rejected(self):
        deploy = load_module(
            "agent_ssh_deploy_dpkg_tested",
            ROOT / "core/agent_ssh_deploy.py",
        )

        def runner(argv, stdin_text, timeout):
            return deploy.SSHResult(
                returncode=42,
                stdout="",
                stderr=(
                    "The following packages are only half configured.\n"
                    "CAPIVARA_PACKAGE_MANAGER_NOT_READY: "
                    "dpkg audit reported incomplete package state\n"
                ),
            )

        options = deploy.SSHDeployOptions(
            host="192.0.2.10",
            ssh_user="root",
            ssh_port=22,
        )

        with self.assertRaisesRegex(
            deploy.AgentDeployError,
            "package manager is not ready",
        ):
            deploy.preflight_ssh(options, runner=runner)


class ControllerReversePreflightBehaviorTest(unittest.TestCase):
    def _module(self):
        return load_module(
            "agent_ssh_deploy_reverse_tested",
            ROOT / "core/agent_ssh_deploy.py",
        )

    def test_controller_https_reachability_succeeds(self):
        deploy = self._module()
        captured = {}

        def runner(argv, stdin_text, timeout):
            captured["argv"] = list(argv)
            return deploy.SSHResult(
                returncode=0,
                stdout="",
                stderr="",
            )

        result = deploy.preflight_controller_reachability(
            deploy.SSHDeployOptions(
                host="192.0.2.10",
                ssh_user="admin",
            ),
            "https://controller.example.test:9443",
            runner=runner,
        )

        self.assertTrue(result["controller_reachable"])
        self.assertTrue(result["controller_tls_verified"])

        command = captured["argv"][-1]
        self.assertIn(
            "https://controller.example.test:9443/health",
            command,
        )
        self.assertNotIn("--insecure", command)
        self.assertNotIn(" -k ", command)

    def test_controller_unreachable_is_rejected(self):
        deploy = self._module()

        def runner(argv, stdin_text, timeout):
            return deploy.SSHResult(
                returncode=7,
                stdout="",
                stderr="curl: (7) Failed to connect to controller",
            )

        with self.assertRaisesRegex(
            deploy.AgentDeployError,
            "Agent-to-Controller preflight failed",
        ):
            deploy.preflight_controller_reachability(
                deploy.SSHDeployOptions(
                    host="192.0.2.10",
                    ssh_user="admin",
                ),
                "https://controller.example.test:9443",
                runner=runner,
            )


class PublicCapEnvironmentContractTest(unittest.TestCase):
    def test_cap_exports_controller_public_url(self):
        text = (ROOT / "bin/cap").read_text(encoding="utf-8")
        self.assertIn(
            "export DSM_CONTROLLER_PUBLIC_URL DSM_CONTROLLER_URL "
            "DSM_PUBLIC_HOST DSM_PUBLIC_PORT",
            text,
        )


class LinuxHostIdentityContractTest(unittest.TestCase):
    def test_agent_reports_composite_host_identity(self):
        text = (
            ROOT / "agents/linux/runtime/agent.py"
        ).read_text(encoding="utf-8")

        self.assertIn("/etc/machine-id", text)
        self.assertIn("/sys/class/dmi/id/product_uuid", text)
        self.assertIn("/sys/class/net", text)
        self.assertIn("capivara-host-v1", text)
        self.assertIn('"host_identity": _host_identity()', text)

    def test_host_identity_does_not_depend_on_hostname(self):
        text = (
            ROOT / "agents/linux/runtime/agent.py"
        ).read_text(encoding="utf-8")

        start = text.index("def _host_identity(")
        end = text.index("\ndef ", start + 10)
        function = text[start:end]

        self.assertNotIn("gethostname", function)


class AgentIdentityCollisionContractTest(unittest.TestCase):
    def test_controller_validates_host_before_any_heartbeat_metadata_write(self):
        text = (
            ROOT / "dashboard/agent_heartbeat_api.py"
        ).read_text(encoding="utf-8")

        start = text.index("def record_agent_heartbeat(")
        function = text[start:]

        validation = function.index("_validate_host_identity(")
        metadata = function.index("_store_agent_metadata(")

        self.assertLess(validation, metadata)

    def test_controller_serializes_first_host_binding(self):
        text = (
            ROOT / "dashboard/agent_heartbeat_api.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "UPDATE agents SET metadata_json=metadata_json",
            text,
        )
        self.assertIn(
            "capivara_host_identity_v1",
            text,
        )
        self.assertIn(
            "AgentHostIdentityCollision",
            text,
        )

    def test_http_returns_conflict_for_identity_collision(self):
        text = (
            ROOT / "dashboard/agent_remote_http.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "except AgentHostIdentityCollision as exc:",
            text,
        )
        self.assertIn(
            '"error": "agent_identity_collision"',
            text,
        )
        self.assertIn(
            "return 409",
            text,
        )

    def test_bound_agent_missing_host_identity_fails_closed(self):
        text = (
            ROOT / "dashboard/agent_heartbeat_api.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "AgentHostIdentityRequired",
            text,
        )
        self.assertIn(
            '"status": "legacy-unbound"',
            text,
        )


class AgentIdentityIncidentContractTest(unittest.TestCase):
    def test_identity_collision_has_dedicated_rule(self):
        text = (
            ROOT / "database/agent_identity_incident_repository.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'RULE_ID = "agent.identity_collision"',
            text,
        )
        self.assertIn(
            '"event_type": "AGENT_IDENTITY_COLLISION"',
            text,
        )

    def test_identity_incident_is_not_heartbeat_auto_resolved(self):
        text = (
            ROOT / "dashboard/agent_remote_http.py"
        ).read_text(encoding="utf-8")

        collision = text.index(
            "except AgentHostIdentityCollision"
        )
        credential = text.index(
            "except AgentCredentialInvalid"
        )

        block = text[collision:credential]

        self.assertIn(
            "AgentIdentityIncidentRepository",
            block,
        )
        self.assertNotIn(
            "AgentLinkIncidentRepository",
            block,
        )

    def test_link_recovery_does_not_reference_identity_rule(self):
        text = (
            ROOT / "database/agent_link_incident_repository.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn(
            "agent.identity_collision",
            text,
        )


class CliContractTest(unittest.TestCase):
    def test_deploy_json_normalizes_database_timestamps(self):
        text = (ROOT / "database/agent_deploy_cli.py").read_text(encoding="utf-8")
        self.assertIn("def _json_timestamp(value):", text)
        self.assertIn('last_seen=_json_timestamp(runtime["last_seen"])', text)
        self.assertIn('"last_seen": _json_timestamp(online.get("last_seen"))', text)


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
