#!/usr/bin/env python3
"""Focused regressions reproduced on a real DSM Hybrid host after v2.0.29."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / "agents" / "linux" / "runtime" / "cap_dispatch.py"


class HybridReadinessDispatcherTest(unittest.TestCase):
    def test_dispatcher_compiles_and_hybrid_doctor_contract_is_reachable(self) -> None:
        subprocess.run([sys.executable, "-m", "py_compile", str(DISPATCH)], check=True)
        source = DISPATCH.read_text(encoding="utf-8")
        self.assertIn('CAPIVARA_AGENT_MODE", "hybrid"', source)
        self.assertIn('CAPIVARA_AGENT_SERVICE", "dsm-dashboard-worker.service"', source)
        self.assertIn('"embedded-database"', source)


if __name__ == "__main__":
    unittest.main()
