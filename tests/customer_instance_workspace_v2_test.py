#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"dashboard",ROOT/"database",ROOT/"core"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from customer_instance_policy import effective_permissions,enforce_content_upload,effective_content_policy
from instance_team_repository import InstanceTeamRepository
from runtime_workspace_catalog import allowed_runtimes,runtime_allowed_by_contract
from schema_baseline import load_schema_baseline

class CustomerWorkspaceV2Test(unittest.TestCase):
 def test_exact_team_permissions_and_console_dependency(self):
  grants=InstanceTeamRepository._exact_grants({"console.execute":True,"files.read":True})
  self.assertTrue(grants["instance.view"]);self.assertTrue(grants["console.read"]);self.assertTrue(grants["console.execute"]);self.assertFalse(grants["instance.delete"])
  permissions=effective_permissions("custom",grants)
  self.assertIn("console.execute",permissions);self.assertNotIn("instance.delete",permissions)
 def test_standard_contract_cannot_bypass_mod_plugin_paths(self):
  policy=effective_content_policy({"mods":False,"plugins":False,"external_upload":True},{"mods":True,"plugins":True,"external_upload":True})
  with self.assertRaises(PermissionError):enforce_content_upload("mods/example.jar",policy=policy,runtime_rules={"mod_paths":["mods"],"runtime_extensions":[".jar"]})
  with self.assertRaises(PermissionError):enforce_content_upload("plugins/example.jar",policy=policy,runtime_rules={"plugin_paths":["plugins"],"runtime_extensions":[".jar"]})
 def test_minecraft_standard_and_modified_runtime_choices(self):
  standard={"product_variant":"standard"};modified={"product_variant":"modified","entitlements":{"mods":True,"plugins":True,"workshop":True,"external_upload":True}}
  self.assertTrue(runtime_allowed_by_contract(ROOT,"minecraft","minecraft.java.vanilla",standard));self.assertFalse(runtime_allowed_by_contract(ROOT,"minecraft","minecraft.java.paper",standard));self.assertTrue(runtime_allowed_by_contract(ROOT,"minecraft","minecraft.java.paper",modified))
  self.assertGreater(len(allowed_runtimes(ROOT,"minecraft",modified)),len(allowed_runtimes(ROOT,"minecraft",standard)))
 def test_baseline_has_workspace_distributed_queues(self):
  for backend in ("sqlite","postgresql","mysql","mariadb"):
   sql=load_schema_baseline(backend).sql
   for table in ("instance_permission_grants","instance_file_commands","instance_console_commands","instance_resource_commands","instance_backup_policy","contract_change_requests","service_contract_revisions","deleted_instance_backups","artifact_transfers","instance_backup_clones"):
    self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}",sql)
 def test_customer_workspace_replaced_legacy_tabs_and_loads_backup_transfer(self):
  html=(ROOT/"dashboard/web/customer-instance.html").read_text(encoding="utf-8")
  self.assertIn('data-view="console"',html);self.assertIn('data-view="team"',html);self.assertIn('data-view="upgrade"',html)
  self.assertNotIn("Log em tempo real",html);self.assertNotIn('data-view="events"',html)
  self.assertIn("customer-instance-v2.js",html);self.assertIn("customer-backup-transfer.js",html)
  transfer=(ROOT/"dashboard/web/customer-backup-transfer.js").read_text(encoding="utf-8")
  for route in ("/api/customer/artifacts/backup-export","/api/customer/artifacts/backup-import","/api/customer/artifacts/upload","/api/customer/artifacts/restore-import"):
   self.assertIn(route,transfer)
 def test_create_from_retained_backup_reuses_normal_instance_creation(self):
  creation=(ROOT/"dashboard/customer_instance_creation.py").read_text(encoding="utf-8")
  self.assertIn('source_vault_id',creation);self.assertIn('InstanceBackupCloneRepository',creation);self.assertIn('backup_clone',creation);self.assertIn('_queue_agent_provisioning',creation)
  vault_ui=(ROOT/"dashboard/web/customer-deleted-backups.js").read_text(encoding="utf-8")
  self.assertIn("Criar servidor deste backup",vault_ui);self.assertIn("capivara_backup_clone_source",vault_ui)
  wizard=(ROOT/"dashboard/web/create-server-wizard.js").read_text(encoding="utf-8")
  self.assertIn("source_vault_id",wizard);self.assertIn("/api/customer/backup-clones/status",wizard)
  clone_http=(ROOT/"dashboard/backup_clone_http.py").read_text(encoding="utf-8")
  self.assertIn('/api/customer/backup-clones',clone_http);self.assertIn('repo.reconcile',clone_http)
 def test_agents_have_distributed_file_console_resource_backup_and_artifact_clients(self):
  for platform in ("linux","windows"):
   runtime=ROOT/"agents"/platform/"runtime";agent=(runtime/"agent.py").read_text(encoding="utf-8")
   for filename in ("console_client.py","instance_files_client.py","resource_profile_client.py","backup_client.py","artifact_transfer_client.py"):
    self.assertTrue((runtime/filename).is_file(),f"{platform}: {filename}")
   for token in ("resource_command","file_command","console_command","artifact_command","artifact_result"):
    self.assertIn(token,agent)
  win=(ROOT/"agents/windows/runtime/adapters/windows_process.py").read_text(encoding="utf-8")
  self.assertIn("apply_process_limits",win);self.assertTrue((ROOT/"agents/windows/runtime/windows_job_limits.py").is_file())
 def test_agent_packages_include_artifact_transfer_client(self):
  linux=(ROOT/"release/build_agent_package.sh").read_text(encoding="utf-8")
  windows=(ROOT/"release/build_windows_agent_package.py").read_text(encoding="utf-8")
  self.assertIn("artifact_transfer_client.py",linux)
  self.assertIn('_runtime_sources(ref)',windows)
  self.assertIn('"agents/windows/runtime"',windows)
  self.assertIn('source.lower().endswith((".py",".ps1",".cmd"))',windows)
 def test_artifact_http_requires_completed_import_before_restore(self):
  text=(ROOT/"dashboard/artifact_transfer_http.py").read_text(encoding="utf-8")
  self.assertIn('CUSTOMER_RESTORE=CUSTOMER_PREFIX+"/restore-import"',text)
  self.assertIn('item.get("direction")!="controller_to_agent"',text)
  self.assertIn('str(item.get("status") or "")!="completed"',text)
  self.assertIn('action="restore",backup_id=backup_id',text)

if __name__=="__main__":unittest.main()
