"""Safe local executor for Universal Smart Backup commands on Windows."""
from __future__ import annotations
import fnmatch,hashlib,json,os,shutil,tarfile,tempfile,uuid
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from instance_runtime import get_instance,lifecycle,status
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));STATE_ROOT=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"));BACKUP_ROOT=Path(os.environ.get("CAPIVARA_BACKUP_ROOT",STATE_ROOT/"backups")).resolve();RESULT_ROOT=STATE_ROOT/"backup-results"
def _now():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _safe(v):
 s=str(v or "").strip()
 if not s or "/" in s or "\\" in s or s in {".",".."}:raise ValueError("unsafe backup identifier")
 return s
def _write(path,payload):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(f".{path.name}.{os.getpid()}.tmp");tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(tmp,path)
def _owned(config,iid):
 rec=get_instance(_safe(iid))
 if not rec:raise LookupError("instance not found")
 if str(rec.get("agent_id") or "")!=str(config.get("agent_id") or ""):raise PermissionError("instance belongs to another Agent")
 root=Path(str(rec.get("path") or "")).resolve()
 if not root.is_dir():raise FileNotFoundError("instance path missing")
 return rec,root
def _digest(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
 return h.hexdigest()
def _selected(root,policy):
 includes=list(policy.get("include_paths") or []);excludes=list(policy.get("exclude_paths") or []);mode=str(policy.get("mode") or "full")
 if mode!="full" and not includes:raise ValueError("non-full backup requires include_paths")
 candidates=[]
 if includes:
  for rel in includes:
   p=(root/str(rel)).resolve();p.relative_to(root)
   if p.exists():candidates.append(p)
 else:candidates=[root]
 def excluded(p):
  rel=p.relative_to(root).as_posix();return any(fnmatch.fnmatch(rel,pat) or fnmatch.fnmatch(rel+"/",pat.rstrip("/")+"/") for pat in excludes)
 return [p for p in candidates if not excluded(p)]
def _create_archive(root,paths,dest,compression):
 mode="w:gz" if compression=="gzip" else "w";dest.parent.mkdir(parents=True,exist_ok=True)
 with tarfile.open(dest,mode,dereference=False) as tar:
  for p in paths:
   arc="." if p==root else p.relative_to(root).as_posix();tar.add(p,arcname=arc,recursive=True,filter=lambda info:None if info.issym() or info.islnk() else info)
def _safe_extract(archive,dest):
 with tarfile.open(archive,"r:*") as tar:
  members=tar.getmembers();base=dest.resolve()
  for m in members:
   if m.issym() or m.islnk():raise ValueError("backup contains links")
   (base/m.name).resolve().relative_to(base)
  tar.extractall(base,members=members)
def _retention(instance_dir,keep):
 archives=sorted([p for p in instance_dir.glob("*.tar*") if p.is_file()],key=lambda p:p.stat().st_mtime,reverse=True)
 for old in archives[max(1,int(keep)):]:old.unlink(missing_ok=True)
def _create(config,cmd):
 iid=str(cmd["instance_id"]);_,root=_owned(config,iid);policy=dict(cmd.get("policy") or {});cons=str(policy.get("consistency") or "live");was_running=False
 if cons=="quiesced":raise RuntimeError("quiesced backup requires a game-specific consistency hook")
 if cons=="stopped":
  was_running=status(config,iid).get("observed_state")=="running"
  if was_running:lifecycle(config,iid,"stop")
 try:
  bid=str(uuid.uuid4());idir=BACKUP_ROOT/_safe(iid);suffix=".tar.gz" if str(policy.get("compression") or "gzip")=="gzip" else ".tar";path=idir/f"{bid}{suffix}";_create_archive(root,_selected(root,policy),path,str(policy.get("compression") or "gzip"));size=path.stat().st_size;sha=_digest(path);_retention(idir,int(policy.get("retention_count") or 7));return {"backup_id":bid,"artifact_path":str(path),"size_bytes":size,"sha256":sha}
 finally:
  if cons=="stopped" and was_running:lifecycle(config,iid,"start")
def _artifact(iid,bid):
 idir=(BACKUP_ROOT/_safe(iid)).resolve();idir.relative_to(BACKUP_ROOT);matches=list(idir.glob(f"{_safe(bid)}.tar*"))
 if len(matches)!=1:raise FileNotFoundError("backup artifact not found")
 return matches[0]
def _restore(config,cmd):
 iid=str(cmd["instance_id"]);_,root=_owned(config,iid);artifact=_artifact(iid,str(cmd.get("backup_id") or ""));was_running=status(config,iid).get("observed_state")=="running"
 if was_running:lifecycle(config,iid,"stop")
 stage=Path(tempfile.mkdtemp(prefix=f".{root.name}.restore-",dir=str(root.parent)))
 try:
  _safe_extract(artifact,stage);previous=root.with_name(root.name+".c5-previous")
  if previous.exists():shutil.rmtree(previous)
  os.replace(root,previous);os.replace(stage,root);shutil.rmtree(previous,ignore_errors=True)
 finally:
  shutil.rmtree(stage,ignore_errors=True)
  if was_running:lifecycle(config,iid,"start")
 return {"backup_id":str(cmd.get("backup_id")),"artifact_path":str(artifact),"size_bytes":artifact.stat().st_size,"sha256":_digest(artifact)}
def _delete(config,cmd):
 iid=str(cmd["instance_id"]);_owned(config,iid);artifact=_artifact(iid,str(cmd.get("backup_id") or ""));artifact.unlink();return {"backup_id":str(cmd.get("backup_id")),"artifact_path":str(artifact)}
def apply_backup_commands(config:dict[str,Any],commands:list[dict[str,Any]])->list[dict[str,Any]]:
 reports=[]
 for cmd in commands[:20]:
  cid=_safe(cmd.get("command_id"));path=RESULT_ROOT/f"{cid}.json"
  try:previous=json.loads(path.read_text()) if path.exists() else {}
  except Exception:previous={}
  if previous.get("status") in {"completed","failed"}:reports.append(previous);continue
  started=_now();_write(path,{"command_id":cid,"status":"running","started_at":started})
  try:
   action=str(cmd.get("action") or "create");detail=_create(config,cmd) if action=="create" else _restore(config,cmd) if action=="restore" else _delete(config,cmd) if action=="delete" else (_ for _ in ()).throw(ValueError("unsupported backup action"));report={"command_id":cid,"instance_id":cmd.get("instance_id"),"action":action,"status":"completed","started_at":started,"completed_at":_now(),**detail}
  except Exception as exc:report={"command_id":cid,"instance_id":cmd.get("instance_id"),"action":cmd.get("action"),"status":"failed","started_at":started,"completed_at":_now(),"last_error":str(exc)[:2000]}
  _write(path,report);reports.append(report)
 return reports
def backup_state():
 out=[]
 for p in sorted(RESULT_ROOT.glob("*.json")) if RESULT_ROOT.exists() else []:
  try:v=json.loads(p.read_text(encoding="utf-8"))
  except Exception:continue
  if isinstance(v,dict):out.append(v)
 return out[-500:]
__all__=["apply_backup_commands","backup_state"]
