#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
for p in (ROOT,ROOT/"dashboard"):
    if str(p) not in sys.path:sys.path.insert(0,str(p))
import agent_storage_pool_admin_http as http

class StoragePoolAdminHttpContractTest(unittest.TestCase):
    def test_endpoint_and_events_are_stable(self):
        self.assertEqual(http.PATH,"/api/admin/agent/storage-pools")
        source=(ROOT/"dashboard"/"agent_storage_pool_admin_http.py").read_text(encoding="utf-8")
        for name in ("AGENT_STORAGE_POOL_CREATED","AGENT_STORAGE_POOL_UPDATED","AGENT_STORAGE_POOL_ENABLED","AGENT_STORAGE_POOL_DISABLED","AGENT_STORAGE_POOL_DEFAULT_CHANGED","AGENT_STORAGE_POOL_REMOVED"):
            self.assertIn(name,source)
        self.assertIn("operator",source)

if __name__=="__main__":unittest.main()
