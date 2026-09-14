#!/usr/bin/env python3
"""Safe desired-state content reconciler for the Linux Agent."""
from __future__ import annotations
import hashlib,json,os,shutil,stat,tarfile,tempfile,time,zipfile
from pathlib import Path
from typing import Any
import instance_runtime
from content_provider import resolve_source
import content_provider_steam_workshop  # noqa: F401
from content_activation_projection import synchronize_activation_state
from content_activation_apply import ContentActivationApplyError,ContentActivationRollbackError,apply_activation_snapshots
from content_security import ContentSecurityRejected,require_clean
STATE_ROOT=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR","/var/lib/capivara-agent"));CONTENT_STATE=STATE_ROOT/"managed-content";GAME_DATA_ROOT=Path(os.environ.get("CAPIVARA_GAME_DATA_ROOT",str(STATE_ROOT/"game-data"))).resolve()
try:SECURITY_RETRY_SECONDS=max(30,min(int(os.environ.get("CAPIVARA_CONTENT_SECURITY_RETRY_SECONDS","300")),3600))
except (TypeError,ValueError):SECURITY_RETRY_SECONDS=300
class ContentActivationError(RuntimeError):pass
class ContentRollbackError(ContentActivationError):pass
def _write(path:Path,payload:dict[str,Any]):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(f".{path.name}.{os.getpid()}.tmp");tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.chmod(tmp,0o600);os.replace(tmp,path)
def _safe_component(v):
 s=str(v or "").strip()
 if not s or "/" in s or "\\" in s or s in {".",".."}:raise ValueError("unsafe content identifier")
 return s
def _state_path(i,c):return CONTENT_STATE/_safe_component(i)/f"{_safe_component(c)}.json"
def _safe_target(root:Path,target:str)->Path:
 rel=Path(str(target or "").replace("\\","/"))
 if rel.is_absolute() or not rel.parts or any(p in {"",".",".."} for p in rel.parts):raise ValueError("unsafe content target")
 base=(root/"content").resolve();candidate=(base/rel).resolve()
 try:candidate.relative_to(base)
 except ValueError as exc:raise ValueError("content target escapes instance") from exc
 return candidate
def _owned(config,cmd):
 iid=str(cmd.get("instance_id") or "").strip();rec=instance_runtime.get_instance(iid)
 if not rec:raise LookupError("instance not found")
 if str(rec.get("agent_id") or "")!=str(config.get("agent_id") or ""):raise PermissionError("instance belongs to another Agent")
 path=Path(str(rec.get("path") or "")).resolve()
 if not path.is_dir():raise FileNotFoundError("instance path missing")
 return rec,path
def _verify_artifact(path,artifact):
 if path.is_dir():return
 expected_size=artifact.get("size_bytes")
 if expected_size is not None:
  try:size=int(expected_size)
  except (TypeError,ValueError) as exc:raise ValueError("invalid artifact size") from exc
  if size<0 or path.stat().st_size!=size:raise ValueError("artifact size mismatch")
 specs=(("sha512",hashlib.sha512,128),("sha256",hashlib.sha256,64),("sha1",hashlib.sha1,40));hashers={}
 for key,factory,length in specs:
  value=str(artifact.get(key) or "").strip().lower()
  if not value:continue
  if len(value)!=length:
   raise ValueError(f"invalid artifact {key}")
  try:int(value,16)
  except ValueError as exc:raise ValueError(f"invalid artifact {key}") from exc
  hashers[key]=(factory(),value)
 if not hashers:return
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""):
   for hasher,_ in hashers.values():hasher.update(chunk)
 for key,(hasher,expected) in hashers.items():
  if hasher.hexdigest().lower()!=expected:raise ValueError(f"artifact {key} mismatch")

def _extract(archive,dest):
 dest.mkdir(parents=True,exist_ok=True);max_entries=100000;max_expanded=128*1024*1024*1024
 def safe(name):
  text=str(name or "").replace("\\","/");rel=Path(text)
  if not text or text.startswith("/") or rel.is_absolute() or any(part==".." for part in rel.parts):raise ValueError("archive path traversal")
  p=(dest/rel).resolve()
  try:p.relative_to(dest.resolve())
  except ValueError as exc:raise ValueError("archive path traversal") from exc
 if zipfile.is_zipfile(archive):
  with zipfile.ZipFile(archive) as z:
   entries=z.infolist();total=0
   if len(entries)>max_entries:raise ValueError("archive has too many entries")
   for i in entries:
    safe(i.filename);total+=max(0,int(i.file_size or 0));mode=(i.external_attr>>16)&0xFFFF
    if stat.S_ISLNK(mode):raise ValueError("unsafe archive member")
    if total>max_expanded:raise ValueError("archive expands beyond safety limit")
   z.extractall(dest);return
 if tarfile.is_tarfile(archive):
  with tarfile.open(archive) as t:
   members=t.getmembers();total=0
   if len(members)>max_entries:raise ValueError("archive has too many entries")
   for m in members:
    safe(m.name);total+=max(0,int(m.size or 0))
    if not (m.isfile() or m.isdir()) or m.issym() or m.islnk():raise ValueError("unsafe archive member")
    if total>max_expanded:raise ValueError("archive expands beyond safety limit")
   t.extractall(dest,members=members,filter="data");return
 raise ValueError("unsupported archive format")
def _source(provider,artifact,stage):return resolve_source(provider,artifact,stage,GAME_DATA_ROOT)
def _dependency_state(instance_id,content_id):
 p=_state_path(instance_id,content_id)
 try:return json.loads(p.read_text()) if p.exists() else {}
 except Exception:return {}
def _validate_relations(cmd):
 iid=str(cmd.get("instance_id") or "");cid=str(cmd.get("content_id") or "")
 for dep in cmd.get("dependencies") or []:
  state=_dependency_state(iid,str(dep))
  if state.get("status")!="applied" or not state.get("installed_version"):raise RuntimeError(f"content dependency is not installed: {dep}")
 for conflict in cmd.get("conflicts") or []:
  state=_dependency_state(iid,str(conflict))
  if state.get("status")=="applied" and state.get("installed_version"):raise RuntimeError(f"conflicting content is installed: {conflict}")
 if cid in (cmd.get("dependencies") or []) or cid in (cmd.get("conflicts") or []):raise ValueError("content cannot depend/conflict with itself")
def _remove_path(path:Path):
 if not path.exists():return
 shutil.rmtree(path) if path.is_dir() else path.unlink()
def _runtime_ready(config:dict[str,Any],iid:str)->bool:return bool(instance_runtime.doctor(config,iid).get("ready"))
def _activate_target(config:dict[str,Any],iid:str,target:Path,payload:Path|None)->None:
 backup=target.with_name(target.name+".c4-old")
 if backup.exists():raise ContentActivationError("unfinished content transaction detected")
 was_running=instance_runtime.status(config,iid).get("observed_state")=="running";previous_exists=target.exists();activated=False
 try:
  if was_running:instance_runtime.lifecycle(config,iid,"stop")
  if previous_exists:os.replace(target,backup)
  if payload is not None:os.replace(payload,target)
  activated=True
  if was_running:
   instance_runtime.lifecycle(config,iid,"start")
   if not _runtime_ready(config,iid):raise ContentActivationError("content activation failed readiness validation")
  _remove_path(backup)
 except Exception as exc:
  try:
   if was_running:
    try:instance_runtime.lifecycle(config,iid,"stop")
    except Exception:pass
   if activated and target.exists():_remove_path(target)
   if backup.exists():os.replace(backup,target)
   if was_running:
    instance_runtime.lifecycle(config,iid,"start")
    if not _runtime_ready(config,iid):raise ContentRollbackError("content rollback failed readiness validation")
  except Exception as rollback_exc:raise ContentRollbackError(f"content activation failed and rollback failed: {rollback_exc}") from exc
  raise
def _install(config,cmd):
 _validate_relations(cmd);_,instance=_owned(config,cmd);iid=str(cmd.get("instance_id") or "");target=_safe_target(instance,str(cmd.get("target") or "assets"));artifact=dict(cmd.get("artifact") or {});provider=str(cmd.get("provider") or artifact.get("provider") or "");parent=target.parent;parent.mkdir(parents=True,exist_ok=True);stage=Path(tempfile.mkdtemp(prefix=f".{target.name}.c4-",dir=str(parent)))
 try:
  source=_source(provider,artifact,stage);_verify_artifact(source,artifact);source_scan=require_clean(source);payload=stage/"payload";payload.mkdir();archive=provider=="http-archive" or bool(artifact.get("archive"));expanded_scan=None
  if archive:_extract(source,payload);expanded_scan=require_clean(payload)
  elif source.is_dir():shutil.copytree(source,payload,dirs_exist_ok=True)
  else:shutil.copy2(source,payload/(str(artifact.get("filename") or source.name or "content.bin")))
  _activate_target(config,iid,target,payload)
 finally:shutil.rmtree(stage,ignore_errors=True)
 return str(target),expanded_scan or source_scan
def _remove(config,cmd):
 _,instance=_owned(config,cmd);iid=str(cmd.get("instance_id") or "");target=_safe_target(instance,str(cmd.get("target") or "assets"));_activate_target(config,iid,target,None);return str(target)
def _source_metadata(cmd:dict[str,Any])->dict[str,Any]:
 artifact=cmd.get("artifact") if isinstance(cmd.get("artifact"),dict) else {};package=str(artifact.get("package_id") or cmd.get("package_id") or "").strip()
 return {"provider":str(cmd.get("provider") or artifact.get("provider") or "").strip().lower(),"content_type":str(cmd.get("content_type") or "other").strip().lower(),"package_id":package or None,"game_id":str(cmd.get("game_id") or "").strip().lower() or None,"target":str(cmd.get("target") or "").strip() or None}
def _reuse_installed(previous,cmd,source_meta):
 if previous.get("status") not in {"applied","rolled_back"} or not previous.get("installed_version"):return False
 if str(cmd.get("desired_state") or "installed")!="installed":return False
 if str(previous.get("installed_version"))!=str(cmd.get("version") or "latest"):return False
 for key in ("provider","package_id","target","game_id"):
  if str(previous.get(key) or "")!=str(source_meta.get(key) or ""):return False
 path=str(previous.get("managed_path") or "")
 return bool(path and Path(path).exists())
def _apply(config,cmd):
 iid=str(cmd.get("instance_id") or "");cid=str(cmd.get("content_id") or "");revision=int(cmd.get("revision") or 0);checksum=str(cmd.get("checksum") or "");state=_state_path(iid,cid);source_meta=_source_metadata(cmd)
 try:previous=json.loads(state.read_text()) if state.exists() else {}
 except Exception:previous={}
 if previous.get("status")=="applied" and previous.get("applied_revision")==revision and previous.get("applied_checksum")==checksum and previous.get("security_state")=="clean" and int(previous.get("security_policy_version") or 0)>=1:
  merged={**previous,**{k:v for k,v in source_meta.items() if v is not None}};_write(state,merged);return merged
 if previous.get("status")=="security_scan_failed" and int(previous.get("desired_revision") or 0)==revision and str(previous.get("desired_checksum") or "")==checksum:
  try:retry_after=float(previous.get("security_retry_after_epoch") or 0)
  except (TypeError,ValueError):retry_after=0
  if time.time()<retry_after:return previous
 try:
  desired=str(cmd.get("desired_state") or "installed");security={"security_state":"clean","engine":"none","policy_version":1,"reason":None,"matches":[]}
  if desired=="absent":path=_remove(config,cmd)
  elif _reuse_installed(previous,cmd,source_meta):path=str(previous.get("managed_path"));security=require_clean(Path(path))
  else:path,security=_install(config,cmd)
  report={"instance_id":iid,"content_id":cid,"desired_revision":revision,"applied_revision":revision,"desired_checksum":checksum,"applied_checksum":checksum,"status":"applied","installed_version":None if desired=="absent" else str(cmd.get("version") or "latest"),"managed_path":path,"last_error":None,"readiness":"healthy","security_state":str(security.get("security_state") or "clean"),"security_policy_version":1,"security":{"engine":security.get("engine"),"matches":security.get("matches") or []},**source_meta}
 except ContentSecurityRejected as exc:
  verdict=exc.verdict;security_state=str(verdict.get("security_state") or "scan_failed");terminal=security_state in {"suspicious","blocked"};report={"instance_id":iid,"content_id":cid,"desired_revision":revision,"applied_revision":None,"desired_checksum":checksum,"applied_checksum":None,"status":"security_blocked" if terminal else "security_scan_failed","installed_version":None,"managed_path":None,"last_error":str(verdict.get("reason") or exc)[:2000],"readiness":"security_rejected","security_state":security_state,"security_policy_version":1,"security_retry_after_epoch":None if terminal else time.time()+SECURITY_RETRY_SECONDS,"security":{"engine":verdict.get("engine"),"matches":verdict.get("matches") or []},**source_meta}
 except ContentRollbackError as exc:report={"instance_id":iid,"content_id":cid,"desired_revision":revision,"applied_revision":None,"desired_checksum":checksum,"applied_checksum":None,"status":"rollback_failed","installed_version":None,"managed_path":None,"last_error":str(exc)[:2000],"readiness":"rollback_failed","security_state":"unscanned","security_policy_version":1,**source_meta}
 except ContentActivationError as exc:
  if previous.get("status")=="applied" and int(previous.get("applied_revision") or 0)>0 and str(previous.get("applied_checksum") or ""):
   restored_meta={key:(previous.get(key) if previous.get(key) is not None else source_meta.get(key)) for key in ("provider","content_type","package_id","game_id","target")}
   report={"instance_id":iid,"content_id":cid,"desired_revision":revision,"applied_revision":int(previous.get("applied_revision")),"desired_checksum":checksum,"applied_checksum":str(previous.get("applied_checksum")),"status":"rolled_back","installed_version":previous.get("installed_version"),"managed_path":previous.get("managed_path"),"last_error":str(exc)[:2000],"readiness":"rolled_back","security_state":str(previous.get("security_state") or "clean"),"security_policy_version":int(previous.get("security_policy_version") or 1),**restored_meta}
  else:report={"instance_id":iid,"content_id":cid,"desired_revision":revision,"applied_revision":None,"desired_checksum":checksum,"applied_checksum":None,"status":"failed","installed_version":None,"managed_path":None,"last_error":str(exc)[:2000],"readiness":"rolled_back","security_state":"unscanned","security_policy_version":1,**source_meta}
 except Exception as exc:report={"instance_id":iid,"content_id":cid,"desired_revision":revision,"applied_revision":None,"desired_checksum":checksum,"applied_checksum":None,"status":"failed","installed_version":None,"managed_path":None,"last_error":str(exc)[:2000],"readiness":"unknown","security_state":"unscanned","security_policy_version":1,**source_meta}
 _write(state,report);return report
def apply_content_commands(config:dict[str,Any],commands:list[dict[str,Any]])->list[dict[str,Any]]:
 bounded=[c for c in commands[:200] if isinstance(c,dict)];ordered=[c for c in bounded if c.get("desired_state")=="absent"]+[c for c in bounded if c.get("desired_state")!="absent"];reports=[];pending=ordered;prior={(str(c.get("instance_id") or ""),str(c.get("content_id") or "")):_dependency_state(str(c.get("instance_id") or ""),str(c.get("content_id") or "")) for c in bounded}
 for _ in range(max(1,len(pending)+1)):
  if not pending:break
  retry=[];progress=False
  for cmd in pending:
   report=_apply(config,cmd);reports.append(report)
   if report.get("status")=="failed" and "dependency is not installed" in str(report.get("last_error") or ""):retry.append(cmd)
   else:progress=True
  if not retry or not progress:break
  pending=retry
 final=reports[-200:];snapshots=synchronize_activation_state(bounded,final)
 try:apply_activation_snapshots(config,snapshots)
 except ContentActivationRollbackError as exc:
  for report in final:
   if report.get("status")=="applied":report.update({"status":"rollback_failed","last_error":str(exc)[:2000],"readiness":"rollback_failed"});_write(_state_path(report.get("instance_id"),report.get("content_id")),report)
 except ContentActivationApplyError as exc:
  for report in final:
   if report.get("status")!="applied":continue
   previous=prior.get((str(report.get("instance_id") or ""),str(report.get("content_id") or ""))) or {}
   if previous.get("status")=="applied" and int(previous.get("applied_revision") or 0)>0 and str(previous.get("applied_checksum") or ""):
    restored={**report,"applied_revision":int(previous["applied_revision"]),"applied_checksum":str(previous["applied_checksum"]),"status":"rolled_back","installed_version":previous.get("installed_version"),"managed_path":previous.get("managed_path"),"last_error":str(exc)[:2000],"readiness":"rolled_back","security_state":str(previous.get("security_state") or "clean")}
    for key in ("provider","content_type","package_id","game_id","target"):
     if previous.get(key) is not None:restored[key]=previous.get(key)
    report.clear();report.update(restored);_write(_state_path(report.get("instance_id"),report.get("content_id")),report)
   else:report.update({"status":"failed","last_error":str(exc)[:2000],"readiness":"rolled_back"});_write(_state_path(report.get("instance_id"),report.get("content_id")),report)
 return final
def content_state():
 out=[]
 try:paths=sorted(CONTENT_STATE.glob("*/*.json"))
 except OSError:paths=[]
 for p in paths:
  try:v=json.loads(p.read_text(encoding="utf-8"))
  except Exception:continue
  if isinstance(v,dict):out.append(v)
 return out[:2000]
__all__=["ContentActivationError","ContentRollbackError","apply_content_commands","content_state"]
