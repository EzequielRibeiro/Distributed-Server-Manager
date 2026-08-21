#!/usr/bin/env python3
"""Canonical contracts for Capivara Universal Smart Backup."""
from __future__ import annotations
import hashlib,json,re,uuid
from typing import Any,Mapping
_TOKEN=re.compile(r"^[A-Za-z0-9._:-]{1,191}$")
_MODES={"full","config","world","custom"};_CONSISTENCY={"live","quiesced","stopped"};_COMPRESSION={"gzip","none"}
class BackupValidationError(ValueError):pass
def _token(v:Any,label:str)->str:
 s=str(v or "").strip()
 if not _TOKEN.fullmatch(s):raise BackupValidationError(f"invalid {label}")
 return s
def _paths(values:Any)->list[str]:
 out=[]
 for raw in values or []:
  p=str(raw or "").strip().replace("\\","/")
  if not p or p.startswith("/") or any(part in {"",".",".."} for part in p.split("/")):raise BackupValidationError("invalid backup path")
  out.append(p[:500])
 return out[:200]
def normalize_policy(raw:Mapping[str,Any],*,expected_agent_id:str|None=None)->dict[str,Any]:
 if not isinstance(raw,Mapping):raise BackupValidationError("backup policy must be an object")
 iid=_token(raw.get("instance_id"),"instance_id");aid=_token(raw.get("agent_id") or expected_agent_id,"agent_id")
 if expected_agent_id and aid!=expected_agent_id:raise BackupValidationError("Agent identity mismatch")
 enabled=bool(raw.get("enabled",True));mode=str(raw.get("mode") or "full").lower();cons=str(raw.get("consistency") or "live").lower();comp=str(raw.get("compression") or "gzip").lower()
 if mode not in _MODES:raise BackupValidationError("invalid backup mode")
 if cons not in _CONSISTENCY:raise BackupValidationError("invalid consistency mode")
 if comp not in _COMPRESSION:raise BackupValidationError("invalid compression")
 interval=int(raw.get("interval_seconds") or 21600);retention=int(raw.get("retention_count") or 7)
 if interval<300 or interval>31536000:raise BackupValidationError("interval_seconds out of range")
 if retention<1 or retention>365:raise BackupValidationError("retention_count out of range")
 includes=_paths(raw.get("include_paths"));excludes=_paths(raw.get("exclude_paths"))
 body={"instance_id":iid,"agent_id":aid,"enabled":enabled,"mode":mode,"consistency":cons,"compression":comp,"interval_seconds":interval,"retention_count":retention,"include_paths":includes,"exclude_paths":excludes}
 checksum=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
 return {"schema_version":1,"kind":"CapivaraBackupPolicy",**body,"checksum":checksum}
def normalize_command(raw:Mapping[str,Any],*,expected_agent_id:str|None=None)->dict[str,Any]:
 if not isinstance(raw,Mapping):raise BackupValidationError("backup command must be an object")
 action=str(raw.get("action") or "create").lower()
 if action not in {"create","restore","delete"}:raise BackupValidationError("invalid backup action")
 command_id=_token(raw.get("command_id") or str(uuid.uuid4()),"command_id");iid=_token(raw.get("instance_id"),"instance_id");aid=_token(raw.get("agent_id") or expected_agent_id,"agent_id")
 if expected_agent_id and aid!=expected_agent_id:raise BackupValidationError("Agent identity mismatch")
 backup_id=str(raw.get("backup_id") or "").strip()
 if action in {"restore","delete"} and not backup_id:raise BackupValidationError("backup_id required")
 return {"schema_version":1,"kind":"CapivaraBackupCommand","command_id":command_id,"action":action,"instance_id":iid,"agent_id":aid,"backup_id":backup_id or None,"policy":dict(raw.get("policy") or {}),"requested_by":raw.get("requested_by")}
__all__=["BackupValidationError","normalize_policy","normalize_command"]
