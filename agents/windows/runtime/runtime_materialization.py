"""Game-agnostic runtime materialization and reconciliation for Windows Agents."""
from __future__ import annotations
import shutil
from pathlib import Path
from typing import Any
import instance_runtime
import managed_firewall
from catalog_runtime_policy import materialize_network_properties
from server_settings_runtime import materialize_server_settings
from server_settings_surface import materialize_dynamic_values
from minecraft_rcon_secret import materialize_password as materialize_minecraft_rcon_password
from adapters import resolve_adapter
from content_activation_projection import activation_snapshot
from content_activation_runtime import materialize_content_activation,project_runtime_spec
from runtime_events import emit_runtime_event
from runtime_spec import validate_runtime_spec
def _events():return Path(instance_runtime.STATE_DIR)
def _project(spec):
 iid=str(spec.get("instance_id") or "").strip();return project_runtime_spec(spec,activation_snapshot(iid)) if iid else dict(spec)
def _within(root:Path,value:str,label:str)->Path:
 root=root.resolve(strict=False);path=Path(value).resolve(strict=False)
 try:path.relative_to(root)
 except ValueError as exc:raise RuntimeError(f"{label} escapes its allowed root") from exc
 return path
def _is_link(path:Path)->bool:
 try:
  if path.is_symlink():return True
  checker=getattr(path,"is_junction",None);return bool(checker and checker())
 except OSError:return True
def _reject_links(root:Path,label:str)->None:
 if _is_link(root):raise RuntimeError(f"{label} root cannot be a link or junction")
 for path in root.rglob("*"):
  if _is_link(path):raise RuntimeError(f"{label} refuses link or junction: {path.relative_to(root)}")
def _same_regular_file(source:Path,target:Path)->bool:
 if not source.is_file() or not target.is_file():return False
 if source.stat().st_size!=target.stat().st_size:return False
 with source.open("rb") as left,target.open("rb") as right:
  while True:
   a=left.read(1024*1024);b=right.read(1024*1024)
   if a!=b:return False
   if not a:return True

def _overlay_seed_directory(source:Path,target:Path)->None:
 _reject_links(source,"directory seed");_reject_links(target,"directory seed target")
 for current in source.rglob("*"):
  relative=current.relative_to(source);destination=target/relative
  if current.is_dir():
   if destination.exists() and (not destination.is_dir() or _is_link(destination)):raise RuntimeError(f"seed overlay target type mismatch: {destination}")
   destination.mkdir(parents=True,exist_ok=True);continue
  if not current.is_file():raise RuntimeError(f"seed overlay source contains unsupported entry: {current}")
  destination.parent.mkdir(parents=True,exist_ok=True)
  if destination.exists():
   if not destination.is_file() or _is_link(destination):raise RuntimeError(f"seed overlay target type mismatch: {destination}")
   if _same_regular_file(current,destination):continue
  temp=destination.with_name(f".{destination.name}.seed-overlay.tmp")
  try:shutil.copy2(current,temp);temp.replace(destination)
  finally:
   try:temp.unlink()
   except FileNotFoundError:pass

def _seed_directory(source:Path,target:Path,*,overlay:bool=False)->None:
 if not source.is_dir():raise RuntimeError(f"seed directory source is unavailable: {source}")
 _reject_links(source,"directory seed")
 if target.exists():
  if not target.is_dir() or _is_link(target):raise RuntimeError(f"seed directory target is not a private directory: {target}")
  if overlay:_overlay_seed_directory(source,target)
  return
 target.parent.mkdir(parents=True,exist_ok=True);staging=target.with_name(f".{target.name}.seed.tmp")
 if staging.exists():shutil.rmtree(staging,ignore_errors=True)
 try:
  shutil.copytree(source,staging,copy_function=shutil.copy2,symlinks=False);_reject_links(staging,"directory seed")
  try:staging.replace(target)
  except OSError:
   if target.is_dir() and not _is_link(target):
    shutil.rmtree(staging,ignore_errors=True)
    if overlay:_overlay_seed_directory(source,target)
    return
   raise
 except Exception:
  if staging.exists():shutil.rmtree(staging,ignore_errors=True)
  raise
def _prepare_private_state(spec:dict[str,Any])->None:
 raw_root=spec.get("instance_state_root");has_private=bool(spec.get("writable_directories") or spec.get("seed_files") or spec.get("seed_directories"))
 if not raw_root:
  if has_private:raise RuntimeError("private runtime state requires instance_state_root")
  return
 state_root=Path(str(raw_root)).resolve(strict=False);state_root.mkdir(parents=True,exist_ok=True);working_root=Path(str(spec["working_directory"])).resolve(strict=False);source_root=Path(str(spec.get("seed_source_root") or working_root)).resolve(strict=False)
 if spec.get("seed_source_root"):_reject_links(source_root,"seed source")
 for item in spec.get("writable_directories",[]):_within(state_root,str(item),"writable directory").mkdir(parents=True,exist_ok=True)
 for item in spec.get("seed_files",[]):
  source=_within(source_root,str(item["source"]),"seed source");target=_within(state_root,str(item["target"]),"seed target")
  if not source.is_file() or _is_link(source):raise RuntimeError(f"seed source is unavailable or unsafe: {source}")
  target.parent.mkdir(parents=True,exist_ok=True)
  if not target.exists():shutil.copy2(source,target)
  elif not target.is_file() or _is_link(target):raise RuntimeError(f"seed target is not a private file: {target}")
 for item in spec.get("seed_directories",[]):source=_within(source_root,str(item["source"]),"seed directory source");target=_within(state_root,str(item["target"]),"seed directory target");_seed_directory(source,target,overlay=bool(item.get("overlay",False)))
def _validate_materialization(spec:dict[str,Any])->dict[str,Any]:
 if spec["adapter"]=="windows-process":
  exe=Path(spec["executable"]).resolve(strict=False);cwd=Path(spec["working_directory"]).resolve(strict=False);scope=spec.get("executable_scope") or "working-directory"
  if not cwd.is_dir():raise RuntimeError("runtime working directory does not exist")
  if not exe.is_file():raise RuntimeError("runtime executable does not exist")
  if scope=="working-directory":_within(cwd,str(exe),"runtime executable")
  elif scope=="provider-content":root=Path(str(spec.get("seed_source_root") or "")).resolve(strict=False);_within(root,str(exe),"provider executable");_reject_links(root,"provider executable")
  elif scope=="system-java":
   java=shutil.which("java.exe") or shutil.which("java")
   if not java or Path(java).resolve(strict=False)!=exe:raise RuntimeError("runtime Java executable is not the trusted system Java")
  else:raise RuntimeError("unsupported runtime executable scope")
  return {"materializer":"windows-process","exists":True,"owned":True,"matches":True,"executable":str(exe),"executable_scope":scope}
 state=resolve_adapter(spec).status(spec)
 if not state.get("available"):raise RuntimeError("Windows service runtime is unavailable")
 return {"materializer":"windows-service","exists":True,"owned":True,"matches":True,"service":state.get("service")}
def materialize(config:dict[str,Any],spec:dict[str,Any])->dict[str,Any]:
 agent_id=str(config.get("agent_id") or "").strip();projected=_project(spec);normalized=validate_runtime_spec(projected,expected_agent_id=agent_id);emit_runtime_event(_events(),"INSTANCE_RUNTIME_MATERIALIZING",agent_id=agent_id,instance_id=normalized["instance_id"])
 try:
  _prepare_private_state(normalized);content_files=materialize_content_activation(normalized);operation=_validate_materialization(normalized);properties=materialize_network_properties(normalized);environment_id=str(normalized.get("environment_id") or "").lower();game_id=str(normalized.get("game_id") or "").lower();materialize_minecraft_rcon_password(normalized) if game_id=="minecraft" and environment_id.startswith("minecraft.java.") else None;server_settings=materialize_server_settings(normalized);server_settings.extend(materialize_dynamic_values(normalized));record=instance_runtime.register_instance({**normalized,"observed_state":"unknown","materialized":True});event=emit_runtime_event(_events(),"INSTANCE_RUNTIME_READY",agent_id=agent_id,instance_id=normalized["instance_id"],data={"adapter":normalized["adapter"],"changed":True,"content_files":content_files});return {"spec":normalized,"instance":record,"operation":{"action":"materialize","changed":True,"state":operation,"network_properties":properties,"server_settings":server_settings,"content_files":content_files},"event":event}
 except Exception as exc:emit_runtime_event(_events(),"INSTANCE_RUNTIME_FAILED",agent_id=agent_id,instance_id=normalized["instance_id"],data={"phase":"materialize","error":str(exc)[:2000]});raise
def reconcile(config:dict[str,Any],instance_id:str)->dict[str,Any]:
 record=instance_runtime._owned(config,instance_id);projected=_project(record)
 if projected!=record:record=instance_runtime.register_instance(projected)
 normalized=validate_runtime_spec(record,expected_agent_id=str(config.get("agent_id") or ""));_prepare_private_state(normalized);content_files=materialize_content_activation(normalized);_validate_materialization(normalized);materialize_network_properties(normalized);environment_id=str(normalized.get("environment_id") or "").lower();game_id=str(normalized.get("game_id") or "").lower();materialize_minecraft_rcon_password(normalized) if game_id=="minecraft" and environment_id.startswith("minecraft.java.") else None;materialize_server_settings(normalized);materialize_dynamic_values(normalized);firewall=managed_firewall.reconcile(normalized);adapter=resolve_adapter(normalized);before=adapter.status(normalized);desired=normalized["desired_state"];running=bool(before.get("running") or before.get("active_state")=="active");operation=None
 if desired=="running" and not running:operation=adapter.start(normalized)
 elif desired=="stopped" and running:operation=adapter.stop(normalized)
 after=adapter.status(normalized);observed=instance_runtime._observed_state(after,record.get("observed_state"));updated=instance_runtime.register_instance({**record,"observed_state":observed});event=emit_runtime_event(_events(),"INSTANCE_RUNTIME_RECONCILED",agent_id=normalized["agent_id"],instance_id=normalized["instance_id"],data={"desired_state":desired,"observed_state":observed,"changed":True,"content_files":content_files}) if operation else None;return {"instance_id":normalized["instance_id"],"desired_state":desired,"observed_state":observed,"changed":operation is not None,"operation":operation,"firewall":firewall,"content_files":content_files,"instance":updated,"event":event}
def remove(config:dict[str,Any],instance_id:str)->dict[str,Any]:
 record=instance_runtime._owned(config,instance_id);normalized=validate_runtime_spec(record,expected_agent_id=str(config.get("agent_id") or ""));adapter=resolve_adapter(normalized);state=adapter.status(normalized);stopped=None
 if bool(state.get("running") or state.get("active_state")=="active"):stopped=adapter.stop(normalized)
 firewall=managed_firewall.remove(normalized)
 removed=[]
 raw_state=str(normalized.get("instance_state_root") or "").strip()
 if raw_state:
  state_root=Path(raw_state).resolve(strict=False)
  if state_root.exists():
   if _is_link(state_root) or not state_root.is_dir():raise RuntimeError("instance private state is not a safe directory")
   _reject_links(state_root,"instance private state");shutil.rmtree(state_root);removed.append(str(state_root))
 managed=(Path(instance_runtime.STATE_DIR)/"managed-content"/instance_id).resolve(strict=False)
 if managed.exists():
  if _is_link(managed) or not managed.is_dir():raise RuntimeError("instance managed content state is not a safe directory")
  _reject_links(managed,"instance managed content state");shutil.rmtree(managed);removed.append(str(managed))
 try:instance_runtime._instance_path(instance_id).unlink()
 except FileNotFoundError:pass
 cleanup={"changed":bool(removed),"removed_paths":removed,"shared_game_data_preserved":True}
 event=emit_runtime_event(_events(),"INSTANCE_RUNTIME_REMOVED",agent_id=normalized["agent_id"],instance_id=normalized["instance_id"],data={"changed":True});return {"instance_id":normalized["instance_id"],"stop":stopped,"firewall":firewall,"operation":{"action":"remove","changed":True,"private_state_cleanup":cleanup},"event":event}
__all__=["materialize","reconcile","remove"]
