"""Boot witness must never turn a stale Done log into release authorization."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
import minecraft_serverpack_boot_witness as witness


class BootWitnessTest(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.runtime = Path(t.name) / "runtime"
        (self.runtime / "logs").mkdir(parents=True)
        self.start = datetime.now(timezone.utc) - timedelta(minutes=3)
        self.clock = datetime.now(timezone.utc)
        local = self.start.astimezone().replace(tzinfo=None)
        self.done = local + timedelta(minutes=2)
        self.write_done(self.done)
        self.stdout = (
            f"MainPID=1234\nActiveState=active\nWorkingDirectory={self.runtime}\n"
        )

    def write_done(self, when):
        stamp = when.strftime("%d%b%Y %H:%M:%S.%f")[:-3]
        (self.runtime / "logs/latest.log").write_text(
            f"[{stamp}] [Server thread/INFO] "
            "[net.minecraft.server.dedicated.DedicatedServer/]: "
            "Done (3.062s)! For help, type \"help\"\n"
        )

    def probe(self, *, second_service=None, process_starts=None):
        original_read = Path.read_text
        original_resolve = Path.resolve
        original_exists = Path.exists
        with (
            patch.object(witness.subprocess, "run",
                         side_effect=[SimpleNamespace(stdout=self.stdout),
                                      SimpleNamespace(stdout=second_service or self.stdout)]),
            patch.object(witness, "_command", side_effect=lambda pid:
                         ["/usr/bin/python3", "/opt/dsm/console_supervisor.py",
                          "capivara-instance-pr855-lab"] if pid == 1234 else
                         ["/usr/bin/java", "@capivara-launch.args"]),
            patch.object(witness, "_process_start",
                         side_effect=process_starts or
                         [self.start, self.start, self.start, self.start]),
            patch.object(witness.Path, "read_text", autospec=True) as reader,
        ):
            # Path.read_text mock only handles the proc children; logs still
            # use the ordinary filesystem method through the captured handle.
            def read(path, *args, **kwargs):
                if str(path) == "/proc/1234/task/1234/children":
                    return "5678"
                return original_read(path, *args, **kwargs)
            reader.side_effect = read
            with patch.object(witness.Path, "resolve", autospec=True) as resolve:
                resolve.side_effect = lambda path, *args, **kwargs: (
                    self.runtime if str(path) == "/proc/5678/cwd" else
                    original_resolve(path, *args, **kwargs)
                )
                with patch.object(witness.Path, "exists", autospec=True) as exists:
                    exists.side_effect = lambda path: (
                        True if str(path) == "/proc/5678" else original_exists(path)
                    )
                    return witness.observe_boot_witness(
                        self.runtime, instance_id="pr855-lab", now=self.clock
                    )

    def test_current_process_log_is_advisory_only(self):
        result = self.probe()
        self.assertEqual(result["status"], "boot_process_observed")
        self.assertIs(result["boot_verified"], False)
        self.assertIs(result["ready_for_release"], False)
        self.assertEqual(result["java_pid"], 5678)

    def test_service_restart_during_log_read_invalidates_positive_proof(self):
        replacement=self.stdout.replace("MainPID=1234", "MainPID=9999")
        result=self.probe(second_service=replacement)
        self.assertEqual(result["status"], "boot_unverified")
        self.assertEqual(result["reason"], "service_changed_during_probe")

    def test_supervisor_pid_reuse_during_log_read_invalidates_proof(self):
        changed=self.start + timedelta(seconds=3)
        result=self.probe(process_starts=[
            self.start, self.start, self.start, changed])
        self.assertEqual(result["status"], "boot_unverified")
        self.assertEqual(result["reason"], "service_changed_during_probe")

    def test_stale_done_and_missing_done_fail_closed(self):
        self.write_done((self.start - timedelta(minutes=15)).astimezone().replace(tzinfo=None))
        self.assertEqual(self.probe()["reason"], "no_current_java_done")
        (self.runtime / "logs/latest.log").write_text("no Done marker\n")
        self.assertEqual(self.probe()["status"], "boot_unverified")

    def test_wrong_service_and_future_done_fail_closed(self):
        self.stdout = self.stdout.replace("active", "inactive")
        self.assertEqual(self.probe()["reason"], "service_not_bound")
        self.stdout = self.stdout.replace("inactive", "active")
        self.write_done((self.clock + timedelta(hours=1)).astimezone().replace(tzinfo=None))
        self.assertEqual(self.probe()["reason"], "no_current_java_done")

    def test_invalid_instance_never_calls_systemd(self):
        self.assertEqual(
            witness.observe_boot_witness(self.runtime, instance_id="../other")["status"],
            "boot_unverified",
        )


if __name__ == "__main__":
    unittest.main()
