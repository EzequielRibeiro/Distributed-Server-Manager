#!/usr/bin/env python3
"""Regression contract for Controller/Customer authentication-domain isolation."""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"


class AuthenticationDomainCompositionTest(unittest.TestCase):

    def source(self, name: str) -> str:
        return (DASHBOARD / name).read_text(encoding="utf-8")

    def test_part10_does_not_replace_global_authenticator_with_customer(self):
        source = self.source("server_part10.py")
        self.assertIn("def integrated_controller_authenticate(headers):", source)
        self.assertIn("def integrated_customer_authenticate(headers):", source)
        self.assertNotIn("part8.integrated_authenticate = integrated_customer_authenticate", source)
        self.assertNotIn("legacy.authenticate = integrated_customer_authenticate", source)

    def test_agent_installation_uses_controller_domain(self):
        source = self.source("server_part12.py")
        self.assertIn("_controller_authenticate = integration.integration.integrated_controller_authenticate", source)
        self.assertIn("_customer_authenticate = integration.integration.integrated_customer_authenticate", source)
        self.assertIn("_authenticate = _controller_authenticate", source)

    def test_part17_administrative_modules_use_controller_domain(self):
        source = self.source("server_part17.py")
        expected = (
            "install_system_user_administration(legacy,_controller_authenticate)",
            "install_contract_upgrade_api(legacy,_controller_authenticate,_ROOT)",
            "install_dashboard_activity_audit(legacy,_controller_authenticate)",
            "install_alert_management(legacy,_controller_authenticate)",
            "install_agent_administration(legacy,_controller_authenticate)",
            "install_agent_public_network(legacy,_controller_authenticate)",
            "install_agent_storage_pool_administration(legacy,_controller_authenticate)",
            "install_storage_pool_source_cleanup_http(legacy,_controller_authenticate)",
            "install_customer_profile_administration(legacy,_controller_authenticate)",
            "install_admin_observability(legacy,_controller_authenticate)",
        )
        for contract in expected:
            with self.subTest(contract=contract):
                self.assertIn(contract, source)

    def test_part17_customer_modules_use_customer_domain(self):
        source = self.source("server_part17.py")
        expected = (
            "install_customer_instance_workspace(legacy,_customer_authenticate)",
            "install_customer_instance_connection(legacy,_customer_authenticate)",
            "install_customer_instance_team(legacy,_customer_authenticate)",
            "install_customer_instance_activity(legacy,_customer_authenticate)",
            "install_artifact_transfer_http(legacy,_customer_authenticate)",
            "install_deleted_backup_vault_http(legacy,_customer_authenticate)",
            "install_backup_clone_http(legacy,_customer_authenticate)",
            "install_customer_health_http(legacy,_customer_authenticate)",
            "install_customer_profile_self_service(legacy,_customer_authenticate)",
            "install_customer_email_change(legacy,_customer_authenticate)",
            "install_customer_placement_locations(legacy,_customer_authenticate)",
            "install_customer_discord(legacy,_customer_authenticate)",
        )
        for contract in expected:
            with self.subTest(contract=contract):
                self.assertIn(contract, source)

    def test_part17_does_not_pass_generic_authenticator_to_installed_modules(self):
        source = self.source("server_part17.py")
        forbidden = (
            "install_system_user_administration(legacy,_authenticate)",
            "install_agent_administration(legacy,_authenticate)",
            "install_agent_public_network(legacy,_authenticate)",
            "install_agent_storage_pool_administration(legacy,_authenticate)",
            "install_admin_observability(legacy,_authenticate)",
            "install_customer_instance_workspace(legacy,_authenticate)",
            "install_customer_instance_connection(legacy,_authenticate)",
            "install_customer_instance_team(legacy,_authenticate)",
            "install_customer_profile_self_service(legacy,_authenticate)",
        )
        for contract in forbidden:
            with self.subTest(contract=contract):
                self.assertNotIn(contract, source)

    def test_composition_exports_both_domains_through_final_layers(self):
        for name in ("server_part13.py", "server_part15.py", "server_part16.py", "server_part17.py"):
            source = self.source(name)
            with self.subTest(file=name, domain="controller"):
                self.assertIn("_controller_authenticate", source)
            with self.subTest(file=name, domain="customer"):
                self.assertIn("_customer_authenticate", source)


if __name__ == "__main__":
    unittest.main()
