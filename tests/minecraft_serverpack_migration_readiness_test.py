from __future__ import annotations
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"agents/linux/runtime"))
import minecraft_serverpack_migration_provisioning as m

class Adapter:
    def __init__(self,state="active"):self.state=state
    def status(self,record):return {"active_state":self.state}

class ReadinessTest(unittest.TestCase):
    def test_heavy_modpack_default_readiness_window_is_ten_minutes(self):
        import inspect
        self.assertEqual(inspect.signature(m._wait_for_done).parameters["timeout_seconds"].default,600)

    def test_old_done_is_rejected_and_new_done_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);log=root/"logs/latest.log";log.parent.mkdir()
            log.write_text("Done (old)\n")
            baseline=m._readiness_log_baseline(root)
            record={"working_directory":str(root)}
            self.assertFalse(m._wait_for_done(record,Adapter(),timeout_seconds=0.01,baseline=baseline))
            with log.open("a") as stream:stream.write("Done (new)\n")
            self.assertTrue(m._wait_for_done(record,Adapter(),timeout_seconds=0.01,baseline=baseline))
            self.assertFalse(m._wait_for_done(record,Adapter("failed"),timeout_seconds=0.01,baseline=baseline))

    def test_rotated_log_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);log=root/"logs/latest.log";log.parent.mkdir()
            log.write_text("Done (old)\n")
            baseline=m._readiness_log_baseline(root)
            log.rename(root/"logs/previous.log")
            log.write_text("Done (new)\n")
            self.assertTrue(m._wait_for_done({"working_directory":str(root)},Adapter(),timeout_seconds=0.01,baseline=baseline))

if __name__=="__main__":unittest.main()
