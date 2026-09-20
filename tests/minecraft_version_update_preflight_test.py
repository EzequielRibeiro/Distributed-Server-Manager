#!/usr/bin/env python3
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"core",ROOT/"database",ROOT/"dashboard"):
    if str(p) not in sys.path:sys.path.insert(0,str(p))

from minecraft_version_update_preflight import MinecraftVersionUpdatePreflightService


class MinecraftVersionUpdatePreflightTest(unittest.TestCase):
    def test_requires_minecraft_and_instance_update_permission(self):
        service=MinecraftVersionUpdatePreflightService.__new__(MinecraftVersionUpdatePreflightService)
        service.workspace=Mock()
        service.workspace.require.return_value={"game_id":"dayz","runtime_id":"dayz.stable"}
        with self.assertRaises(PermissionError):
            service._context({"role":"customer"},"i")
        service.workspace.require.assert_called_once_with({"role":"customer"},"i","instance.update")

    def test_project_reference_falls_back_to_artifact_package_project(self):
        item={"artifact":{"package_id":"project-id:version-id"}}
        self.assertEqual("project-id",MinecraftVersionUpdatePreflightService._project_reference(item))

    def test_customer_surface_contains_warning_and_disable_action(self):
        script=(ROOT/"dashboard/web/customer-instance-v2.js").read_text(encoding="utf-8")
        html=(ROOT/"dashboard/web/customer-instance.html").read_text(encoding="utf-8")
        policy=(ROOT/"database/instance_workspace_policy.py").read_text(encoding="utf-8")
        self.assertIn('"instance.update"',policy)
        self.assertIn("minecraft-update-preflight",script)
        self.assertIn("Desativar temporariamente",script)
        self.assertIn("Versão do Minecraft",html)
        self.assertIn("compatibilidade",html.lower())


if __name__=="__main__":
    unittest.main()
