#!/usr/bin/env python3
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"core",ROOT/"database",ROOT/"dashboard"):
    if str(p) not in sys.path:sys.path.insert(0,str(p))

from minecraft_version_update_service import MinecraftVersionUpdateService
from minecraft_runtime_migration_service import MinecraftRuntimeMigrationService


class MinecraftVersionUpdateExecutionTest(unittest.TestCase):
    def test_isolated_game_data_target_is_deterministic_and_release_specific(self):
        first=MinecraftVersionUpdateService._isolated_install_dir("instance-a","minecraft.java.neoforge","1.21.1","21.1.251")
        same=MinecraftVersionUpdateService._isolated_install_dir("instance-a","minecraft.java.neoforge","1.21.1","21.1.251")
        next_version=MinecraftVersionUpdateService._isolated_install_dir("instance-a","minecraft.java.neoforge","1.21.2","21.2.0")
        other_instance=MinecraftVersionUpdateService._isolated_install_dir("instance-b","minecraft.java.neoforge","1.21.1","21.1.251")
        self.assertEqual(first,same)
        self.assertNotEqual(first,next_version)
        self.assertNotEqual(first,other_instance)
        self.assertRegex(first,r"^instance-[0-9a-f]{20}-[0-9a-f]{12}$")

    def test_explicit_risk_confirmation_is_required_before_any_preflight(self):
        service=MinecraftVersionUpdateService.__new__(MinecraftVersionUpdateService)
        service.preflight_service=Mock()
        with self.assertRaisesRegex(ValueError,"confirmation"):
            service.request({"role":"customer"},"instance-a","1.21.2","build",confirm_risk=False)
        service.preflight_service.preflight.assert_not_called()

    def test_transactional_contract_is_present_on_both_agents(self):
        linux=(ROOT/"agents/linux/runtime/provisioning_executor.py").read_text(encoding="utf-8")
        windows=(ROOT/"agents/windows/runtime/provisioning_executor.py").read_text(encoding="utf-8")
        for source in (linux,windows):
            self.assertIn("minecraft_version_update",source)
            self.assertIn("minecraft_runtime_migration",source)
            self.assertIn("backup_current_runtime",source)
            self.assertIn("previous_runtime_restored",source)
            self.assertIn("update_readiness",source)

    def test_controller_commits_version_only_after_completed_agent_result(self):
        source=(ROOT/"database/agent_instance_provisioning_repository.py").read_text(encoding="utf-8")
        self.assertIn('status == "completed" and minecraft_change',source)
        self.assertIn("UPDATE instances SET game_version=",source)
        self.assertIn("MINECRAFT_VERSION_UPDATE_COMPLETED",source)
        self.assertIn("MINECRAFT_VERSION_UPDATE_FAILED",source)
        self.assertIn("MINECRAFT_RUNTIME_MIGRATION_COMPLETED",source)
        self.assertIn("MINECRAFT_RUNTIME_MIGRATION_FAILED",source)
        self.assertIn("UPDATE instances SET runtime_id=",source)

    def test_customer_ui_requires_preflight_then_confirmation(self):
        source=(ROOT/"dashboard/web/customer-instance-v2.js").read_text(encoding="utf-8")
        self.assertIn("Atualizar versão do Minecraft",source)
        self.assertIn("confirm_risk:true",source)
        self.assertIn("/minecraft-update/preflight",source)
        self.assertIn("/minecraft-update",source)
        self.assertIn("minecraft-update-runtime",source)
        self.assertIn("/minecraft-runtime/preflight",source)
        self.assertIn("/minecraft-runtime",source)

    def test_runtime_migration_preflight_is_contract_scoped_and_fail_closed(self):
        service=MinecraftRuntimeMigrationService.__new__(MinecraftRuntimeMigrationService)
        service.root=ROOT
        service.workspace=Mock()
        service.workspace.require.return_value={"id":"instance-a","game_id":"minecraft","runtime_id":"minecraft.java.youer","game_version":"1.21.1","build_id":"old","contract_metadata":{}}
        service.compatibility=Mock()
        service.compatibility._content_compatibility.return_value=[{"compatibility":"unknown"}]
        current={"id":"minecraft.java.youer","edition":"java","version":{"resolver":"youer_api"}}
        target={"id":"minecraft.java.paper","name":"Paper","edition":"java","version":{"resolver":"papermc"}}
        with patch("minecraft_runtime_migration_service.allowed_runtimes",return_value=[{"runtime_id":"minecraft.java.paper"}]),patch("minecraft_runtime_migration_service.runtime_definition",side_effect=lambda root,game,runtime: target if runtime=="minecraft.java.paper" else current),patch("minecraft_runtime_migration_service.resolve_catalog_provisioning",return_value=({"version":"1.21.4","build":"100"},{})):
            result=service.preflight({"role":"customer"},"instance-a","minecraft.java.paper","1.21.4","100")
        self.assertFalse(result["can_request_migration"])
        self.assertEqual(result["blocking_content_count"],1)
        self.assertEqual(result["target"]["runtime_id"],"minecraft.java.paper")

    def test_runtime_migration_blocks_downgrade_even_when_content_is_empty(self):
        service=MinecraftRuntimeMigrationService.__new__(MinecraftRuntimeMigrationService)
        service.root=ROOT
        service.workspace=Mock()
        service.workspace.require.return_value={"id":"instance-a","game_id":"minecraft","runtime_id":"minecraft.java.youer","game_version":"1.21.4","build_id":"old","contract_metadata":{}}
        service.compatibility=Mock()
        service.compatibility._content_compatibility.return_value=[]
        current={"id":"minecraft.java.youer","edition":"java"}
        target={"id":"minecraft.java.paper","name":"Paper","edition":"java"}
        with patch("minecraft_runtime_migration_service.allowed_runtimes",return_value=[{"runtime_id":"minecraft.java.paper"}]),patch("minecraft_runtime_migration_service.runtime_definition",side_effect=lambda root,game,runtime: target if runtime=="minecraft.java.paper" else current),patch("minecraft_runtime_migration_service.resolve_catalog_provisioning",return_value=({"version":"1.21.1","build":"100"},{})):
            result=service.preflight({"role":"customer"},"instance-a","minecraft.java.paper","1.21.1","100")
        self.assertEqual(result["version_direction"],"downgrade")
        self.assertTrue(result["has_blocking_version"])
        self.assertFalse(result["can_request_migration"])

    def test_runtime_migration_does_not_accept_unrelated_active_provisioning(self):
        service=MinecraftRuntimeMigrationService.__new__(MinecraftRuntimeMigrationService)
        service.backend=Mock()
        service.root=ROOT
        service.workspace=Mock()
        service._context=lambda user,iid: {"id":iid,"game_id":"minecraft","runtime_id":"minecraft.java.youer","game_version":"1.21.1","build_id":"old","agent_id":"agent-a"}
        service.preflight=lambda *args: {"can_request_migration":True,"target":{"runtime_id":"minecraft.java.paper","version":"1.21.4","build":"100","selector":"1.21.4@100"}}
        service.workspace._runtime_projection.return_value={"state":"running"}
        with patch("minecraft_runtime_migration_service.runtime_definition",return_value={"edition":"java"}),patch("minecraft_runtime_migration_service.resolve_catalog_provisioning",return_value=({"version":"1.21.4","build":"100"},{})),patch("minecraft_runtime_migration_service.AgentInstanceProvisioningRepository") as repository:
            repository.return_value.enqueue.return_value={"provisioning_id":"existing-unrelated","status":"running","request":{"configuration":{}}}
            with self.assertRaisesRegex(ValueError,"different active provisioning"):
                service.request({"username":"alice"},"instance-a","minecraft.java.paper","1.21.4","100",confirm_risk=True)

    def test_runtime_migration_rejects_cross_edition(self):
        service=MinecraftRuntimeMigrationService.__new__(MinecraftRuntimeMigrationService)
        service.root=ROOT
        service.workspace=Mock()
        context={"id":"instance-a","game_id":"minecraft","runtime_id":"minecraft.java.paper","contract_metadata":{}}
        current={"id":"minecraft.java.paper","edition":"java"}
        target={"id":"minecraft.bedrock.vanilla","edition":"bedrock"}
        with patch("minecraft_runtime_migration_service.allowed_runtimes",return_value=[{"runtime_id":"minecraft.bedrock.vanilla"}]),patch("minecraft_runtime_migration_service.runtime_definition",side_effect=lambda root,game,runtime: target if runtime=="minecraft.bedrock.vanilla" else current):
            with self.assertRaisesRegex(ValueError,"editions"):
                service._target_definition(context,"minecraft.bedrock.vanilla")


if __name__=="__main__":
    unittest.main()
