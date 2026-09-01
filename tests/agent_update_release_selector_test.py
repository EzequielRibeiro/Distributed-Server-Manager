#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_registration_repository import AgentRegistrationRepository
from agent_update_api import agent_update_versions_for_user, create_agent_rollout_for_user
from agent_update_http import VERSIONS_PATH, dispatch_update_get
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class AgentUpdateReleaseSelectorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(driver="sqlite", database=str(Path(self.temp.name) / "capivara.db"))
        )
        self.backend.initialize()
        registry = RegistryRepository(self.backend)
        identity = installation_profile_identity(registry, profile="controller", hostname="selector-controller")
        self.controller_id = identity["controller_id"]
        AgentRegistrationRepository(self.backend).register(
            controller_id=self.controller_id,
            agent_id="agent-windows",
            node_id="node-windows",
            name="Windows Agent",
        )
        self.user = {"role": "admin", "username": "admin"}

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    @staticmethod
    def releases():
        return [
            {"tag": "v2.0.21", "version": "2.0.21", "prerelease": False},
            {"tag": "v2.0.20", "version": "2.0.20", "prerelease": False},
        ]

    @patch("agent_update_api._agent_platforms", return_value={"agent-windows": "windows"})
    @patch("agent_update_api._published_versions_for_platform")
    def test_versions_endpoint_lists_only_published_compatible_releases(self, published, _platforms):
        published.return_value = self.releases()
        result = agent_update_versions_for_user(self.user, self.backend, "agent-windows", "stable")
        self.assertEqual(result["platform"], "windows")
        self.assertEqual(result["recommended_version"], "2.0.21")
        self.assertEqual([item["version"] for item in result["releases"]], ["2.0.21", "2.0.20"])

    @patch("agent_update_api._agent_platforms", return_value={"agent-windows": "windows"})
    @patch("agent_update_api._published_versions_for_platform")
    def test_rollout_accepts_published_version(self, published, _platforms):
        published.return_value = self.releases()
        rollout = create_agent_rollout_for_user(
            self.user,
            self.backend,
            {
                "agent_ids": ["agent-windows"],
                "desired_version": "2.0.21",
                "update_channel": "stable",
                "batch_size": 1,
            },
        )
        self.assertEqual(rollout["desired_version"], "2.0.21")

    @patch("agent_update_api._agent_platforms", return_value={"agent-windows": "windows"})
    @patch("agent_update_api._published_versions_for_platform")
    def test_rollout_rejects_arbitrary_version_even_when_api_is_called_directly(self, published, _platforms):
        published.return_value = self.releases()
        with self.assertRaisesRegex(ValueError, "não é uma release publicada compatível"):
            create_agent_rollout_for_user(
                self.user,
                self.backend,
                {
                    "agent_ids": ["agent-windows"],
                    "desired_version": "99.99.99",
                    "update_channel": "stable",
                    "batch_size": 1,
                },
            )

    def test_local_manual_channel_cannot_accept_typed_rollout_version(self):
        with patch("agent_update_api._agent_platforms", return_value={"agent-windows": "windows"}):
            with self.assertRaisesRegex(ValueError, "local/manual não aceita rollout por versão"):
                create_agent_rollout_for_user(
                    self.user,
                    self.backend,
                    {
                        "agent_ids": ["agent-windows"],
                        "desired_version": "2.0.21",
                        "update_channel": "local/manual",
                        "batch_size": 1,
                    },
                )

    @patch("agent_update_http.agent_update_versions_for_user")
    def test_http_versions_contract(self, versions):
        versions.return_value = {
            "agent_id": "agent-windows",
            "platform": "windows",
            "channel": "stable",
            "recommended_version": "2.0.21",
            "releases": self.releases(),
        }
        status, body = dispatch_update_get(
            VERSIONS_PATH,
            user=self.user,
            backend=self.backend,
            agent_id="agent-windows",
            channel="stable",
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["recommended_version"], "2.0.21")

    def test_dashboard_uses_select_instead_of_free_text_version_input(self):
        html = (ROOT / "dashboard" / "web" / "agents.html").read_text(encoding="utf-8")
        javascript = (ROOT / "dashboard" / "web" / "agent-updates-v3.js").read_text(encoding="utf-8")
        self.assertIn('<select id="agent-rollout-version"', html)
        self.assertNotIn('<input id="agent-rollout-version"', html)
        self.assertIn("/agents/updates/versions?agent_id=", javascript)
        self.assertIn("Selecione uma versão publicada para o rollout.", javascript)


if __name__ == "__main__":
    unittest.main()
