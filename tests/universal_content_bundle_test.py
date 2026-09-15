#!/usr/bin/env python3
from __future__ import annotations
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"core",ROOT/"database",ROOT/"dashboard"):
 if str(path) not in sys.path:sys.path.insert(0,str(path))
from backend import DatabaseConfig
from backend_factory import create_backend
from content_bundle import ContentBundleValidationError,normalize_bundle
from content_repository import ContentRepository
from schema_baseline import load_schema_baseline
from baseline_upgrade_engine import apply_pending_upgrades


def artifact(name):return {"provider":"modrinth","url":f"https://cdn.modrinth.com/{name}.jar","filename":f"{name}.jar","sha512":"a"*128}
def member(cid,path):return {"content_id":cid,"path":path,"required":True,"artifact":artifact(cid)}
def bundle(version="v1",members=None):return {"provider":"modrinth","provider_project_id":"pack-project","provider_version_id":version,"minecraft_version":"1.21.1","loader_id":"fabric","loader_version":"0.16.0","manifest_kind":"mrpack-v1","members":members or [member("child-a","mods/a.jar")],"override_roots":["overrides","server-overrides"]}

class ContentBundleContractTest(unittest.TestCase):
 def test_normalizes_manifest_and_checksum(self):
  value=normalize_bundle({"instance_id":"inst","parent_content_id":"pack",**bundle()})
  self.assertEqual(value["kind"],"CapivaraContentBundle");self.assertEqual(value["manifest"]["members"][0]["content_id"],"child-a");self.assertEqual(len(value["manifest_sha256"]),64)
 def test_unsafe_paths_duplicates_and_missing_hash_fail_closed(self):
  for bad in ("../mods/a.jar","/mods/a.jar","C:/mods/a.jar"):
   with self.subTest(path=bad),self.assertRaises(ContentBundleValidationError):normalize_bundle({"instance_id":"inst","parent_content_id":"pack",**bundle(members=[member("child-a",bad)])})
  with self.assertRaises(ContentBundleValidationError):normalize_bundle({"instance_id":"inst","parent_content_id":"pack",**bundle(members=[member("child-a","mods/a.jar"),member("child-b","mods/a.jar")])})
  bad=member("child-a","mods/a.jar");bad["artifact"].pop("sha512")
  with self.assertRaises(ContentBundleValidationError):normalize_bundle({"instance_id":"inst","parent_content_id":"pack",**bundle(members=[bad])})
  bad_hash=member("child-a","mods/a.jar");bad_hash["artifact"]["sha512"]="not-a-digest"
  with self.assertRaises(ContentBundleValidationError):normalize_bundle({"instance_id":"inst","parent_content_id":"pack",**bundle(members=[bad_hash])})
 def test_all_baselines_include_bundle_tables(self):
  for backend in ("sqlite","postgresql","mysql","mariadb"):
   sql=load_schema_baseline(backend).sql.lower();self.assertIn("create table if not exists content_bundles",sql);self.assertIn("create table if not exists content_bundle_revisions",sql)

class ContentBundleRepositoryTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(Path(self.tmp.name)/"db.sqlite")));self.backend.initialize()
  with self.backend.transaction() as c:
   c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("ctrl-node","Controller","controller"));c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("agent-node","Agent","agent"));c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("ctrl","ctrl-node","Controller"));c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent","ctrl","agent-node","Agent","active"));customer=c.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("ctrl","Customer"));c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("inst","agent-node","minecraft","MC","stopped","ctrl","agent",customer.lastrowid))
  self.repo=ContentRepository(self.backend);self.repo.initialize()
 def tearDown(self):self.backend.close();self.tmp.cleanup()
 def parent(self,version="1"):return {"instance_id":"inst","content_id":"pack","content_type":"modpack","provider":"modrinth","version":version,"artifact":{"provider":"modrinth","url":"https://cdn.modrinth.com/pack.mrpack","filename":"pack.mrpack","sha512":"b"*128,"archive":True}}
 def child(self,cid):return {"instance_id":"inst","content_id":cid,"content_type":"mod","provider":"modrinth","version":"1","artifact":artifact(cid)}
 def test_bundle_update_is_atomic_and_marks_stale_children_absent(self):
  first=self.repo.put_bundle(self.parent(),bundle(members=[member("child-a","mods/a.jar"),member("child-b","mods/b.jar")]),[self.child("child-a"),self.child("child-b")],requested_by="test")
  self.assertEqual(first["bundle_revision"],1);self.assertEqual(first["assignment"]["metadata"]["activation"]["mode"],"bundle-parent")
  second=self.repo.put_bundle(self.parent("2"),bundle("v2",[member("child-b","mods/b.jar")]),[self.child("child-b")],requested_by="test")
  self.assertEqual(second["bundle_revision"],2);stale=self.repo.get("inst","child-a");self.assertEqual((stale["desired_state"],stale["activation_state"]),("absent","disabled"))
  with self.backend.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM content_bundle_revisions").fetchone()[0],2)
 def test_bundle_enable_disable_remove_propagates_to_children(self):
  self.repo.put_bundle(self.parent(),bundle(members=[member("child-a","mods/a.jar"),member("child-b","mods/b.jar")]),[self.child("child-a"),self.child("child-b")],requested_by="test")
  disabled=self.repo.set_bundle_state("inst","pack",desired_state="installed",activation_state="disabled",requested_by="test");self.assertEqual(disabled["assignment"]["activation_state"],"disabled");self.assertTrue(all(row["activation_state"]=="disabled" for row in disabled["children"]))
  enabled=self.repo.set_bundle_state("inst","pack",desired_state="installed",activation_state="enabled",requested_by="test");self.assertTrue(all(row["activation_state"]=="enabled" for row in enabled["children"]))
  removed=self.repo.set_bundle_state("inst","pack",desired_state="absent",activation_state="disabled",requested_by="test");self.assertEqual(removed["assignment"]["desired_state"],"absent");self.assertTrue(all(row["desired_state"]=="absent" for row in removed["children"]))
 def test_upgrade_10_creates_bundle_tables_for_existing_ledger(self):
  with self.backend.transaction() as c:
   c.execute("DROP TABLE content_bundle_revisions");c.execute("DROP TABLE content_bundles");c.execute("DELETE FROM baseline_upgrades WHERE version>=10")
  with self.backend.transaction() as c:
   completed=apply_pending_upgrades(self.backend,c,installed_checksum="ledger-already-exists")
  self.assertEqual(completed,[10,11])
  with self.backend.connect() as c:
   tables={row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
  self.assertTrue({"content_bundles","content_bundle_revisions"}.issubset(tables))
 def test_bundle_refuses_parent_or_child_owned_by_other_content(self):
  self.repo.put({"instance_id":"inst","content_id":"pack","content_type":"mod","provider":"modrinth","version":"1","artifact":artifact("foreign-parent")},requested_by="test")
  with self.assertRaisesRegex(Exception,"parent content_id"):
   self.repo.put_bundle(self.parent(),bundle(),[self.child("child-a")],requested_by="test")
  with self.backend.transaction() as c:
   c.execute("DELETE FROM content_assignment_revisions WHERE assignment_id=(SELECT assignment_id FROM content_assignments WHERE instance_id=? AND content_id=?)",("inst","pack"))
   c.execute("DELETE FROM content_assignments WHERE instance_id=? AND content_id=?",("inst","pack"))
  self.repo.put({"instance_id":"inst","content_id":"child-a","content_type":"mod","provider":"modrinth","version":"1","artifact":artifact("foreign-child")},requested_by="test")
  with self.assertRaisesRegex(Exception,"child content_id"):
   self.repo.put_bundle(self.parent(),bundle(),[self.child("child-a")],requested_by="test")
  self.assertIsNone(self.repo.get("inst","pack"))
 def test_bundle_rejects_child_manifest_mismatch_and_parent_as_child(self):
  bad=self.child("child-a");bad["artifact"]={**bad["artifact"],"url":"https://cdn.modrinth.com/other.jar"}
  with self.assertRaisesRegex(Exception,"artifact does not match manifest"):
   self.repo.put_bundle(self.parent(),bundle(),[bad],requested_by="test")
  parent_member=member("pack","mods/pack.jar")
  with self.assertRaisesRegex(Exception,"parent cannot also be a child"):
   self.repo.put_bundle(self.parent(),bundle(members=[parent_member]),[self.child("pack")],requested_by="test")
 def test_foreign_stale_assignment_aborts_entire_bundle_transaction(self):
  self.repo.put_bundle(self.parent(),bundle(),[self.child("child-a")],requested_by="test")
  with self.backend.transaction() as c:c.execute("UPDATE content_assignments SET metadata_json=? WHERE instance_id=? AND content_id=?",(json.dumps({"name":"foreign"}),"inst","child-a"))
  with self.assertRaises(Exception):self.repo.put_bundle(self.parent("2"),bundle("v2",[member("child-b","mods/b.jar")]),[self.child("child-b")],requested_by="test")
  self.assertEqual(self.repo.get("inst","pack")["version"],"1");self.assertIsNone(self.repo.get("inst","child-b"))
  with self.backend.connect() as c:self.assertEqual(c.execute("SELECT revision FROM content_bundles WHERE instance_id='inst' AND parent_content_id='pack'").fetchone()[0],1)

if __name__=="__main__":unittest.main()
