#!/usr/bin/env python3
from __future__ import annotations
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for path in (ROOT/"core",ROOT/"database",ROOT/"dashboard"):
    if str(path) not in sys.path:sys.path.insert(0,str(path))
from backend import DatabaseConfig
from backend_factory import create_backend
from content_platform import ContentValidationError,normalize_assignment
from content_repository import ContentRepository
from schema_baseline import load_schema_baseline


class ContentContractV2Test(unittest.TestCase):
    def base(self):
        return {"agent_id":"agent-c4","instance_id":"instance-c4","content_id":"mod-one","game_id":"dayz","content_type":"mod","provider":"http","artifact":{"url":"https://example.invalid/mod.zip"}}

    def test_legacy_defaults_preserve_current_activation_behavior(self):
        item=normalize_assignment(self.base())
        self.assertEqual(item["schema_version"],2)
        self.assertEqual(item["desired_state"],"installed")
        self.assertEqual(item["activation_state"],"enabled")
        self.assertEqual(item["activation_order"],0)
        self.assertEqual(item["provenance"],{})
        self.assertEqual(item["metadata"],{})
        self.assertEqual(item["security_state"],"unscanned")
        absent=normalize_assignment({**self.base(),"desired_state":"absent"})
        self.assertEqual(absent["activation_state"],"disabled")

    def test_activation_is_distinct_from_installation_and_order_affects_checksum(self):
        enabled=normalize_assignment({**self.base(),"activation_state":"enabled","activation_order":10})
        disabled=normalize_assignment({**self.base(),"activation_state":"disabled","activation_order":10})
        reordered=normalize_assignment({**self.base(),"activation_state":"enabled","activation_order":20})
        self.assertEqual(disabled["desired_state"],"installed")
        self.assertNotEqual(enabled["checksum"],disabled["checksum"])
        self.assertNotEqual(enabled["checksum"],reordered["checksum"])

    def test_invalid_activation_and_spoofed_security_fail_closed(self):
        with self.assertRaises(ContentValidationError):normalize_assignment({**self.base(),"activation_state":"maybe"})
        with self.assertRaises(ContentValidationError):normalize_assignment({**self.base(),"desired_state":"absent","activation_state":"enabled"})
        for order in (-1,1000001,"abc"):
            with self.subTest(order=order),self.assertRaises(ContentValidationError):normalize_assignment({**self.base(),"activation_order":order})
        for state in ("clean","blocked","scan_failed"):
            with self.subTest(state=state),self.assertRaises(ContentValidationError):normalize_assignment({**self.base(),"security_state":state})

    def test_provenance_metadata_are_safe_structured_values(self):
        item=normalize_assignment({**self.base(),"source":{"kind":"steam-workshop","item_id":"123"},"metadata":{"name":"Example","size_bytes":42}})
        self.assertEqual(item["provenance"]["item_id"],"123")
        self.assertEqual(item["metadata"]["name"],"Example")
        with self.assertRaises(ContentValidationError):normalize_assignment({**self.base(),"metadata":{"nested":{"token":"secret"}}})
        with self.assertRaises(ContentValidationError):normalize_assignment({**self.base(),"provenance":{"script":"echo no"}})
        with self.assertRaises(ContentValidationError):normalize_assignment({**self.base(),"metadata":{"blob":"x"*70000}})

    def test_all_baselines_receive_v2_contract_before_checksum(self):
        for backend in ("sqlite","postgresql","mysql","mariadb"):
            with self.subTest(backend=backend):
                sql=load_schema_baseline(backend).sql
                self.assertIn("ADD COLUMN activation_state",sql)
                self.assertIn("ADD COLUMN activation_order",sql)
                self.assertIn("ADD COLUMN provenance_json",sql)
                self.assertIn("ADD COLUMN metadata_json",sql)
                self.assertIn("ADD COLUMN security_state",sql)


class ContentContractV2RepositoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.backend=create_backend(DatabaseConfig(driver="sqlite",database=str(Path(self.tmp.name)/"capivara.db")))
        self.backend.initialize()
        with self.backend.transaction() as c:
            c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node-controller","Controller","controller"))
            c.execute("INSERT INTO nodes(id,name,role) VALUES (?,?,?)",("node-agent","Agent","agent"))
            c.execute("INSERT INTO controllers(id,node_id,name) VALUES (?,?,?)",("controller-c4","node-controller","C4"))
            c.execute("INSERT INTO agents(id,controller_id,node_id,name,status) VALUES (?,?,?,?,?)",("agent-c4","controller-c4","node-agent","Agent C4","active"))
            customer=c.execute("INSERT INTO customers(controller_id,name) VALUES (?,?)",("controller-c4","Customer C4"))
            c.execute("INSERT INTO instances(id,node_id,game_id,name,status,controller_id,agent_id,customer_id) VALUES (?,?,?,?,?,?,?,?)",("instance-c4","node-agent","dayz","C4 Instance","stopped","controller-c4","agent-c4",int(customer.lastrowid)))
        self.repo=ContentRepository(self.backend);self.repo.initialize()

    def tearDown(self):
        self.backend.close();self.tmp.cleanup()

    def payload(self,order=20,state="enabled"):
        return {"instance_id":"instance-c4","content_id":"mod-one","content_type":"mod","provider":"http","artifact":{"url":"https://example.invalid/mod.zip"},"activation_state":state,"activation_order":order,"provenance":{"source":"customer"},"metadata":{"name":"Mod One"}}

    def test_roundtrip_revision_and_history_preserve_v2_fields(self):
        first=self.repo.put(self.payload(),requested_by="test")["assignment"]
        self.assertEqual(first["schema_version"],2)
        self.assertEqual(first["activation_state"],"enabled")
        self.assertEqual(first["activation_order"],20)
        self.assertEqual(first["provenance"],{"source":"customer"})
        self.assertEqual(first["metadata"],{"name":"Mod One"})
        self.assertEqual(first["security_state"],"unscanned")
        second=self.repo.put(self.payload(10,"disabled"),requested_by="test")["assignment"]
        self.assertEqual(second["revision"],2)
        history=self.repo.history(first["assignment_id"])
        self.assertEqual([row["activation_order"] for row in history],[10,20])
        self.assertEqual([row["activation_state"] for row in history],["disabled","enabled"])

    def test_list_order_is_activation_order_then_content_id(self):
        self.repo.put(self.payload(20))
        other={**self.payload(10),"content_id":"mod-two","artifact":{"url":"https://example.invalid/mod-two.zip"}}
        self.repo.put(other)
        self.assertEqual([row["content_id"] for row in self.repo.list(instance_id="instance-c4")],["mod-two","mod-one"])

    def test_agent_security_state_is_allowlisted(self):
        stored=self.repo.put(self.payload())["assignment"]
        base={"instance_id":"instance-c4","content_id":"mod-one","desired_revision":stored["revision"],"applied_revision":stored["revision"],"desired_checksum":stored["checksum"],"applied_checksum":stored["checksum"],"status":"applied","installed_version":"1.0"}
        self.assertEqual(self.repo.record_agent_state("agent-c4",[{**base,"security_state":"clean"}]),1)
        self.assertEqual(self.repo.record_agent_state("agent-c4",[{**base,"security_state":"invented"}]),0)


if __name__=="__main__":unittest.main()
