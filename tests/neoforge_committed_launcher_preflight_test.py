#!/usr/bin/env python3
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "linux" / "runtime"))
from adapters.systemd import AdapterError, SystemdAdapter

class CommittedLauncherPreflightTest(unittest.TestCase):
    def test_prevents_restart_with_old_launcher_and_allows_correct_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            runtime = state / "runtime"
            old = runtime / "libraries/net/neoforged/neoforge/26.1.2.94/unix_args.txt"
            new = runtime / "libraries/net/neoforged/neoforge/26.1.2.109/unix_args.txt"
            old.parent.mkdir(parents=True)
            new.parent.mkdir(parents=True)
            old.write_bytes(b"--fml.neoForgeVersion 26.1.2.94")
            new.write_bytes(b"--fml.neoForgeVersion 26.1.2.109")
            launch = runtime / "capivara-launch.args"
            launch.write_bytes(old.read_bytes())
            journal = state / ".dsm/minecraft-serverpack-migration.json"
            journal.parent.mkdir()
            journal.write_text(json.dumps({"phase":"committed","target_loader_version":"26.1.2.109"}))
            instance = {"instance_id":"minecraft-test", "environment_id":"minecraft.java.neoforge",
                        "instance_state_root":str(state),"working_directory":str(runtime)}
            calls=[]
            def runner(argv, timeout):
                calls.append(argv)
                return (0, "LoadState=loaded\nActiveState=active\nSubState=running\nMainPID=123", "")
            adapter = SystemdAdapter(runner=runner)
            with self.assertRaisesRegex(AdapterError, "does not match committed"):
                adapter.restart(instance)
            self.assertEqual(calls, [])
            # Legacy instance registry records may omit state root.
            without_state = dict(instance)
            without_state.pop("instance_state_root")
            with self.assertRaisesRegex(AdapterError, "does not match committed"):
                adapter.restart(without_state)
            self.assertEqual(calls, [])
            launch.write_bytes(new.read_bytes())
            result=adapter.restart(instance)
            self.assertEqual(result["action"], "restart")
            self.assertTrue(any(cmd[:2]==["systemctl","restart"] for cmd in calls))

    def test_unrelated_instance_skips_preflight(self):
        SystemdAdapter._verify_committed_neoforge_launcher({"environment_id":"minecraft.java.paper"})

if __name__ == "__main__":
    unittest.main()
