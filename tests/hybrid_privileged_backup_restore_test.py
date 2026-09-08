#!/usr/bin/env python3
"""Regression tests for the Hybrid privileged backup restore boundary."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "agents" / "linux" / "runtime"
PRIVILEGED = ROOT / "agents" / "linux" / "privileged"
for item in (RUNTIME, PRIVILEGED):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

import backup_client
import restore_instance_backup


class HybridPrivilegedBackupRestoreTest(unittest.TestCase):
    def test_non_hybrid_restore_keeps_direct_path(self):
        direct = Mock(return_value={"backup_id": "backup-1"})
        privileged = Mock()
        with (
            patch.object(backup_client, "_restore_direct", direct),
            patch.object(
                backup_client,
                "_restore_via_privileged_helper",
                privileged,
            ),
            patch.dict(
                os.environ,
                {"CAPIVARA_BACKUP_RESTORE_UNIT_TEMPLATE": ""},
                clear=False,
            ),
        ):
            result = backup_client._restore(
                {"agent_id": "agent-1"},
                {
                    "command_id": "command-1",
                    "instance_id": "instance-1",
                    "backup_id": "backup-1",
                },
            )
        self.assertEqual(result, {"backup_id": "backup-1"})
        direct.assert_called_once()
        privileged.assert_not_called()

    def test_hybrid_restore_delegates_to_privileged_unit(self):
        direct = Mock()
        privileged = Mock(return_value={"backup_id": "backup-1"})
        template = "dsm-hybrid-agent-backup-restore@{command_id}.service"
        with (
            patch.object(backup_client, "_restore_direct", direct),
            patch.object(
                backup_client,
                "_restore_via_privileged_helper",
                privileged,
            ),
            patch.dict(
                os.environ,
                {"CAPIVARA_BACKUP_RESTORE_UNIT_TEMPLATE": template},
                clear=False,
            ),
        ):
            result = backup_client._restore(
                {"agent_id": "agent-1"},
                {
                    "command_id": "command-1",
                    "instance_id": "instance-1",
                    "backup_id": "backup-1",
                },
            )
        self.assertEqual(result, {"backup_id": "backup-1"})
        direct.assert_not_called()
        privileged.assert_called_once()
        self.assertEqual(privileged.call_args.args[2], template)

    def test_privileged_helper_executes_only_validated_direct_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "state"
            requests = state / "privileged-backup-restore"
            requests.mkdir(parents=True)
            config_path = Path(temp) / "agent.json"
            config_path.write_text(
                json.dumps({"agent_id": "agent-1"}),
                encoding="utf-8",
            )
            command_id = "command-1"
            request = {
                "schema_version": 1,
                "kind": "CapivaraPrivilegedBackupRestoreRequest",
                "command_id": command_id,
                "action": "restore",
                "instance_id": "instance-1",
                "agent_id": "agent-1",
                "backup_id": "backup-1",
            }
            (requests / f"{command_id}.request.json").write_text(
                json.dumps(request),
                encoding="utf-8",
            )
            operation = {
                "backup_id": "backup-1",
                "artifact_path": "/tmp/backup-1.tar.gz",
            }
            files_access = {
                "instance_id": "instance-1",
                "directories": 2,
                "files": 3,
            }
            with (
                patch.object(restore_instance_backup, "REQUEST_ROOT", requests),
                patch.object(
                    restore_instance_backup,
                    "CONFIG_PATH",
                    config_path,
                ),
                patch.object(
                    restore_instance_backup.os,
                    "geteuid",
                    return_value=0,
                ),
                patch.object(
                    restore_instance_backup.backup_client,
                    "_restore_direct",
                    return_value=operation,
                ) as direct,
                patch.object(
                    restore_instance_backup.prepare_customer_files,
                    "run",
                    return_value=files_access,
                ) as prepare_files,
                patch.object(
                    restore_instance_backup,
                    "_write_result",
                ),
            ):
                result = restore_instance_backup.run(command_id)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(
                result["operation"],
                {**operation, "files_access": files_access},
            )
            direct.assert_called_once_with(
                {"agent_id": "agent-1"},
                {
                    "command_id": "command-1",
                    "instance_id": "instance-1",
                    "action": "restore",
                    "backup_id": "backup-1",
                },
            )
            prepare_files.assert_called_once_with("instance-1")

    def test_installer_preserves_private_storage_boundary(self):
        installer = (
            ROOT / "installer" / "install_hybrid_runtime_substrate.sh"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'install -d -m 0711 -o root -g root "${DSM_ROOT}/runtime/hybrid-instance-storage"',
            installer,
        )
        self.assertIn(
            "dsm-hybrid-agent-backup-restore@.service",
            installer,
        )
        self.assertIn(
            "CAPIVARA_BACKUP_RESTORE_UNIT_TEMPLATE=",
            installer,
        )
        self.assertIn(
            'unit.indexOf("dsm-hybrid-agent-backup-restore@") === 0',
            installer,
        )

    def test_privileged_unit_is_root_owned_and_storage_scoped(self):
        unit = (
            ROOT / "systemd" / "dsm-hybrid-agent-backup-restore@.service.in"
        ).read_text(encoding="utf-8")
        self.assertIn("User=root", unit)
        self.assertIn("NoNewPrivileges=true", unit)
        self.assertIn(
            "ReadWritePaths=@DSM_ROOT@/runtime/hybrid-agent-state "
            "@DSM_ROOT@/runtime/hybrid-instance-storage",
            unit,
        )
        self.assertNotIn("ReadWritePaths=/", unit)


if __name__ == "__main__":
    unittest.main()
