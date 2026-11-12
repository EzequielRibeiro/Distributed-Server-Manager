#!/usr/bin/env python3
"""Read-only Controller receipt for committed Server Pack source promotion.

Not a content apply acknowledgement. Checks durable Controller DB state and the
stored provisioning publication in one database snapshot, never trusts the
Agent's standalone 'completed' file as publication proof.
"""
from __future__ import annotations
import json
from typing import Any, Mapping
from core.minecraft_serverpack_pending_commit import validate_pending_bundle_commit


class ServerPackControllerReceiptError(RuntimeError):
    pass


def confirmed_serverpack_receipt(*, backend, provisioning_id: str,
                                  agent_id: str, instance_id: str,
                                  candidate_sha256: str) -> dict[str, Any]:
    def require(value: Any, reason: str) -> None:
        if not value:
            raise ServerPackControllerReceiptError(reason)
    ph = "?" if backend.name == "sqlite" else "%s"
    with backend.connect() as connection:
        # A consistent read prevents a concurrent update from mixing a prior
        # provisioning receipt with a newer manifest or assignment revision.
        if backend.name == "postgresql":
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        elif backend.name == "sqlite":
            connection.execute("BEGIN")
        row = connection.execute(
            f"SELECT agent_id,instance_id,status,request_json,result_json "
            f"FROM agent_instance_provisioning WHERE provisioning_id={ph}",
            (provisioning_id,),
        ).fetchone()
        require(row is not None, "unknown provisioning operation")
        require(row["agent_id"] == agent_id and row["instance_id"] == instance_id,
                "provisioning does not belong to Agent/instance")
        require(row["status"] == "completed", "provisioning not completed")
        try:
            request = json.loads(row["request_json"])
            result = json.loads(row["result_json"])
            pending = validate_pending_bundle_commit(
                request["configuration"]["minecraft_serverpack_pending_bundle"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ServerPackControllerReceiptError("invalid stored publication evidence") from exc
        pub = result.get("controller_bundle_publication")
        require(isinstance(pub, Mapping) and pub.get("kind") == "MinecraftServerPackBundlePublication"
                and pub.get("status") == "published", "Controller publication not acknowledged")
        require(pending["candidate_sha256"] == candidate_sha256
                and pub.get("candidate_sha256") == candidate_sha256
                and pending["instance_id"] == instance_id
                and pub.get("content_id") == pending["content_id"]
                and pub.get("transfer_id") == pending["transfer_id"]
                and pub.get("migration_plan_sha256") == pending["migration_plan_sha256"],
                "candidate receipt mismatch")
        expected_revision = int(pending["expected_previous_revision"]) + 1
        require(pub.get("previous_bundle_revision") == expected_revision - 1
                and pub.get("bundle_revision") == expected_revision,
                "receipt revision mismatch")
        bundle = connection.execute(
            f"SELECT bundle_id,revision,manifest_sha256,loader_version,provider_version_id "
            f"FROM content_bundles WHERE instance_id={ph} AND parent_content_id={ph}",
            (instance_id, pending["content_id"]),
        ).fetchone()
        require(bundle is not None and bundle["revision"] == expected_revision
                and bundle["manifest_sha256"] == pub["manifest_sha256"]
                and bundle["loader_version"] == pending["bundle"]["loader_version"]
                and bundle["provider_version_id"] == pending["bundle"]["provider_version_id"],
                "published bundle is stale or changed")
        inst = connection.execute(
            f"SELECT agent_id,runtime_id,build_id FROM instances WHERE id={ph}",
            (instance_id,),
        ).fetchone()
        require(inst is not None and inst["agent_id"] == agent_id
                and inst["runtime_id"] == "minecraft.java.neoforge"
                and inst["build_id"] == pending["bundle"]["loader_version"],
                "runtime identity diverged after publication")
        history = connection.execute(
            f"SELECT manifest_json,manifest_sha256 FROM content_bundle_revisions "
            f"WHERE bundle_id={ph} AND revision={ph}",
            (bundle["bundle_id"],expected_revision),
        ).fetchone()
        require(history is not None and history["manifest_sha256"] == bundle["manifest_sha256"],
                "bundle revision history mismatch")
        try:
            members = json.loads(history["manifest_json"])["members"]
        except (ValueError, TypeError, KeyError) as exc:
            raise ServerPackControllerReceiptError("invalid stored bundle manifest") from exc
        ids = [str(x["content_id"]) for x in members]
        expected_ids = {x["content_id"] for x in pending["children"]}
        require(len(ids) == len(expected_ids) == len(pending["children"])
                and set(ids) == expected_ids, "published child inventory mismatch")
        published_members = {x["content_id"]: x for x in members}
        for child in pending["children"]:
            member = published_members[child["content_id"]]
            artifact = child["artifact"]
            expected_path = artifact.get("bundle_member") or f"mods/{child['content_id']}.jar"
            require(member.get("artifact") == artifact
                    and member.get("path") == expected_path
                    and expected_path.startswith("mods/")
                    and "/" not in expected_path[5:]
                    and "\\" not in expected_path,
                    "published member artifact changed")
        assignments = connection.execute(
            f"SELECT content_id,desired_state FROM content_assignments "
            f"WHERE instance_id={ph}", (instance_id,),
        ).fetchall()
        active = {r["content_id"] for r in assignments if r["desired_state"] == "installed"}
        require(active == {pending["content_id"], *expected_ids},
                "installed assignments do not match published Server Pack")
        return {
            "kind": "VerifiedServerPackControllerReceipt", "status": "verified",
            "provisioning_id": provisioning_id, "instance_id": instance_id,
            "agent_id": agent_id, "content_id": pending["content_id"],
            "candidate_sha256": candidate_sha256,
            "migration_plan_sha256": pending["migration_plan_sha256"],
            "bundle_revision": expected_revision,
            "manifest_sha256": bundle["manifest_sha256"],
            "loader_version": bundle["loader_version"],
            "child_count": len(expected_ids),
        }
