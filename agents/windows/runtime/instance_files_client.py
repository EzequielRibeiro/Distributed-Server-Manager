"""Agent-owned safe file manager for Windows game-server instances."""
from __future__ import annotations
import base64,io,json,os,shutil,tarfile,zipfile
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
import instance_runtime
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));STATE_DIR=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"));RESULT_DIR=STATE_DIR/"file-results";HISTORY_DIR=STATE_DIR/"file-history"
MAX_TRANSFER_BYTES=16*1024*1024;MAX_ARCHIVE_MEMBERS=10000
EDITABLE_SUFFIXES={".txt",".cfg",".conf",".config",".ini",".json",".properties",".toml",".xml",".yaml",".yml",".log",".md",".csv"}
def _now():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _safe_id(value,label):
 value=str(value or "").strip()
 if not value or len(value)>191 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in value):raise ValueError(f"invalid {label}")
 return value
def _state(root,command_id):return root/f"{_safe_id(command_id,'command_id')}.json"
def _read(path):
 try:v=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,ValueError):return None
 return v if isinstance(v,dict) else None
def _write(path,payload):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(f".{path.name}.{os.getpid()}.tmp");tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(tmp,path)
def _owned(config,instance_id):
 record=instance_runtime.get_instance(_safe_id(instance_id,"instance_id"))
 if not isinstance(record,dict):raise LookupError("instance not found")
 if str(record.get("agent_id") or "")!=str(config.get("agent_id") or ""):raise PermissionError("instance belongs to another Agent")
 return record
def _root(record):
 raw=record.get("files_root") or record.get("configuration_root") or record.get("working_directory") or record.get("path");root=Path(str(raw or ""))
 if not root.is_absolute() or not root.is_dir() or root.is_symlink():raise RuntimeError("instance customer files root is unavailable")
 return root.resolve()
def _relative(value):
 raw=str(value or ".").replace("\\","/");p=Path(raw)
 if p.is_absolute() or ".." in p.parts:raise ValueError("invalid instance file path")
 return Path(*[x for x in p.parts if x not in {"","."}])
def _resolve(root,value,missing=False):
 rel=_relative(value);cur=root
 for part in rel.parts:
  cur=cur/part
  if cur.is_symlink():raise ValueError("symbolic links are not allowed")
 p=(root/rel).resolve(strict=False);p.relative_to(root)
 if not missing and not p.exists():raise FileNotFoundError(rel.as_posix())
 return p
def _sets(raw):return {str(x).strip().strip("/\\").lower() for x in raw if str(x).strip()} if isinstance(raw,list) else set()
def _under(rel,roots):
 text=rel.as_posix().lower();return any(text==r or text.startswith(r.rstrip("/")+"/") for r in roots)
def _guard(rel,policy,upload=False):
 fp=policy.get("file_policy") if isinstance(policy.get("file_policy"),dict) else {};cp=policy.get("content_policy") if isinstance(policy.get("content_policy"),dict) else {};protected=_sets(fp.get("protected_paths"))|{".dsm","runtime"}
 if rel.parts and str(rel.parts[0]).lower() in protected:raise PermissionError("protected instance path")
 if not upload:return
 if not bool(cp.get("external_upload_allowed",True)):raise PermissionError("external uploads are not allowed by this contract")
 mods=_sets(fp.get("mod_paths"));plugins=_sets(fp.get("plugin_paths"));workshop=_sets(fp.get("workshop_paths"))
 if _under(rel,mods) and not bool(cp.get("mods_allowed")):raise PermissionError("mods are not allowed by this contract")
 if _under(rel,plugins) and not bool(cp.get("plugins_allowed")):raise PermissionError("plugins are not allowed by this contract")
 if _under(rel,workshop) and not bool(cp.get("workshop_allowed")):raise PermissionError("Workshop content is not allowed by this contract")
 extensions={str(x).lower() for x in fp.get("runtime_extensions") or []}
 if rel.suffix.lower() in extensions and not _under(rel,mods|plugins|workshop) and not bool(cp.get("custom_runtime_allowed")):raise PermissionError("custom runtime artifacts are not allowed by this contract")
def _usage(root):
 total=0
 for base,dirs,files in os.walk(root,followlinks=False):
  bp=Path(base);dirs[:]=[d for d in dirs if not (bp/d).is_symlink()]
  for name in files:
   p=bp/name
   if p.is_symlink():continue
   try:total+=p.stat().st_size
   except OSError:pass
 return total
def _limit(policy):
 try:v=int(policy.get("storage_limit_bytes")) if policy.get("storage_limit_bytes") is not None else None
 except (TypeError,ValueError):v=None
 return v if v and v>0 else None
def _quota(root,policy,added,replacing=None):
 limit=_limit(policy)
 if limit is None:return
 previous=replacing.stat().st_size if replacing is not None and replacing.is_file() and not replacing.is_symlink() else 0;projected=_usage(root)-previous+max(0,int(added))
 if projected>limit:raise OSError(f"storage quota exceeded: {projected} > {limit}")
def _entry(root,p):
 s=p.stat();return {"name":p.name,"path":p.relative_to(root).as_posix(),"directory":p.is_dir(),"size":None if p.is_dir() else s.st_size,"modified_at":int(s.st_mtime),"editable":p.is_file() and p.suffix.lower() in EDITABLE_SUFFIXES and s.st_size<=2*1024*1024}
def _list(root,path,policy):
 d=_resolve(root,path)
 if not d.is_dir():raise ValueError("path is not a directory")
 out=[]
 for p in sorted(d.iterdir(),key=lambda x:(not x.is_dir(),x.name.lower())):
  if p.is_symlink():continue
  try:_guard(p.relative_to(root),policy)
  except PermissionError:continue
  out.append(_entry(root,p))
 return {"path":d.relative_to(root).as_posix() or ".","entries":out,"usage_bytes":_usage(root),"limit_bytes":_limit(policy)}
def _read_text(root,path,policy):
 p=_resolve(root,path);rel=p.relative_to(root);_guard(rel,policy)
 if not p.is_file() or p.suffix.lower() not in EDITABLE_SUFFIXES:raise ValueError("file is not editable text")
 if p.stat().st_size>2*1024*1024:raise ValueError("editable file is too large")
 return {"path":rel.as_posix(),"content":p.read_text(encoding="utf-8"),"size":p.stat().st_size}
def _write_text(root,path,payload,policy):
 p=_resolve(root,path,True);rel=p.relative_to(root);_guard(rel,policy,True);content=payload.get("content")
 if not isinstance(content,str):raise ValueError("content must be text")
 data=content.encode("utf-8")
 if len(data)>2*1024*1024 or p.suffix.lower() not in EDITABLE_SUFFIXES:raise ValueError("file is not editable text")
 if not p.parent.is_dir():raise ValueError("destination directory does not exist")
 _quota(root,policy,len(data),p);tmp=p.with_name(f".{p.name}.{os.getpid()}.tmp");tmp.write_bytes(data);os.replace(tmp,p);return {"path":rel.as_posix(),"size":len(data),"saved":True}
def _decode(payload):
 raw=payload.get("content_base64")
 if not isinstance(raw,str):raise ValueError("content_base64 is required")
 try:data=base64.b64decode(raw,validate=True)
 except Exception as exc:raise ValueError("invalid base64 upload") from exc
 if len(data)>MAX_TRANSFER_BYTES:raise ValueError("uploaded file exceeds transfer limit")
 return data
def _upload(root,path,payload,policy):
 p=_resolve(root,path,True);rel=p.relative_to(root);_guard(rel,policy,True)
 if not p.parent.is_dir():raise ValueError("destination directory does not exist")
 data=_decode(payload);_quota(root,policy,len(data),p);tmp=p.with_name(f".{p.name}.{os.getpid()}.upload");tmp.write_bytes(data);os.replace(tmp,p);return {"path":rel.as_posix(),"size":len(data),"uploaded":True}
def _download(root,path,policy):
 p=_resolve(root,path);rel=p.relative_to(root);_guard(rel,policy)
 if not p.is_file():raise ValueError("path is not a file")
 data=p.read_bytes()
 if len(data)>MAX_TRANSFER_BYTES:raise ValueError("file exceeds transfer limit")
 return {"path":rel.as_posix(),"name":p.name,"size":len(data),"content_base64":base64.b64encode(data).decode("ascii")}
def _mkdir(root,path,policy):
 p=_resolve(root,path,True);rel=p.relative_to(root);_guard(rel,policy,True)
 if p.exists():raise FileExistsError(rel.as_posix())
 if not p.parent.is_dir():raise ValueError("parent directory does not exist")
 p.mkdir();return {"path":rel.as_posix(),"created":True}
def _delete(root,path,policy):
 p=_resolve(root,path);rel=p.relative_to(root);_guard(rel,policy)
 if p==root:raise PermissionError("instance files root cannot be deleted")
 shutil.rmtree(p) if p.is_dir() else p.unlink();return {"path":rel.as_posix(),"deleted":True}
def _move(root,source,target,policy):
 s=_resolve(root,source);t=_resolve(root,target,True);sr=s.relative_to(root);tr=t.relative_to(root);_guard(sr,policy);_guard(tr,policy,True)
 if s==root or t==root or t.exists():raise ValueError("invalid move target")
 if not t.parent.is_dir():raise ValueError("target parent does not exist")
 shutil.move(str(s),str(t));return {"from":sr.as_posix(),"to":tr.as_posix(),"moved":True}
def _archive(data,name):
 lower=name.lower()
 if lower.endswith(".zip"):
  a=zipfile.ZipFile(io.BytesIO(data),"r");infos=a.infolist()
  if len(infos)>MAX_ARCHIVE_MEMBERS:a.close();raise ValueError("archive has too many entries")
  def it():
   for i in infos:
    if ((i.external_attr>>16)&0o170000)==0o120000:raise ValueError("archive symbolic links are not allowed")
    yield i.filename,i.file_size,i.is_dir(),lambda x=i:a.open(x,"r")
  return a,it()
 if lower.endswith((".tar",".tar.gz",".tgz")):
  a=tarfile.open(fileobj=io.BytesIO(data),mode="r:gz" if lower.endswith((".tar.gz",".tgz")) else "r:");infos=a.getmembers()
  if len(infos)>MAX_ARCHIVE_MEMBERS:a.close();raise ValueError("archive has too many entries")
  def it():
   for i in infos:
    if i.issym() or i.islnk() or i.isdev():raise ValueError("archive links/devices are not allowed")
    yield i.name,i.size,i.isdir(),lambda x=i:a.extractfile(x)
  return a,it()
 raise ValueError("unsupported archive type")
def _extract(root,archive_value,target_value,policy):
 ap=_resolve(root,archive_value);ar=ap.relative_to(root);_guard(ar,policy);target=_resolve(root,target_value or ap.parent.relative_to(root),True)
 if not target.exists():target.mkdir()
 if not target.is_dir():raise ValueError("extract target is not a directory")
 data=ap.read_bytes()
 if len(data)>MAX_TRANSFER_BYTES:raise ValueError("archive exceeds transfer limit")
 archive,members=_archive(data,ap.name);planned=[];total=0
 try:
  for raw,size,directory,opener in members:
   relm=_relative(raw);dest=(target/relm).resolve(strict=False);dest.relative_to(root);rel=dest.relative_to(root);_guard(rel,policy,True);total+=max(0,int(size or 0));planned.append((dest,directory,opener))
  _quota(root,policy,total)
  for dest,directory,opener in planned:
   if directory:dest.mkdir(parents=True,exist_ok=True);continue
   dest.parent.mkdir(parents=True,exist_ok=True);h=opener()
   if h is None:continue
   with h,dest.open("wb") as out:shutil.copyfileobj(h,out,length=1024*1024)
 finally:archive.close()
 return {"archive":ar.as_posix(),"target":target.relative_to(root).as_posix(),"entries":len(planned),"expanded_bytes":total,"extracted":True}
def execute(config,command):
 record=_owned(config,str(command.get("instance_id") or ""));root=_root(record);policy=command.get("policy") if isinstance(command.get("policy"),dict) else {};action=str(command.get("action") or "").lower();path=command.get("path");target=command.get("target_path");payload=command.get("payload") if isinstance(command.get("payload"),dict) else {}
 if action=="list":return _list(root,path,policy)
 if action=="usage":return {"usage_bytes":_usage(root),"limit_bytes":_limit(policy)}
 if action=="read_text":return _read_text(root,path,policy)
 if action=="write_text":return _write_text(root,path,payload,policy)
 if action=="download":return _download(root,path,policy)
 if action=="upload":return _upload(root,path,payload,policy)
 if action=="mkdir":return _mkdir(root,path,policy)
 if action=="delete":return _delete(root,path,policy)
 if action in {"rename","move"}:return _move(root,path,target,policy)
 if action=="extract":return _extract(root,path,target,policy)
 raise ValueError("unsupported instance file action")
def handle_command(config,command):
 cid=_safe_id(command.get("command_id"),"command_id");history=_state(HISTORY_DIR,cid);previous=_read(history)
 if previous is not None:_write(_state(RESULT_DIR,cid),previous);return previous
 iid=str(command.get("instance_id") or "");action=str(command.get("action") or "")
 try:report={"command_id":cid,"instance_id":iid,"action":action,"status":"completed","result":execute(config,command),"generated_at":_now()}
 except Exception as exc:report={"command_id":cid,"instance_id":iid or None,"action":action or None,"status":"failed","error":str(exc)[:4000],"generated_at":_now()}
 _write(history,report);_write(_state(RESULT_DIR,cid),report);return report
def read_result():
 try:paths=sorted(RESULT_DIR.glob("*.json"))
 except OSError:paths=[]
 for p in paths:
  v=_read(p)
  if v:return v
 return None
def clear_result(command_id):
 try:_state(RESULT_DIR,command_id).unlink()
 except FileNotFoundError:pass
__all__=["clear_result","execute","handle_command","read_result"]
