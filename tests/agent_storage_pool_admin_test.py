#!/usr/bin/env python3
from __future__ import annotations
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"database",ROOT/"dashboard"):
    if str(p) not in sys.path:sys.path.insert(0,str(p))
from agent_pairing_repository import AgentPairingRepository
from agent_storage_pool_admin import AgentStoragePoolAdmin
from backend import DatabaseConfig
from backend_factory import create_backend
from registry import installation_profile_identity
from registry_repository import RegistryRepository

class AgentStoragePoolAdminTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(Path(self.temp.name)/"db.sqlite")));self.backend.initialize()
        identity=installation_profile_identity(RegistryRepository(self.backend),profile="controller",hostname="controller-storage-admin");pairing=AgentPairingRepository(self.backend);issued=pairing.issue_token(controller_id=str(identity["controller_id"]),ttl_seconds=300)
        pairing.enroll(pairing_token=issued.token,agent_id="agent-one",node_id="node-one",name="Agent",fingerprint="sha256:one",hostname="agent-one",os_name="linux",architecture="x86_64")
        metadata={"telemetry":{"storage_pools":[{"id":"default","name":"Default","root_path":"/srv/default","storage_class":"ssd","enabled":True,"priority":10,"reserve_bytes":0,"default":True,"health":"online","usable_bytes":10000}]},"instance_telemetry":[]}
        with self.backend.transaction() as c:c.execute("UPDATE agents SET status=?,metadata_json=? WHERE id=?",("active",json.dumps(metadata),"agent-one"))
        self.service=AgentStoragePoolAdmin(self.backend);self.service.initialize()
    def tearDown(self):self.backend.close();self.temp.cleanup()
    def test_create_pool_and_set_default(self):
        detail,pid,created=self.service.upsert("agent-one",{"id":"nvme","name":"NVMe","root_path":"/srv/nvme","storage_class":"nvme","enabled":True,"priority":100,"reserve_bytes":1024},actor="admin")
        self.assertTrue(created);self.assertEqual(pid,"nvme");self.assertEqual({p["id"] for p in detail["pools"]},{"default","nvme"})
        detail=self.service.set_default("agent-one","nvme",actor="admin");self.assertEqual(detail["default_storage_pool_id"],"nvme")
    def test_default_pool_cannot_be_disabled_or_removed(self):
        with self.assertRaises(ValueError):self.service.set_enabled("agent-one","default",False,actor="admin")
        with self.assertRaises(ValueError):self.service.remove("agent-one","default",actor="admin")
    def test_assigned_pool_cannot_be_removed(self):
        self.service.upsert("agent-one",{"id":"hdd","root_path":"/srv/hdd","storage_class":"hdd","enabled":True},actor="admin")
        with self.backend.transaction() as c:
            row=c.execute("SELECT metadata_json FROM agents WHERE id=?",("agent-one",)).fetchone();metadata=json.loads(row["metadata_json"]);metadata["instance_telemetry"]=[{"instance_id":"instance-one","storage_pool_id":"hdd"}];c.execute("UPDATE agents SET metadata_json=? WHERE id=?",(json.dumps(metadata),"agent-one"))
        with self.assertRaisesRegex(ValueError,"assigned instances"):self.service.remove("agent-one","hdd",actor="admin")
    def test_duplicate_root_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"root_path"):self.service.upsert("agent-one",{"id":"dup","root_path":"/srv/default","storage_class":"ssd"},actor="admin")

if __name__=="__main__":unittest.main()
