#!/usr/bin/env python3
"""Opt-in authenticated heartbeat bridge for atomic Server Pack reports.

Must be invoked only AFTER AgentPairingRepository.authenticate.
This is the Controller boundary; the Agent's asserted local evidence still
requires independent end-to-end validation before enabling in production.
"""
from __future__ import annotations
import os,re
from typing import Any,Mapping
from minecraft_serverpack_agent_report_publication import publish_attested_serverpack_reports

_TOKEN=re.compile(r"^[A-Za-z0-9._-]{1,191}$")
_SHA=re.compile(r"^[0-9a-f]{64}$")
_ALLOWED=frozenset({"provisioning_id","instance_id","candidate_sha256","reports"})
_REPORT=frozenset({
 "agent_id","instance_id","content_id","status","desired_state",
 "desired_revision","applied_revision","desired_checksum","applied_checksum",
 "installed_version","security_state","attestation_candidate_sha256","last_error",
})


def dispatch_serverpack_report_delivery(backend:Any, payload:Any,
                                         *,authenticated_agent_id:str)->dict[str,Any]:
    """Fail closed; no operation is dispatched while the feature is disabled."""
    if os.environ.get("DSM_SERVERPACK_REPORT_DELIVERY_ENABLED")!="1":
        return {"status":"disabled"}
    if not isinstance(payload,dict) or set(payload)!=_ALLOWED:
        return {"status":"rejected","reason":"invalid_batch"}
    iid=payload["instance_id"]
    pid=payload["provisioning_id"]
    digest=payload["candidate_sha256"]
    agent=authenticated_agent_id
    reports=payload["reports"]
    if (not isinstance(agent,str) or not _TOKEN.fullmatch(agent)
        or not isinstance(iid,str) or not _TOKEN.fullmatch(iid)
        or not isinstance(pid,str) or not _TOKEN.fullmatch(pid)
        or not pid.startswith("instance-provision-")
        or not isinstance(digest,str) or not _SHA.fullmatch(digest)
        or not isinstance(reports,list) or not 1<=len(reports)<=1024):
        return {"status":"rejected","reason":"invalid_batch"}
    ids=set()
    for r in reports:
        if (not isinstance(r,dict) or set(r)!=_REPORT
            or r.get("agent_id")!=agent or r.get("instance_id")!=iid
            or not isinstance(r.get("content_id"),str)
            or not _TOKEN.fullmatch(r["content_id"])
            or r["content_id"] in ids
            or r.get("desired_state") not in ("installed","absent")
            or r.get("status")!="applied"
            or r.get("security_state") not in ("clean","unscanned")
            or not isinstance(r.get("desired_revision"),int)
            or isinstance(r.get("desired_revision"),bool)
            or not isinstance(r.get("applied_revision"),int)
            or isinstance(r.get("applied_revision"),bool)):
            return {"status":"rejected","reason":"invalid_report"}
        ids.add(r["content_id"])
    try:
        result=publish_attested_serverpack_reports(
            backend=backend,provisioning_id=pid,agent_id=agent,
            instance_id=iid,candidate_sha256=digest,reports=reports,
        )
    except Exception:
        # Do not reveal whether another Agent's provisioning exists.
        return {"status":"rejected","reason":"publication_not_verified"}
    return {"status":"published","provisioning_id":pid,
            "instance_id":iid,"candidate_sha256":digest,
            "bundle_revision":result["bundle_revision"],
            "reports":result["reports"]}
