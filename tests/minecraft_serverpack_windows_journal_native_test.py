"""Native Windows Agent runtime operation journal durability and pending barrier.

Launches an independent interpreter with Windows Agent module search path,
using only TemporaryDirectory. Designed to run on Windows and Linux CI; on
Windows the real msvcrt instance lock is used instead of a stub.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
WINDOWS=ROOT/"agents/windows/runtime"
IID="pr855-windows-journal-e2e"
AID="pr839-isolated-agent"

_SCRIPT=r'''
import json,sys
from pathlib import Path
import runtime_operations
iid=sys.argv[1]
mode=sys.argv[2]
config={"agent_id":"pr839-isolated-agent"}
path=Path(runtime_operations.instance_runtime.STATE_DIR)/"instance-operations"/(iid+".json")
if mode=="pending":
    with runtime_operations.runtime_operation(config,iid,"minecraft_serverpack_migration") as journal:
        journal["status"]="finalization_pending"
        journal["migration_plan_sha256"]="a"*64
    print(json.dumps(runtime_operations.read_operation(iid)),flush=True)
elif mode=="reject":
    try:
        with runtime_operations.runtime_operation(config,iid,"minecraft_serverpack_migration"):
            raise AssertionError("unsafe reentry permitted")
    except RuntimeError as exc:
        if "interrupted staged Minecraft migration" not in str(exc):
            raise
    print(json.dumps(runtime_operations.read_operation(iid)),flush=True)
elif mode=="recover-scan":
    recovered=runtime_operations.recover_interrupted_operations(config)
    print(json.dumps({"recovered":recovered,"journal":runtime_operations.read_operation(iid)}),flush=True)
elif mode=="read":
    print(json.dumps(runtime_operations.read_operation(iid)),flush=True)
else:
    raise ValueError(mode)
'''

class NativeWindowsJournalE2E(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="dsm-pr981-windows-journal-")
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.env={**os.environ,
            "CAPIVARA_AGENT_STATE_DIR":str(self.root),
            "PYTHONPATH":str(WINDOWS),
        }
    def child(self,mode):
        process=subprocess.run(
            [sys.executable,"-c",_SCRIPT,IID,mode],env=self.env,
            capture_output=True,text=True,timeout=15,
        )
        self.assertEqual(process.returncode,0,
                         f"{mode}: {process.stderr}\n{process.stdout}")
        return json.loads(process.stdout)
    def test_windows_pending_journal_survives_agent_restart_and_blocks_reentry(self):
        created=self.child("pending")
        self.assertEqual(created["status"],"finalization_pending")
        self.assertEqual(created["migration_plan_sha256"],"a"*64)
        self.assertEqual(self.child("read"),created)
        self.assertEqual(self.child("reject"),created)
        self.assertEqual(self.child("read"),created)
        self.assertEqual(self.child("recover-scan")["journal"],created)
        self.assertEqual(self.child("recover-scan")["recovered"],[])
        self.assertEqual(len(list((self.root/"instance-operations").glob("*.json"))),1)

    def test_windows_restart_marks_only_running_operations_interrupted(self):
        journal=self.root/"instance-operations"/(IID+".json")
        journal.parent.mkdir(parents=True)
        journal.write_text(json.dumps({
            "kind":"CapivaraInstanceRuntimeOperation",
            "agent_id":AID,"instance_id":IID,
            "operation":"minecraft_serverpack_migration",
            "status":"running","migration_plan_sha256":"a"*64,
        }))
        recovered=self.child("recover-scan")
        self.assertEqual(len(recovered["recovered"]),1)
        self.assertEqual(recovered["journal"]["status"],"interrupted")
        self.assertEqual(self.child("reject")["status"],"interrupted")
        self.assertEqual(self.child("recover-scan")["recovered"],[])

if __name__=="__main__":
    unittest.main()
