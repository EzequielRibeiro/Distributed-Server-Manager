#!/usr/bin/env python3
"""Materialize Capivara-owned systemd units from validated local runtime specs."""
from __future__ import annotations
import os,subprocess
from pathlib import Path
from typing import Any,Callable
from adapters.systemd import unit_for_instance
from .base import InstanceRuntimeMaterializer,MaterializerError
Runner=Callable[[list[str],int],tuple[int,str,str]];_GENERATED_BY="capivara-instance-runtime-v1";_RUNTIME_ACCOUNT_HOME="/var/lib/capivara-agent/runtime-home"
def _default_runner(command,timeout):
 try:cp=subprocess.run(command,capture_output=True,text=True,check=False,timeout=timeout)
 except (OSError,subprocess.SubprocessError) as exc:return 127,"",str(exc)
 return cp.returncode,cp.stdout.strip(),cp.stderr.strip()
def _quote(value):return '"'+value.replace("\\","\\\\").replace('"','\\"')+'"'
def _working_directory(value):
 path=str(value or "").strip()
 if not path.startswith("/") or any(c in path for c in ("\x00","\n","\r")):raise MaterializerError("invalid systemd WorkingDirectory")
 return path
def _bind_path(source,target):
 source_path=str(source or "").strip();target_path=str(target or "").strip()
 for label,path in (("source",source_path),("target",target_path)):
  if not path.startswith("/") or any(c in path for c in (":"," ","\t","\x00","\n","\r")):raise MaterializerError(f"systemd BindPaths {label} contains unsupported characters")
 return f"{source_path}:{target_path}"
def _instance_state(instance_id):
 token=str(instance_id or "").strip()
 if not token or any(c in token for c in ("/","\\","\x00","\n","\r")):raise MaterializerError("invalid systemd instance state directory")
 relative=f"capivara-instances/{token}";return relative,f"/var/lib/{relative}"
def _unit_dir():return Path(os.environ.get("CAPIVARA_INSTANCE_SYSTEMD_DIR","/etc/systemd/system"))
def unit_path_for_spec(spec):return _unit_dir()/unit_for_instance(spec)
def _resource_lines(spec):
 lines=[]
 memory=spec.get("memory_limit_bytes")
 if memory is not None:
  try:memory=int(memory)
  except (TypeError,ValueError) as exc:raise MaterializerError("invalid memory_limit_bytes") from exc
  if memory<64*1024*1024:raise MaterializerError("memory limit is below safe minimum")
  lines.append(f"MemoryMax={memory}")
 cpu=spec.get("cpu_limit_cores")
 if cpu is not None:
  try:cpu=float(cpu)
  except (TypeError,ValueError) as exc:raise MaterializerError("invalid cpu_limit_cores") from exc
  if cpu<=0:raise MaterializerError("CPU limit must be positive")
  lines.append(f"CPUQuota={cpu*100:.3f}%")
 pids=spec.get("pids_limit")
 if pids is not None:
  try:pids=int(pids)
  except (TypeError,ValueError) as exc:raise MaterializerError("invalid pids_limit") from exc
  if pids<16:raise MaterializerError("TasksMax is below safe minimum")
  lines.append(f"TasksMax={pids}")
 return lines
def render_unit(spec):
 instance_id=str(spec["instance_id"]);agent_id=str(spec["agent_id"]);runtime_id=str(spec["runtime_id"]);state_directory,private_state_path=_instance_state(instance_id);argv=[str(spec["executable"]),*[str(x) for x in spec.get("arguments",[])]]
 lines=["[Unit]",f"Description=Capivara instance {instance_id}","After=network-online.target","Wants=network-online.target",f"X-Capivara-GeneratedBy={_GENERATED_BY}",f"X-Capivara-Instance={instance_id}",f"X-Capivara-Agent={agent_id}",f"X-Capivara-Runtime={runtime_id}","","[Service]","Type=simple",f"User={spec['user']}",f"StateDirectory={state_directory}","StateDirectoryMode=0700",f"BindPaths={_bind_path(private_state_path,_RUNTIME_ACCOUNT_HOME)}"]
 for binding in spec.get("bind_paths",[]):lines.append(f"BindPaths={_bind_path(binding['source'],binding['target'])}")
 lines.extend([f"WorkingDirectory={_working_directory(spec['working_directory'])}",f"Environment={_quote(f'HOME={_RUNTIME_ACCOUNT_HOME}')}",f"Environment={_quote(f'XDG_DATA_HOME={_RUNTIME_ACCOUNT_HOME}/.local/share')}",f"Environment={_quote(f'XDG_CACHE_HOME={_RUNTIME_ACCOUNT_HOME}/.cache')}",f"Environment={_quote(f'XDG_CONFIG_HOME={_RUNTIME_ACCOUNT_HOME}/.config')}"])
 lines.extend(_resource_lines(spec))
 for item in spec.get("pre_start",[]):
  pre_argv=[str(item["executable"]),*[str(x) for x in item.get("arguments",[])]]
  lines.append("ExecStartPre="+" ".join(_quote(x) for x in pre_argv))
 lines.extend(["ExecStart="+" ".join(_quote(x) for x in argv),"Restart=no","KillSignal=SIGTERM","TimeoutStopSec=60"])
 for key,value in sorted(dict(spec.get("environment",{})).items()):lines.append(f"Environment={_quote(f'{key}={value}')}")
 lines.extend(["","[Install]","WantedBy=multi-user.target",""]);return "\n".join(lines)
def _owned_content(content,spec):
 required={f"X-Capivara-GeneratedBy={_GENERATED_BY}",f"X-Capivara-Instance={spec['instance_id']}",f"X-Capivara-Agent={spec['agent_id']}"};lines={line.strip() for line in content.splitlines()};return required.issubset(lines)
class SystemdMaterializer(InstanceRuntimeMaterializer):
 name="systemd"
 def __init__(self,runner=None):self.runner=runner or _default_runner
 def inspect(self,spec):
  path=unit_path_for_spec(spec)
  try:content=path.read_text(encoding="utf-8")
  except FileNotFoundError:return {"materializer":self.name,"unit":path.name,"path":str(path),"exists":False,"owned":False,"matches":False}
  except OSError as exc:raise MaterializerError(str(exc)) from exc
  expected=render_unit(spec);return {"materializer":self.name,"unit":path.name,"path":str(path),"exists":True,"owned":_owned_content(content,spec),"matches":content==expected}
 def _reload(self):
  code,stdout,stderr=self.runner(["systemctl","daemon-reload"],30)
  if code!=0:raise MaterializerError((stderr or stdout or "systemctl daemon-reload failed")[:2000])
 def apply(self,spec):
  path=unit_path_for_spec(spec);before=self.inspect(spec)
  if before["exists"] and not before["owned"]:raise MaterializerError(f"refusing to replace non-Capivara unit: {path.name}")
  content=render_unit(spec)
  if before["matches"]:return {"action":"materialize","changed":False,"idempotent":True,"state":before}
  path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(f".{path.name}.{os.getpid()}.tmp")
  try:temp.write_text(content,encoding="utf-8");os.chmod(temp,0o644);os.replace(temp,path);self._reload()
  except Exception:
   try:temp.unlink()
   except FileNotFoundError:pass
   raise
  after=self.inspect(spec)
  if not after["owned"] or not after["matches"]:raise MaterializerError("materialized unit failed ownership validation")
  return {"action":"materialize","changed":True,"idempotent":False,"state":after}
 def remove(self,spec):
  path=unit_path_for_spec(spec);before=self.inspect(spec)
  if not before["exists"]:return {"action":"remove","changed":False,"idempotent":True,"state":before}
  if not before["owned"]:raise MaterializerError(f"refusing to remove non-Capivara unit: {path.name}")
  try:path.unlink()
  except OSError as exc:raise MaterializerError(str(exc)) from exc
  self._reload();return {"action":"remove","changed":True,"idempotent":False,"state":self.inspect(spec)}
__all__=["SystemdMaterializer","render_unit","unit_path_for_spec"]
