#!/usr/bin/env python3
"""Capivara Windows Agent using the same distributed Controller contract as Linux."""
from __future__ import annotations
import json,os,platform,shutil,socket,sys,time,urllib.error,urllib.request
from pathlib import Path
from typing import Any
RUNTIME_DIR=Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:sys.path.insert(0,str(RUNTIME_DIR))
from backup_client import apply_backup_commands,backup_state
from broadcast_client import apply_broadcast_commands,broadcast_state
from capabilities import detect_capabilities
from configuration_client import apply_configuration_commands,configuration_state
from content_client import apply_content_commands,content_state
from game_data_client import clear_game_data_result,read_game_data_result,stage_game_data_command
from game_data_state import summary as game_data_summary
from instance_runtime import clear_result as clear_instance_result
from instance_runtime import handle_command as handle_instance_command
from instance_runtime import inventory as instance_inventory
from instance_runtime import read_result as read_instance_result
from network_inventory import collect_network_inventory
from provisioning_client import clear_provisioning_result,read_provisioning_result,stage_provisioning_command
from resource_telemetry import collect_agent_telemetry,collect_host_telemetry,collect_instance_resources
from runtime_events import acknowledge_runtime_events,read_runtime_events
from runtime_health import health_inventory
from runtime_metrics import snapshot as runtime_metrics_snapshot
from runtime_operations import recover_interrupted_operations
from runtime_reconciler import reconcile_all,reconciliation_inventory
from update_client import clear_update_result,read_update_result,stage_update_request
PROGRAM_DATA=Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"));STATE_DIR=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR",PROGRAM_DATA/"CapivaraAgent"/"state"));CONFIG_PATH=Path(os.environ.get("CAPIVARA_AGENT_CONFIG",PROGRAM_DATA/"CapivaraAgent"/"agent.json"));DEFAULT_HEARTBEAT_SECONDS=30;DEFAULT_RECONCILE_SECONDS=15
def _load_config()->dict[str,Any]:return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
def _write_config(config):
 CONFIG_PATH.parent.mkdir(parents=True,exist_ok=True);temp=CONFIG_PATH.with_suffix(".tmp");temp.write_text(json.dumps(config,indent=2,sort_keys=True)+"\n",encoding="utf-8");temp.replace(CONFIG_PATH)
def _post(url,payload,headers=None):
 body=json.dumps(payload,separators=(",",":")).encode("utf-8");h={"Content-Type":"application/json","Accept":"application/json"};h.update(headers or {});req=urllib.request.Request(url,data=body,headers=h,method="POST")
 try:
  with urllib.request.urlopen(req,timeout=20) as response:return json.loads(response.read().decode("utf-8"))
 except urllib.error.HTTPError as exc:detail=exc.read().decode("utf-8",errors="replace");raise RuntimeError(f"Controller rejected request ({exc.code}): {detail}") from exc
 except urllib.error.URLError as exc:raise RuntimeError(f"Controller unavailable: {exc.reason}") from exc
def _memory_total_bytes():
 try:
  import ctypes
  class MEMORYSTATUSEX(ctypes.Structure):_fields_=[("dwLength",ctypes.c_ulong),("dwMemoryLoad",ctypes.c_ulong),("ullTotalPhys",ctypes.c_ulonglong),("ullAvailPhys",ctypes.c_ulonglong),("ullTotalPageFile",ctypes.c_ulonglong),("ullAvailPageFile",ctypes.c_ulonglong),("ullTotalVirtual",ctypes.c_ulonglong),("ullAvailVirtual",ctypes.c_ulonglong),("ullAvailExtendedVirtual",ctypes.c_ulonglong)]
  s=MEMORYSTATUSEX();s.dwLength=ctypes.sizeof(MEMORYSTATUSEX)
  if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):return int(s.ullTotalPhys)
 except Exception:pass
 return None
def _queue_depth():
 def count(path:Path,pattern:str)->int:
  try:return sum(1 for _ in path.glob(pattern))
  except OSError:return 0
 return {"instance_results":count(STATE_DIR/"instance-results","*.json"),"provisioning":count(STATE_DIR/"instance-provisioning","*.request.json"),"game_data":count(STATE_DIR/"game-data-jobs","*.json"),"backup_results":count(STATE_DIR/"backup-results","*.json"),"broadcast_state":count(STATE_DIR/"broadcast-state","*.json"),"runtime_events":len(read_runtime_events(STATE_DIR,limit=1000))}
def _inventory(config):
 root=Path(os.environ.get("SystemDrive","C:")+"\\");disk=shutil.disk_usage(root);version_path=Path(__file__).resolve().parents[1]/"VERSION"
 try:version=version_path.read_text(encoding="utf-8").strip()
 except OSError:version=str(config.get("capivara_version","unknown"))
 instances=instance_inventory(config);host_telemetry=collect_host_telemetry();agent_telemetry=collect_agent_telemetry();instance_resources=collect_instance_resources(instances)
 payload={"agent_id":config["agent_id"],"hostname":socket.gethostname(),"os":"windows","architecture":platform.machine(),"capivara_version":version,"address":config.get("advertise_address"),"fingerprint":config["fingerprint"],"capabilities":detect_capabilities(),"cpu":{"logical_cores":os.cpu_count(),"machine":platform.machine(),"usage_percent":host_telemetry.get("cpu_percent")},"ram_total_bytes":_memory_total_bytes(),"storage":{"root_total_bytes":disk.total,"root_free_bytes":disk.free,"usage_percent":host_telemetry.get("storage",{}).get("used_percent")},"network":collect_network_inventory(),"host_telemetry":host_telemetry,"agent_telemetry":agent_telemetry,"instance_resource_metrics":instance_resources,"instances":instances,"instance_reconciliation":reconciliation_inventory(config),"instance_runtime_health":health_inventory(config),"instance_runtime_metrics":runtime_metrics_snapshot(queue_depth=_queue_depth()),"runtime_events":read_runtime_events(STATE_DIR,limit=int(config.get("event_batch_size",200))),"configuration_state":configuration_state(),"content_state":content_state(),"backup_state":backup_state(),"broadcast_state":broadcast_state(),"game_data":game_data_summary(),"heartbeat_interval_seconds":int(config.get("heartbeat_interval_seconds",DEFAULT_HEARTBEAT_SECONDS)),"degraded_after_seconds":int(config.get("degraded_after_seconds",60)),"offline_after_seconds":int(config.get("offline_after_seconds",120))}
 for key,value in (("update_result",read_update_result()),("provisioning_result",read_provisioning_result()),("game_data_result",read_game_data_result()),("instance_result",read_instance_result())):
  if value:payload[key]=value
 return payload
def enroll(config):
 token=str(config.get("pairing_token","")).strip()
 if not token:raise RuntimeError("Agent has no permanent credential and no pairing token")
 base=str(config["controller_url"]).rstrip("/");result=_post(base+"/api/agent/enroll",{"pairing_token":token,"agent_id":config["agent_id"],"node_id":config["node_id"],"name":config.get("name") or socket.gethostname(),"fingerprint":config["fingerprint"],"hostname":socket.gethostname(),"os":"windows","architecture":platform.machine(),"capivara_version":config.get("capivara_version"),"address":config.get("advertise_address")});config.update({"controller_id":result["controller_id"],"credential_id":result["credential_id"],"credential_secret":result["credential_secret"],"credential_type":result.get("credential_type","opaque-v1")});config.pop("pairing_token",None);_write_config(config);return config
def heartbeat(config):
 base=str(config["controller_url"]).rstrip("/");result=_post(base+"/api/agent/heartbeat",_inventory(config),headers={"X-Capivara-Agent-Credential":str(config["credential_id"]),"X-Capivara-Agent-Secret":str(config["credential_secret"]),"X-Capivara-Agent-Fingerprint":str(config["fingerprint"])})
 ids=result.get("accepted_event_ids")
 if isinstance(ids,list):acknowledge_runtime_events(STATE_DIR,ids)
 commands=result.get("configuration_commands")
 if isinstance(commands,list):apply_configuration_commands([x for x in commands if isinstance(x,dict)])
 commands=result.get("content_commands")
 if isinstance(commands,list):apply_content_commands(config,[x for x in commands if isinstance(x,dict)])
 commands=result.get("backup_commands")
 if isinstance(commands,list):apply_backup_commands(config,[x for x in commands if isinstance(x,dict)])
 commands=result.get("broadcast_commands")
 if isinstance(commands,list):apply_broadcast_commands(config,[x for x in commands if isinstance(x,dict)])
 if result.get("update") and stage_update_request(dict(result["update"])):print(f"update staged version={result['update'].get('desired_version')}",flush=True);raise SystemExit(0)
 if result.get("update_state",{}).get("update_status")=="completed":clear_update_result()
 pc=result.get("provisioning_command")
 if isinstance(pc,dict):stage_provisioning_command(pc,config_path=CONFIG_PATH)
 ps=result.get("provisioning_state") if isinstance(result.get("provisioning_state"),dict) else {}
 if str(ps.get("status") or "").lower() in {"completed","failed"} and ps.get("provisioning_id"):clear_provisioning_result(str(ps["provisioning_id"]))
 gc=result.get("game_data_command")
 if isinstance(gc,dict):stage_game_data_command(gc)
 gs=result.get("game_data_state") if isinstance(result.get("game_data_state"),dict) else {}
 if str(gs.get("status") or "").lower() in {"completed","failed"} and gs.get("job_id"):clear_game_data_result(str(gs["job_id"]))
 ic=result.get("instance_command")
 if isinstance(ic,dict):
  ir=handle_instance_command(config,ic);print(f"instance command action={ir.get('action')} instance={ir.get('instance_id')} status={ir.get('status')}",flush=True)
 ins=result.get("instance_state") if isinstance(result.get("instance_state"),dict) else {}
 if str(ins.get("status") or "").lower() in {"completed","failed"} and ins.get("command_id"):clear_instance_result(str(ins["command_id"]))
 return result
def run_forever():
 config=_load_config()
 if not config.get("credential_id") or not config.get("credential_secret"):config=enroll(config)
 recover_interrupted_operations(config);heartbeat_interval=max(10,int(config.get("heartbeat_interval_seconds",DEFAULT_HEARTBEAT_SECONDS)));reconcile_interval=max(5,int(config.get("reconcile_interval_seconds",DEFAULT_RECONCILE_SECONDS)));next_hb=next_rec=0.0
 while True:
  now=time.monotonic()
  if now>=next_rec:
   try:reconcile_all(config)
   except Exception as exc:print(f"reconcile loop failed: {exc}",file=sys.stderr,flush=True)
   next_rec=now+reconcile_interval
  if now>=next_hb:
   try:
    result=heartbeat(config);print(f"heartbeat ok agent={result.get('agent_id')} health={result.get('health_status')} status={result.get('status')}",flush=True)
   except SystemExit:raise
   except Exception as exc:print(f"heartbeat failed: {exc}",file=sys.stderr,flush=True)
   next_hb=now+heartbeat_interval
  time.sleep(min(max(.25,min(next_rec,next_hb)-time.monotonic()),1.0))
if __name__=="__main__":run_forever()
