#!/usr/bin/env python3
"""Root-owned helper that applies/removes only validated Capivara instance runtimes."""
from __future__ import annotations
import grp, json, os, pwd, stat, subprocess, sys
from pathlib import Path
from typing import Any
INSTALL_ROOT=Path(os.environ.get("CAPIVARA_AGENT_ROOT","/opt/capivara-agent"));RUNTIME_DIR=INSTALL_ROOT/"runtime"
if str(RUNTIME_DIR) not in sys.path:sys.path.insert(0,str(RUNTIME_DIR))
from catalog_runtime_policy import materialize_network_properties,materialize_templates
from materializers import resolve_materializer
from runtime_spec import validate_runtime_spec
STATE_DIR=Path(os.environ.get("CAPIVARA_AGENT_STATE_DIR","/var/lib/capivara-agent"));CONFIG_PATH=Path(os.environ.get("CAPIVARA_AGENT_CONFIG","/etc/capivara-agent/agent.json"));REQUEST_ROOT=STATE_DIR/"privileged-materialization"
_DEFAULT_RUNTIME_USER="capivara-instance";_AGENT_GROUP="capivara-agent"
def _token(value:Any)->str:
 text=str(value or "").strip();allowed="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
 if not text or len(text)>191 or any(ch not in allowed for ch in text):raise ValueError("invalid instance_id")
 return text
def _write_result(path:Path,payload:dict[str,Any])->None:
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(f".{path.name}.{os.getpid()}.tmp");temp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8");os.chmod(temp,0o600)
 try:
  account=pwd.getpwnam("capivara-agent");os.chown(temp,account.pw_uid,account.pw_gid)
 except (KeyError,OSError):pass
 os.replace(temp,path)
def _run_admin(command:list[str])->None:
 completed=subprocess.run(command,capture_output=True,text=True,check=False,timeout=30)
 if completed.returncode!=0:raise RuntimeError((completed.stderr or completed.stdout or f"command failed: {' '.join(command)}")[:2000])
def _ensure_runtime_user(user:str)->None:
 try:group=grp.getgrnam(_AGENT_GROUP)
 except KeyError as exc:raise RuntimeError("capivara-agent group is unavailable") from exc
 try:account=pwd.getpwnam(user)
 except KeyError:
  if user!=_DEFAULT_RUNTIME_USER:raise RuntimeError(f"runtime user does not exist: {user}")
  _run_admin(["useradd","--system","--gid",_AGENT_GROUP,"--home-dir","/nonexistent","--no-create-home","--shell","/usr/sbin/nologin",user]);account=pwd.getpwnam(user)
 if user==_DEFAULT_RUNTIME_USER and account.pw_gid!=group.gr_gid:
  _run_admin(["usermod","-a","-G",_AGENT_GROUP,user])
def _grant_runtime_access(working_directory:str,user:str)->None:
 if user!=_DEFAULT_RUNTIME_USER:return
 try:group=grp.getgrnam(_AGENT_GROUP)
 except KeyError as exc:raise RuntimeError("capivara-agent group is unavailable") from exc
 state=STATE_DIR.resolve();game_data=(STATE_DIR/"game-data").resolve();working=Path(working_directory).resolve()
 try:relative=working.relative_to(game_data)
 except ValueError:return
 paths=[state,game_data];current=game_data
 for part in relative.parts:
  current=current/part
  if current.is_dir():paths.append(current)
 if state.is_dir():
  os.chown(state,-1,group.gr_gid);os.chmod(state,stat.S_IMODE(state.stat().st_mode)|stat.S_IXGRP)
 for path in paths[1:]:
  if not path.is_dir():continue
  os.chown(path,-1,group.gr_gid);os.chmod(path,stat.S_IMODE(path.stat().st_mode)|stat.S_IRGRP|stat.S_IXGRP)
def _ensure_runtime_identity(spec:dict[str,Any])->None:
 user=str(spec.get("user") or _DEFAULT_RUNTIME_USER);_ensure_runtime_user(user);_grant_runtime_access(str(spec["working_directory"]),user)
def run(instance_id:str)->dict[str,Any]:
 if os.geteuid()!=0:raise RuntimeError("privileged materializer helper must run as root")
 instance_id=_token(instance_id);request_path=REQUEST_ROOT/f"{instance_id}.request.json";result_path=REQUEST_ROOT/f"{instance_id}.result.json";request=json.loads(request_path.read_text(encoding="utf-8"))
 if not isinstance(request,dict) or request.get("kind")!="CapivaraPrivilegedMaterializationRequest":raise RuntimeError("invalid privileged materialization request")
 if str(request.get("instance_id") or "")!=instance_id:raise RuntimeError("privileged materialization instance_id mismatch")
 config=json.loads(CONFIG_PATH.read_text(encoding="utf-8"));local_agent_id=str(config.get("agent_id") or "").strip()
 if not local_agent_id:raise RuntimeError("local Agent identity is unavailable")
 if str(request.get("agent_id") or "")!=local_agent_id:raise PermissionError("privileged materialization request belongs to another Agent")
 spec=validate_runtime_spec(request.get("spec"),expected_agent_id=local_agent_id)
 if spec["instance_id"]!=instance_id:raise RuntimeError("runtime spec instance_id mismatch")
 action=str(request.get("action") or "").strip().lower();materializer=resolve_materializer(spec);templates=[]
 if action=="apply":
  _ensure_runtime_identity(spec);operation=materializer.apply(spec);templates=materialize_templates(spec);templates.extend(materialize_network_properties(spec))
 elif action=="remove":operation=materializer.remove(spec)
 else:raise RuntimeError("unsupported privileged materialization action")
 result={"status":"completed","action":action,"instance_id":instance_id,"agent_id":local_agent_id,"operation":operation,"templates":templates};_write_result(result_path,result);return result
def main()->int:
 if len(sys.argv)!=2:print("usage: materialize_instance.py INSTANCE_ID",file=sys.stderr);return 2
 instance_id=sys.argv[1];result_path=REQUEST_ROOT/f"{_token(instance_id)}.result.json"
 try:result=run(instance_id);print(json.dumps(result,sort_keys=True),flush=True);return 0
 except Exception as exc:_write_result(result_path,{"status":"failed","instance_id":instance_id,"error":str(exc)[:2000]});print(f"privileged materialization failed: {exc}",file=sys.stderr,flush=True);return 1
if __name__=="__main__":raise SystemExit(main())
