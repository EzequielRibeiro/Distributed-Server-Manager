#!/usr/bin/env python3
from __future__ import annotations
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"dashboard",ROOT/"database",ROOT/"core"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from customer_instance_policy import PERMISSION_PRESETS,effective_permissions,enforce_content_upload,effective_content_policy
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from customer_content_workspace import CustomerContentWorkspaceService
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
 def test_instance_mod_override_disables_derived_modpacks_and_datapacks(self):
  service=CustomerInstanceWorkspaceService.__new__(CustomerInstanceWorkspaceService);service.root=ROOT
  context={"game_id":"minecraft","runtime_id":"minecraft.java.neoforge","contract_metadata":{"product_variant":"modified"}}
  _,policy=service._contract_policy(context,{"mods_allowed":False})
  self.assertFalse(policy.mods_allowed);self.assertFalse(policy.modpacks_allowed);self.assertFalse(policy.datapacks_allowed)
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
  for chart_id in ("cpu-chart","memory-chart","network-chart","players-chart","latency-chart"):
   self.assertIn(f'id="{chart_id}"',html)
  telemetry_js=(ROOT/"dashboard/web/customer-instance-v2.js").read_text(encoding="utf-8")
  self.assertIn('overview.runtime?.state||inst.status||"unknown"',telemetry_js)
  self.assertIn('$("start").disabled=!can("instance.start")||!!pr||!startable||busy',telemetry_js)
  self.assertIn('$("stop").disabled=!can("instance.stop")||!!pr||!running||busy',telemetry_js)
  for marker in ("networkRate",'network_rx_bytes','network_tx_bytes','sampled_at','telemetry-window',"Runtime sem query de latência","Não suportada"):
   self.assertIn(marker,telemetry_js)
  transfer=(ROOT/"dashboard/web/customer-backup-transfer.js").read_text(encoding="utf-8")
  for route in ("/api/customer/artifacts/backup-export","/api/customer/artifacts/backup-import","/api/customer/artifacts/upload","/api/customer/artifacts/restore-import"):
   self.assertIn(route,transfer)
  self.assertIn("availableBackupJobs",transfer)
  self.assertIn('x.action==="delete"&&x.status==="completed"',transfer)
  overview=(ROOT/"dashboard/web/customer-backups.js").read_text(encoding="utf-8")
  self.assertIn("availableBackupJobs",overview)
  self.assertIn('job.action === "delete" && job.status === "completed"',overview)
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
  self.assertTrue((ROOT/"agents/linux/runtime/artifact_transfer_client.py").is_file())
  self.assertIn('git -C "${ROOT}" ls-tree -r --name-only "${REF}" -- agents/linux/runtime',linux)
  self.assertIn('copy "${source}" "agent/runtime/${relative}"',linux)
  self.assertIn('_runtime_sources(ref)',windows)
  self.assertIn('"agents/windows/runtime"',windows)
  self.assertIn('source.endswith(".py")',windows)
 def test_artifact_http_requires_completed_import_before_restore(self):
  text=(ROOT/"dashboard/artifact_transfer_http.py").read_text(encoding="utf-8")
  self.assertIn('CUSTOMER_RESTORE=CUSTOMER_PREFIX+"/restore-import"',text)
  self.assertIn('item.get("direction")!="controller_to_agent"',text)
  self.assertIn('str(item.get("status") or "")!="completed"',text)
  self.assertIn('action="restore",backup_id=backup_id',text)

 def test_manager_can_retry_failed_provisioning(self):
  self.assertIn("instance.provision.retry",PERMISSION_PRESETS["manager"])
  self.assertNotIn("instance.provision.retry",PERMISSION_PRESETS["viewer"])

 def test_agent_console_output_reads_heartbeat_snapshot_for_instance(self):
  service=CustomerInstanceWorkspaceService.__new__(CustomerInstanceWorkspaceService)
  service.require=lambda user,instance_id,permission:{"id":instance_id,"agent_id":"agent-remote"}
  service._location=lambda agent_id:{"agent_metadata":{"instance_console_state":[
   {"instance_id":"other","supported":True,"transport":"exec","output":["ignore"]},
   {"instance_id":"instance-1","supported":True,"transport":"tmux","output":["one","two","three"]},
  ]}}
  service.agent_runtime=type("Agent",(),{
   "snapshot":lambda self,agent_id,refresh_health=False:{"health_status":"online","last_seen":"2026-09-14T23:30:00Z"}
  })()

  result=service.agent_console_output({"role":"customer"},"instance-1",2)

  self.assertEqual(["two","three"],result["lines"])
  self.assertEqual("tmux",result["transport"])
  self.assertTrue(result["supported"])
  self.assertEqual("online",result["agent_health"])
  self.assertEqual("2026-09-14T23:30:00Z",result["last_seen"])

 def test_overview_uses_agent_runtime_state_instead_of_stale_persisted_status(self):
  service=CustomerInstanceWorkspaceService.__new__(CustomerInstanceWorkspaceService)
  service.permissions=lambda user,instance_id:{"instance.view","instance.start","instance.stop","instance.restart"}
  service.require=lambda user,instance_id,permission:{
   "id":instance_id,"name":"DayZ","game_id":"dayz","edition":"default",
   "runtime_id":"dayz.stable","variant":"stable","game_version":"current",
   "status":"online","agent_id":"agent-hybrid","contract_id":None,"instance_metadata":{},
  }
  service.runtime_health=type("Health",(),{
   "list_for_agent":lambda self,agent_id:[{
    "instance_id":"instance-1","desired_state":"running","observed_state":"stopped",
    "reconcile_status":"healthy","health":"offline","operation_status":"idle",
    "reported_at":"2026-09-14T22:55:00Z",
   }]
  })()
  service.agent_runtime=type("Agent",(),{
   "snapshot":lambda self,agent_id:{"health_status":"online"}
  })()
  service.repo=type("Repo",(),{
   "workspace_policy":lambda self,instance_id:{},
   "telemetry":lambda self,instance_id,limit:[],
  })()
  service.provisioning=type("Provisioning",(),{
   "latest_for_instance":lambda self,instance_id:None
  })()
  service._resolved_resource_policy=lambda context,policy:{}
  service._location=lambda agent_id:{}
  service._contract_policy=lambda context,policy:(
   {},type("Content",(),{
    "mods_allowed":False,"plugins_allowed":False,"modpacks_allowed":False,
    "datapacks_allowed":False,"workshop_allowed":False,"as_dict":lambda self:{},
   })(),
  )
  service._ports=lambda instance_id:[]

  result=service.overview({"role":"customer","username":"owner"},"instance-1")

  self.assertEqual("offline",result["instance"]["status"])
  self.assertEqual("online",result["instance"]["persisted_status"])
  self.assertEqual("agent",result["runtime"]["source"])
  self.assertEqual("stopped",result["runtime"]["observed_state"])

 def test_overview_prefers_distributed_provisioning_state(self):
  service=CustomerInstanceWorkspaceService.__new__(CustomerInstanceWorkspaceService)
  service.permissions=lambda user,instance_id:{"instance.view","instance.provision.retry"}
  service.require=lambda user,instance_id,permission:{
   "id":instance_id,
   "name":"Test instance",
   "game_id":"dayz",
   "edition":"default",
   "runtime_id":"dayz.stable",
   "variant":"stable",
   "game_version":"current",
   "status":"failed",
   "agent_id":"agent-1",
   "contract_id":None,
   "instance_metadata":{"provision":{"status":"queued","stage":"legacy","progress":10}},
  }
  service.repo=type("Repo",(),{
   "workspace_policy":lambda self,instance_id:{},
   "telemetry":lambda self,instance_id,limit:[],
  })()
  service.provisioning=type("Provisioning",(),{
   "latest_for_instance":lambda self,instance_id:{
    "provisioning_id":"prov-2",
    "instance_id":instance_id,
    "status":"failed",
    "current_step":"install_content",
    "progress":100,
    "last_error":"boom",
    "result":{},
   }
  })()
  service._location=lambda agent_id:{}
  service._contract_policy=lambda context,policy:(
   {},
   type("Content",(),{"mods_allowed":False,"plugins_allowed":False,"modpacks_allowed":False,"datapacks_allowed":False,"workshop_allowed":False,"as_dict":lambda self:{}})(),
  )
  service._ports=lambda instance_id:[]

  result=service.overview(
   {"role":"customer","username":"owner"},
   "instance-1",
  )

  self.assertEqual("failed",result["provision"]["status"])
  self.assertEqual("install_content",result["provision"]["stage"])
  self.assertEqual(99,result["provision"]["progress"])
  self.assertEqual("prov-2",result["provision"]["provisioning_id"])

 def test_content_tab_remains_visible_when_runtime_supports_managed_content(self):
  script=(ROOT/"dashboard"/"web"/"customer-instance-v2.js").read_text(encoding="utf-8")
  self.assertIn("runtimeContentSupported",script)
  self.assertIn('!can("content.read")||(!(overview.content_sections||[]).length&&!runtimeContentSupported)',script)
  self.assertIn('Este runtime/contrato não permite conteúdo gerenciado.',script)

 def test_dayz_customer_can_choose_mod_or_server_mod_without_raw_arguments(self):
  service=CustomerContentWorkspaceService.__new__(CustomerContentWorkspaceService)
  current={
   "instance_id":"dayz-1","content_id":"steam-workshop:1828439124","game_id":"dayz",
   "content_type":"workshop","desired_state":"installed","activation_state":"enabled",
   "activation_order":10,"version":"100","provider":"steam-workshop",
   "target":"workshop/steam-workshop:1828439124",
   "artifact":{"provider":"steam-workshop","package_id":"221100:1828439124"},
   "provenance":{},"metadata":{},"dependencies":[],"conflicts":[],
  }
  context={"id":"dayz-1","game_id":"dayz","runtime_id":"dayz.stable"}
  config=service._activation_configuration(context,current)
  self.assertEqual("mod",config["mode"])
  self.assertEqual({"mod","server-mod"},{item["value"] for item in config["modes"]})

  payload=service._configure_activation(context,current,{"mode":"server-mod"})
  self.assertEqual(
   {"adapter":"dayz","mode":"server-mod","identifier":"steam-workshop:1828439124"},
   payload["metadata"]["activation"],
  )
  self.assertNotIn("arguments",payload)
  with self.assertRaisesRegex(ValueError,"unsupported activation fields"):
   service._configure_activation(context,current,{"mode":"mod","adapter":"custom"})
  with self.assertRaisesRegex(ValueError,"unsupported DayZ"):
   service._configure_activation(context,current,{"mode":"anything"})

 def test_customer_dayz_content_ui_exposes_activation_mode_selector(self):
  script=(ROOT/"dashboard"/"web"/"customer-instance-v2.js").read_text(encoding="utf-8")
  for marker in ("configure-activation","content-activation-mode","Salvar modo","Mod somente servidor","runtime ${item.activation_config.mode}"):
   self.assertIn(marker.replace("\\$","$"),script)
  dayz=(ROOT/"agents"/"linux"/"runtime"/"content_activation_dayz.py").read_text(encoding="utf-8")
  self.assertIn('mode not in {"mod", "server-mod"}',dayz)
  self.assertIn('arguments.append("-mod="',dayz)
  self.assertIn('arguments.append("-serverMod="',dayz)

 def test_palworld_console_blocks_admin_password_before_queueing(self):
  service=CustomerInstanceWorkspaceService.__new__(CustomerInstanceWorkspaceService);service.root=ROOT
  service.require=lambda user,instance_id,permission:{"id":instance_id,"game_id":"palworld","runtime_id":"palworld.stable","agent_id":"agent-1"}
  class Repo:
   def enqueue_console(self,**kwargs):raise AssertionError("credential command must not be queued")
  service.repo=Repo()
  with self.assertRaisesRegex(PermissionError,"AdminPassword"):
   service.send_console({"username":"owner"},"instance-1","/AdminPassword secret-value")

 def test_console_command_status_is_instance_scoped_and_secret_free(self):
  service=CustomerInstanceWorkspaceService.__new__(CustomerInstanceWorkspaceService)
  service.require=lambda user,instance_id,permission:{}
  class Repo:
   def console_command(self,command_id):
    return {"command_id":command_id,"instance_id":"instance-1","status":"failed","command_text":"/AdminPassword must-not-return","last_error":"boom","result":{"error":"boom"},"completed_at":"now"}
  service.repo=Repo()
  result=service.console_command_status({"username":"owner"},"instance-1","cmd-1")
  self.assertEqual("failed",result["status"]);self.assertNotIn("command_text",result)
  with self.assertRaises(PermissionError):service.console_command_status({"username":"owner"},"instance-2","cmd-1")

if __name__=="__main__":unittest.main()
