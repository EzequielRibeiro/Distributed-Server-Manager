#!/usr/bin/env python3
"""Prevent stale managed content from deleted instances leaking into new ones."""
import tempfile
import unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
for part in ("database","core","dashboard"):
    sys.path.insert(0,str(ROOT/part))
from backend import DatabaseConfig
from backend_factory import create_backend
from dashboard_repository import DashboardRepository
from content_repository import ContentRepository

class ContentDeletionIdentityTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.backend=create_backend(DatabaseConfig(
            driver="sqlite",database=str(Path(self.tmp.name)/"test.db")))
        self.backend.initialize()
        with self.backend.transaction() as db:
            db.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",
                       ("node","Node","hybrid"))
            db.execute("INSERT INTO controllers(id,node_id,name,status) VALUES (?,?,?,?)",
                       ("ctrl","node","Controller","active"))
            db.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",
                       ("agent","ctrl","node","Agent","active"))
            db.execute("INSERT INTO customers(id,controller_id,name,status) VALUES (?,?,?,?)",
                       (1,"ctrl","Cliente","active"))
            db.execute("INSERT INTO service_contracts(id,customer_id,game_id,status,instance_limit) VALUES (?,?,?,?,?)",
                       ("contract",1,"minecraft","active",1))
        self.db=DashboardRepository(self.backend)
        self.content=ContentRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.tmp.cleanup()

    def create(self):
        return self.db.create_customer_instance(
            customer_id=1,username="client",game="minecraft",
            runtime_id="minecraft.java.vanilla",edition="java",
            variant="vanilla",version="1.21.1",build="1.21.1",
            instances_root=Path(self.tmp.name)/"instances")

    def test_delete_purges_content_and_never_recycles_identity(self):
        first=self.create()
        old=first["instance_id"]
        item=self.content.put({
            "instance_id":old,"content_id":"VoteMe",
            "content_type":"plugin","provider":"http",
            "artifact":{"provider":"http","url":"https://example.invalid/voteme.jar"}
        },requested_by="test")["assignment"]
        self.assertEqual(len(self.content.list(instance_id=old)),1)
        self.assertEqual(self.db.delete_instance(old),1)
        with self.db.session() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM content_assignment_revisions WHERE assignment_id=?",
                (item["assignment_id"],)).fetchone()[0],0)
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM audit_log WHERE instance_id=? AND action=?",
                (old,"instance.identity.retired")).fetchone()[0],1)
        self.assertEqual(self.content.list(instance_id=old),[])
        second=self.create()
        self.assertNotEqual(second["instance_id"],old)
        self.assertTrue(second["instance_id"].endswith("-002"))
        self.assertEqual(self.content.list(instance_id=second["instance_id"]),[])

    def test_legacy_orphaned_content_never_reuses_id(self):
        first=self.create()
        old=first["instance_id"]
        self.content.put({"instance_id":old,"content_id":"old-plugin",
            "content_type":"plugin","provider":"http",
            "artifact":{"provider":"http","url":"https://example.invalid/old.jar"}})
        # Simulate a delete performed by an earlier release without content cleanup.
        with self.db.session(transaction=True) as db:
            db.execute("DELETE FROM instances WHERE id=?",(old,))
        self.assertEqual(len(self.content.list(instance_id=old)),1)
        second=self.create()
        self.assertNotEqual(second["instance_id"],old)
        self.assertEqual(self.content.list(instance_id=second["instance_id"]),[])

    def test_delete_purges_modpack_bundle_agent_state_and_update_state(self):
        iid=self.create()["instance_id"]
        art={"provider":"modrinth","url":"https://cdn.modrinth.com/a.jar",
             "filename":"a.jar","sha512":"a"*128}
        self.content.put_bundle(
            {"instance_id":iid,"content_id":"pack","content_type":"modpack",
             "provider":"modrinth","artifact":{"provider":"modrinth",
             "url":"https://cdn.modrinth.com/pack.mrpack","filename":"pack.mrpack",
             "sha512":"b"*128,"archive":True}},
            {"provider":"modrinth","provider_project_id":"pack-project",
             "provider_version_id":"version-1","minecraft_version":"1.21.1",
             "loader_id":"fabric","loader_version":"0.16.0",
             "manifest_kind":"mrpack-v1","override_roots":["overrides"],
             "members":[{"content_id":"child-a","path":"mods/a.jar",
                         "required":True,"artifact":art}]},
            [{"instance_id":iid,"content_id":"child-a","content_type":"mod",
              "provider":"modrinth","target":"mods/child-a","artifact":art}])
        with self.db.session(transaction=True) as db:
            db.execute("INSERT INTO agent_content_state(agent_id,instance_id,content_id,desired_revision,desired_checksum,status,reported_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                       ("agent",iid,"pack",1,"checksum","applied","2026-09-25","2026-09-25"))
            db.execute("INSERT INTO content_update_policy(instance_id,content_id,mode,created_at,updated_at) VALUES (?,?,?,?,?)",
                       (iid,"pack","manual","2026-09-25","2026-09-25"))
            db.execute("INSERT INTO content_update_state(agent_id,instance_id,content_id,provider,content_type,updated_at) VALUES (?,?,?,?,?,?)",
                       ("agent",iid,"pack","modrinth","modpack","2026-09-25"))
        self.assertEqual(self.db.delete_instance(iid),1)
        with self.db.session() as db:
            for table in ("content_assignments","content_assignment_revisions",
                          "content_bundles","content_bundle_revisions","agent_content_state",
                          "content_update_policy","content_update_state"):
                self.assertEqual(db.execute("SELECT COUNT(*) FROM "+table).fetchone()[0],0,table)

if __name__=="__main__":
    unittest.main()
