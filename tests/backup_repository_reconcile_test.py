#!/usr/bin/env python3
"""Regression tests for Customer Workspace -> canonical backup reconciliation."""

from __future__ import annotations

import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for item in (ROOT, ROOT / "database"):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from admin_management_repository import AdminManagementRepository
from agent_pairing_repository import AgentPairingRepository
from backend import DatabaseConfig
from backend_factory import create_backend
from backup_repository import BackupRepository
from registry import installation_profile_identity
from registry_repository import RegistryRepository


class BackupRepositoryReconcileTest(unittest.TestCase):
    NOW_EPOCH = datetime(
        2026, 9, 7, 12, 0, 0, tzinfo=timezone.utc
    ).timestamp()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.backend = create_backend(
            DatabaseConfig(
                driver="sqlite",
                database=str(Path(self.temp.name) / "capivara.db"),
            )
        )
        self.backend.initialize()

        identity = installation_profile_identity(
            RegistryRepository(self.backend),
            profile="controller",
            hostname="backup-reconcile-controller",
        )
        self.controller_id = str(identity["controller_id"])

        self.agent_id = "agent-backup-reconcile"
        self.node_id = "node-backup-reconcile"

        pairing = AgentPairingRepository(self.backend)
        token = pairing.issue_token(
            controller_id=self.controller_id,
            created_by="test",
        )
        pairing.enroll(
            pairing_token=token.token,
            agent_id=self.agent_id,
            node_id=self.node_id,
            name="Backup Reconcile Agent",
            fingerprint="sha256:backup-reconcile-agent",
            hostname="backup-reconcile-agent",
            os_name="linux",
            architecture="x86_64",
            address="192.0.2.77",
        )

        admin = AdminManagementRepository(self.backend)
        customer = admin.create_customer(
            name="Backup Reconcile Customer",
            username="backup-reconcile-customer",
            password_hash="test-hash",
            controller_id=self.controller_id,
        )
        self.customer_id = customer["id"]

        self.instance_id = "instance-backup-reconcile"

        with self.backend.transaction() as connection:
            connection.execute(
                """
                INSERT INTO instances(
                    id,
                    node_id,
                    game_id,
                    name,
                    status,
                    controller_id,
                    agent_id,
                    customer_id
                )
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    self.instance_id,
                    self.node_id,
                    "minecraft",
                    "Backup Reconcile Instance",
                    "pending",
                    self.controller_id,
                    self.agent_id,
                    self.customer_id,
                ),
            )

            # Deliberately create only the Customer Workspace schedule.
            # There must be no corresponding backup_policies row yet.
            connection.execute(
                """
                INSERT INTO instance_backup_policy(
                    instance_id,
                    enabled,
                    schedule_time,
                    schedule_timezone,
                    healthy_only,
                    keep_single_operational
                )
                VALUES (?,?,?,?,?,?)
                """,
                (
                    self.instance_id,
                    1,
                    "00:00",
                    "UTC",
                    0,
                    1,
                ),
            )

        self.repo = BackupRepository(self.backend)

    def tearDown(self):
        self.backend.close()
        self.temp.cleanup()

    def _count(self, table: str, where: str, value) -> int:
        with self.backend.connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {where}=?",
                (value,),
            ).fetchone()
        return int(row["n"])

    def test_schedule_due_does_not_reconcile_other_agent_instance(self):
        self.assertIsNone(self.repo.get_policy(self.instance_id))

        created = self.repo.schedule_due(
            "agent-that-does-not-own-instance",
            now_epoch=self.NOW_EPOCH,
        )

        self.assertEqual(created, [])
        self.assertIsNone(self.repo.get_policy(self.instance_id))
        self.assertEqual(
            self._count(
                "backup_policies",
                "instance_id",
                self.instance_id,
            ),
            0,
        )
        self.assertEqual(
            self._count(
                "backup_jobs",
                "instance_id",
                self.instance_id,
            ),
            0,
        )

    def test_customer_schedule_disabled_blocks_job_without_disabling_canonical_policy(self):
        with self.backend.transaction() as connection:
            connection.execute(
                """
                UPDATE instance_backup_policy
                SET enabled=0
                WHERE instance_id=?
                """,
                (self.instance_id,),
            )

        first = self.repo.schedule_due(
            self.agent_id,
            now_epoch=self.NOW_EPOCH,
        )

        # Backfill still materializes a usable canonical policy.
        policy = self.repo.get_policy(self.instance_id)
        self.assertIsNotNone(policy)
        self.assertTrue(policy["enabled"])
        self.assertEqual(policy["revision"], 1)

        # Customer schedule is disabled, therefore no scheduled job.
        self.assertEqual(first, [])
        self.assertEqual(
            self._count(
                "backup_jobs",
                "instance_id",
                self.instance_id,
            ),
            0,
        )

        # Re-enable only the customer schedule.
        with self.backend.transaction() as connection:
            connection.execute(
                """
                UPDATE instance_backup_policy
                SET enabled=1
                WHERE instance_id=?
                """,
                (self.instance_id,),
            )

        second = self.repo.schedule_due(
            self.agent_id,
            now_epoch=self.NOW_EPOCH,
        )

        self.assertEqual(len(second), 1)

        # Canonical policy was not rewritten just because the
        # customer changed its schedule state.
        policy_after = self.repo.get_policy(self.instance_id)
        self.assertTrue(policy_after["enabled"])
        self.assertEqual(policy_after["revision"], 1)
        self.assertEqual(
            policy_after["policy_id"],
            policy["policy_id"],
        )

        self.assertEqual(
            self._count(
                "backup_jobs",
                "instance_id",
                self.instance_id,
            ),
            1,
        )

    def test_admin_disabled_canonical_policy_overrides_enabled_customer_schedule(self):
        result = self.repo.put_policy(
            {
                "instance_id":self.instance_id,
                "enabled":False,
                "mode":"world",
                "consistency":"quiesced",
                "compression":"none",
                "interval_seconds":3600,
                "retention_count":3,
                "include_paths":["config"],
                "exclude_paths":["cache"],
            },
            requested_by="admin",
        )

        policy = result["policy"]

        self.assertFalse(policy["enabled"])
        self.assertEqual(policy["revision"], 1)
        self.assertEqual(policy["requested_by"], "admin")

        # Workspace schedule remains enabled from setUp(), but the
        # administrative/global canonical gate must win.
        created = self.repo.schedule_due(
            self.agent_id,
            now_epoch=self.NOW_EPOCH,
        )

        self.assertEqual(created, [])

        policy_after = self.repo.get_policy(self.instance_id)

        # Scheduler must not overwrite an administrative policy.
        self.assertFalse(policy_after["enabled"])
        self.assertEqual(policy_after["revision"], 1)
        self.assertEqual(policy_after["requested_by"], "admin")
        self.assertEqual(policy_after["mode"], "world")
        self.assertEqual(policy_after["consistency"], "quiesced")
        self.assertEqual(policy_after["compression"], "none")
        self.assertEqual(policy_after["interval_seconds"], 3600)
        self.assertEqual(policy_after["retention_count"], 3)
        self.assertEqual(policy_after["include_paths"], ["config"])
        self.assertEqual(policy_after["exclude_paths"], ["cache"])

        self.assertEqual(
            self._count(
                "backup_jobs",
                "instance_id",
                self.instance_id,
            ),
            0,
        )

    def test_healthy_only_requires_runtime_health_projection(self):
        from agent_instance_runtime_health_repository import (
            AgentInstanceRuntimeHealthRepository,
        )

        with self.backend.transaction() as connection:
            connection.execute(
                """
                UPDATE instance_backup_policy
                SET healthy_only=1
                WHERE instance_id=?
                """,
                (self.instance_id,),
            )

        # Without a Controller-side runtime health projection,
        # healthy_only must block the scheduled backup.
        blocked = self.repo.schedule_due(
            self.agent_id,
            now_epoch=self.NOW_EPOCH,
        )

        self.assertEqual(blocked, [])
        self.assertEqual(
            self._count(
                "backup_jobs",
                "instance_id",
                self.instance_id,
            ),
            0,
        )

        health = AgentInstanceRuntimeHealthRepository(self.backend)
        health.initialize()

        applied = health.apply_inventory(
            self.agent_id,
            [
                {
                    "instance_id":self.instance_id,
                    "desired_state":"running",
                    "observed_state":"running",
                    "reconcile_status":"healthy",
                    "health":"healthy",
                    "operation_status":"idle",
                }
            ],
        )

        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["health"], "healthy")

        created = self.repo.schedule_due(
            self.agent_id,
            now_epoch=self.NOW_EPOCH,
        )

        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["instance_id"], self.instance_id)
        self.assertEqual(created[0]["reason"], "schedule")

    def test_schedule_due_reconciles_and_is_idempotent(self):
        # Legacy/current workspace-only state.
        self.assertIsNone(self.repo.get_policy(self.instance_id))
        self.assertEqual(
            self._count(
                "backup_policies",
                "instance_id",
                self.instance_id,
            ),
            0,
        )

        # First scheduler pass must materialize the canonical policy
        # and create exactly one due backup job.
        first = self.repo.schedule_due(
            self.agent_id,
            now_epoch=self.NOW_EPOCH,
        )

        policy = self.repo.get_policy(self.instance_id)
        self.assertIsNotNone(policy)

        self.assertEqual(policy["instance_id"], self.instance_id)
        self.assertEqual(policy["agent_id"], self.agent_id)
        self.assertTrue(policy["enabled"])
        self.assertEqual(policy["mode"], "full")
        self.assertEqual(policy["consistency"], "live")
        self.assertEqual(policy["compression"], "gzip")
        self.assertEqual(policy["interval_seconds"], 21600)
        self.assertEqual(policy["retention_count"], 7)
        self.assertEqual(policy["revision"], 1)
        self.assertEqual(policy["requested_by"], "scheduler")

        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["instance_id"], self.instance_id)
        self.assertEqual(first[0]["agent_id"], self.agent_id)
        self.assertEqual(first[0]["action"], "create")
        self.assertEqual(first[0]["status"], "pending")
        self.assertEqual(first[0]["reason"], "schedule")
        self.assertEqual(first[0]["requested_by"], "scheduler")

        self.assertEqual(
            self._count(
                "backup_policies",
                "instance_id",
                self.instance_id,
            ),
            1,
        )
        self.assertEqual(
            self._count(
                "backup_policy_revisions",
                "policy_id",
                policy["policy_id"],
            ),
            1,
        )
        self.assertEqual(
            self._count(
                "backup_jobs",
                "instance_id",
                self.instance_id,
            ),
            1,
        )

        # A second scheduler pass at the same instant must be a no-op:
        # existing canonical policy remains unchanged and the pending
        # job prevents another schedule job from being created.
        second = self.repo.schedule_due(
            self.agent_id,
            now_epoch=self.NOW_EPOCH,
        )

        self.assertEqual(second, [])

        policy_after = self.repo.get_policy(self.instance_id)
        self.assertEqual(
            policy_after["policy_id"],
            policy["policy_id"],
        )
        self.assertEqual(policy_after["revision"], 1)
        self.assertEqual(
            policy_after["checksum"],
            policy["checksum"],
        )

        self.assertEqual(
            self._count(
                "backup_policies",
                "instance_id",
                self.instance_id,
            ),
            1,
        )
        self.assertEqual(
            self._count(
                "backup_policy_revisions",
                "policy_id",
                policy["policy_id"],
            ),
            1,
        )
        self.assertEqual(
            self._count(
                "backup_jobs",
                "instance_id",
                self.instance_id,
            ),
            1,
        )


    def test_workspace_reconciliation_tolerates_concurrent_policy_winner(self):
        concurrent_policy = {
            "instance_id": self.instance_id,
            "agent_id": self.agent_id,
        }

        with (
            patch.object(
                self.repo,
                "get_policy",
                side_effect=[None, concurrent_policy],
            ) as get_policy,
            patch.object(
                self.repo,
                "put_policy",
                side_effect=RuntimeError("unique constraint"),
            ) as put_policy,
        ):
            created = self.repo._ensure_workspace_policies(
                self.agent_id
            )

        self.assertEqual(created, 0)
        self.assertEqual(get_policy.call_count, 2)
        put_policy.assert_called_once_with(
            {"instance_id": self.instance_id},
            requested_by="scheduler",
        )

    def test_workspace_reconciliation_does_not_hide_real_database_failure(self):
        with (
            patch.object(
                self.repo,
                "get_policy",
                side_effect=[None, None],
            ),
            patch.object(
                self.repo,
                "put_policy",
                side_effect=RuntimeError("database unavailable"),
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "database unavailable",
            ):
                self.repo._ensure_workspace_policies(
                    self.agent_id
                )


if __name__ == "__main__":
    unittest.main()
