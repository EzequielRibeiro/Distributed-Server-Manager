#!/usr/bin/env python3
"""Synthetic, filesystem-free recovery assessment regression tests."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "common"))
from minecraft_serverpack_committed_recovery_assessment import (
    CommittedRecoveryAssessmentError, assess_failed_committed_migration,
)

OLD = "a" * 64
NEW = "b" * 64
DRIFT = "c" * 64


def evidence():
    return dict(
        instance_id="synthetic-minecraft-005", agent_id="agent-isolated",
        operation={"instance_id":"synthetic-minecraft-005", "agent_id":"agent-isolated",
                   "operation":"minecraft_serverpack_migration", "status":"failed",
                   "error":"migration failed and rollback also failed: manual recovery required"},
        journal={"kind":"CapivaraMinecraftServerPackMigrationSwap",
                 "phase":"committed", "original_tree_sha256":OLD,
                 "staged_managed_sha256":NEW,"target_loader_version":"26.1.2.109"},
        active_managed_sha256=NEW,rollback_tree_sha256=OLD,
        installed_loader_version="26.1.2.109",retained_backup_verified=True,
        game_unit_state="inactive",
    )


class AssessmentTest(unittest.TestCase):
    def test_matching_evidence_requires_manual_review_not_recovery(self):
        data=evidence();before=deepcopy(data)
        result=assess_failed_committed_migration(**data)
        self.assertEqual(result["status"],"manual_review_required")
        self.assertEqual(result["findings"],[])
        self.assertFalse(result["safe_to_change_journals"])
        self.assertFalse(result["rollback_authorized"])
        self.assertFalse(result["runtime_changes_authorized"])
        self.assertEqual(data,before)

    def test_mismatched_managed_runtime_is_blocked(self):
        data=evidence();data["active_managed_sha256"]=DRIFT
        result=assess_failed_committed_migration(**data)
        self.assertEqual(result["status"],"blocked")
        self.assertIn("active_managed_checkpoint_mismatch",result["findings"])

    def test_mismatched_rollback_is_blocked(self):
        data=evidence();data["rollback_tree_sha256"]=DRIFT
        self.assertIn("original_rollback_checkpoint_mismatch",
                      assess_failed_committed_migration(**data)["findings"])

    def test_missing_backup_is_blocked(self):
        data=evidence();data["retained_backup_verified"]=False
        self.assertIn("retained_backup_not_verified",
                      assess_failed_committed_migration(**data)["findings"])

    def test_service_must_be_inactive(self):
        for state in ("active","failed","unknown"):
            with self.subTest(state=state):
                data=evidence();data["game_unit_state"]=state
                self.assertIn("unit_not_proven_inactive",
                              assess_failed_committed_migration(**data)["findings"])

    def test_loader_proof_required_and_mismatch_blocks(self):
        data=evidence();data["installed_loader_version"]="26.1.2.94"
        self.assertIn("active_loader_mismatch",
                      assess_failed_committed_migration(**data)["findings"])
        data["installed_loader_version"]=""
        with self.assertRaises(CommittedRecoveryAssessmentError):
            assess_failed_committed_migration(**data)

    def test_wrong_agent_or_instance_cannot_review(self):
        for key,value in (("instance_id","other"),("agent_id","other")):
            with self.subTest(key=key):
                data=evidence();data[key]=value
                with self.assertRaises(CommittedRecoveryAssessmentError):
                    assess_failed_committed_migration(**data)

    def test_unsupported_operation_or_phase_fails_closed(self):
        for field,value in (("status","finalization_pending"),("error","readiness failed"),
                            ("operation","other")):
            with self.subTest(field=field):
                data=evidence();data["operation"][field]=value
                with self.assertRaises(CommittedRecoveryAssessmentError):
                    assess_failed_committed_migration(**data)
        data=evidence();data["journal"]["phase"]="swapped"
        with self.assertRaises(CommittedRecoveryAssessmentError):
            assess_failed_committed_migration(**data)

    def test_missing_or_malformed_digests_fail_closed(self):
        for key in ("original_tree_sha256","staged_managed_sha256"):
            data=evidence();data["journal"][key]="x"*64
            with self.subTest(key=key),self.assertRaises(CommittedRecoveryAssessmentError):
                assess_failed_committed_migration(**data)
        data=evidence();data["active_managed_sha256"]=""
        with self.assertRaises(CommittedRecoveryAssessmentError):
            assess_failed_committed_migration(**data)

    def test_cannot_infer_success_from_committed_phase_alone(self):
        data=evidence();data["active_managed_sha256"]=DRIFT
        data["retained_backup_verified"]=False;data["game_unit_state"]="active"
        result=assess_failed_committed_migration(**data)
        self.assertEqual(result["status"],"blocked")
        self.assertEqual(len(result["findings"]),3)
        self.assertFalse(result["rollback_authorized"])


if __name__=="__main__":
    unittest.main()
