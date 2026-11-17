#!/usr/bin/env python3
"""Prepare an isolated, reproducible Server Pack Agent-state revision.

No active Agent state, Controller, world, runtime or game service is modified.
The caller must verify the installed/source JAR hashes and YARA-X scans
independently before passing the clean source evidence to this module.
"""
from __future__ import annotations
import hashlib,json,os,re,shutil,tempfile
from pathlib import Path
from typing import Any,Mapping,Sequence
from content_activation_projection import build_activation_snapshot_from_states

class ServerPackRevisionStageError(RuntimeError):pass
_SAFE=re.compile(r"^[A-Za-z0-9._:-]{1,191}$")


def require(value:Any,message:str)->None:
 if not value:raise ServerPackRevisionStageError(message)


def sha(path:Path)->str:
 with path.open("rb") as stream:return hashlib.file_digest(stream,"sha256").hexdigest()


def stage_serverpack_agent_revision(*,assignments:Sequence[Mapping[str,Any]],
  receipt:Mapping[str,Any],parent_content_id:str,child_content_ids:set[str],
  live_runtime:Path,staging_dir:Path,
  scan_evidence:Mapping[str,str])->dict[str,Any]:
 iid=str(receipt.get("instance_id") or "")
 candidate=str(receipt.get("candidate_sha256") or "")
 revision=receipt.get("bundle_revision")
 require(receipt.get("kind")=="VerifiedServerPackControllerReceipt"
  and receipt.get("status")=="verified"
  and re.fullmatch(r"[A-Za-z0-9._-]{1,191}",iid)
  and re.fullmatch(r"[0-9a-f]{64}",candidate)
  and isinstance(revision,int) and revision>0,"Controller receipt not verified")
 require(parent_content_id==receipt.get("content_id")
  and len(child_content_ids)==receipt.get("child_count"),"Server Pack member identity mismatch")
 require(all(scan_evidence.get(key)=="clean" for key in ("parent","children","running")),
         "missing full YARA-X clean evidence")
 runtime=Path(live_runtime)
 stage=Path(staging_dir)
 require(runtime.is_dir() and not runtime.is_symlink(),"missing runtime")
 require(stage.parent.is_dir() and not stage.parent.is_symlink()
  and not stage.is_symlink(),"unsafe stage root")
 expect={parent_content_id,*child_content_ids}
 ids=set()
 states=[]
 reports=[]
 for row in assignments:
  cid=str(row.get("content_id") or "")
  require(_SAFE.fullmatch(cid) is not None and cid not in (".","..") and cid not in ids,
          "unsafe or duplicate assignment ID")
  ids.add(cid)
  require(row.get("instance_id")==iid,"assignment belongs to another instance")
  active=row.get("desired_state")=="installed"
  require(row.get("desired_state") in ("installed","absent")
   and active==(cid in expect),"desired content differs from published bundle")
  rev=row.get("revision");checksum=row.get("checksum")
  require(isinstance(rev,int) and rev>0 and isinstance(checksum,str)
    and bool(checksum),"assignment revision/checksum missing")
  installed=row.get("version") if active else None
  artifact=row.get("artifact") or {}
  metadata=row.get("metadata") or {}
  require(isinstance(artifact,dict) and isinstance(metadata,dict),"invalid assignment metadata")
  if active:
   target=(runtime/"content/modpacks"/cid) if cid==parent_content_id else (runtime/"content/mods"/cid)
   require(target.parent.is_dir(),"canonical content root is missing")
  else:target=None
  security="clean" if active else "unscanned"
  state={
   "instance_id":iid,"content_id":cid,"content_type":row.get("content_type"),
   "desired_state":row["desired_state"],"activation_state":row.get("activation_state","enabled"),
   "activation_order":row.get("activation_order",0),
   "dependencies":row.get("dependencies") or [],"conflicts":row.get("conflicts") or [],
   "activation":metadata.get("activation") or {},
   "desired_revision":rev,"applied_revision":rev,
   "desired_checksum":checksum,"applied_checksum":checksum,
   "status":"applied","installed_version":installed,
   "managed_path":str(target) if target else None,
   "provider":row.get("provider"),"game_id":row.get("game_id"),
   "target":row.get("target"),
   "package_id":artifact.get("package_id"),
   "artifact_filename":artifact.get("filename"),
   "source_sha256":artifact.get("sha256"),
   "source_size_bytes":artifact.get("size_bytes"),
   "security_state":security,"applied_security_state":security,
   "security_policy_version":1,"security":{"engine":"yara-x","policy_version":1,"matches":[]} if active else {},
   "last_error":None,"readiness":"verified_committed_runtime",
   "attestation_kind":"CommittedServerPackRuntimeReconciliation" if active else None,
   "attestation_candidate_sha256":candidate if active else None,
  }
  states.append(state)
  reports.append({
   "agent_id":receipt["agent_id"],"instance_id":iid,"content_id":cid,
   "desired_state":row["desired_state"],"status":"applied",
   "desired_revision":rev,"applied_revision":rev,
   "desired_checksum":checksum,"applied_checksum":checksum,
   "installed_version":installed,"security_state":security,
   "attestation_candidate_sha256":candidate if active else None,
   "last_error":None,
  })
 require(ids>=expect and len(states)==len(reports),"incomplete Server Pack assignment inventory")
 snapshot=build_activation_snapshot_from_states(iid,states)
 require(len(snapshot["entries"])<=len(expect),"snapshot contains unexpected active content")
 manifest={
  "kind":"ServerPackPreparedAgentRevision","instance_id":iid,
  "candidate_sha256":candidate,"bundle_revision":revision,
  "total":len(states),"installed":len(expect),
  "activation_checksum":snapshot["checksum"],
 }
 if stage.exists():
  require(stage.is_dir(),"prepared revision staging is not a directory")
  try:
   existing=json.loads((stage/"manifest.json").read_text())
   require(existing==manifest,"prepared revision has another identity")
   files=list((stage/"managed-content").glob("*.json"))
   require(len(files)==len(states) and {x.stem for x in files}==ids,
           "prepared Agent state file list incomplete")
   expected_rows={x["content_id"]:x for x in states}
   require(all(json.loads(path.read_text())==expected_rows[path.stem] for path in files),
           "prepared Agent records differ from assignments")
   require(json.loads((stage/"activation.json").read_text())==snapshot,
           "prepared activation snapshot changed")
   require(json.loads((stage/"reports.json").read_text())==reports,
           "prepared Controller reports changed")
  except (FileNotFoundError,ValueError,KeyError) as exc:
   raise ServerPackRevisionStageError("corrupt previously prepared Agent revision") from exc
  return {"status":"already_prepared",**manifest}
 scratch=Path(tempfile.mkdtemp(prefix=".serverpack-states-",dir=stage.parent))
 try:
  directory=scratch/"managed-content";directory.mkdir()
  for item in states:
   path=directory/(item["content_id"]+".json")
   path.write_text(json.dumps(item,sort_keys=True,indent=2)+"\n")
   path.chmod(0o600)
  for name,value in (("activation.json",snapshot),("reports.json",reports),("manifest.json",manifest)):
   path=scratch/name
   path.write_text(json.dumps(value,sort_keys=True,indent=2)+"\n")
   path.chmod(0o600)
  scratch.chmod(0o700);directory.chmod(0o700)
  os.rename(scratch,stage)
 finally:
  if scratch.exists():shutil.rmtree(scratch)
 return {"status":"prepared",**manifest}
