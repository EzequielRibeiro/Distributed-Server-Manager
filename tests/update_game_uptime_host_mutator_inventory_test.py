"""#928 grouped, source-only inventory regression; no production host touched."""
from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
from game_uptime_host_mutator_inventory import (
    PRIVILEGED, NONCOOPERATING, READ_ONLY, CHILD_PATH, assess,
)


class MutatorInventoryTests(unittest.TestCase):
    def test_grouped_fails_closed_for_uncovered_and_regressed_host_paths(self):
        current = assess(ROOT)
        self.assertEqual(current["status"],
                         "source_inventory_only_no_quiescence")
        self.assertEqual(current["privileged_expected_modules"], 9)
        self.assertEqual(current["privileged_observed_modules"], 9)
        self.assertEqual(current["guarded_source_entrypoints"], 9)
        self.assertEqual(current["privileged_unclassified_modules"], [])
        self.assertIn(
            "detached_uninstall_finalizer_runtime_coverage_unverified",
            current["blockers"])
        for key in ("installed_process_identity_verified",
                    "all_runtime_flags_verified",
                    "all_external_jobs_inventoried",
                    "external_jobs_acked", "remote_agents_acked",
                    "live_no_drain_authorized"):
            self.assertIs(current[key], False)

        with tempfile.TemporaryDirectory(prefix="dsm928-inventory-") as temp:
            stage = Path(temp)
            privileged = stage / "agents/linux/privileged"
            privileged.mkdir(parents=True)
            for name in (set(PRIVILEGED) | set(NONCOOPERATING) | READ_ONLY):
                shutil.copy2(ROOT / "agents/linux/privileged" / name,
                             privileged / name)
            child_path = stage / CHILD_PATH
            child_path.parent.mkdir(parents=True)
            shutil.copy2(ROOT / CHILD_PATH, child_path)

            ready = assess(stage)
            self.assertEqual(ready["guarded_source_entrypoints"], 9)
            self.assertFalse(ready["live_no_drain_authorized"])
            self.assertIn("all_external_jobs_not_inventoried", ready["blockers"])

            # A removed decorator, newly introduced root executable, and
            # changed child source must all be reported; no silent approval.
            target = privileged / "native_command.py"
            text = target.read_text()
            self.assertIn("@fence_privileged_helper_run", text)
            target.write_text(text.replace("@fence_privileged_helper_run",
                                           "# deleted by regression fixture", 1))
            (privileged / "new_privileged_job.py").write_text(
                "def run():\n    pass\n", encoding="utf-8")
            unsafe = assess(stage)
            self.assertIn("missing_source_guard:native_command.py:run",
                          unsafe["blockers"])
            self.assertEqual(unsafe["privileged_unclassified_modules"],
                             ["new_privileged_job.py"])
            self.assertIn("unclassified_privileged_executables",
                          unsafe["blockers"])

            uninstall = privileged / "uninstall_agent.py"
            source = uninstall.read_text()
            self.assertIn("@fence_privileged_helper_run", source)
            uninstall.write_text(source.replace(
                "@fence_privileged_helper_run",
                "# missing uninstall guard in fixture", 1,
            ))
            missing_uninstall = assess(stage)
            self.assertIn("missing_source_guard:uninstall_agent.py:main",
                          missing_uninstall["blockers"])
            self.assertFalse(missing_uninstall["live_no_drain_authorized"])

            child_path.unlink()
            child_path.symlink_to(ROOT / CHILD_PATH)
            unsafe_child = assess(stage)
            self.assertIn("missing_detached_child_source_guard",
                          unsafe_child["blockers"])
            self.assertFalse(unsafe_child["external_jobs_acked"])
            self.assertFalse(unsafe_child["live_no_drain_authorized"])


if __name__ == "__main__":
    unittest.main()
