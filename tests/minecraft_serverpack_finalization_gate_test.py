"""Isolated finalization-result tests without importing live Agent services."""
import ast
from pathlib import Path
import unittest
from typing import Any

MODULE = Path(__file__).resolve().parents[1] / "agents/linux/runtime/provisioning_executor.py"
TREE = ast.parse(MODULE.read_text(encoding="utf-8"))
FUNCTION = next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "_serverpack_completion_state")
NS = {"Any": Any}
exec(compile(ast.Module(body=[FUNCTION], type_ignores=[]), str(MODULE), "exec"), NS)
completion = NS["_serverpack_completion_state"]


class FinalizationGateTests(unittest.TestCase):
    def test_committed_and_archived(self):
        self.assertEqual(completion({"status": "completed", "trace": ["committed", "finalized"], "finalization": {"status": "archived"}}), "completed")

    def test_idempotent_archive_is_complete(self):
        self.assertEqual(completion({"status": "completed", "trace": ["committed", "finalized"], "finalization": {"status": "already_archived"}}), "completed")

    def test_post_commit_pending(self):
        self.assertEqual(completion({"status": "finalization_pending", "trace": ["committed", "finalization_pending"]}), "finalization_pending")

    def test_legacy_completed_without_finalizer_rejected(self):
        with self.assertRaisesRegex(ValueError, "finalization"):
            completion({"status": "completed", "trace": ["committed"]})

    def test_completed_without_archive_rejected(self):
        with self.assertRaisesRegex(ValueError, "archival evidence"):
            completion({"status": "completed", "trace": ["committed", "finalized"]})

    def test_unknown_result_rejected(self):
        with self.assertRaisesRegex(ValueError, "did not complete"):
            completion({"status": "failed"})

    def test_nonmapping_rejected(self):
        with self.assertRaisesRegex(ValueError, "mapping"):
            completion(None)

    def test_executor_does_not_publish_success_on_pending(self):
        src = MODULE.read_text()
        assert src.index("completion = _serverpack_completion_state(detail)") < src.index('status="completed",\n                current_step="completed"')
        branch = src[src.index('if completion == "finalization_pending":'):src.index('            result = _result(\n                result_path,\n                request,\n                status="completed"')]
        self.assertIn('status="running"', branch)
        self.assertIn('finalization_state="pending"', branch)
        self.assertNotIn("INSTANCE_PROVISIONING_COMPLETED", branch)
        self.assertIn("INSTANCE_PROVISIONING_FINALIZATION_PENDING", branch)


if __name__ == "__main__":
    unittest.main()
