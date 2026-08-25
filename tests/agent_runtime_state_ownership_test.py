#!/usr/bin/env python3

from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import instance_runtime
import runtime_operations


class RuntimeStateOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_instance_state_preserves_existing_owner_and_mode(self):
        path = self.root / "instances" / "instance-one.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}\n", encoding="utf-8")

        with patch.object(instance_runtime, "_existing_owner", return_value=(4242, 4343)), \
             patch.object(instance_runtime.os, "chown") as chown:
            instance_runtime._write(path, {"instance_id": "instance-one"})

        chown.assert_called_once()
        temp, uid, gid = chown.call_args.args
        self.assertEqual((uid, gid), (4242, 4343))
        self.assertEqual(Path(temp).parent, path.parent)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_operation_journal_preserves_existing_owner_and_mode(self):
        path = self.root / "instance-operations" / "instance-one.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}\n", encoding="utf-8")

        with patch.object(runtime_operations, "_existing_owner", return_value=(4242, 4343)), \
             patch.object(runtime_operations.os, "chown") as chown:
            runtime_operations._atomic(path, {"status": "completed"})

        chown.assert_called_once()
        temp, uid, gid = chown.call_args.args
        self.assertEqual((uid, gid), (4242, 4343))
        self.assertEqual(Path(temp).parent, path.parent)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_new_state_does_not_attempt_privileged_chown(self):
        instance_path = self.root / "instances" / "new.json"
        operation_path = self.root / "instance-operations" / "new.json"

        with patch.object(instance_runtime.os, "chown") as instance_chown:
            instance_runtime._write(instance_path, {"instance_id": "new"})
        with patch.object(runtime_operations.os, "chown") as operation_chown:
            runtime_operations._atomic(operation_path, {"status": "completed"})

        instance_chown.assert_not_called()
        operation_chown.assert_not_called()
        self.assertEqual(stat.S_IMODE(instance_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(operation_path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
