#!/usr/bin/env python3
"""Per-instance telemetry for the Windows Agent."""
from __future__ import annotations
import ctypes,json,os,re,subprocess,time
from ctypes import wintypes
from pathlib import Path
from typing import Any
import instance_runtime
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));STATE_DIR=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"));SAMPLE_STATE_DIR=STATE_DIR/"instance-telemetry"
def _process_pid(instance_id,record):
 adapter=str(record.get("adapter") or "").lower()
 if adapter=="windows-process":
  try:return int(json.loads((STATE_DIR/"runtime-processes"/f"{instance_id}.json").read_text(encoding="utf-8")).get("pid") or 0) or None
  except (OSError,ValueError,TypeError):return None
 if adapter=="windows-service":
  service=str(record.get("runtime_id") or "").strip()
  if not service:return None
  try:
   cp=subprocess.run(["sc.exe","queryex",service],capture_output=True,text=True,timeout=5,check=False,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0));m=re.search(r"PID\s*:\s*(\d+)",(cp.stdout or "")+(cp.stderr or ""),re.I);pid=int(m.group(1)) if m else 0;return pid or None
  except (OSError,ValueError,subprocess.SubprocessError):return None
 return None
def _process_values(pid):
 if os.name!="nt" or not pid:return None,None,None
 kernel=ctypes.windll.kernel32;psapi=ctypes.windll.psapi;handle=kernel.OpenProcess(0x1000|0x0010,False,int(pid))
 if not handle:return None,None,None
 class PMC(ctypes.Structure):_fields_=[("cb",wintypes.DWORD),("PageFaultCount",wintypes.DWORD),("PeakWorkingSetSize",ctypes.c_size_t),("WorkingSetSize",ctypes.c_size_t),("QuotaPeakPagedPoolUsage",ctypes.c_size_t),("QuotaPagedPoolUsage",ctypes.c_size_t),("QuotaPeakNonPagedPoolUsage",ctypes.c_size_t),("QuotaNonPagedPoolUsage",ctypes.c_size_t),("PagefileUsage",ctypes.c_size_t),("PeakPagefileUsage",ctypes.c_size_t)]
 try:
  creation=wintypes.FILETIME();exit_time=wintypes.FILETIME();kernel_time=wintypes.FILETIME();user_time=wintypes.FILETIME();cpu=None;started=None
  if kernel.GetProcessTimes(handle,ctypes.byref(creation),ctypes.byref(exit_time),ctypes.byref(kernel_time),ctypes.byref(user_time)):
   to_int=lambda ft:(int(ft.dwHighDateTime)<<32)|int(ft.dwLowDateTime);cpu=to_int(kernel_time)+to_int(user_time);started=(to_int(creation)-116444736000000000)/10_000_000
  mem=PMC();mem.cb=ctypes.sizeof(PMC);rss=int(mem.WorkingSetSize) if psapi.GetProcessMemoryInfo(handle,ctypes.byref(mem),mem.cb) else None;return cpu,rss,started
 finally:kernel.CloseHandle(handle)
def _cpu_percent(instance_id,cpu):
 if cpu is None:return None
 now=time.monotonic();path=SAMPLE_STATE_DIR/f"{instance_id}.json";previous=None
 try:previous=json.loads(path.read_text(encoding="utf-8"))
 except (OSError,ValueError):pass
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(".tmp");temp.write_text(json.dumps({"monotonic":now,"cpu_100ns":cpu}),encoding="utf-8");os.replace(temp,path)
 if not isinstance(previous,dict):return None
 try:elapsed=now-float(previous["monotonic"]);delta=int(cpu)-int(previous["cpu_100ns"]);return round((delta/10_000_000)/elapsed*100.0,2) if elapsed>0 and delta>=0 else None
 except (KeyError,TypeError,ValueError,ZeroDivisionError):return None
def _storage_used(path_value,max_entries=200000):
 root=Path(str(path_value or ""))
 if not root.is_dir():return None
 total=0;seen=0
 try:
  for current,dirs,files in os.walk(root,followlinks=False):
   dirs[:]=[n for n in dirs if not (Path(current)/n).is_symlink()]
   for name in files:
    seen+=1
    if seen>max_entries:return total
    try:
     p=Path(current)/name
     if not p.is_symlink():total+=p.stat().st_size
    except OSError:pass
 except OSError:return None
 return total
def _query(config):
 argv=config.get("query_argv")
 if not isinstance(argv,list) or not argv or not all(isinstance(x,str) for x in argv):return {}
 try:
  cp=subprocess.run(argv,capture_output=True,text=True,timeout=max(1,min(int(config.get("query_timeout_seconds") or 5),15)),check=False,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0));value=json.loads(cp.stdout or "{}") if cp.returncode==0 else {};return value if isinstance(value,dict) else {}
 except (OSError,ValueError,subprocess.SubprocessError):return {}
def collect_instance_telemetry(config:dict[str,Any]):
 result=[]
 for item in instance_runtime.list_instances(config):
  iid=str(item.get("instance_id") or "").strip();record=instance_runtime.get_instance(iid) or {};pid=_process_pid(iid,record);cpu,rss,started=_process_values(pid);game=_query(record.get("telemetry") if isinstance(record.get("telemetry"),dict) else {})
  try:view=instance_runtime.status(config,iid);state=str(view.get("observed_state") or "unknown").lower();health="healthy" if state=="running" else "degraded" if state in {"starting","failed","unavailable"} else "unknown"
  except Exception:health="unknown"
  private_root=record.get("instance_state_root") or record.get("path")
  result.append({"instance_id":iid,"storage_pool_id":record.get("storage_pool_id"),"instance_state_root":str(record.get("instance_state_root") or "") or None,"cpu_percent":_cpu_percent(iid,cpu),"memory_bytes":rss,"storage_used_bytes":_storage_used(private_root),"network_rx_bytes":game.get("network_rx_bytes"),"network_tx_bytes":game.get("network_tx_bytes"),"players_online":game.get("players_online"),"players_max":game.get("players_max"),"latency_ms":game.get("latency_ms"),"uptime_seconds":max(0,int(time.time()-started)) if started else None,"health":str(game.get("health") or health)})
 return result
__all__=["collect_instance_telemetry"]
