#!/usr/bin/env python3
"""Atomic, replayable Controller recording of attested Server Pack Agent states.

The caller MUST independently attest the running JARs, prepared sources,
security scan and local JSON states before constructing these reports.
This module never reads or writes the Agent filesystem or restarts games.
It does not declare final convergence; the separate read-only convergence
verifier issues that receipt after local snapshot activation succeeds.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from minecraft_serverpack_content_receipt import confirmed_serverpack_receipt


class ServerPackAgentReportPublicationError(RuntimeError):
    pass


def publish_attested_serverpack_reports(
    *, backend, provisioning_id: str, agent_id: str, instance_id: str,
    candidate_sha256: str, reports: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """All-or-nothing Agent report CAS against the Controller's published rev.

    A retry with exactly the same evidence is safe. An older migration is
    rejected once Controller's bundle has advanced.
    """
    receipt = confirmed_serverpack_receipt(
        backend=backend, provisioning_id=provisioning_id,
        agent_id=agent_id, instance_id=instance_id,
        candidate_sha256=candidate_sha256,
    )

    def require(cond: Any, reason: str) -> None:
        if not cond:
            raise ServerPackAgentReportPublicationError(reason)

    require(isinstance(reports, Sequence) and not isinstance(reports, (str,bytes)),
            "invalid attested Agent report payload")
    ph = "?" if backend.name == "sqlite" else "%s"
    with backend.transaction() as conn:
        # Keep the revision and assignments locked while atomically updating
        # all of the child reports; no partial state can be observed at commit.
        if backend.name == "postgresql":
            conn.execute("SET LOCAL lock_timeout = '5s'")
            conn.execute("SET LOCAL statement_timeout = '120s'")
        lock = " FOR UPDATE" if backend.name == "postgresql" else ""
        bundle = conn.execute(
            f"SELECT revision,manifest_sha256 FROM content_bundles WHERE "
            f"instance_id={ph} AND parent_content_id={ph}" + lock,
            (instance_id,receipt["content_id"]),
        ).fetchone()
        require(bundle is not None and bundle["revision"] == receipt["bundle_revision"]
                and bundle["manifest_sha256"] == receipt["manifest_sha256"],
                "bundle moved since publication receipt")
        operation = conn.execute(
            f"SELECT agent_id,instance_id,status,request_json,result_json "
            f"FROM agent_instance_provisioning WHERE provisioning_id={ph}" + lock,
            (provisioning_id,),
        ).fetchone()
        require(operation is not None
                and operation["agent_id"] == agent_id
                and operation["instance_id"] == instance_id
                and operation["status"] == "completed", "provisioning changed before report publication")
        request = json.loads(operation["request_json"])
        completion = json.loads(operation["result_json"])
        pending = request["configuration"]["minecraft_serverpack_pending_bundle"]
        pub = completion.get("controller_bundle_publication") or {}
        require(pending.get("candidate_sha256") == candidate_sha256
                and pub.get("candidate_sha256") == candidate_sha256
                and pub.get("bundle_revision") == receipt["bundle_revision"],
                "transactional receipt mismatch")
        inst = conn.execute(
            f"SELECT agent_id,build_id FROM instances WHERE id={ph}" + lock,
            (instance_id,),
        ).fetchone()
        require(inst is not None and inst["agent_id"] == agent_id
                and inst["build_id"] == receipt["loader_version"],
                "running instance no longer agrees with Server Pack")
        assignments = conn.execute(
            f"SELECT content_id,revision,checksum,version,desired_state "
            f"FROM content_assignments WHERE instance_id={ph}" + lock,
            (instance_id,),
        ).fetchall()
        expected = {str(row["content_id"]):row for row in assignments}
        require(len(expected) == len(assignments) and len(expected) == len(reports),
                "partial or duplicate Agent report batch")
        report_index: dict[str, Mapping[str, Any]] = {}
        for report in reports:
            require(isinstance(report, Mapping), "invalid Agent report entry")
            cid = str(report.get("content_id") or "")
            require(cid in expected and cid not in report_index,
                    "foreign or duplicate report")
            report_index[cid] = report
        require(set(report_index) == set(expected), "Agent report batch omits assignments")
        active_ids = {cid for cid,row in expected.items() if row["desired_state"]=="installed"}
        members={str(m["content_id"]) for m in pending["children"]}
        require(active_ids == {receipt["content_id"], *members}, "active members changed")
        for cid,row in expected.items():
            report = report_index[cid]
            active = row["desired_state"] == "installed"
            target_version = row["version"] if active else None
            expected_security = "clean" if active else "unscanned"
            require(report.get("instance_id") == instance_id
                    and report.get("agent_id") == agent_id
                    and report.get("status") == "applied"
                    and report.get("desired_state") == row["desired_state"]
                    and report.get("desired_revision") == row["revision"]
                    and report.get("applied_revision") == row["revision"]
                    and report.get("desired_checksum") == row["checksum"]
                    and report.get("applied_checksum") == row["checksum"]
                    and report.get("installed_version") == target_version
                    and report.get("security_state") == expected_security,
                    f"report revision/security/identity does not match: {cid}")
            require(not active or report.get("attestation_candidate_sha256") == candidate_sha256,
                    f"missing candidate-bound attestation: {cid}")
            require(not report.get("last_error"), f"report has error: {cid}")
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join([ph]*13)
        sql = (f"INSERT INTO agent_content_state "
               f"(agent_id,instance_id,content_id,desired_revision,applied_revision,"
               f"desired_checksum,applied_checksum,status,installed_version,security_state,"
               f"last_error,reported_at,updated_at) "
               f"VALUES ({placeholders}) "
               f"ON CONFLICT(agent_id,instance_id,content_id) DO UPDATE SET "
               f"desired_revision=excluded.desired_revision,applied_revision=excluded.applied_revision,"
               f"desired_checksum=excluded.desired_checksum,applied_checksum=excluded.applied_checksum,"
               f"status=excluded.status,installed_version=excluded.installed_version,"
               f"security_state=excluded.security_state,last_error=NULL,"
               f"reported_at=excluded.reported_at,updated_at=excluded.updated_at")
        for cid,row in expected.items():
            report = report_index[cid]
            conn.execute(sql, (
                agent_id,instance_id,cid,row["revision"],row["revision"],
                row["checksum"],row["checksum"],"applied",
                report["installed_version"],report["security_state"],
                None,now,now,
            ))
        tally = conn.execute(
            f"SELECT content_id FROM agent_content_state WHERE agent_id={ph} AND instance_id={ph}",
            (agent_id,instance_id),
        ).fetchall()
        require(len(tally) == len(reports) and
                {row["content_id"] for row in tally} == set(expected),
                "Agent reports did not converge atomically")
    return {
        "kind":"ServerPackAgentReportBatchPublication",
        "status":"published","instance_id":instance_id,
        "candidate_sha256":candidate_sha256,
        "bundle_revision":receipt["bundle_revision"],
        "reports":len(reports),"installed":len(active_ids),
        "absent":len(reports)-len(active_ids),
    }
