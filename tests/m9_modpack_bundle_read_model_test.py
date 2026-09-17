#!/usr/bin/env python3
from __future__ import annotations
import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"core",ROOT/"database",ROOT/"dashboard"):
    if str(path) not in sys.path:sys.path.insert(0,str(path))

from backend import DatabaseConfig
from backend_factory import create_backend
from content_repository import ContentRepository
from customer_content_workspace import CustomerContentWorkspaceService


def artifact(name,digest="a"):
    return {"provider":"modrinth","url":f"https://cdn.modrinth.com/{name}.jar","filename":f"{name}.jar","sha512":digest*128}

def member(cid,digest="a"):
    return {"content_id":cid,"path":f"mods/{cid}.jar","required":True,"artifact":artifact(cid,digest)}

def bundle(version,members):
    return {"provider":"modrinth","provider_project_id":"pack-project","provider_version_id":version,"minecraft_version":"1.21.1","loader_id":"fabric","loader_version":"0.16.0","manifest_kind":"mrpack-v1","members":members,"override_roots":["overrides"]}


class M9ModpackBundleReadModelTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(Path(self.tmp.name)/"db.sqlite")))
        self.backend.initialize()
        with self.backend.transaction() as c:
            c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("ctrl-node","Controller","controller"))
            c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("agent-node","Agent","agent"))
            c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("ctrl","ctrl-node","Controller"))
            c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent","ctrl","agent-node","Agent","active"))
            customer=c.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("ctrl","Customer"))
            c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("inst","agent-node","minecraft","MC","stopped","ctrl","agent",customer.lastrowid))
        self.repo=ContentRepository(self.backend);self.repo.initialize()
        self.service=CustomerContentWorkspaceService.__new__(CustomerContentWorkspaceService)
        policy=SimpleNamespace(workshop_allowed=True,plugins_allowed=True,modpacks_allowed=True,datapacks_allowed=True,mods_allowed=True,modifications_allowed=True)
        self.service.workspace=SimpleNamespace(
            root=ROOT,
            require=lambda user,iid,permission:{"id":iid,"game_id":"minecraft","runtime_id":"minecraft.java.fabric","game_version":"1.21.1"},
            repo=SimpleNamespace(workspace_policy=lambda iid:{}),
            _contract_policy=lambda context,value:({"providers":{"modpack":["modrinth"],"mod":["modrinth"]}},policy),
        )
        self.service.content=self.repo

    def tearDown(self):
        self.backend.close();self.tmp.cleanup()

    def parent(self,version,digest="b"):
        return {"instance_id":"inst","content_id":"pack","content_type":"modpack","provider":"modrinth","version":version,"artifact":{"provider":"modrinth","url":f"https://cdn.modrinth.com/pack-{version}.mrpack","filename":"pack.mrpack","sha512":digest*128,"archive":True},"provenance":{"minecraft_modpack":{"project_id":"pack-project","version_id":version}}}

    def child(self,cid,version="1",digest="a"):
        return {"instance_id":"inst","content_id":cid,"content_type":"mod","provider":"modrinth","version":version,"artifact":artifact(cid,digest),"target":f"mods/{cid}"}

    def install(self,version="v1",members=None):
        members=members or [member("a"),member("b")]
        children=[self.child(m["content_id"],version,m["artifact"]["sha512"][0]) for m in members]
        return self.repo.put_bundle(self.parent(version),bundle(version,members),children,requested_by="test")

    def test_managed_bundle_view_is_customer_safe(self):
        self.install()
        view=self.service.bundle_details({"username":"customer"},"inst","pack")
        self.assertEqual(view["bundle_state"],"managed")
        self.assertEqual(view["current_revision"],1)
        self.assertEqual([m["content_id"] for m in view["members"]],["a","b"])
        payload=json.dumps(view,sort_keys=True)
        for forbidden in ("artifact","sha512","checksum","https://","manifest_json","override_roots"):
            self.assertNotIn(forbidden,payload)

    def test_bundle_view_exposes_revision_diff(self):
        self.install("v1",[member("a"),member("b")])
        self.install("v2",[member("b","c"),member("c")])
        view=self.service.bundle_details({"username":"customer"},"inst","pack")
        self.assertEqual(view["current_revision"],2)
        self.assertEqual(view["previous_revision"],1)
        self.assertEqual(view["diff_from_previous"],{"added":["c"],"removed":["a"],"updated":["b"],"unchanged":[]})

    def test_child_artifact_drift_marks_bundle_customized(self):
        self.install()
        child=self.repo.get("inst","a")
        raw={key:child.get(key) for key in ("instance_id","content_id","content_type","desired_state","activation_state","activation_order","version","provider","target","provenance","metadata","dependencies","conflicts")}
        raw["version"]="custom";raw["artifact"]=artifact("a-custom","f")
        self.repo.put(raw,requested_by="test")
        view=self.service.bundle_details({"username":"customer"},"inst","pack")
        self.assertEqual(view["bundle_state"],"customized")
        self.assertIn({"content_id":"a","reason":"artifact_drift"},view["customization_reasons"])


if __name__=="__main__":
    unittest.main()
