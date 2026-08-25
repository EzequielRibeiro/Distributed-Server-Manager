"""Supervise arbitrary game-server processes on Windows without shell execution."""
from __future__ import annotations
import json,os,signal,subprocess,time
from datetime import datetime,timezone
from pathlib import Path
from .base import AdapterError,InstanceRuntimeAdapter
from windows_job_limits import apply_process_limits,release_process
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));STATE_ROOT=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"))/"runtime-processes"
def _now():return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _token(v):
 t=str(v or "").strip()
 if not t or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in t):raise AdapterError("invalid instance id")
 return t
def _state_path(instance):return STATE_ROOT/f"{_token(instance.get('instance_id'))}.json"
def _read(instance):
 try:v=json.loads(_state_path(instance).read_text(encoding="utf-8"))
 except (OSError,ValueError):return None
 return v if isinstance(v,dict) else None
def _write(instance,payload):
 p=_state_path(instance);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_suffix(".tmp");tmp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.replace(tmp,p)
def _alive(pid):
 if int(pid or 0)<=0:return False
 try:os.kill(int(pid),0);return True
 except OSError:return False
def _argv(instance):
 exe=Path(str(instance.get("executable") or ""))
 if not exe.is_absolute():raise AdapterError("runtime executable must be absolute")
 if not exe.is_file():raise AdapterError(f"runtime executable is unavailable: {exe}")
 args=instance.get("arguments",[])
 if not isinstance(args,list) or len(args)>128:raise AdapterError("invalid runtime arguments")
 values=[str(exe)]
 for item in args:
  text=str(item)
  if "\x00" in text or "\n" in text or "\r" in text:raise AdapterError("invalid runtime argument")
  values.append(text)
 return values
def _cwd(instance):
 p=Path(str(instance.get("working_directory") or instance.get("path") or ""))
 if not p.is_absolute() or not p.is_dir():raise AdapterError("runtime working directory is unavailable")
 return p
def _env(instance):
 raw=instance.get("environment") or {}
 if not isinstance(raw,dict):raise AdapterError("invalid runtime environment")
 return {**os.environ,**{str(k):str(v) for k,v in raw.items()}}
class WindowsProcessAdapter(InstanceRuntimeAdapter):
 name="windows-process"
 def status(self,instance):
  state=_read(instance) or {};pid=int(state.get("pid") or 0);running=_alive(pid)
  if state and not running:state={**state,"exited":True,"observed_at":_now()};_write(instance,state);release_process(pid)
  return {"available":True,"active_state":"active" if running else "inactive","running":running,"pid":pid or None,"started_at":state.get("started_at"),"log_path":state.get("log_path"),"resource_limits":state.get("resource_limits")}
 def start(self,instance):
  before=self.status(instance)
  if before["running"]:return {"action":"start","changed":False,"idempotent":True,"state":before}
  argv=_argv(instance);cwd=_cwd(instance);logs=STATE_ROOT/"logs";logs.mkdir(parents=True,exist_ok=True);log=logs/f"{_token(instance.get('instance_id'))}.log";handle=open(log,"ab",buffering=0);flags=getattr(subprocess,"CREATE_NEW_PROCESS_GROUP",0)|getattr(subprocess,"CREATE_NO_WINDOW",0)
  try:
   proc=subprocess.Popen(argv,cwd=str(cwd),env=_env(instance),stdin=subprocess.DEVNULL,stdout=handle,stderr=subprocess.STDOUT,close_fds=True,creationflags=flags);limits=apply_process_limits(proc.pid,instance)
  except Exception as exc:
   handle.close()
   try:
    if 'proc' in locals():proc.kill()
   except Exception:pass
   raise AdapterError(f"failed to start runtime process: {exc}") from exc
  handle.close();_write(instance,{"pid":proc.pid,"started_at":_now(),"log_path":str(log),"argv0":argv[0],"resource_limits":limits});time.sleep(.05);after=self.status(instance)
  if not after["running"]:raise AdapterError("runtime process exited immediately after start")
  return {"action":"start","changed":True,"idempotent":False,"state":after}
 def stop(self,instance):
  before=self.status(instance)
  if not before["running"]:return {"action":"stop","changed":False,"idempotent":True,"state":before}
  pid=int(before["pid"])
  try:
   if os.name=="nt":
    cp=subprocess.run(["taskkill.exe","/PID",str(pid),"/T","/F"],capture_output=True,text=True,timeout=30,check=False,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    if cp.returncode!=0 and _alive(pid):raise AdapterError((cp.stderr or cp.stdout or "taskkill failed")[:2000])
   else:os.kill(pid,signal.SIGTERM)
  except OSError as exc:
   if _alive(pid):raise AdapterError(f"failed to stop runtime process: {exc}") from exc
  deadline=time.monotonic()+30
  while _alive(pid) and time.monotonic()<deadline:time.sleep(.1)
  if _alive(pid):raise AdapterError("runtime process did not stop")
  release_process(pid);return {"action":"stop","changed":True,"idempotent":False,"state":self.status(instance)}
 def restart(self,instance):self.stop(instance);out=self.start(instance);return {"action":"restart","changed":True,"state":out["state"]}
 def doctor(self,instance):
  findings=[]
  try:_argv(instance)
  except Exception as exc:findings.append({"code":"runtime_executable_invalid","severity":"critical","message":str(exc)[:2000]})
  try:_cwd(instance)
  except Exception as exc:findings.append({"code":"runtime_workdir_invalid","severity":"critical","message":str(exc)[:2000]})
  return {"adapter":self.name,"ready":not findings,"status":"healthy" if not findings else "critical","state":self.status(instance),"findings":findings}
__all__=["WindowsProcessAdapter"]
