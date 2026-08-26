#!/usr/bin/env python3
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);assert spec and spec.loader;spec.loader.exec_module(module);return module
class CatalogArchitectureStages5To10Test(unittest.TestCase):
 def test_stage5_runtime_policy_validation_and_persistence(self):
  policy=load("dashboard_catalog_controller_runtime_policy",ROOT/"dashboard/catalog_controller_runtime_policy.py")
  runtime={"id":"minecraft.java.vanilla","process":{"executable":"server.jar","args":["nogui"]}}
  with tempfile.TemporaryDirectory() as td:
   old=os.environ.get("CAPIVARA_CATALOG_POLICY_ROOT");os.environ["CAPIVARA_CATALOG_POLICY_ROOT"]=td
   try:
    saved=policy.save_policy(ROOT,runtime["id"],{**policy.default_policy(runtime),"arguments":["-Xmx{{MEMORY_MB}}M","-jar","server.jar"],"variables":[{"name":"MEMORY_MB","default":"8192"}],"templates":[{"path":"server.properties","content":"max-players={{MAX_PLAYERS}}"}]})
    self.assertEqual(saved["kind"],"CatalogRuntimePolicy");self.assertEqual(policy.load_policy(ROOT,runtime)["arguments"][0],"-Xmx{{MEMORY_MB}}M")
    with self.assertRaises(ValueError):policy.validate_policy({**saved,"templates":[{"path":"../escape","content":"x"}]},runtime_id=runtime["id"])
   finally:
    if old is None:os.environ.pop("CAPIVARA_CATALOG_POLICY_ROOT",None)
    else:os.environ["CAPIVARA_CATALOG_POLICY_ROOT"]=old
 def test_stage6_linux_policy_and_templates_materialize_without_shell(self):
  runtime_policy=load("linux_catalog_runtime_policy",ROOT/"agents/linux/runtime/catalog_runtime_policy.py")
  with tempfile.TemporaryDirectory() as td:
   base=Path(td);content=base/"content";work=base/"instance";content.mkdir();work.mkdir();(content/"server.jar").write_text("jar")
   instance={"instance_id":"i1","game_id":"minecraft"};context={"content_root":str(content),"ports":{"game":{"port":25565}},"resource_profile":{"memory_mb":8192},"catalog_runtime_policy":{"runtime_id":"minecraft.java.vanilla","executable":"server.jar","arguments":["-Xmx{{MEMORY_MB}}M","--port","{{PORT_GAME}}"],"environment":{},"variables":[],"templates":[{"path":"server.properties","content":"server-port={{PORT_GAME}}"}]}}
   spec=runtime_policy.apply_policy({"executable":str(content/"server.jar"),"working_directory":str(work),"arguments":[],"environment":{}},instance,context)
   self.assertEqual(spec["arguments"],["-Xmx8192M","--port","25565"]);self.assertEqual(runtime_policy.materialize_templates(spec),["server.properties"]);self.assertEqual((work/"server.properties").read_text(),"server-port=25565")
 def test_dayz_network_policy_applies_process_and_server_browser_ports(self):
  controller_policy=load("dayz_controller_runtime_policy",ROOT/"dashboard/catalog_controller_runtime_policy.py")
  runtime_policy=load("dayz_linux_runtime_policy",ROOT/"agents/linux/runtime/catalog_runtime_policy.py")
  runtime=__import__("json").loads((ROOT/"catalog/v2/games/dayz/runtimes/stable.json").read_text())
  policy=controller_policy.default_policy(runtime)
  self.assertIn("-port={{PORT_GAME}}",policy["arguments"])
  self.assertEqual(policy["network_properties"][0]["key"],"steamQueryPort")
  with tempfile.TemporaryDirectory() as td:
   old=os.environ.get("CAPIVARA_CATALOG_POLICY_ROOT");os.environ["CAPIVARA_CATALOG_POLICY_ROOT"]=td
   try:
    controller_policy.save_policy(ROOT,runtime["id"],{**policy,"arguments":["-config=custom.cfg"],"network_properties":[]})
    enforced=controller_policy.load_policy(ROOT,runtime)
    self.assertIn("-port={{PORT_GAME}}",enforced["arguments"]);self.assertEqual(enforced["network_properties"][0]["key"],"steamQueryPort")
   finally:
    if old is None:os.environ.pop("CAPIVARA_CATALOG_POLICY_ROOT",None)
    else:os.environ["CAPIVARA_CATALOG_POLICY_ROOT"]=old
  with tempfile.TemporaryDirectory() as td:
   work=Path(td);config=work/"serverDZ.cfg";config.write_text('hostname = "Capivara";\nsteamQueryPort = 2305;\n')
   context={"content_root":str(work),"ports":{"game":{"port":24000},"steam_query":{"port":24003}},"catalog_runtime_policy":policy}
   spec=runtime_policy.apply_policy({"executable":str(work/"DayZServer"),"working_directory":str(work),"arguments":[],"environment":{}},{"instance_id":"i1","game_id":"dayz"},context)
   self.assertIn("-port=24000",spec["arguments"])
   self.assertEqual(runtime_policy.materialize_network_properties(spec),["serverDZ.cfg"])
   text=config.read_text();self.assertIn('hostname = "Capivara";',text);self.assertIn("steamQueryPort = 24003;",text)
 def test_stage7_and_9_integrity_detects_missing_and_healthy(self):
  module=load("linux_integrity",ROOT/"agents/linux/runtime/game_data_integrity.py")
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/"game";self.assertEqual(module.inspect_game_data(path)["health"],"missing");path.mkdir();(path/"server.bin").write_bytes(b"x")
   result=module.inspect_game_data(path,{"executable":"server.bin"});self.assertEqual(result["health"],"ok");self.assertEqual(result["files"],1);self.assertTrue(result["tree_digest"])
 def test_stage8_provisioning_uses_ensure_and_catalog_resolver(self):
  repository=(ROOT/"database/agent_instance_provisioning_repository.py").read_text();contract=(ROOT/"agents/linux/runtime/provisioning_contract.py").read_text();resolver=(ROOT/"dashboard/catalog_provisioning_resolver.py").read_text()
  compact="".join(repository.split())
  self.assertIn('"content":{"action":"ensure"',compact);self.assertIn('"ensure"',contract);self.assertIn('catalog_runtime_policy',resolver);self.assertIn('resource_profile',resolver);self.assertIn('allowed_resource_profiles',resolver)
 def test_stage10_windows_file_manager_is_confined_and_integrity_exists(self):
  module=load("windows_files",ROOT/"agents/windows/runtime/game_data_files.py")
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);created=module.execute_file_operation(root,{"action":"create","path":"config/server.txt","content":"ok"});self.assertEqual(created["size"],2);self.assertEqual(module.execute_file_operation(root,{"action":"read","path":"config/server.txt"})["content"],"ok")
   with self.assertRaises(ValueError):module.execute_file_operation(root,{"action":"read","path":"../outside"})
  self.assertTrue((ROOT/"agents/windows/runtime/game_data_integrity.py").is_file());self.assertIn("FILE_ACTIONS",(ROOT/"agents/windows/runtime/game_data_executor.py").read_text())
 def test_dashboard_and_packaging_contracts_cover_completed_architecture(self):
  html=(ROOT/"dashboard/web/catalog.html").read_text(encoding="utf-8");js=(ROOT/"dashboard/web/catalog-page.js").read_text(encoding="utf-8");service=(ROOT/"systemd/dsm-dashboard.service").read_text(encoding="utf-8");build=(ROOT/"release/build_agent_package.sh").read_text(encoding="utf-8")
  for text in ("Parâmetros de execução","Templates de configuração","Reparar","Linux + Windows"):self.assertIn(text,html)
  for text in ("/api/catalog/runtime-policy","gameData('repair')","saveRuntimePolicy"):self.assertIn(text,js)
  self.assertIn("dashboard/server_part17.py",service)
  for name in ("catalog_runtime_policy.py","game_data_integrity.py","game_data_reconcile.py"):self.assertIn(name,build)
if __name__=="__main__":unittest.main()
