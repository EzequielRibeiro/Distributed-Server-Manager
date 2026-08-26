#!/usr/bin/env python3
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class StoragePoolBrowserContractTest(unittest.TestCase):
    def test_ui_exposes_managed_pool_actions(self):
        source=(ROOT/"dashboard"/"web"/"agent-storage-pools.js").read_text(encoding="utf-8")
        for token in ("Adicionar Storage Pool","set-default","enable","disable","DELETE","/api/admin/agent/storage-pools"):
            self.assertIn(token,source)
if __name__=="__main__":unittest.main()
