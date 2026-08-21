#!/usr/bin/env python3
"""Safe desired-state content reconciler for the Linux Agent."""
from __future__ import annotations
import hashlib,json,os,shutil,tarfile,tempfile,urllib.request,zipfile
from pathlib import Path
from typing import Any
from instance_runtime import get_instance

STATE_ROOT=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR","/var/lib/capivara-agent"))
CONTENT_STATE=STATE_ROOT/"managed-content"
GAME_DATA_ROOT=Path(os.environ.get("CAPIVARA_GAME_DATA_ROOT",str(STATE_ROOT/"game-data"))).resolve()

def _write(path:Path,payload:dict[str,Any]):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(f".{path.name}.{os.getpid()}.tmp")
 tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.chmod(tmp,0o600);os.replace(tmp,path)
def _safe_component(v:Any)->str:
 s=str(v or "").strip()
 if not s or "/" in s or "\\" in s or s in {".",".."}:raise ValueError("unsafe content identifier")
 return s
def _state_path(instance_id,content_id):return CONTENT_STATE/_safe_component(instance_id)/f"{_safe_component(content_id)}.json"
def _safe_target(root:Path,target:str)->Path:
 rel=Path(str(target or "").replace("\\","/"))
 if rel.is_absolute() or not rel.parts or any(p in {"",".",".."} for p in rel.parts):raise ValueError("unsafe content target")
 base=(root/"content").resolve();candidate=(base/rel).resolve()
 try:candidate.relative_to(base)
 except ValueError as exc:raise ValueError("content target escapes instance") from exc
 return candidate
def _owned(config,cmd):
 iid=str(cmd.get("instance_id") or "").strip();rec=get_instance(iid)
 if not rec:raise LookupError("instance not found")
 if str(rec.get("agent_id") or "")!=str(config.get("agent_id") or ""):raise PermissionError("instance belongs to another Agent")
 path=Path(str(rec.get("path") or "")).resolve()
 if not path.is_dir():raise FileNotFoundError("instance path missing")
 return rec,path
def _sha(path:Path,expected:str|None):
 if not expected:return
 h=hashlib.sha256()
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
 if h.hexdigest().lower()!=str(expected).lower():raise ValueError("artifact checksum mismatch")
def _extract(archive:Path,dest:Path):
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
   for m in t.getmembers():
    safe(m.name)
    if m.issym() or m.islnk():raise ValueError("archive links are forbidden")
   t.extractall(dest,filter="data");return
 raise ValueError("unsupported archive format")
def _local_artifact(artifact):
 raw=str(artifact.get("package_id") or artifact.get("path") or "").strip()
 if not raw:raise ValueError("local artifact path required")
 candidate=(GAME_DATA_ROOT/raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
 try:candidate.relative_to(GAME_DATA_ROOT)
 except ValueError as exc:raise ValueError("local artifact outside game-data root") from exc
 if not candidate.exists():raise FileNotFoundError("local artifact missing")
 return candidate
def _download(artifact,dest):
 url=str(artifact.get("url") or artifact.get("package_id") or "").strip()
 if not url.startswith("https://"):raise ValueError("remote content requires HTTPS")
 with urllib.request.urlopen(url,timeout=60) as r,dest.open("wb") as f:shutil.copyfileobj(r,f)
 return dest
def _install(config,cmd):
 _,instance=_owned(config,cmd);target=_safe_target(instance,str(cmd.get("target") or "assets"));artifact=dict(cmd.get("artifact") or {});provider=str(cmd.get("provider") or artifact.get("provider") or "")
 parent=target.parent;parent.mkdir(parents=True,exist_ok=True)
 stage=Path(tempfile.mkdtemp(prefix=f".{target.name}.c4-",dir=str(parent)))
 backup=target.with_name(target.name+".c4-old")
 try:
  source=None
  if provider=="local":source=_local_artifact(artifact)
  elif provider in {"http","http-archive","github"}:source=_download(artifact,stage/"artifact")
  else:raise ValueError(f"provider not executable by Linux Agent: {provider}")
  _sha(source,artifact.get("sha256"))
  payload=stage/"payload";payload.mkdir()
  archive=provider=="http-archive" or bool(artifact.get("archive"))
  if archive:_extract(source,payload)
  elif source.is_dir():shutil.copytree(source,payload,dirs_exist_ok=True)
  else:shutil.copy2(source,payload/(str(artifact.get("filename") or source.name or "content.bin")))
  if backup.exists():shutil.rmtree(backup)
  if target.exists():os.replace(target,backup)
  os.replace(payload,target)
  if backup.exists():shutil.rmtree(backup)
 finally:
  shutil.rmtree(stage,ignore_errors=True)
 return str(target)
def _remove(config,cmd):
 _,instance=_owned(config,cmd);target=_safe_target(instance,str(cmd.get("target") or "assets"))
 if target.exists():shutil.rmtree(target) if target.is_dir() else target.unlink()
 return str(target)
def apply_content_commands(config:dict[str,Any],commands:list[dict[str,Any]])->list[dict[str,Any]]:
 reports=[]
 for cmd in commands[:200]:
  iid=str(cmd.get("instance_id") or "");cid=str(cmd.get("content_id") or "");revision=int(cmd.get("revision") or 0);checksum=str(cmd.get("checksum") or "")
  state=_state_path(iid,cid)
  try:
   previous=json.loads(state.read_text()) if state.exists() else {}
  except Exception:previous={}
  if previous.get("status")=="applied" and previous.get("applied_revision")==revision and previous.get("applied_checksum")==checksum:
   reports.append(previous);continue
  try:
   desired=str(cmd.get("desired_state") or "installed")
   path=_remove(config,cmd) if desired=="absent" else _install(config,cmd)
   report={"instance_id":iid,"content_id":cid,"desired_revision":revision,"applied_revision":revision,"desired_checksum":checksum,"applied_checksum":checksum,"status":"applied","installed_version":None if desired=="absent" else str(cmd.get("version") or "latest"),"managed_path":path,"last_error":None}
  except Exception as exc:
   report={"instance_id":iid,"content_id":cid,"desired_revision":revision,"applied_revision":None,"desired_checksum":checksum,"applied_checksum":None,"status":"failed","installed_version":None,"last_error":str(exc)[:2000]}
  _write(state,report);reports.append(report)
 return reports

def content_state()->list[dict[str,Any]]:
 out=[]
 try:paths=sorted(CONTENT_STATE.glob("*/*.json"))
 except OSError:paths=[]
 for p in paths:
  try:v=json.loads(p.read_text(encoding="utf-8"))
  except Exception:continue
  if isinstance(v,dict):out.append(v)
 return out[:2000]

__all__=["apply_content_commands","content_state"]
