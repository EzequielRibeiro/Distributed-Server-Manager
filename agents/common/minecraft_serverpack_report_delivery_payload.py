#!/usr/bin/env python3
"""Prepare authenticated report batch only after durable source/state promotion.

No network or database operations, and no writes. The caller must send this
through the Agent's existing authenticated heartbeat, after the feature gate
and remote multi-host protocol are explicitly enabled.
"""
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from typing import Any, Mapping


class ServerPackReportDeliveryError(ValueError):
    pass


def require(value: Any, reason: str) -> None:
    if not value:
        raise ServerPackReportDeliveryError(reason)


def load(path: Path) -> Any:
    require(path.is_file() and not path.is_symlink(), "unsafe or missing local evidence")
    return json.loads(path.read_text(encoding="utf-8"))


def build_committed_serverpack_report_delivery(
    *, offer: Mapping[str, Any], agent_id: str,
    source_promotion_journal: Path, state_promotion_journal: Path,
    staged_manifest: Path, prepared_reports: Path,
    active_states: Path, active_snapshot: Path,
) -> dict[str, Any]:
    iid = offer.get("instance_id") if isinstance(offer, Mapping) else None
    candidate = offer.get("candidate_sha256") if isinstance(offer, Mapping) else None
    revision = offer.get("bundle_revision") if isinstance(offer, Mapping) else None
    require(isinstance(iid,str) and re.fullmatch(r"[A-Za-z0-9._-]{1,191}",iid),
            "invalid instance")
    require(isinstance(agent_id,str) and re.fullmatch(r"[A-Za-z0-9._-]{1,191}",agent_id),
            "invalid agent")
    require(isinstance(candidate,str) and re.fullmatch(r"[0-9a-f]{64}",candidate),
            "invalid candidate")
    require(isinstance(revision,int) and not isinstance(revision,bool) and revision>0,
            "invalid revision")
    require(offer.get("kind")=="VerifiedServerPackRecoveryOffer"
            and offer.get("status")=="verified"
            and isinstance(offer.get("provisioning_id"),str),
            "Controller offer not verified")

    sources=load(Path(source_promotion_journal))
    local=load(Path(state_promotion_journal))
    require(sources.get("kind")=="VerifiedSourcePromotion"
            and sources.get("phase")=="committed"
            and sources.get("instance_id")==iid
            and sources.get("candidate_sha256")==candidate
            and sources.get("revision")==revision,
            "sources not committed to candidate")
    require(local.get("kind")=="ServerPackLocalStatePromotion"
            and local.get("phase")=="committed"
            and local.get("instance_id")==iid
            and local.get("candidate_sha256")==candidate
            and local.get("bundle_revision")==revision,
            "Agent states not committed to candidate")
    require(isinstance(local.get("entries"),list) and len(local["entries"])==2,
            "invalid state promotion journal")
    active_states=Path(active_states)
    active_snapshot=Path(active_snapshot)
    require(not active_states.is_symlink() and active_states.is_dir()
            and not active_snapshot.is_symlink() and active_snapshot.is_file(),
            "missing active Agent state")
    require(Path(local["entries"][0]["active"]).resolve()==active_states.resolve()
            and Path(local["entries"][1]["active"]).resolve()==active_snapshot.resolve(),
            "local promotion journal points elsewhere")

    manifest=load(Path(staged_manifest))
    reports=load(Path(prepared_reports))
    snapshot=load(active_snapshot)
    require(isinstance(manifest,dict) and manifest.get("kind")=="ServerPackPreparedAgentRevision"
            and manifest.get("instance_id")==iid
            and manifest.get("candidate_sha256")==candidate
            and manifest.get("bundle_revision")==revision,
            "staged report manifest mismatch")
    require(isinstance(reports,list) and 1<=len(reports)<=1024
            and manifest.get("total")==len(reports),
            "incomplete report inventory")
    require(isinstance(snapshot,dict)
            and snapshot.get("kind")=="CapivaraContentActivationSnapshot"
            and snapshot.get("instance_id")==iid
            and manifest.get("activation_checksum")==snapshot.get("checksum"),
            "active activation snapshot differs from prepared revision")
    identity={k:v for k,v in snapshot.items() if k!="checksum"}
    checksum=hashlib.sha256(json.dumps(identity,sort_keys=True,
                    separators=(",",":"),ensure_ascii=False).encode("utf-8")).hexdigest()
    require(checksum==snapshot.get("checksum"),"invalid activation checksum")
    files=list(active_states.iterdir())
    require(len(files)==len(reports)
            and all(p.is_file() and not p.is_symlink() and p.suffix==".json" for p in files),
            "live Agent inventory contains extra or unsafe entries")
    states={}
    for p in files:
        state=load(p)
        cid=p.stem
        require(isinstance(state,dict)
                and isinstance(state.get("content_id"),str)
                and cid==state["content_id"]
                and cid not in states
                and state.get("instance_id")==iid,"foreign or duplicate Agent state")
        states[cid]=state
    seen=set();active=set()
    for report in reports:
        require(isinstance(report,dict),"invalid report record")
        cid=report.get("content_id")
        require(isinstance(cid,str) and cid in states and cid not in seen,
                "report does not match active Agent state")
        seen.add(cid)
        state=states[cid]
        for key in ("instance_id","content_id","status","desired_state",
                    "desired_revision","applied_revision","desired_checksum",
                    "applied_checksum","installed_version","security_state",
                    "attestation_candidate_sha256","last_error"):
            require(report.get(key)==state.get(key),
                    "report differs from activated Agent state")
        require(report.get("agent_id")==agent_id
                and report.get("status")=="applied"
                and report.get("desired_revision")==report.get("applied_revision")
                and report.get("desired_checksum")==report.get("applied_checksum"),
                "report identity or commit mismatch")
        if report.get("desired_state")=="installed":
            require(report.get("attestation_candidate_sha256")==candidate
                    and state.get("applied_security_state")=="clean"
                    and report.get("security_state")=="clean",
                    "installed content lacks attestation")
            active.add(cid)
        else:
            require(report.get("desired_state")=="absent"
                    and report.get("security_state")=="unscanned"
                    and not report.get("installed_version")
                    and not state.get("managed_path"),
                    "absent content still owns files")
    require(seen==set(states) and len(active)==manifest.get("installed"),
            "active Agent state inventory incomplete")
    activated={entry["content_id"] for entry in snapshot["entries"]}
    require(activated <= active and len(activated)==len(snapshot["entries"]),
            "activation contains unexpected content")
    return {
        "provisioning_id":offer["provisioning_id"],
        "instance_id":iid,
        "candidate_sha256":candidate,
        "reports":reports,
    }
