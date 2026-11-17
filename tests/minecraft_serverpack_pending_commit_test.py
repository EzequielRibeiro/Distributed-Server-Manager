#!/usr/bin/env python3
from __future__ import annotations

import unittest

from core.minecraft_serverpack_pending_commit import (
    MinecraftServerPackPendingCommitError,
    authorize_after_agent_completion,
    build_pending_bundle_commit,
    validate_pending_bundle_commit,
)


def candidate():
    parent={
        "instance_id":"pr855-controller-pending",
        "content_id":"atm11",
        "content_type":"modpack",
        "provider":"local",
        "version":"0.9.0-beta",
        "target":"modpacks/atm11",
        "artifact":{"provider":"local","package_id":"quarantine/x.zip"},
        "metadata":{},
    }
    children=[
        {
            "instance_id":"pr855-controller-pending",
            "content_id":"mod-a",
            "content_type":"mod",
            "provider":"local",
            "version":"imported",
            "target":"mods/mod-a",
            "artifact":{"provider":"local","package_id":"mods/a.jar"},
            "metadata":{},
        },
        {
            "instance_id":"pr855-controller-pending",
            "content_id":"mod-b",
            "content_type":"mod",
            "provider":"local",
            "version":"imported",
            "target":"mods/mod-b",
            "artifact":{"provider":"local","package_id":"mods/b.jar"},
            "metadata":{},
        },
    ]
    bundle={
        "provider":"local",
        "provider_project_id":"atm11",
        "provider_version_id":"0.9.0-beta",
        "minecraft_version":"26.1.2",
        "loader_id":"neoforge",
        "loader_version":"26.1.2.109",
        "manifest_kind":"serverpack-local-v1",
        "manifest_sha256":"a"*64,
        "manifest":{"members":[]},
        "override_roots":["config","kubejs"],
        "checksum":"b"*64,
    }
    return build_pending_bundle_commit(
        instance_id="pr855-controller-pending",
        content_id="atm11",
        transfer_id="transfer-pending-1",
        migration_plan_sha256="c"*64,
        expected_previous_revision=3,
        parent=parent,
        bundle=bundle,
        children=children,
        requested_by="customer",
    )


def completed(pending):
    return {
        "status":"completed",
        "minecraft_serverpack_migration":{
            "status":"completed",
            "instance_id":pending["instance_id"],
            "content_id":pending["content_id"],
            "transfer_id":pending["transfer_id"],
            "migration_plan_sha256":pending["migration_plan_sha256"],
            "commit":{
                "status":"committed",
                "journal":{
                    "phase":"committed",
                    "migration_plan_sha256":pending["migration_plan_sha256"],
                },
            },
        },
    }


class PendingCommitTest(unittest.TestCase):
    def test_pending_candidate_is_immutable_and_unpublished(self):
        value=candidate()
        self.assertFalse(value["publish_allowed"])
        self.assertEqual(len(value["candidate_sha256"]),64)
        self.assertEqual(
            validate_pending_bundle_commit(value)["candidate_sha256"],
            value["candidate_sha256"],
        )

    def test_agent_completion_with_exact_committed_fingerprint_authorizes_publish(self):
        pending=candidate()
        authorized=authorize_after_agent_completion(pending,completed(pending))
        self.assertTrue(authorized["publish_allowed"])
        self.assertTrue(authorized["agent_commit_verified"])
        self.assertEqual(
            authorized["candidate_sha256"],
            pending["candidate_sha256"],
        )

    def test_failed_running_or_missing_migration_result_never_authorizes(self):
        pending=candidate()
        for result in (
            {"status":"failed"},
            {"status":"running"},
            {"status":"completed"},
        ):
            with self.subTest(result=result):
                with self.assertRaises(MinecraftServerPackPendingCommitError):
                    authorize_after_agent_completion(pending,result)

    def test_identity_fingerprint_and_swap_phase_mismatch_fail_closed(self):
        pending=candidate()
        mutations=(
            ("instance_id","other-instance"),
            ("content_id","other-content"),
            ("transfer_id","other-transfer"),
            ("migration_plan_sha256","d"*64),
        )
        for key,value in mutations:
            with self.subTest(key=key):
                result=completed(pending)
                result["minecraft_serverpack_migration"][key]=value
                with self.assertRaises(MinecraftServerPackPendingCommitError):
                    authorize_after_agent_completion(pending,result)
        result=completed(pending)
        result["minecraft_serverpack_migration"]["commit"]["journal"]["phase"]="recovered"
        with self.assertRaises(MinecraftServerPackPendingCommitError):
            authorize_after_agent_completion(pending,result)

    def test_tampered_pending_payload_is_rejected_even_if_agent_completed(self):
        pending=candidate()
        pending["children"][0]["version"]="tampered"
        with self.assertRaisesRegex(
            MinecraftServerPackPendingCommitError,
            "candidate checksum mismatch",
        ):
            authorize_after_agent_completion(pending,completed(candidate()))

    def test_pending_contract_rejects_prepublished_or_extra_fields(self):
        pending=candidate()
        for mutation in (
            {**pending,"publish_allowed":True},
            {**pending,"unexpected":"value"},
        ):
            with self.subTest(keys=sorted(mutation)):
                with self.assertRaises(MinecraftServerPackPendingCommitError):
                    validate_pending_bundle_commit(mutation)


if __name__=="__main__":
    unittest.main()
