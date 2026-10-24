"""Validate quarantine lookup in standalone and hybrid Agent configurations."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "agents" / "linux" / "runtime"

class ContentUploadQuarantineRootTest(unittest.TestCase):
    def root_for(self, **values):
        env = {k: v for k, v in os.environ.items()
               if k not in ("CAPIVARA_AGENT_STATE_DIR", "CAPIVARA_GAME_DATA_ROOT",
                            "CAPIVARA_AGENT_GAME_DATA_ROOT")}
        env.update(values)
        proc = subprocess.run(
            [sys.executable, "-c", "import content_upload_quarantine as q; print(q.GAME_DATA_ROOT)"],
            env={**env, "PYTHONPATH": str(MODULE)},
            check=True, text=True, capture_output=True,
        )
        return proc.stdout.strip()

    def test_standalone_default(self):
        self.assertEqual(self.root_for(), "/var/lib/capivara-agent/game-data")

    def test_hybrid_follows_agent_state_dir(self):
        self.assertEqual(
            self.root_for(CAPIVARA_AGENT_STATE_DIR="/opt/dsm/runtime/hybrid-agent-state"),
            "/opt/dsm/runtime/hybrid-agent-state/game-data",
        )

    def test_explicit_root_overrides_state_dir(self):
        self.assertEqual(
            self.root_for(CAPIVARA_AGENT_STATE_DIR="/opt/dsm/runtime/hybrid-agent-state",
                          CAPIVARA_GAME_DATA_ROOT="/srv/custom-data"),
            "/srv/custom-data",
        )

    def test_agent_game_data_root_override(self):
        self.assertEqual(
            self.root_for(CAPIVARA_AGENT_STATE_DIR="/opt/dsm/runtime/hybrid-agent-state",
                          CAPIVARA_AGENT_GAME_DATA_ROOT="/srv/agent-data"),
            "/srv/agent-data",
        )

if __name__ == "__main__":
    unittest.main()
