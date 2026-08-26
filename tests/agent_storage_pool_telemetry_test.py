#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
for path in (ROOT, RUNTIME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import instance_runtime
import runtime_metrics


class AgentStoragePoolTelemetryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old_state = instance_runtime.STATE_DIR
        self.old_config = os.environ.get("CAPIVARA_AGENT_CONFIG")
        instance_runtime.STATE_DIR = self.root / "agent-state"
        instance_runtime.STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root / "agent.json"
        os.environ["CAPIVARA_AGENT_CONFIG"] = str(self.config_path)

        self.nvme = self.root / "nvme"
        self.hdd = self.root / "hdd"
        self.nvme.mkdir()
        self.hdd.mkdir()
        self.config_path.write_text(json.dumps({
            "agent_id": "agent-one",
            "storage_pools": [
                {"id": "nvme", "root_path": str(self.nvme), "storage_class": "nvme", "priority": 100, "reserve_bytes": 1024},
                {"id": "hdd", "root_path": str(self.hdd), "storage_class": "capacity", "priority": 10, "reserve_bytes": 0},
            ],
            "default_storage_pool_id": "nvme",
        }), encoding="utf-8")

    def tearDown(self):
        instance_runtime.STATE_DIR = self.old_state
        if self.old_config is None:
            os.environ.pop("CAPIVARA_AGENT_CONFIG", None)
        else:
            os.environ["CAPIVARA_AGENT_CONFIG"] = self.old_config
        self.temp.cleanup()

    def test_snapshot_contains_storage_pool_inventory(self):
        snapshot = runtime_metrics.snapshot()
        pools = snapshot["storage_pools"]
        self.assertEqual({item["id"] for item in pools}, {"nvme", "hdd"})
        self.assertEqual(snapshot["telemetry"]["storage_pools"], pools)
        nvme = next(item for item in pools if item["id"] == "nvme")
        self.assertEqual(nvme["storage_class"], "nvme")
        self.assertTrue(nvme["default"])
        self.assertEqual(nvme["health"], "online")
        self.assertGreater(nvme["total_bytes"], 0)
        self.assertGreaterEqual(nvme["free_bytes"], nvme["usable_bytes"])
        self.assertEqual(nvme["free_bytes"] - nvme["usable_bytes"], 1024)

    def test_snapshot_emits_observability_metrics_per_pool(self):
        snapshot = runtime_metrics.snapshot()
        samples = snapshot["observability_samples"]
        pool_samples = [item for item in samples if str(item.get("metric_name", "")).startswith("capivara.storage.pool.")]
        self.assertTrue(pool_samples)
        ids = {item.get("dimensions", {}).get("storage_pool_id") for item in pool_samples}
        self.assertEqual(ids, {"nvme", "hdd"})
        usable = [item for item in pool_samples if item["metric_name"] == "capivara.storage.pool.usable_bytes"]
        self.assertEqual(len(usable), 2)
        self.assertTrue(all(item["unit"] == "bytes" for item in usable))

    def test_missing_agent_config_keeps_snapshot_available(self):
        os.environ["CAPIVARA_AGENT_CONFIG"] = str(self.root / "missing.json")
        snapshot = runtime_metrics.snapshot()
        self.assertEqual(snapshot["storage_pools"], [])
        self.assertNotIn("storage_pools", snapshot["telemetry"])


if __name__ == "__main__":
    unittest.main()
