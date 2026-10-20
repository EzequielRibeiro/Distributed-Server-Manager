#!/usr/bin/env python3
"""Isolated regression checks for Controller terminal-result replay boundaries."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "dashboard" / "agent_instance_provisioning_repository.py"


class ControllerTerminalReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = CONTROLLER.read_text(encoding="utf-8")
        cls.module = ast.parse(cls.source)
        cls.repository = next(
            item for item in cls.module.body
            if isinstance(item, ast.ClassDef)
            and item.name == "AgentInstanceProvisioningRepository"
        )
        cls.method = next(
            item for item in cls.repository.body
            if isinstance(item, ast.FunctionDef) and item.name == "apply_result"
        )

    def test_terminal_claim_occurs_before_publication(self):
        source = ast.get_source_segment(self.source, self.method)
        self.assertIsNotNone(source)
        self.assertLess(
            source.index('updated_at={ph}'),
            source.index('publication = publish_pending_serverpack_bundle('),
        )
        self.assertIn("status NOT IN ('completed','failed')", source)

    def test_replay_reads_persisted_terminal_result(self):
        source = ast.get_source_segment(self.source, self.method)
        self.assertIn('SELECT * FROM agent_instance_provisioning WHERE provisioning_id=', source)
        self.assertIn('return _public_snapshot(terminal)', source)

    def test_base_repository_claims_terminal_before_publication(self):
        base_path = ROOT / "database" / "agent_instance_provisioning_repository.py"
        source = base_path.read_text(encoding="utf-8")
        module = ast.parse(source)
        repository = next(
            item for item in module.body
            if isinstance(item, ast.ClassDef)
            and item.name == "AgentInstanceProvisioningRepository"
        )
        method = next(
            item for item in repository.body
            if isinstance(item, ast.FunctionDef) and item.name == "apply_result"
        )
        body = ast.get_source_segment(source, method)
        self.assertLess(
            body.index("updated_at={ph}"),
            body.index("publication = publish_pending_serverpack_bundle("),
        )
        self.assertIn("return terminal", body)
        self.assertIn("status NOT IN ('completed','failed')", body)

    def test_stale_running_result_does_not_emit_progress_event(self):
        for relative_path in (
            "database/agent_instance_provisioning_repository.py",
            "dashboard/agent_instance_provisioning_repository.py",
        ):
            with self.subTest(repository=relative_path):
                source = (ROOT / relative_path).read_text(encoding="utf-8")
                module = ast.parse(source)
                repository = next(
                    item for item in module.body
                    if isinstance(item, ast.ClassDef)
                    and item.name == "AgentInstanceProvisioningRepository"
                )
                method = next(
                    item for item in repository.body
                    if isinstance(item, ast.FunctionDef) and item.name == "apply_result"
                )
                body = ast.get_source_segment(source, method)
                self.assertIn('running_updated = int(getattr(update, "rowcount", 0) or 0) == 1', body)
                self.assertIn('if status == "running" and not running_updated:', body)
                self.assertLess(
                    body.index('if status == "running" and not running_updated:'),
                    body.index("return state", body.index('if status == "running" and not running_updated:')) + 12,
                )

    def test_public_projection_removes_sensitive_diagnostics(self):
        projection = next(
            item for item in self.module.body
            if isinstance(item, ast.FunctionDef) and item.name == "_public_snapshot"
        )
        source = ast.get_source_segment(self.source, projection)
        self.assertIn("public_result.pop(field, None)", source)
        self.assertIn("_SENSITIVE_RESULT_FIELDS", source)


if __name__ == "__main__":
    unittest.main()
