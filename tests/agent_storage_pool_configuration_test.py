#!/usr/bin/env python3
from __future__ import annotations
import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/"agents"/"linux"/"runtime"
for p in (ROOT,RUNTIME):
    if str(p) not in sys.path:sys.path.insert(0,str(p))
import configuration_client

class AgentStoragePoolConfigurationTest(unittest.TestCase):
    def test_managed_pools_are_written_after_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config_path=root/"agent.json";state=root/"state";pool1=root/"p1";pool2=root/"p2"
            config_path.write_text(json.dumps({"agent_id":"agent-one","instance_storage_root":str(pool1)}),encoding="utf-8")
            command={"target_type":"agent","target_id":"agent-one","namespace":"capivara.agent.storage","revision":"1","checksum":"abc","value":{"instance_storage_root":str(pool1),"storage_pools":[{"id":"ssd","root_path":str(pool1),"storage_class":"ssd","enabled":True},{"id":"hdd","root_path":str(pool2),"storage_class":"hdd","enabled":True}],"default_storage_pool_id":"ssd","migrate_existing":False}}
            with patch.dict(os.environ,{"CAPIVARA_AGENT_CONFIG":str(config_path),"CAPIVARA_AGENT_STATE_DIR":str(state)},clear=False):
                result=configuration_client.apply_configuration(command)
            stored=json.loads(config_path.read_text(encoding="utf-8"));self.assertEqual(result["status"],"applied");self.assertEqual(stored["default_storage_pool_id"],"ssd");self.assertEqual({p["id"] for p in stored["storage_pools"]},{"ssd","hdd"});self.assertTrue(pool1.is_dir());self.assertTrue(pool2.is_dir())

if __name__=="__main__":unittest.main()
