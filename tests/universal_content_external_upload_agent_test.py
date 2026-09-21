#!/usr/bin/env python3
from __future__ import annotations
import importlib.util,io,os,sys,tarfile,tempfile,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DATABASE=ROOT/"database"
if str(DATABASE) not in sys.path:sys.path.insert(0,str(DATABASE))
from artifact_transfer_repository import ArtifactTransferRepository,_validated_content_upload_destination
from backend import DatabaseConfig
from runtime_backend import create_backend

def _load(path:Path,name:str):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class ExternalUploadAgentTest(unittest.TestCase):
 def _module(self,platform,tmp):
  if platform=="linux":os.environ["CAPIVARA_GAME_DATA_ROOT"]=str(Path(tmp)/"game-data")
  else:os.environ["CAPIVARA_AGENT_GAME_DATA_ROOT"]=str(Path(tmp)/"game-data")
  return _load(ROOT/f"agents/{platform}/runtime/content_upload_quarantine.py",f"u6_quarantine_{platform}_{id(self)}")
 def test_zip_and_jar_are_confined_and_inspected_on_both_agents(self):
  for platform in ("linux","windows"):
   with self.subTest(platform=platform),tempfile.TemporaryDirectory() as tmp:
    module=self._module(platform,tmp)
    for filename,expected_type in (("mods.zip","zip"),("plugin.jar","jar")):
     dest=module.quarantine_destination("i1","transfer-abc",filename);dest.parent.mkdir(parents=True,exist_ok=True)
     with zipfile.ZipFile(dest,"w") as archive:archive.writestr("META-INF/manifest.txt","ok")
     result=module.validate_quarantine_archive(dest);self.assertEqual(result["archive_type"],expected_type);self.assertEqual(result["entries"],1);self.assertEqual(module.quarantine_relative_path(dest),f"quarantine/i1/transfer-abc/{filename}")
 def test_archive_path_traversal_and_tar_symlink_fail_closed(self):
  for platform in ("linux","windows"):
   with self.subTest(platform=platform),tempfile.TemporaryDirectory() as tmp:
    module=self._module(platform,tmp);bad=module.quarantine_destination("i1","transfer-abc","bad.zip");bad.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(bad,"w") as archive:archive.writestr("../escape.txt","nope")
    with self.assertRaises(ValueError):module.validate_quarantine_archive(bad)
    tar=module.quarantine_destination("i1","transfer-def","bad.tar");tar.parent.mkdir(parents=True,exist_ok=True)
    with tarfile.open(tar,"w") as archive:
     item=tarfile.TarInfo("link");item.type=tarfile.SYMTYPE;item.linkname="target";archive.addfile(item)
    with self.assertRaises(ValueError):module.validate_quarantine_archive(tar)
 def test_filename_instance_and_transfer_tokens_are_restricted(self):
  with tempfile.TemporaryDirectory() as tmp:
   module=self._module("linux",tmp)
   for iid,transfer,filename in (("../i1","t1","mods.zip"),("i1","../t","mods.zip"),("i1","t1","../mods.zip"),("i1","t1","mods.exe")):
    with self.subTest(iid=iid,transfer=transfer,filename=filename),self.assertRaises(ValueError):module.quarantine_destination(iid,transfer,filename)
 def test_external_payload_semantics_fail_closed_on_both_agents(self):
  for platform in ("linux","windows"):
   with self.subTest(platform=platform),tempfile.TemporaryDirectory() as tmp:
    module=_load(ROOT/f"agents/{platform}/runtime/content_semantic_validation.py",f"semantic_{platform}_{id(self)}")
    root=Path(tmp)

    random_zip=root/"random";random_zip.mkdir()
    (random_zip/"readme.txt").write_text("not a mod",encoding="utf-8")
    with self.assertRaisesRegex(ValueError,"valid DayZ mod"):
     module.validate_external_content_payload(random_zip,{
      "game_id":"dayz","content_type":"mod","provider":"local",
      "artifact":{"provider":"local","ephemeral_upload":True},
     })

    dayz=root/"dayz";(dayz/"Addons").mkdir(parents=True)
    (dayz/"Addons"/"example.pbo").write_bytes(b"pbo")
    result=module.validate_external_content_payload(dayz,{
     "game_id":"dayz","content_type":"mod","provider":"local",
     "artifact":{"provider":"local","ephemeral_upload":True},
    })
    self.assertEqual(result["validator"],"dayz-mod-v1")

    plugin=root/"plugin";plugin.mkdir()
    jar=plugin/"plugin.jar"
    with zipfile.ZipFile(jar,"w") as archive:archive.writestr("plugin.yml","name: Example\nmain: example.Main\n")
    result=module.validate_external_content_payload(plugin,{
     "game_id":"minecraft","content_type":"plugin","provider":"local",
     "artifact":{"provider":"local","ephemeral_upload":True},
    })
    self.assertEqual(result["validator"],"minecraft-plugin-v1")

    bogus=root/"bogus";bogus.mkdir()
    badjar=bogus/"random.jar"
    with zipfile.ZipFile(badjar,"w") as archive:archive.writestr("hello.txt","not a plugin")
    with self.assertRaisesRegex(ValueError,"recognized Minecraft plugin"):
     module.validate_external_content_payload(bogus,{
      "game_id":"minecraft","content_type":"plugin","provider":"local",
      "artifact":{"provider":"local","ephemeral_upload":True},
     })

 def test_content_clients_enforce_semantic_validation_before_activation(self):
  for platform in ("linux","windows"):
   source=(ROOT/f"agents/{platform}/runtime/content_client.py").read_text(encoding="utf-8")
   self.assertIn("from content_semantic_validation import validate_external_content_payload",source)
   validation=source.index("validate_external_content_payload(payload,cmd)")
   activation=source.index("_activate_target(config,iid,target,payload)",validation)
   self.assertLess(validation,activation)

 def test_repository_persists_only_validated_agent_quarantine_ack(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);backend=create_backend(DatabaseConfig(driver="sqlite",database=str(root/"capivara.db")));backend.initialize()
   with backend.transaction() as c:
    c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node-controller","Controller","controller"));c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node-agent","Agent","agent"));c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("controller-u6","node-controller","Controller U6"));c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent-u6","controller-u6","node-agent","Agent U6","active"));customer=c.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("controller-u6","Customer U6"));customer_id=int(customer.lastrowid);c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("instance-u6","node-agent","minecraft","Minecraft U6","stopped","controller-u6","agent-u6",customer_id))
   repo=ArtifactTransferRepository(backend,root);item=repo.create(agent_id="agent-u6",instance_id="instance-u6",customer_id=customer_id,direction="controller_to_agent",purpose="content_upload",filename="plugin.jar",requested_by="alice");self.assertEqual(item["status"],"staging");self.assertIsNone(repo.command_for_agent("agent-u6"));item=repo.stage_from_controller(item["transfer_id"],io.BytesIO(b"jar-bytes"),9);self.assertEqual(item["status"],"queued");command=repo.command_for_agent("agent-u6");self.assertEqual(command["transfer_id"],item["transfer_id"]);self.assertEqual(repo.get(item["transfer_id"])["status"],"delivered")
   report={"transfer_id":item["transfer_id"],"status":"completed","transferred_bytes":9,"destination_ref":f"quarantine/instance-u6/{item['transfer_id']}/plugin.jar","sha256":item["sha256"],"archive_type":"jar","archive_entries":2}
   completed=repo.apply_agent_result("agent-u6",report);self.assertEqual(completed["status"],"completed");self.assertEqual(completed["destination_ref"],report["destination_ref"])
   second=repo.create(agent_id="agent-u6",instance_id="instance-u6",customer_id=customer_id,direction="controller_to_agent",purpose="content_upload",filename="mod.zip",requested_by="alice");second=repo.stage_from_controller(second["transfer_id"],io.BytesIO(b"zip-bytes"),9);bad={"transfer_id":second["transfer_id"],"status":"completed","transferred_bytes":9,"destination_ref":f"quarantine/other/{second['transfer_id']}/mod.zip","sha256":second["sha256"],"archive_type":"zip","archive_entries":1};failed=repo.apply_agent_result("agent-u6",bad);self.assertEqual(failed["status"],"failed");self.assertIsNone(failed["destination_ref"]);self.assertIn("invalid content upload Agent destination",failed["last_error"])
 def test_rejected_upload_deletes_controller_spool_and_queues_agent_cleanup(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);backend=create_backend(DatabaseConfig(driver="sqlite",database=str(root/"capivara.db")));backend.initialize()
   with backend.transaction() as c:
    c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node-controller","Controller","controller"));c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node-agent","Agent","agent"));c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("controller-u6","node-controller","Controller U6"));c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent-u6","controller-u6","node-agent","Agent U6","active"));customer=c.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("controller-u6","Customer U6"));customer_id=int(customer.lastrowid);c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("instance-u6","node-agent","minecraft","Minecraft U6","stopped","controller-u6","agent-u6",customer_id))
   repo=ArtifactTransferRepository(backend,root);item=repo.create(agent_id="agent-u6",instance_id="instance-u6",customer_id=customer_id,direction="controller_to_agent",purpose="content_upload",filename="pack.zip",requested_by="alice");item=repo.stage_from_controller(item["transfer_id"],io.BytesIO(b"zip-bytes"),9);path,_=repo.controller_artifact(item["transfer_id"]);self.assertTrue(path.exists())
   command=repo.command_for_agent("agent-u6");self.assertEqual(command["purpose"],"content_upload");completed=repo.apply_agent_result("agent-u6",{"transfer_id":item["transfer_id"],"status":"completed","transferred_bytes":9,"destination_ref":f"quarantine/instance-u6/{item['transfer_id']}/pack.zip","sha256":item["sha256"],"archive_type":"zip","archive_entries":1});self.assertEqual(completed["status"],"completed")
   rejected=repo.reject_content_upload(item["transfer_id"],"Minecraft version mismatch");self.assertEqual(rejected["status"],"failed");self.assertFalse(path.exists());cleanup=repo.command_for_agent("agent-u6");self.assertEqual(cleanup["purpose"],"content_upload_cleanup");self.assertEqual(cleanup["source_ref"],item["transfer_id"]);self.assertEqual(cleanup["filename"],"pack.zip")

 def test_agent_clients_handle_content_upload_cleanup(self):
  for platform in ("linux","windows"):
   source=(ROOT/f"agents/{platform}/runtime/artifact_transfer_client.py").read_text(encoding="utf-8");self.assertIn('purpose=="content_upload_cleanup"',source);self.assertIn("dest.unlink(missing_ok=True)",source)

 def test_cancelled_transfer_is_not_delivered_or_resurrected(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);backend=create_backend(DatabaseConfig(driver="sqlite",database=str(root/"capivara.db")));backend.initialize()
   with backend.transaction() as c:
    c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node-controller","Controller","controller"));c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node-agent","Agent","agent"));c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("controller-u6","node-controller","Controller U6"));c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent-u6","controller-u6","node-agent","Agent U6","active"));customer=c.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("controller-u6","Customer U6"));customer_id=int(customer.lastrowid);c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("instance-u6","node-agent","minecraft","Minecraft U6","stopped","controller-u6","agent-u6",customer_id))
   repo=ArtifactTransferRepository(backend,root);item=repo.create(agent_id="agent-u6",instance_id="instance-u6",customer_id=customer_id,direction="controller_to_agent",purpose="content_upload",filename="plugin.jar",requested_by="alice");item=repo.stage_from_controller(item["transfer_id"],io.BytesIO(b"jar-bytes"),9);cancelled=repo.cancel(item["transfer_id"]);self.assertEqual(cancelled["status"],"cancelled");self.assertIsNone(repo.command_for_agent("agent-u6"))
   late=repo.apply_agent_result("agent-u6",{"transfer_id":item["transfer_id"],"status":"completed","transferred_bytes":9,"destination_ref":f"quarantine/instance-u6/{item['transfer_id']}/plugin.jar","sha256":item["sha256"],"archive_type":"jar","archive_entries":1});self.assertEqual(late["status"],"cancelled")

 def test_controller_accepts_only_exact_agent_quarantine_ack(self):
  item={"instance_id":"i1","transfer_id":"transfer-1","filename":"plugin.jar","sha256":"a"*64}
  good={"destination_ref":"quarantine/i1/transfer-1/plugin.jar","sha256":"a"*64,"archive_type":"jar","archive_entries":4}
  self.assertEqual(_validated_content_upload_destination(item,good),good["destination_ref"])
  for patch in ({"destination_ref":"quarantine/i2/transfer-1/plugin.jar"},{"sha256":"b"*64},{"archive_type":"exe"},{"archive_entries":0}):
   bad={**good,**patch}
   with self.subTest(patch=patch),self.assertRaises(ValueError):_validated_content_upload_destination(item,bad)

if __name__=="__main__":unittest.main()
