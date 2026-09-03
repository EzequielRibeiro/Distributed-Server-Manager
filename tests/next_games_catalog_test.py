#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];LINUX_RUNTIME=ROOT/"agents/linux/runtime";sys.path.insert(0,str(LINUX_RUNTIME))
from profiles.registry import resolve_profile,supported_profiles
def load(path):return json.loads(path.read_text(encoding="utf-8"))
def load_module(name,path):
 spec=importlib.util.spec_from_file_location(name,path);assert spec and spec.loader;module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
class NextGamesCatalogTest(unittest.TestCase):
 def test_supported_and_deferred_decisions_are_explicit(self):
  matrix=load(ROOT/"catalog/v2/support-matrix.json");published={r["id"] for r in matrix["published_runtimes"]};deferred={r["id"] for r in matrix["deferred_runtimes"]}
  self.assertTrue({"sevendaystodie.stable","satisfactory.stable","garrysmod.stable","factorio.stable","left4dead2.stable","armareforger.stable","theisle.stable"}<=published);self.assertTrue({"fivem.stable","valheim.stable","arksurvivalascended.stable"}<=deferred);self.assertTrue(published.isdisjoint(deferred))
 def test_artifact_contracts_match_known_dedicated_distributions(self):
  expected={"sevendaystodie":("294420","7DaysToDieServer.x86_64"),"satisfactory":("1690800","FactoryServer.sh"),"garrysmod":("4020","srcds_run"),"left4dead2":("222860","srcds_run"),"armareforger":("1874900","ArmaReforgerServer"),"theisle":("412680","TheIsle/Binaries/Linux/TheIsleServer-Linux-Shipping")}
  for game,(app_id,exe) in expected.items():
   runtime=load(ROOT/f"catalog/v2/games/{game}/runtimes/stable.json");self.assertEqual(runtime["artifact"]["provider"],"steam");self.assertEqual(runtime["artifact"]["package_id"],app_id);self.assertEqual(runtime["process"]["executable"],exe);self.assertEqual(runtime["requirements"]["os"],["linux"])
  factorio=load(ROOT/"catalog/v2/games/factorio/runtimes/stable.json");self.assertEqual(factorio["artifact"]["provider"],"http-archive")
 def test_protocols_are_deterministic(self):
  for game in ("sevendaystodie","satisfactory","garrysmod","left4dead2","theisle"):
   runtime=load(ROOT/f"catalog/v2/games/{game}/runtimes/stable.json");ports=runtime["network"]["ports"];pairs=[(x["protocol"],x["offset"]) for x in ports];self.assertEqual(len(pairs),len(set(pairs)));self.assertTrue(all(0<=x["offset"]<runtime["network"]["block_size"] for x in ports))
 def test_registry_exposes_intended_profiles(self):
  names=set(supported_profiles())
  for key in ("sevendaystodie.stable","factorio.stable","armareforger.stable","satisfactory.stable","garrysmod.stable","left4dead2.stable","theisle.stable"):self.assertIn(key,names)
  for key in ("fivem.stable","valheim.stable","arksurvivalascended.stable"):self.assertNotIn(key,names)
 def test_source_profile_keeps_port_typed(self):
  profile=resolve_profile({"environment_id":"garrysmod.stable","game_id":"garrysmod"});spec=profile.build_runtime_spec({"instance_id":"gmod-1","agent_id":"agent-1","game_id":"garrysmod","environment_id":"garrysmod.stable"},{"install_path":"/opt/dsm/game-data/garrysmod/serverfiles","instance_state_root":"/var/lib/capivara-instances/gmod-1","ports":{"game_udp":{"port":27015,"protocol":"udp"},"game_tcp":{"port":27015,"protocol":"tcp"}},"catalog_runtime_policy":{"runtime_id":"garrysmod.stable","executable":"srcds_run","working_directory":"."}});self.assertEqual(spec["arguments"][:2],["-port","27015"])
 def test_seven_days_xml_preparer_is_private(self):
  m=load_module("seven",LINUX_RUNTIME/"sevendaystodie_prepare.py")
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"serverconfig.xml";p.write_text('<ServerSettings><property name="ServerPort" value="26900" /></ServerSettings>');m.prepare(str(p),28000);self.assertEqual(p.stat().st_mode&0o777,0o600)
 def test_armareforger_has_no_admin_secret(self):
  m=load_module("arma",LINUX_RUNTIME/"armareforger_prepare.py")
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"server.json";m.prepare(str(p),2001,17777,"Capivara Test");payload=load(p);self.assertEqual(payload["game"]["password"],"");self.assertEqual(payload["game"]["passwordAdmin"],"")
 def test_factorio_preparer_creates_one_save(self):
  m=load_module("factorio",LINUX_RUNTIME/"factorio_prepare.py")
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);binary=root/"factorio";binary.write_text("stub");save=root/"state/saves/capivara.zip";settings=root/"state/config/server-settings.json"
   def fake(argv,**kwargs):save.parent.mkdir(parents=True,exist_ok=True);save.write_bytes(b"save");return type("C",(),{"returncode":0})()
   with patch.object(m.subprocess,"run",side_effect=fake) as run:m.prepare(str(binary),str(save),str(settings),"Capivara Factorio");m.prepare(str(binary),str(save),str(settings),"Capivara Factorio")
   self.assertEqual(run.call_count,1)
 def test_catalog_files_contain_no_real_credentials(self):
  paths=[ROOT/f"catalog/v2/games/{g}/deferred/stable.json" for g in ("fivem","valheim","arksurvivalascended")]+[ROOT/"catalog/v2/games/theisle/runtimes/stable.json"]
  combined="\n".join(p.read_text(encoding="utf-8") for p in paths).lower();self.assertNotIn("sv_licensekey ",combined);self.assertNotIn("dedicatedserverclientsecret=",combined);theisle=load(ROOT/"catalog/v2/games/theisle/runtimes/stable.json");self.assertEqual(theisle["artifact"]["branch"],"evrima")
if __name__=="__main__":unittest.main()
