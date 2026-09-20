#!/usr/bin/env python3
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"core",ROOT/"database",ROOT/"dashboard"):
    if str(p) not in sys.path:sys.path.insert(0,str(p))

from minecraft_version_update_service import MinecraftVersionUpdateService


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
            self.assertIn("backup_current_runtime",source)
            self.assertIn("previous_runtime_restored",source)
            self.assertIn("update_readiness",source)

    def test_controller_commits_version_only_after_completed_agent_result(self):
        source=(ROOT/"database/agent_instance_provisioning_repository.py").read_text(encoding="utf-8")
        self.assertIn('status == "completed" and minecraft_update',source)
        self.assertIn("UPDATE instances SET game_version=",source)
        self.assertIn("MINECRAFT_VERSION_UPDATE_COMPLETED",source)
        self.assertIn("MINECRAFT_VERSION_UPDATE_FAILED",source)

    def test_customer_ui_requires_preflight_then_confirmation(self):
        source=(ROOT/"dashboard/web/customer-instance-v2.js").read_text(encoding="utf-8")
        self.assertIn("Atualizar versão do Minecraft",source)
        self.assertIn("confirm_risk:true",source)
        self.assertIn("/minecraft-update/preflight",source)
        self.assertIn("/minecraft-update",source)


if __name__=="__main__":
    unittest.main()
