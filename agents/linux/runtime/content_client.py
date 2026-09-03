#!/usr/bin/env python3
"""Safe desired-state content reconciler for the Linux Agent."""
from __future__ import annotations
import hashlib,json,os,shutil,tarfile,tempfile,urllib.request,zipfile
from pathlib import Path
from typing import Any
import instance_runtime
STATE_ROOT=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR","/var/lib/capivara-agent"));CONTENT_STATE=STATE_ROOT/"managed-content";GAME_DATA_ROOT=Path(os.environ.get("CAPIVARA_GAME_DATA_ROOT",str(STATE_ROOT/"game-data"))).resolve()
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
def _sha(path,expected):
 if not expected or path.is_dir():return
 h=hashlib.sha256()
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
 if h.hexdigest().lower()!=str(expected).lower():raise ValueError("artifact checksum mismatch")
def _extract(archive,dest):
 dest.mkdir(parents=True,exist_ok=True)
 def safe(name):
  p=(dest/name).resolve()
  try:p.relative_to(dest.resolve())
  except ValueError as exc:raise ValueError("archive path traversal") from exc
 if zipfile.is_zipfile(archive):
  with zipfile.ZipFile(archive) as z:
   for i in z.infolist():safe(i.filename)
   z.extractall(dest);return
 if tarfile.is_tarfile(archive):
  with tarfile.open(archive) as t:
   members=t.getmembers()
   for m in members:
    safe(m.name)
    if not (m.isfile() or m.isdir()) or m.issym() or m.islnk():raise ValueError("unsafe archive member")
   t.extractall(dest,members=members,filter="data");return
 raise ValueError("unsupported archive format")
def _controlled_local(raw):
 raw=str(raw or "").strip()
 if not raw:raise ValueError("resolved artifact path required")
 candidate=(GAME_DATA_ROOT/raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
 try:candidate.relative_to(GAME_DATA_ROOT)
 except ValueError as exc:raise ValueError("local artifact outside game-data root") from exc
 if not candidate.exists():raise FileNotFoundError("local artifact missing")
 return candidate
def _download(artifact,dest):
 url=str(artifact.get("url") or artifact.get("download_url") or "").strip()
 if not url.startswith("https://"):raise ValueError("remote content requires HTTPS")
 req=urllib.request.Request(url,headers={"User-Agent":"Capivara-Agent/1"})
 with urllib.request.urlopen(req,timeout=60) as r,dest.open("wb") as f:shutil.copyfileobj(r,f,length=1024*1024)
 return dest
def _source(provider,artifact,stage):
 resolved=artifact.get("resolved_path")
 if resolved:return _controlled_local(resolved)
 if provider=="local":return _controlled_local(artifact.get("package_id") or artifact.get("path"))
 if provider in {"http","http-archive","github","modrinth"} and (artifact.get("url") or artifact.get("download_url")):return _download(artifact,stage/"artifact")
 if provider in {"steam","modrinth","custom","source-build"}:raise RuntimeError(f"{provider} content must be resolved by an Agent provider capability before reconciliation")
 raise RuntimeError(f"provider not executable by Linux Agent: {provider}")
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
  source=_source(provider,artifact,stage);_sha(source,artifact.get("sha256"));payload=stage/"payload";payload.mkdir();archive=provider=="http-archive" or bool(artifact.get("archive"))
  if archive:_extract(source,payload)
  elif source.is_dir():shutil.copytree(source,payload,dirs_exist_ok=True)
  else:shutil.copy2(source,payload/(str(artifact.get("filename") or source.name or "content.bin")))
  _activate_target(config,iid,target,payload)
 finally:shutil.rmtree(stage,ignore_errors=True)
 return str(target)
def _remove(config,cmd):
 _,instance=_owned(config,cmd);iid=str(cmd.get("instance_id") or "");target=_safe_target(instance,str(cmd.get("target") or "assets"));_activate_target(config,iid,target,None);return str(target)
def _source_metadata(cmd:dict[str,Any])->dict[str,Any]:
 artifact=cmd.get("artifact") if isinstance(cmd.get("artifact"),dict) else {};package=str(artifact.get("package_id") or cmd.get("package_id") or "").strip()
 return {"provider":str(cmd.get("provider") or artifact.get("provider") or "").strip().lower(),"content_type":str(cmd.get("content_type") or "other").strip().lower(),"package_id":package or None,"game_id":str(cmd.get("game_id") or "").strip().lower() or None,"target":str(cmd.get("target") or "").strip() or None}
def _apply(config,cmd):
 iid=str(cmd.get("instance_id") or "");cid=str(cmd.get("content_id") or "");revision=int(cmd.get("revision") or 0);checksum=str(cmd.get("checksum") or "");state=_state_path(iid,cid);source_meta=_source_metadata(cmd)
 try:previous=json.loads(state.read_text()) if state.exists() else {}
 except Exception:previous={}
 if previous.get("status")=="applied" and previous.get("applied_revision")==revision and previous.get("applied_checksum")==checksum:
  merged={**previous,**{k:v for k,v in source_meta.items() if v is not None}};_write(state,merged);return merged
 try:
  desired=str(cmd.get("desired_state") or "installed");path=_remove(config,cmd) if desired=="absent" else _install(config,cmd);report={"instance_id":iid,"content_id":cid,"desired_revision":revision,"applied_revision":revision,"desired_checksum":checksum,"applied_checksum":checksum,"status":"applied","installed_version":None if desired=="absent" else str(cmd.get("version") or "latest"),"managed_path":path,"last_error":None,"readiness":"healthy",**source_meta}
 except Exception as exc:report={"instance_id":iid,"content_id":cid,"desired_revision":revision,"applied_revision":None,"desired_checksum":checksum,"applied_checksum":None,"status":"failed","installed_version":None,"last_error":str(exc)[:2000],"readiness":"rollback_failed" if isinstance(exc,ContentRollbackError) else "rolled_back" if isinstance(exc,ContentActivationError) else "unknown",**source_meta}
 _write(state,report);return report
def apply_content_commands(config:dict[str,Any],commands:list[dict[str,Any]])->list[dict[str,Any]]:
 bounded=[c for c in commands[:200] if isinstance(c,dict)];ordered=[c for c in bounded if c.get("desired_state")=="absent"]+[c for c in bounded if c.get("desired_state")!="absent"];reports=[];pending=ordered
 for _ in range(max(1,len(pending)+1)):
  if not pending:break
  retry=[];progress=False
  for cmd in pending:
   report=_apply(config,cmd);reports.append(report)
   if report.get("status")=="failed" and "dependency is not installed" in str(report.get("last_error") or ""):retry.append(cmd)
   else:progress=True
  if not retry or not progress:break
  pending=retry
 return reports[-200:]
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
