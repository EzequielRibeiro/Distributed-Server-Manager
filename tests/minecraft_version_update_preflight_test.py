#!/usr/bin/env python3
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"core",ROOT/"database",ROOT/"dashboard"):
    if str(p) not in sys.path:sys.path.insert(0,str(p))

from minecraft_version_update_preflight import MinecraftVersionUpdatePreflightService,_version_direction


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
        self.assertIn("Remover bloqueadores e reanalisar",script)
        self.assertIn("has_blocking_content",script)
        self.assertIn("has_blocking_version",script)
        self.assertIn("Downgrade bloqueado",script)
        self.assertIn("Versão do Minecraft",html)
        self.assertIn("compatibilidade",html.lower())

    def test_version_direction_blocks_downgrade(self):
        self.assertEqual(_version_direction("1.21.4","1.21.1"),"downgrade")
        self.assertEqual(_version_direction("1.21.1","1.21.4"),"upgrade")
        self.assertEqual(_version_direction("1.21.1","1.21.1"),"same")
        self.assertEqual(_version_direction("latest","1.21.1"),"unknown")

    def test_unknown_content_blocks_version_change_and_bundle_children_are_collapsed(self):
        service=MinecraftVersionUpdatePreflightService.__new__(MinecraftVersionUpdatePreflightService)
        service.content=Mock()
        service.content.list.return_value=[
            {"content_id":"pack-child","content_type":"mod","provider":"modrinth","metadata":{"bundle":{"parent_content_id":"pack"}}},
            {"content_id":"local-plugin","content_type":"plugin","provider":"local","activation_state":"enabled"},
        ]
        rows=service._content_compatibility("i","1.21.4",{})
        self.assertEqual([item["content_id"] for item in rows],["local-plugin"])
        self.assertEqual(rows[0]["compatibility"],"unknown")
        self.assertTrue(rows[0]["can_remove"])

    @patch("minecraft_version_update_preflight.resolve_catalog_provisioning")
    @patch("minecraft_version_update_preflight._selector")
    @patch("minecraft_version_update_preflight.runtime_definition")
    def test_preflight_fails_closed_for_unverified_content(self,runtime_definition_mock,selector_mock,resolve_mock):
        runtime_definition_mock.return_value={}
        selector_mock.return_value={"version":"1.21.4","build":"latest"}
        resolve_mock.return_value=({"version":"1.21.4","build":"latest"},{})
        service=MinecraftVersionUpdatePreflightService.__new__(MinecraftVersionUpdatePreflightService)
        service.root=ROOT
        service._context=lambda user,instance_id:{"game_id":"minecraft","runtime_id":"minecraft.java.youer","game_version":"1.21.1","build_id":"old"}
        service._content_compatibility=lambda instance_id,target_version,definition:[{"compatibility":"unknown"}]
        result=service.preflight({"role":"customer"},"i","1.21.4","latest")
        self.assertTrue(result["has_unverified_content"])
        self.assertTrue(result["has_blocking_content"])
        self.assertEqual(result["blocking_content_count"],1)
        self.assertFalse(result["can_request_update"])


if __name__=="__main__":
    unittest.main()
