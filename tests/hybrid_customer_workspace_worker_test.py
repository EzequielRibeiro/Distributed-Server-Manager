#!/usr/bin/env python3
"""Regression tests for Hybrid Customer Workspace command planes."""
from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "dashboard" / "workers"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from backend import DatabaseConfig
from backend_factory import create_backend
from hybrid_customer_workspace_worker import (
    _import_suffix,
    process_hybrid_artifact_cycle,
    process_hybrid_console_cycle,
    process_hybrid_file_cycle,
    workspace_cycle,
)


class HybridCustomerWorkspaceWorkerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "dsm"
        (self.root / "config").mkdir(parents=True)
        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(Path(self.temp.name) / "capivara.db"),
            )
        )

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def test_non_hybrid_installation_is_inert(self):
        (self.root / "config" / "agent.conf").write_text(
            'AGENT_ID=""\nDSM_NODE_ROLE="controller"\n',
            encoding="utf-8",
        )
        self.assertEqual(
            workspace_cycle(self.root, backend=self.backend),
            {"active": False, "reason": "not_hybrid"},
        )

    def test_file_cycle_uses_canonical_linux_executor(self):
        repository = Mock()
        repository.command_for_agent.return_value = {
            "command_id": "instance-file-1",
            "instance_id": "instance-1",
            "action": "list",
        }
        repository.apply_result.return_value = {
            "status": "completed",
        }
        client = Mock()
        client.handle_command.return_value = {
            "command_id": "instance-file-1",
            "instance_id": "instance-1",
            "action": "list",
            "status": "completed",
            "result": {"entries": []},
        }
        with (
            patch(
                "hybrid_customer_workspace_worker._hybrid_agent_config",
                return_value={"agent_id": "hybrid-1"},
            ),
            patch(
                "hybrid_customer_workspace_worker.InstanceFileRepository",
                return_value=repository,
            ),
            patch(
                "hybrid_customer_workspace_worker._runtime_client",
                return_value=client,
            ),
        ):
            result = process_hybrid_file_cycle(
                self.backend,
                self.root,
                "hybrid-1",
            )
        repository.initialize.assert_called_once_with()
        repository.command_for_agent.assert_called_once_with("hybrid-1")
        client.handle_command.assert_called_once()
        repository.apply_result.assert_called_once()
        client.clear_result.assert_called_once_with("instance-file-1")
        self.assertEqual(result["status"], "completed")

    def test_console_cycle_marks_delivery_and_applies_result(self):
        repository = Mock()
        repository.command_for_agent.return_value = {
            "command_id": "console-1",
            "instance_id": "instance-1",
            "command_text": "status",
        }
        repository.apply_console_result.return_value = {
            "status": "completed",
        }
        client = Mock()
        client.handle_command.return_value = {
            "command_id": "console-1",
            "instance_id": "instance-1",
            "status": "completed",
            "output": ["ok"],
        }
        with (
            patch(
                "hybrid_customer_workspace_worker._hybrid_agent_config",
                return_value={"agent_id": "hybrid-1"},
            ),
            patch(
                "hybrid_customer_workspace_worker.InstanceWorkspaceRepository",
                return_value=repository,
            ),
            patch(
                "hybrid_customer_workspace_worker._runtime_client",
                return_value=client,
            ),
        ):
            result = process_hybrid_console_cycle(
                self.backend,
                self.root,
                "hybrid-1",
            )
        repository.mark_console_delivered.assert_called_once_with("console-1")
        repository.apply_console_result.assert_called_once()
        client.clear_result.assert_called_once_with("console-1")
        self.assertEqual(result["status"], "completed")

    def test_artifact_export_streams_local_backup_without_agent_http(self):
        artifact = Path(self.temp.name) / "backup.tar.gz"
        artifact.write_bytes(b"capivara-backup")
        repository = Mock()
        repository.command_for_agent.return_value = {
            "transfer_id": "transfer-1",
            "direction": "agent_to_controller",
            "instance_id": "instance-1",
            "source_ref": "backup-1",
        }
        repository.receive_from_agent.return_value = {
            "status": "completed",
        }
        with (
            patch(
                "hybrid_customer_workspace_worker._hybrid_agent_config",
                return_value={"agent_id": "hybrid-1"},
            ),
            patch(
                "hybrid_customer_workspace_worker.ArtifactTransferRepository",
                return_value=repository,
            ),
            patch(
                "hybrid_customer_workspace_worker._backup_artifact",
                return_value=artifact,
            ),
        ):
            result = process_hybrid_artifact_cycle(
                self.backend,
                self.root,
                "hybrid-1",
            )
        repository.mark_transferring.assert_called_once_with("transfer-1")
        call = repository.receive_from_agent.call_args
        self.assertEqual(call.args[0:2], ("transfer-1", "hybrid-1"))
        self.assertEqual(call.kwargs["content_length"], len(b"capivara-backup"))
        self.assertEqual(result["status"], "completed")

    def test_content_upload_uses_quarantine_path_not_backup_id(self):
        repository = Mock()
        repository.command_for_agent.return_value = {
            "transfer_id": "transfer-content-1",
            "direction": "controller_to_agent",
            "purpose": "content_upload",
            "instance_id": "instance-1",
            "filename": "eicar-test.zip",
            "destination_ref": None,
        }
        repository.apply_agent_result.return_value = {
            "status": "completed",
        }
        detail = {
            "size_bytes": 236,
            "sha256": "a" * 64,
            "destination_ref": (
                "quarantine/instance-1/transfer-content-1/eicar-test.zip"
            ),
            "archive_type": "zip",
            "archive_entries": 1,
        }
        with (
            patch(
                "hybrid_customer_workspace_worker._hybrid_agent_config",
                return_value={"agent_id": "hybrid-1"},
            ),
            patch(
                "hybrid_customer_workspace_worker.ArtifactTransferRepository",
                return_value=repository,
            ),
            patch(
                "hybrid_customer_workspace_worker._install_content_upload_artifact",
                return_value=detail,
            ) as install_upload,
            patch(
                "hybrid_customer_workspace_worker._install_controller_artifact"
            ) as install_backup,
        ):
            result = process_hybrid_artifact_cycle(
                self.backend,
                self.root,
                "hybrid-1",
            )

        install_upload.assert_called_once()
        install_backup.assert_not_called()
        repository.apply_agent_result.assert_called_once_with(
            "hybrid-1",
            {
                "transfer_id": "transfer-content-1",
                "status": "completed",
                "transferred_bytes": 236,
                "destination_ref": (
                    "quarantine/instance-1/transfer-content-1/eicar-test.zip"
                ),
                "archive_type": "zip",
                "archive_entries": 1,
                "sha256": "a" * 64,
            },
        )
        self.assertEqual(result["status"], "completed")

    def test_unknown_controller_to_agent_purpose_fails_closed(self):
        repository = Mock()
        repository.command_for_agent.return_value = {
            "transfer_id": "transfer-unknown-1",
            "direction": "controller_to_agent",
            "purpose": "unexpected",
            "instance_id": "instance-1",
        }
        repository.apply_agent_result.return_value = {"status": "failed"}
        with (
            patch(
                "hybrid_customer_workspace_worker._hybrid_agent_config",
                return_value={"agent_id": "hybrid-1"},
            ),
            patch(
                "hybrid_customer_workspace_worker.ArtifactTransferRepository",
                return_value=repository,
            ),
            patch(
                "hybrid_customer_workspace_worker._install_content_upload_artifact"
            ) as install_upload,
            patch(
                "hybrid_customer_workspace_worker._install_controller_artifact"
            ) as install_backup,
        ):
            result = process_hybrid_artifact_cycle(
                self.backend,
                self.root,
                "hybrid-1",
            )

        install_upload.assert_not_called()
        install_backup.assert_not_called()
        report = repository.apply_agent_result.call_args.args[1]
        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            report["error"],
            "unsupported controller-to-agent artifact purpose",
        )
        self.assertEqual(result["status"], "failed")

    def test_import_archive_suffix_is_normalized_for_backup_client(self):
        self.assertEqual(_import_suffix("backup.tar"), ".tar")
        self.assertEqual(_import_suffix("backup.tar.gz"), ".tar.gz")
        self.assertEqual(_import_suffix("backup.tgz"), ".tar.gz")
        with self.assertRaises(ValueError):
            _import_suffix("backup.zip")

    def test_worker_supervisor_starts_hybrid_customer_workspace_plane(self):
        shell = (ROOT / "dashboard" / "workers" / "worker.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "start_python_worker hybrid_customer_workspace_worker.py",
            shell,
        )


if __name__ == "__main__":
    unittest.main()
