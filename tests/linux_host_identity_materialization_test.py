#!/usr/bin/env python3
"""Contract tests for canonical Linux Agent host identity materialization."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LinuxHostIdentityMaterializationTest(unittest.TestCase):
    def test_privileged_reconciler_materializes_canonical_host_identity(self):
        text = (ROOT / "agents/linux/privileged/reconcile_runtime_identity.py").read_text()
        self.assertIn('HOST_IDENTITY_PATH = STATE_DIR / "host-identity"', text)
        self.assertIn('product_uuid = _read_text(Path("/sys/class/dmi/id/product_uuid"))', text)
        self.assertIn('_write_canonical_host_identity(group.gr_gid)', text)
        self.assertIn('os.chmod(HOST_IDENTITY_PATH, 0o640)', text)

    def test_runtime_prefers_materialized_identity(self):
        text = (ROOT / "agents/linux/runtime/agent.py").read_text()
        self.assertIn('CAPIVARA_AGENT_HOST_IDENTITY', text)
        self.assertIn('canonical = _read_text(HOST_IDENTITY_PATH)', text)
        self.assertIn('if canonical:', text)
        self.assertIn('return canonical', text)

    def test_runtime_retains_legacy_fallback(self):
        text = (ROOT / "agents/linux/runtime/agent.py").read_text()
        self.assertIn('machine_id = _read_text("/etc/machine-id")', text)
        self.assertIn('product_uuid = _read_text("/sys/class/dmi/id/product_uuid")', text)


if __name__ == "__main__":
    unittest.main()
