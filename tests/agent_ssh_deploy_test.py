#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "core", ROOT / "database"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_deploy_cli import build_parser
from agent_ssh_prepare_cli import (
    build_parser as build_prepare_parser,
    parse_target,
    restricted_sudo_command,
)
from agent_deploy_topology import validate_deploy_location
from agent_ssh_deploy import (
    AgentDeployError,
    SSHDeployOptions,
    SSHResult,
    bootstrap_agent,
    build_ssh_argv,
    preflight_ssh,
    remote_agent_present,
    validate_host,
    validate_ssh_user,
    wait_for_agent_online,
)
from backend import DatabaseConfig
from backend_factory import create_backend


class AgentSSHDeployTest(unittest.TestCase):
    def test_cli_contract(self):
        args = build_parser().parse_args([
            "192.168.15.55",
            "--ssh-user",
            "ezequiel",
            "--ssh-port",
            "2222",
            "--controller-url",
            "http://192.168.15.35:8080",
        ])
        self.assertEqual(args.host, "192.168.15.55")
        self.assertEqual(args.ssh_user, "ezequiel")
        self.assertEqual(args.ssh_port, 2222)
        self.assertEqual(args.controller_url, "http://192.168.15.35:8080")

    def test_ssh_prepare_cli_contract_and_restricted_rule(self):
        args = build_prepare_parser().parse_args([
            "mine@192.168.15.55", "--ssh-port", "2222"
        ])
        self.assertEqual(parse_target(args.target), ("mine", "192.168.15.55"))
        self.assertEqual(args.ssh_port, 2222)
        command = restricted_sudo_command("mine")
        self.assertIn("NOPASSWD: %s, %s -", command)
        self.assertIn("capivara-agent-mine", command)
        self.assertNotIn("NOPASSWD: ALL", command)
        with self.assertRaises(AgentDeployError):
            parse_target("mine;id@192.168.15.55")

    def test_host_and_user_validation(self):
        self.assertEqual(validate_host("192.168.15.55"), "192.168.15.55")
        self.assertEqual(validate_host("agent-node02.local"), "agent-node02.local")
        self.assertEqual(validate_ssh_user("svc-capivara"), "svc-capivara")
        with self.assertRaises(AgentDeployError):
            validate_host("bad host;rm")
        with self.assertRaises(AgentDeployError):
            validate_ssh_user("user;id")

    def test_ssh_argv_is_structured_and_has_no_password_flag(self):
        with tempfile.TemporaryDirectory() as temp:
            key = Path(temp) / "id_ed25519"
            key.write_text("fake", encoding="utf-8")
            argv = build_ssh_argv(
                SSHDeployOptions(
                    host="192.168.15.55",
                    ssh_user="ezequiel",
                    ssh_port=2222,
                    identity_file=str(key),
                ),
                "uname -s",
            )
        self.assertEqual(argv[0], "ssh")
        self.assertIn("2222", argv)
        self.assertIn("ezequiel@192.168.15.55", argv)
        joined = " ".join(argv).lower()
        self.assertNotIn("password", joined)
        self.assertNotIn("stricthostkeychecking=no", joined)

    def test_preflight_is_read_only_and_requires_noninteractive_sudo(self):
        calls = []

        def runner(argv, stdin_text, timeout):
            calls.append((list(argv), stdin_text, timeout))
            return SSHResult(0, "CAPIVARA_PREFLIGHT_OK\nx86_64\n", "")

        result = preflight_ssh(
            SSHDeployOptions(host="192.168.15.55", ssh_user="ezequiel"),
            runner=runner,
        )
        self.assertEqual(result["platform"], "linux")
        self.assertEqual(result["architecture"], "x86_64")
        remote = calls[0][0][-1]
        self.assertIn("sudo -n true", remote)
        self.assertNotIn("apt ", remote)
        self.assertNotIn("mkdir", remote)

    def test_existing_agent_detection(self):
        def present(argv, stdin_text, timeout):
            return SSHResult(0, "", "")

        def absent(argv, stdin_text, timeout):
            return SSHResult(1, "", "")

        options = SSHDeployOptions(host="192.168.15.55", ssh_user="ezequiel")
        self.assertTrue(remote_agent_present(options, runner=present))
        self.assertFalse(remote_agent_present(options, runner=absent))

    def test_pairing_token_is_sent_only_via_stdin_not_ssh_argv(self):
        secret = "pairing-SUPER-SECRET"
        observed = {}

        def runner(argv, stdin_text, timeout):
            observed["argv"] = list(argv)
            observed["stdin"] = stdin_text
            return SSHResult(0, "", "")

        bootstrap_agent(
            SSHDeployOptions(host="192.168.15.55", ssh_user="ezequiel"),
            controller_url="http://192.168.15.35:8080",
            pairing_token=secret,
            runner=runner,
        )
        self.assertNotIn(secret, " ".join(observed["argv"]))
        self.assertIn(secret, observed["stdin"])
        self.assertEqual(observed["argv"][-1], "sudo -n python3 -")
        self.assertIn('env["CAPIVARA_PAIRING_TOKEN"]', observed["stdin"])
        self.assertNotIn('"--pairing-token", payload["pairing_token"]', observed["stdin"])

    def test_bootstrap_failure_does_not_echo_token(self):
        secret = "pairing-DO-NOT-PRINT"

        def runner(argv, stdin_text, timeout):
            return SSHResult(1, "", "curl: failed")

        with self.assertRaises(AgentDeployError) as ctx:
            bootstrap_agent(
                SSHDeployOptions(host="192.168.15.55", ssh_user="ezequiel"),
                controller_url="http://192.168.15.35:8080",
                pairing_token=secret,
                runner=runner,
            )
        self.assertNotIn(secret, str(ctx.exception))

    def test_wait_for_online(self):
        states = iter([
            {"agent_status": None, "health_status": None},
            {"agent_status": "active", "health_status": "online", "agent_id": "agent-node02"},
        ])
        result = wait_for_agent_online(lambda: next(states), timeout=2, interval=0.01)
        self.assertEqual(result["agent_id"], "agent-node02")

    def test_deploy_location_requires_valid_matching_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            backend = create_backend(
                DatabaseConfig(driver="sqlite", database=str(Path(temp) / "capivara.db"))
            )
            backend.initialize()
            try:
                with backend.transaction() as connection:
                    connection.execute(
                        "INSERT INTO regions(id,name,status) VALUES (?,?,?)",
                        ("region-a", "Region A", "active"),
                    )
                    connection.execute(
                        "INSERT INTO regions(id,name,status) VALUES (?,?,?)",
                        ("region-b", "Region B", "active"),
                    )
                    connection.execute(
                        "INSERT INTO datacenters(id,region_id,name,status) VALUES (?,?,?,?)",
                        ("dc-a", "region-a", "DC A", "active"),
                    )
                self.assertEqual(
                    validate_deploy_location(
                        backend, region_id="region-a", datacenter_id="dc-a"
                    ),
                    ("region-a", "dc-a"),
                )
                with self.assertRaises(AgentDeployError):
                    validate_deploy_location(
                        backend, region_id="region-b", datacenter_id="dc-a"
                    )
                with self.assertRaises(AgentDeployError):
                    validate_deploy_location(
                        backend, region_id="region-a", datacenter_id=None
                    )
            finally:
                backend.close()

    def test_release_bootstrap_keeps_token_out_of_child_argv(self):
        release_bootstrap = (
            ROOT / "agents/linux/installer/bootstrap-release.sh"
        ).read_text(encoding="utf-8")
        local_installer = (
            ROOT / "agents/linux/installer/install-agent.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('PAIRING_TOKEN="${CAPIVARA_PAIRING_TOKEN:-}"', release_bootstrap)
        self.assertIn('CAPIVARA_PAIRING_TOKEN="${PAIRING_TOKEN}" exec', release_bootstrap)
        self.assertNotIn('--pairing-token "${PAIRING_TOKEN}"', release_bootstrap.split("exec", 1)[-1])
        self.assertIn('PAIRING_TOKEN="${CAPIVARA_PAIRING_TOKEN:-}"', local_installer)

    def test_cap_routes_agent_deploy(self):
        cap = (ROOT / "bin/cap").read_text(encoding="utf-8")
        self.assertIn('agent)', cap)
        self.assertIn('deploy)', cap)
        self.assertIn('database/agent_deploy_cli.py', cap)
        self.assertIn('cap agent deploy HOST --ssh-user USER', cap)
        self.assertIn('cap agent ssh-prepare USER@HOST', cap)
        self.assertIn('database/agent_ssh_prepare_cli.py', cap)


if __name__ == "__main__":
    unittest.main()
