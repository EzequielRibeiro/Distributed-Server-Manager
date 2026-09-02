#!/usr/bin/env python3
"""Capivara Linux Agent runtime: enroll once, then heartbeat permanently."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parent
if str(RUNTIME_DIR) not in sys.path:
    sys.path.insert(0, str(RUNTIME_DIR))

from artifact_transfer_client import clear_result as clear_artifact_result, handle_command as handle_artifact_command, read_result as read_artifact_result
from backup_client import apply_backup_commands, backup_state
from broadcast_client import apply_broadcast_commands, broadcast_state
from capabilities import detect_capabilities
from configuration_client import apply_configuration_commands, configuration_state
from console_client import clear_result as clear_console_result
from console_client import console_state, handle_command as handle_console_command, read_result as read_console_result
from content_client import apply_content_commands, content_state
from doctor_client import clear_result as clear_doctor_result, handle_command as handle_doctor_command, read_result as read_doctor_result
from game_data_client import clear_game_data_result, read_game_data_result, stage_game_data_command
from instance_files_client import clear_result as clear_file_result
from instance_files_client import handle_command as handle_file_command, read_result as read_file_result
from instance_runtime import clear_result as clear_instance_result
from instance_runtime import handle_command as handle_instance_command
from instance_runtime import inventory as instance_inventory
from instance_runtime import read_result as read_instance_result
from instance_telemetry import collect_instance_telemetry
from network_inventory import collect_network_inventory
from provisioning_client import clear_provisioning_result, read_provisioning_result, stage_provisioning_command
from resource_profile_client import apply as apply_resource_profile
from resource_profile_client import clear_result as clear_resource_result, read_result as read_resource_result
from runtime_events import acknowledge_runtime_events, read_runtime_events
from runtime_health import health_inventory
from runtime_metrics import increment, snapshot as runtime_metrics_snapshot
from runtime_operations import recover_interrupted_operations
from runtime_reconciler import reconcile_all, reconciliation_inventory
from storage_pool_migration_client import clear_storage_pool_migration_result, read_storage_pool_migration_result, stage_storage_pool_migration
from uninstall_client import clear_result as clear_uninstall_result, handle_command as handle_uninstall_command, read_result as read_uninstall_result
from update_client import clear_update_result, read_update_result, stage_update_request

CONFIG_PATH = Path(os.environ.get("CAPIVARA_AGENT_CONFIG", "/etc/capivara-agent/agent.json"))
DEFAULT_HEARTBEAT_SECONDS = 30
DEFAULT_RECONCILE_SECONDS = 15
STATE_DIR = Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR", "/var/lib/capivara-agent"))
HOST_IDENTITY_PATH = Path(os.environ.get("CAPIVARA_AGENT_HOST_IDENTITY", str(STATE_DIR / "host-identity")))
AGENT_LOG = STATE_DIR / "agent-runtime.log"


def _log(message, error=False):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {'ERROR' if error else 'INFO'} {message}"
    print(message, file=sys.stderr if error else sys.stdout, flush=True)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if AGENT_LOG.exists() and AGENT_LOG.stat().st_size > 262144:
            AGENT_LOG.replace(AGENT_LOG.with_suffix(".log.1"))
        with AGENT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _recent_logs(limit=200):
    try:return AGENT_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:return []


def _load_config():return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def _write_config(config):
    temp=CONFIG_PATH.with_suffix(".tmp");temp.write_text(json.dumps(config,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.chmod(temp,0o600);temp.replace(CONFIG_PATH);os.chmod(CONFIG_PATH,0o600)


def _post(url,payload,headers=None):
    body=json.dumps(payload,separators=(",",":")).encode();request_headers={"Content-Type":"application/json","Accept":"application/json"};request_headers.update(headers or {});request=urllib.request.Request(url,data=body,headers=request_headers,method="POST")
    try:
        with urllib.request.urlopen(request,timeout=20) as response:return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail=exc.read().decode("utf-8",errors="replace");raise RuntimeError(f"Controller rejected request ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:raise RuntimeError(f"Controller unavailable: {exc.reason}") from exc


def _read_text(path):
    try:return Path(path).read_text(encoding="utf-8").strip().lower()
    except OSError:return ""


def _host_identity():
    """Return the canonical, non-secret identity for the physical/virtual host."""
    canonical=_read_text(HOST_IDENTITY_PATH)
    if canonical:return canonical
    machine_id=_read_text("/etc/machine-id");product_uuid=_read_text("/sys/class/dmi/id/product_uuid");macs=[]
    try:interfaces=Path("/sys/class/net").iterdir()
    except OSError:interfaces=()
    for interface in interfaces:
        if interface.name=="lo":continue
        value=_read_text(interface/"address")
        if value and value!="00:00:00:00:00:00":macs.append(value)
    hardware_identity=product_uuid or "|".join(sorted(set(macs)));material="\n".join(["capivara-host-v1",machine_id,hardware_identity]).encode("utf-8")
    return "sha256:"+hashlib.sha256(material).hexdigest()


def _memory_total_bytes():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):return int(line.split()[1])*1024
    except (OSError,ValueError,IndexError):pass
    return None


def _queue_depth():
    def count(path):
        try:return sum(1 for _ in Path(path).parent.glob(Path(path).name))
        except OSError:return 0
    state=STATE_DIR
    return {"instance_results":count(state/"instance-results"/"*.json"),"console_results":count(state/"console-results"/"*.json"),"file_results":count(state/"file-results"/"*.json"),"resource_results":count(state/"resource-results"/"*.json"),"artifact_results":count(state/"artifact-results"/"*.json"),"provisioning":count(state/"instance-provisioning"/"*.request.json"),"storage_pool_migrations":count(state/"storage-pool-migrations"/"*.request.json"),"game_data":count(state/"game-data-jobs"/"*.json"),"backup_results":count(state/"backup-results"/"*.json"),"broadcast_state":count(state/"broadcast-state"/"*.json"),"runtime_events":len(read_runtime_events(state,limit=1000))}


def _inventory(config):
    disk=shutil.disk_usage("/");version_path=Path(__file__).resolve().parents[1]/"VERSION"
    try:installed_version=version_path.read_text().strip()
    except OSError:installed_version=str(config.get("capivara_version","unknown"))
    payload={"agent_id":config["agent_id"],"hostname":socket.gethostname(),"os":platform.system().lower(),"architecture":platform.machine(),"capivara_version":installed_version,"address":config.get("advertise_address"),"fingerprint":config["fingerprint"],"host_identity":_host_identity(),"capabilities":detect_capabilities(),"cpu":{"logical_cores":os.cpu_count(),"machine":platform.machine()},"ram_total_bytes":_memory_total_bytes(),"storage":{"root_total_bytes":disk.total,"root_free_bytes":disk.free},"network":collect_network_inventory(),"instances":instance_inventory(config),"instance_reconciliation":reconciliation_inventory(config),"instance_runtime_health":health_inventory(config),"instance_telemetry":collect_instance_telemetry(config),"instance_console_state":console_state(config),"instance_runtime_metrics":runtime_metrics_snapshot(queue_depth=_queue_depth()),"runtime_events":read_runtime_events(STATE_DIR,limit=int(config.get("event_batch_size",200))),"configuration_state":configuration_state(),"content_state":content_state(),"backup_state":backup_state(),"broadcast_state":broadcast_state(),"heartbeat_interval_seconds":int(config.get("heartbeat_interval_seconds",DEFAULT_HEARTBEAT_SECONDS)),"degraded_after_seconds":int(config.get("degraded_after_seconds",60)),"offline_after_seconds":int(config.get("offline_after_seconds",120))}
    payload["agent_logs"]=_recent_logs()
    result_readers=(("update_result",read_update_result),("provisioning_result",read_provisioning_result),("storage_pool_migration_result",read_storage_pool_migration_result),("game_data_result",read_game_data_result),("instance_result",read_instance_result),("console_result",read_console_result),("file_result",read_file_result),("resource_result",read_resource_result),("artifact_result",read_artifact_result),("doctor_result",read_doctor_result),("uninstall_result",read_uninstall_result))
    for key,reader in result_readers:
        value=reader()
        if value:payload[key]=value
    return payload


def enroll(config):
    token=str(config.get("pairing_token","")).strip()
    if not token:raise RuntimeError("Agent has no permanent credential and no pairing token")
    base=str(config["controller_url"]).rstrip("/")
    result=_post(base+"/api/agent/enroll",{"pairing_token":token,"agent_id":config["agent_id"],"node_id":config["node_id"],"name":config.get("name") or socket.gethostname(),"fingerprint":config["fingerprint"],"hostname":socket.gethostname(),"os":platform.system().lower(),"architecture":platform.machine(),"capivara_version":config.get("capivara_version"),"address":config.get("advertise_address")})
    config.update({"controller_id":result["controller_id"],"credential_id":result["credential_id"],"credential_secret":result["credential_secret"],"credential_type":result.get("credential_type","opaque-v1")});config.pop("pairing_token",None);_write_config(config);return config


def heartbeat(config):
    base=str(config["controller_url"]).rstrip("/")
    result=_post(base+"/api/agent/heartbeat",_inventory(config),headers={"X-Capivara-Agent-Credential":str(config["credential_id"]),"X-Capivara-Agent-Secret":str(config["credential_secret"]),"X-Capivara-Agent-Fingerprint":str(config["fingerprint"])})
    ids=result.get("accepted_event_ids")
    if isinstance(ids,list):acknowledge_runtime_events(STATE_DIR,ids)
    commands=result.get("configuration_commands")
    if isinstance(commands,list):apply_configuration_commands([item for item in commands if isinstance(item,dict)])
    commands=result.get("content_commands")
    if isinstance(commands,list):apply_content_commands(config,[item for item in commands if isinstance(item,dict)])
    commands=result.get("backup_commands")
    if isinstance(commands,list):apply_backup_commands(config,[item for item in commands if isinstance(item,dict)])
    commands=result.get("broadcast_commands")
    if isinstance(commands,list):apply_broadcast_commands(config,[item for item in commands if isinstance(item,dict)])
    doctor_command=result.get("doctor_command")
    if isinstance(doctor_command,dict):
        doctor_report=handle_doctor_command(config,doctor_command);_log(f"doctor request={doctor_report.get('request_id')} status={doctor_report.get('status')}")
    doctor_state=result.get("doctor_state") if isinstance(result.get("doctor_state"),dict) else {}
    if str(doctor_state.get("status") or "").lower() in {"completed","failed"} and doctor_state.get("request_id"):clear_doctor_result(str(doctor_state["request_id"]))
    if result.get("update") and stage_update_request(dict(result["update"])):print(f"update staged version={result['update'].get('desired_version')} rollout={result['update'].get('rollout_id')}",flush=True)
    if result.get("update_state",{}).get("update_status")=="completed":clear_update_result()
    provisioning_command=result.get("provisioning_command")
    if isinstance(provisioning_command,dict) and stage_provisioning_command(provisioning_command,config_path=CONFIG_PATH):print(f"provisioning staged id={provisioning_command.get('provisioning_id')} instance={provisioning_command.get('instance_id')}",flush=True)
    provisioning_state=result.get("provisioning_state") if isinstance(result.get("provisioning_state"),dict) else {}
    if str(provisioning_state.get("status") or "").lower() in {"completed","failed"} and provisioning_state.get("provisioning_id"):clear_provisioning_result(str(provisioning_state["provisioning_id"]))
    migration_command=result.get("storage_pool_migration_command")
    if isinstance(migration_command,dict) and stage_storage_pool_migration(migration_command,config_path=CONFIG_PATH):print(f"storage-pool migration staged id={migration_command.get('migration_id')} instance={migration_command.get('instance_id')} target={migration_command.get('target_storage_pool_id')}",flush=True)
    migration_state=result.get("storage_pool_migration_state") if isinstance(result.get("storage_pool_migration_state"),dict) else {}
    if str(migration_state.get("status") or "").lower() in {"completed","failed"} and migration_state.get("migration_id"):clear_storage_pool_migration_result(str(migration_state["migration_id"]))
    game_command=result.get("game_data_command")
    if isinstance(game_command,dict) and stage_game_data_command(game_command):print(f"game-data staged job={game_command.get('job_id')} environment={game_command.get('environment_id')}",flush=True)
    game_state=result.get("game_data_state") if isinstance(result.get("game_data_state"),dict) else {}
    if str(game_state.get("status") or "").lower() in {"completed","failed"} and game_state.get("job_id"):clear_game_data_result(str(game_state["job_id"]))
    command_contracts=(("instance_command","instance_state",handle_instance_command,clear_instance_result,"command_id","instance"),("console_command","console_state",handle_console_command,clear_console_result,"command_id","console"),("file_command","file_state",handle_file_command,clear_file_result,"command_id","file"),("resource_command","resource_state",apply_resource_profile,clear_resource_result,"command_id","resource"),("artifact_command","artifact_state",handle_artifact_command,clear_artifact_result,"transfer_id","artifact"))
    for command_key,state_key,handler,clear,id_key,label in command_contracts:
        command=result.get(command_key)
        if isinstance(command,dict):
            report=handler(config,command);print(f"{label} command instance={report.get('instance_id')} status={report.get('status')}",flush=True)
        state=result.get(state_key) if isinstance(result.get(state_key),dict) else {}
        if str(state.get("status") or "").lower() in {"completed","failed"} and state.get(id_key):clear(str(state[id_key]))
    uninstall_command=result.get("uninstall_command")
    if isinstance(uninstall_command,dict):
        report=handle_uninstall_command(config,uninstall_command,host_identity=_host_identity());_log(f"uninstall request={report.get('request_id')} phase={uninstall_command.get('phase')} status={report.get('status')}")
    uninstall_state=result.get("uninstall_state") if isinstance(result.get("uninstall_state"),dict) else {}
    if str(uninstall_state.get("status") or "").lower() in {"completed","failed","cancelled"} and uninstall_state.get("request_id"):clear_uninstall_result(str(uninstall_state["request_id"]))
    return result


def run_forever():
    config=_load_config()
    if not config.get("credential_id") or not config.get("credential_secret"):config=enroll(config)
    interrupted=recover_interrupted_operations(config)
    if interrupted:increment("operations_interrupted",len(interrupted))
    heartbeat_interval=max(10,int(config.get("heartbeat_interval_seconds",DEFAULT_HEARTBEAT_SECONDS)));reconcile_interval=max(5,int(config.get("reconcile_interval_seconds",DEFAULT_RECONCILE_SECONDS)));next_heartbeat=next_reconcile=0.0
    while True:
        now=time.monotonic()
        if now>=next_reconcile:
            try:reconcile_all(config)
            except Exception as exc:_log(f"reconcile loop failed: {exc}",True)
            next_reconcile=now+reconcile_interval
        if now>=next_heartbeat:
            try:
                result=heartbeat(config);_log(f"heartbeat ok agent={result.get('agent_id')} health={result.get('health_status')} status={result.get('status')}")
            except Exception as exc:_log(f"heartbeat failed: {exc}",True)
            next_heartbeat=now+heartbeat_interval
        time.sleep(min(max(0.25,min(next_reconcile,next_heartbeat)-time.monotonic()),1.0))


if __name__=="__main__":run_forever()
