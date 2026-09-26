#!/usr/bin/env python3
"""Cross-platform safe Server Pack activation and bounded reconciliation."""
from __future__ import annotations
import importlib.util
import os
import sys
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agents/common"))
from minecraft_serverpack_agent import prepare_serverpack_payload,validate_extracted_serverpack,verify_installed_neoforge


def payload(root):
 root=Path(root)
 (root/"mods").mkdir(parents=True)
 with zipfile.ZipFile(root/"mods"/"demo.jar","w") as archive:
  archive.writestr("META-INF/neoforge.mods.toml",'modLoader="javafml"')
 (root/"config").mkdir()
 (root/"config"/"settings.toml").write_text("config=true")
 (root/"StartServer.sh").write_text("exit 999")
 return root


def load(platform,name):
 base=ROOT/f"agents/{platform}/runtime"
 sys.path.insert(0,str(base))
 spec=importlib.util.spec_from_file_location(name,base/"content_semantic_validation.py")
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 return module


class ServerPackAgentTest(unittest.TestCase):
 def test_payload_projects_safe_overrides_and_keeps_launchers_inert(self):
  with tempfile.TemporaryDirectory() as td:
   root=payload(td)
   artifact={"serverpack_v1":True,"serverpack_mod_count":1,
             "serverpack_override_dirs":["config"],"serverpack_prefix":""}
   prepared=prepare_serverpack_payload(root,artifact)
   self.assertEqual(prepared["mods"],1)
   self.assertTrue((root/"server-overrides"/"config"/"settings.toml").is_file())
   self.assertFalse((root/"config").exists())
   self.assertTrue((root/"StartServer.sh").is_file())
   self.assertEqual(validate_extracted_serverpack(root,artifact)["mods"],1)
   for platform in ("linux","windows"):
    with self.subTest(platform=platform):
     semantic=load(platform,f"serverpack_semantic_{platform}")
     verdict=semantic.validate_external_content_payload(root,{
       "provider":"local","game_id":"minecraft","content_type":"modpack",
       "artifact":{"provider":"local","ephemeral_upload":True,**artifact}})
     self.assertEqual(verdict["validator"],"minecraft-serverpack-v1")

 def test_explicit_wrapper_folder_is_flattened(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   wrapped=root/"Release"
   wrapped.mkdir()
   payload(wrapped)
   out=prepare_serverpack_payload(root,{"serverpack_v1":True,
     "serverpack_prefix":"Release","serverpack_mod_count":1,
     "serverpack_override_dirs":["config"]})
   self.assertEqual(out["mods"],1)
   self.assertFalse(wrapped.exists())
   self.assertTrue((root/"mods"/"demo.jar").is_file())

 def test_never_project_unsupported_directories_or_dangerous_configs(self):
  for kind in ("bad_override","executable","wrong_mod_count","no_mods"):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as td:
    root=payload(td)
    options={"serverpack_v1":True,"serverpack_mod_count":1,
             "serverpack_override_dirs":["config"]}
    if kind=="bad_override":options["serverpack_override_dirs"]=["libraries"]
    if kind=="executable":(root/"config"/"startup.sh").write_text("echo no")
    if kind=="wrong_mod_count":options["serverpack_mod_count"]=100
    if kind=="no_mods":(root/"mods"/"demo.jar").unlink()
    with self.assertRaises(ValueError):
     prepare_serverpack_payload(root,options)

 def test_neo_loader_must_be_provably_installed_before_parent_or_child_activation(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   with self.assertRaisesRegex(ValueError,"Unable to verify"):
    verify_installed_neoforge(root,"26.1.2.109")
   lib=root/"game-data"/"libraries"/"net"/"neoforged"/"neoforge"/"26.1.2.109"
   lib.mkdir(parents=True)
   (lib/"unix_args.txt").write_text("@some-launcher")
   with self.assertRaisesRegex(ValueError,"launcher metadata is missing"):
    verify_installed_neoforge(root,"26.1.2.109")
   args=root/"game-data"/"capivara-launch.args"
   args.write_text("@libraries/net/neoforged/neoforge/26.1.2.109/unix_args.txt")
   accepted=verify_installed_neoforge(root,"26.1.2.109")
   self.assertEqual(accepted["loader_version"],"26.1.2.109")
   with self.assertRaisesRegex(ValueError,"expected 26.1.2.99"):
    verify_installed_neoforge(root,"26.1.2.99")
   args.write_text("@libraries/net/neoforged/neoforge/26.1.2.99/unix_args.txt")
   with self.assertRaisesRegex(ValueError,"Active launcher"):
    verify_installed_neoforge(root,"26.1.2.109")

 def test_official_serverpack_checks_real_staging_volume_space(self):
  gib=1024**3
  for platform in ("linux","windows"):
   with self.subTest(platform=platform),tempfile.TemporaryDirectory() as td:
    folder=ROOT/f"agents/{platform}/runtime"
    sys.path.insert(0,str(folder))
    spec=importlib.util.spec_from_file_location(f"serverpack_disk_{platform}",folder/"content_client.py")
    client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
    source=Path(td)/"official.zip"
    stage=Path(td)/"stage"
    stage.mkdir()
    with zipfile.ZipFile(source,"w",zipfile.ZIP_DEFLATED) as archive:
     archive.writestr("mods/example.jar",b"z"*32768)
    with patch.object(client.shutil,"disk_usage",return_value=SimpleNamespace(total=100*gib,free=1*gib)):
     with self.assertRaisesRegex(ValueError,"Espaço insuficiente"):
      client._serverpack_disk_preflight(source,stage)
    with patch.object(client.shutil,"disk_usage",return_value=SimpleNamespace(total=100*gib,free=20*gib)):
     self.assertEqual(client._serverpack_disk_preflight(source,stage),32768)
    with patch.object(client.zipfile,"ZipFile") as archive:
     archive.return_value.__enter__.return_value.infolist.return_value=[
       SimpleNamespace(file_size=9*gib)]
     with self.assertRaisesRegex(ValueError,"8 GiB expanded"):
      client._serverpack_disk_preflight(source,stage)

 def test_normalized_capivara_launch_args_copy_proves_installed_build(self):
  # DSM copies the installer-produced platform args file to this filename.
  # A byte-identical copy is valid evidence even without a library path.
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   libs=root/"libraries"/"net"/"neoforged"/"neoforge"
   canonical=libs/"26.1.2.109"/"unix_args.txt"
   canonical.parent.mkdir(parents=True)
   canonical.write_bytes(b"-cp libraries/a.jar:libs/b.jar\\n--launchTarget neoforgeserver\\n")
   active=root/"capivara-launch.args"
   active.write_bytes(canonical.read_bytes())
   self.assertEqual(verify_installed_neoforge(root,"26.1.2.109")["loader_version"],"26.1.2.109")
   # Merely leaving the expected library on disk is not proof it is active.
   stale=libs/"26.1.2.107"/"unix_args.txt"
   stale.parent.mkdir()
   stale.write_bytes(b"-cp libraries/different.jar\\n--launchTarget neoforgeserver\\n")
   active.write_bytes(stale.read_bytes())
   with self.assertRaisesRegex(ValueError,"Active launcher does not prove"):
    verify_installed_neoforge(root,"26.1.2.109")
   # The Windows normalization copies win_args.txt instead.
   active.write_bytes(canonical.read_bytes())
   canonical.unlink()
   win=canonical.with_name("win_args.txt")
   win.write_bytes(active.read_bytes())
   self.assertEqual(verify_installed_neoforge(root,"26.1.2.109")["loader_version"],"26.1.2.109")

 def test_linux_and_windows_clients_accept_more_than_200_mod_commands(self):
  for platform in ("linux","windows"):
   source=(ROOT/f"agents/{platform}/runtime/content_client.py").read_text()
   with self.subTest(platform=platform):
    self.assertIn("commands[:2000]",source)
    self.assertIn("reports[-2000:]",source)
    self.assertIn('artifact.get("serverpack_child_v1") is True',source)
    self.assertIn("state!=\"stopped\"",source)
    self.assertIn("prepare_serverpack_payload(payload,artifact)",source)
    self.assertIn("candidate.resolve(strict=True).relative_to(root.resolve(strict=True))",source)
    self.assertIn("verify_installed_neoforge(instance",source)

 def test_reconciliation_really_processes_over_200_items(self):
  for platform in ("linux","windows"):
   with self.subTest(platform=platform):
    folder=ROOT/f"agents/{platform}/runtime"
    sys.path.insert(0,str(folder))
    spec=importlib.util.spec_from_file_location(f"serverpack_content_client_{platform}",folder/"content_client.py")
    client=importlib.util.module_from_spec(spec);spec.loader.exec_module(client)
    cmds=[{"instance_id":"i1","content_id":f"member-{i}","desired_state":"installed"} for i in range(205)]
    with patch.object(client,"_dependency_state",return_value={}),patch.object(
     client,"_apply",side_effect=lambda config,cmd:{"instance_id":"i1","content_id":cmd["content_id"],"status":"applied"}),patch.object(
     client,"synchronize_activation_state",return_value=[]),patch.object(
     client,"apply_activation_snapshots",return_value=None):
     result=client.apply_content_commands({"agent_id":"agent"},cmds)
    self.assertEqual(len(result),205)


if __name__=="__main__":
 unittest.main()
