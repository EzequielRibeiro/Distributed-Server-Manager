#!/usr/bin/env python3
"""Durable post-commit Server Pack phase coordinator; no game lifecycle actions.

Callbacks must be idempotent: a crash can occur after an action but before
the journal checkpoint. Receipt verification is required on every replay.
"""
from __future__ import annotations
import json,os,re
from pathlib import Path
from typing import Any,Callable,Mapping

class ServerPackRecoveryCoordinatorError(RuntimeError):pass
PHASES=("awaiting_sources","sources_prepared","sources_promoted",
        "local_states_promoted","reports_published","ack_verified")
STEPS=(("prepare_sources_and_states","sources_prepared"),
       ("promote_sources","sources_promoted"),
       ("promote_local_states_and_snapshot","local_states_promoted"),
       ("publish_attested_reports","reports_published"),
       ("verify_ack","ack_verified"))

def require(ok,msg):
 if not ok:raise ServerPackRecoveryCoordinatorError(msg)

def persist(path,value):
 temp=path.with_name("."+path.name+".partial")
 require(not temp.exists() and not temp.is_symlink(),"orphaned partial journal")
 with temp.open("x",encoding="utf-8") as f:
  json.dump(value,f,sort_keys=True,indent=2);f.write("\n");f.flush();os.fsync(f.fileno())
 os.replace(temp,path)
 fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)

def resume_serverpack_recovery(*,journal_path:Path,instance_id:str,
 candidate_sha256:str,revision:int,
 receipt_check:Callable[[],Mapping[str,Any]],
 callbacks:Mapping[str,Callable[[],Mapping[str,Any]]],
 after_phase:Callable[[str],None]|None=None)->dict[str,Any]:
 path=Path(journal_path)
 require(re.fullmatch(r"[A-Za-z0-9._-]{1,191}",instance_id)!=None,"invalid instance ID")
 require(re.fullmatch(r"[0-9a-f]{64}",candidate_sha256)!=None,"invalid candidate SHA")
 require(isinstance(revision,int) and revision>0,"invalid bundle revision")
 require(path.parent.is_dir() and not path.parent.is_symlink() and not path.is_symlink(),"unsafe journal path")
 require(set(name for name,_ in STEPS)<=set(callbacks),"missing recovery callbacks")
 identity={"kind":"ServerPackPostCommitRecovery","instance_id":instance_id,
           "candidate_sha256":candidate_sha256,"revision":revision}
 if path.exists():
  try:state=json.loads(path.read_text())
  except (OSError,ValueError) as exc:raise ServerPackRecoveryCoordinatorError("corrupt journal") from exc
  require(isinstance(state,dict) and all(state.get(k)==v for k,v in identity.items()),"foreign journal")
  require(state.get("phase") in PHASES,"invalid recovery phase")
 else:
  state={**identity,"phase":PHASES[0]};persist(path,state)
 def controller():
  r=receipt_check()
  require(isinstance(r,Mapping) and r.get("kind")=="VerifiedServerPackControllerReceipt"
   and r.get("status")=="verified" and r.get("instance_id")==instance_id
   and r.get("candidate_sha256")==candidate_sha256 and r.get("bundle_revision")==revision,
   "Controller receipt does not match committed Server Pack")
 controller()
 if state["phase"]=="ack_verified":return {**identity,"status":"completed","replayed":True}
 for i,(name,new_phase) in enumerate(STEPS):
  if i<PHASES.index(state["phase"]):continue
  controller()
  result=callbacks[name]()
  require(isinstance(result,Mapping),"missing phase result")
  if name=="verify_ack":
   require(result.get("kind")=="VerifiedServerPackContentConvergence"
    and result.get("status")=="ready" and result.get("instance_id")==instance_id
    and result.get("candidate_sha256")==candidate_sha256
    and result.get("bundle_revision")==revision,"convergence ACK not verified")
  else:
   require(result.get("status") in ("verified","prepared","already_prepared",
    "committed","published","replayed"),"phase failed closed")
  state={**state,"phase":new_phase};persist(path,state)
  if after_phase:after_phase(new_phase)
 return {**identity,"status":"completed","replayed":False}
