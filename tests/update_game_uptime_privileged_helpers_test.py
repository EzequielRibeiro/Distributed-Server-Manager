"""DSM #928: one grouped admission-only proof for two privileged Agent helpers.

No root service, game, user files, Agent host, network or updater is used.
No claim that an already-running helper has stopped is made.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
for folder in (
    ROOT / "agents/linux/runtime",
    ROOT / "agents/linux/privileged",
    ROOT / "agents/common",
):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import game_uptime_privileged_admission as admission


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrivilegedHelperAdmissionTests(unittest.TestCase):
    def test_two_root_helpers_refuse_new_mutations_without_touching_games(self):
        from unittest.mock import Mock

        materializer = load(
            "dsm928_privileged_materializer",
            ROOT / "agents/linux/privileged/materialize_instance.py")
        native = load(
            "dsm928_privileged_native_command",
            ROOT / "agents/linux/privileged/native_command.py")
        helpers = ((materializer, "dayz-002"), (native, "native-command-123"))

        # Both real run() entrypoints must check a genuine current hold before
        # touching any request file, runtime, instance or game.
        for observed in (
            {"active": True, "reason": "root_owned_maintenance_hold"},
            {"active": True, "reason": "pending_journal_requires_operator_recovery"},
            {"active": "invalid"},
            None,
        ):
            with self.subTest(observed=observed), \
                 patch.object(admission, "observe", return_value=observed):
                for helper, ident in helpers:
                    with patch.object(helper.os, "geteuid", return_value=0), \
                         patch.object(Path, "read_text",
                                      side_effect=AssertionError("request read before hold check")):
                        with self.assertRaisesRegex(
                                admission.PrivilegedMutationHold,
                                "agent_privileged_maintenance_hold_active"):
                            helper.run(ident)

        # Reader exceptions also fail closed, not fallback to 'no hold'.
        with patch.object(admission, "observe", side_effect=OSError("missing evidence")):
            with self.assertRaises(admission.PrivilegedMutationHold):
                admission.require_privileged_mutation_admission()

        # Explicitly absent hold must allow old routing to proceed to the
        # request-file read; we deliberately abort before any real action.
        with patch.object(admission, "observe", return_value={"active": False}):
            for helper, ident in helpers:
                with patch.object(helper.os, "geteuid", return_value=0), \
                     patch.object(Path, "read_text", side_effect=LookupError("fixture stop")):
                    with self.assertRaisesRegex(LookupError, "fixture stop"):
                        helper.run(ident)

        # Materializer's legacy apply-error cleanup grants read access.
        # It must never run this mutation if the *reason* for error is a
        # maintenance hold. The error result itself is allowed bookkeeping.
        with tempfile.TemporaryDirectory(prefix="dsm928-privileged-") as temp:
            root = Path(temp)
            (root / "dayz-002.request.json").write_text(
                json.dumps({"action": "apply"}), encoding="utf-8")
            with patch.object(materializer, "REQUEST_ROOT", root), \
                 patch.object(materializer.sys, "argv",
                              ["materialize_instance.py", "dayz-002"]), \
                 patch.object(admission, "observe",
                              return_value={"active": True}), \
                 patch.object(materializer.os, "geteuid", return_value=0), \
                 patch.object(materializer, "_grant_customer_files_access") as grant:
                self.assertEqual(materializer.main(), 1)
                grant.assert_not_called()
            result = json.loads(
                (root / "dayz-002.result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "failed")
            self.assertIn("maintenance_hold_active", result["error"])


if __name__ == "__main__":
    unittest.main()
