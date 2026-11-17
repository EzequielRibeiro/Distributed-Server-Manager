#!/usr/bin/env python3
"""Crash-recoverable Agent state and activation snapshot promotion.

No Controller writes, game lifecycle actions or deletion of previous state.
Caller must hold the Server Pack fence and verify the matching Controller
publication. After a crash prior to commit, recover prior local files.
"""
from __future__ import annotations
import hashlib,json,os
from pathlib import Path
from typing import Any,Callable,Mapping
from minecraft_serverpack_content_promotion import _persist,_rename
from minecraft_serverpack_content_sync import _need,_segment


def _load(path:Path)->dict[str,Any]:
 _need(path.is_file() and not path.is_symlink(),"missing or unsafe JSON file")
 value=json.loads(path.read_text(encoding="utf-8"))
 _need(isinstance(value,dict),"invalid JSON state")
 return value


def recover_local_state_promotion(journal_path:Path)->str:
 journal_path=Path(journal_path)
 journal=_load(journal_path)
 _need(journal.get("kind")=="ServerPackLocalStatePromotion"
  and journal.get("phase") in ("promoting","committed","rolled_back"),"invalid promotion journal")
 if journal["phase"]!="promoting":return journal["phase"]
 for entry in reversed(journal["entries"]):
  active,stage,backup=(Path(entry[k]) for k in ("active","stage","backup"))
  _need(not any(p.is_symlink() for p in (active,stage,backup)),"unsafe state recovery path")
  if backup.exists():
   if active.exists():
    _need(not stage.exists(),"ambiguous local recovery")
    _rename(active,stage)
   _rename(backup,active)
  else:
   _need(active.exists() and stage.exists(),"lost prior Agent state during recovery")
 journal["phase"]="rolled_back"
 _persist(journal_path,journal)
 return "rolled_back"


def promote_local_state_snapshot(*, staged_states:Path, staged_snapshot:Path,
  active_states:Path, active_snapshot:Path, recovery_dir:Path,
  instance_id:str,candidate_sha256:str,revision:int,expected_content_ids:set[str],
  expected_active_ids:set[str],controller_receipt:Callable[[],Mapping[str,Any]],
  checkpoint:Callable[[str],None]|None=None)->dict[str,Any]:
 _segment(instance_id,"instance ID")
 _need(isinstance(revision,int) and revision>0,"invalid Controller revision")
 staged_states,staged_snapshot,active_states,active_snapshot,recovery_dir=map(
  Path,(staged_states,staged_snapshot,active_states,active_snapshot,recovery_dir))
 _need(recovery_dir.is_dir() and not recovery_dir.is_symlink(),"invalid rollback directory")
 _need(staged_states.is_dir() and active_states.is_dir()
  and not staged_states.is_symlink() and not active_states.is_symlink(),"invalid state directories")
 _need(staged_snapshot.is_file() and active_snapshot.is_file()
  and not staged_snapshot.is_symlink() and not active_snapshot.is_symlink(),"invalid snapshot files")
 _need(len(expected_content_ids)>0 and expected_active_ids<=expected_content_ids,
       "invalid expected state inventory")
 paths=list(staged_states.iterdir())
 _need(len(paths)==len(expected_content_ids)
  and all(p.is_file() and not p.is_symlink() and p.suffix==".json" for p in paths)
  and {p.stem for p in paths}==expected_content_ids,"staged Agent inventory mismatch")
 for path in paths:
  state=_load(path);cid=path.stem
  _need(state.get("instance_id")==instance_id and state.get("content_id")==cid
   and state.get("status")=="applied","invalid staged Agent identity/status")
  installed=cid in expected_active_ids
  _need(state.get("desired_state")==("installed" if installed else "absent"),
        "wrong desired state in staged Agent file")
  if installed:
   _need(state.get("security_state")=="clean"
    and state.get("applied_security_state")=="clean"
    and state.get("attestation_candidate_sha256")==candidate_sha256
    and state.get("installed_version") and state.get("managed_path"),
    "unverified installed content in staged Agent state")
  else:
   _need(not state.get("managed_path") and not state.get("installed_version"),
         "removed content still has managed source")
 snapshot=_load(staged_snapshot)
 _need(snapshot.get("kind")=="CapivaraContentActivationSnapshot"
       and snapshot.get("instance_id")==instance_id
       and isinstance(snapshot.get("entries"),list)
       and all(isinstance(v,dict) and isinstance(v.get("content_id"),str)
               for v in snapshot["entries"])
       and len({v["content_id"] for v in snapshot["entries"]})==len(snapshot["entries"])
       and {v["content_id"] for v in snapshot["entries"]}<=expected_active_ids,
       "staged activation snapshot mismatch")
 identity={k:v for k,v in snapshot.items() if k!="checksum"}
 actual=hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(",",":"),
                                  ensure_ascii=False).encode("utf-8")).hexdigest()
 _need(snapshot.get("checksum")==actual,"staged activation checksum mismatch")
 proof=controller_receipt()
 _need(proof.get("kind")=="VerifiedServerPackControllerReceipt"
       and proof.get("status")=="verified"
       and proof.get("instance_id")==instance_id
       and proof.get("candidate_sha256")==candidate_sha256
       and proof.get("bundle_revision")==revision,
       "Controller did not confirm local state revision")
 journal_path=recovery_dir/"local-state-promotion.json"
 entries=[
  {"active":str(active_states),"stage":str(staged_states),
   "backup":str(recovery_dir/"previous-states")},
  {"active":str(active_snapshot),"stage":str(staged_snapshot),
   "backup":str(recovery_dir/"previous-snapshot.json")},
 ]
 _need(not journal_path.exists() and
  all(not Path(item["backup"]).exists() for item in entries),"local state promotion already exists")
 journal={"kind":"ServerPackLocalStatePromotion","phase":"promoting",
          "instance_id":instance_id,"candidate_sha256":candidate_sha256,
          "bundle_revision":revision,"entries":entries}
 _persist(journal_path,journal)
 try:
  for number,entry in enumerate(entries):
   live,stage,backup=(Path(entry[k]) for k in ("active","stage","backup"))
   _rename(live,backup)
   if checkpoint:checkpoint(f"backup_{number}")
   _rename(stage,live)
   if checkpoint:checkpoint(f"promoted_{number}")
  final=controller_receipt()
  _need(final==proof,"Controller changed during local state promotion")
  journal["phase"]="committed"
  _persist(journal_path,journal)
  return {"status":"committed","content_count":len(expected_content_ids)}
 except Exception:
  recover_local_state_promotion(journal_path)
  raise
