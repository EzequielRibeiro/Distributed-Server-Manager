#!/usr/bin/env python3
"""Service layer for Customer Instance Workspace v2."""
from __future__ import annotations
import json
from pathlib import Path, PurePosixPath
from typing import Any
from alert_repository import AlertSession,dialect_for_backend
from agent_instance_provisioning_repository import AgentInstanceProvisioningRepository
from agent_instance_runtime_health_repository import AgentInstanceRuntimeHealthRepository
from agent_runtime_repository import AgentRuntimeRepository
from instance_provisioning_projection import dashboard_provision_state
from backup_repository import BackupRepository
from catalog_resource_profiles_http import catalog_resource_profiles
from instance_file_repository import InstanceFileRepository
from configuration_repository import ConfigurationRepository
from instance_workspace_policy import INSTANCE_PERMISSIONS,content_ui_sections,effective_content_policy,enforce_managed_content_mutation,require_permission,validate_server_settings,validate_startup_values
from instance_workspace_repository import InstanceWorkspaceRepository
from runtime_instance_projection import project_runtime_state
from runtime_workspace_catalog import allowed_runtimes,contract_entitlements,runtime_workspace_capabilities

def _json(value,default):
 if isinstance(value,(dict,list)):return value
 try:result=json.loads(str(value))
 except (TypeError,ValueError):return default
 return result if isinstance(result,type(default)) else default

class CustomerInstanceWorkspaceService:
 def __init__(self,backend,root:Path):self.backend=backend;self.root=Path(root);self.repo=InstanceWorkspaceRepository(backend);self.provisioning=AgentInstanceProvisioningRepository(backend);self.files=InstanceFileRepository(backend);self.backups=BackupRepository(backend);self.runtime_health=AgentInstanceRuntimeHealthRepository(backend);self.agent_runtime=AgentRuntimeRepository(backend);self.dialect=dialect_for_backend(backend)
 def _session(self,c):return AlertSession(self.backend,c)
 def permissions(self,user:dict[str,Any],instance_id:str)->set[str]:
  role=str((user or {}).get("role") or "").lower()
  if role in {"admin","controller"}:return set(INSTANCE_PERMISSIONS)
  if role!="customer":return set()
  return self.repo.effective_permissions_for(str(user.get("username") or ""),instance_id)
 def require(self,user,instance_id,permission):require_permission(self.permissions(user,instance_id),permission);return self.repo.instance_context(instance_id)
 def _ports(self,instance_id):
  ph=self.dialect.placeholder
  with self.backend.connect() as c:
   s=self._session(c)
   try:rows=s.execute(f"SELECT name,protocol,port,bind_address FROM instance_ports WHERE instance_id={ph} ORDER BY port,name",(instance_id,)).fetchall()
   finally:s.close()
  return [dict(x) for x in rows]
 def _location(self,agent_id):
  ph=self.dialect.placeholder
  with self.backend.connect() as c:
   s=self._session(c)
   try:row=s.execute("SELECT a.name AS agent_name,a.metadata_json,l.public_host,l.latitude,l.longitude,d.id AS datacenter_id,d.name AS datacenter_name,d.city,d.country_code,r.id AS region_id,r.name AS region_name,r.country_code AS region_country_code FROM agents a LEFT JOIN agent_locations l ON l.agent_id=a.id LEFT JOIN datacenters d ON d.id=l.datacenter_id LEFT JOIN regions r ON r.id=d.region_id "+f"WHERE a.id={ph}",(agent_id,)).fetchone()
   finally:s.close()
  if row is None:return {}
  value=dict(row);value["agent_metadata"]=_json(value.pop("metadata_json",None),{});return value
 def _runtime_projection(self,context):
  agent_id=str(context.get("agent_id") or "").strip();instance_id=str(context.get("id") or context.get("instance_id") or "").strip();observation=None;agent_health="unknown"
  if agent_id:
   try:
    values=self.runtime_health.list_for_agent(agent_id);observation=next((dict(item) for item in values if str(item.get("instance_id") or "")==instance_id),None)
   except Exception:observation=None
   try:agent_health=str(self.agent_runtime.snapshot(agent_id).get("health_status") or "unknown")
   except Exception:agent_health="unknown"
  return project_runtime_state(record=context,runtime_health=observation,agent_health=agent_health,fallback_state=context.get("status") or "unknown",fallback_health="unknown")
 def _contract_policy(self,context,policy):
  metadata=context.get("contract_metadata") or {};runtime_id=str(context.get("runtime_id") or "");capabilities=runtime_workspace_capabilities(self.root,str(context.get("game_id") or ""),runtime_id) if runtime_id else {};entitlements=contract_entitlements(metadata)
  for key,column in (("mods","mods_allowed"),("plugins","plugins_allowed"),("workshop","workshop_allowed"),("external_upload","external_upload_allowed"),("custom_runtime","custom_runtime_allowed")):
   if column in policy:entitlements[key]=bool(entitlements.get(key)) and bool(policy.get(column))
  if "mods_allowed" in policy and not bool(policy.get("mods_allowed")):
   entitlements["modpacks"]=False;entitlements["datapacks"]=False
  return capabilities,effective_content_policy(entitlements,capabilities)
 def _resolved_resource_policy(self,context,policy):
  result=dict(policy or {});metadata=context.get("contract_metadata") if isinstance(context.get("contract_metadata"),dict) else {};instance_metadata=context.get("instance_metadata") if isinstance(context.get("instance_metadata"),dict) else {};resources=metadata.get("resources") if isinstance(metadata.get("resources"),dict) else {};effective=metadata.get("effective_resource_policy") if isinstance(metadata.get("effective_resource_policy"),dict) else {}
  profile_id=str(result.get("resource_profile_id") or metadata.get("resource_profile_id") or metadata.get("profile_id") or instance_metadata.get("resource_profile_id") or "").strip().lower()
  if profile_id and not result.get("resource_profile_id"):result["resource_profile_id"]=profile_id
  def number(source,key,kind=int):
   value=source.get(key) if isinstance(source,dict) else None
   if value is None:return None
   try:return kind(value)
   except (TypeError,ValueError):return None
  if result.get("cpu_limit_cores") is None:
   result["cpu_limit_cores"]=number(effective,"cpu_cores",float) if number(effective,"cpu_cores",float) is not None else number(resources,"cpu_cores",float)
  for target,byte_key,mb_key in (("memory_limit_bytes","memory_bytes","memory_mb"),("storage_limit_bytes","storage_bytes","storage_mb")):
   if result.get(target) is not None:continue
   value=number(effective,byte_key)
   if value is None:value=number(resources,byte_key)
   if value is None:
    mb=number(resources,mb_key)
    value=mb*1024*1024 if mb is not None else None
   result[target]=value
  if result.get("player_limit") is None:
   result["player_limit"]=number(effective,"player_limit")
   if result.get("player_limit") is None:result["player_limit"]=number(resources,"player_limit") if resources.get("player_limit") is not None else number(resources,"slots")
  if not profile_id or all(result.get(k) is not None for k in ("cpu_limit_cores","memory_limit_bytes","storage_limit_bytes","player_limit")):return result
  try:catalog=catalog_resource_profiles(self.root,str(context.get("game_id") or ""))
  except (OSError,ValueError,json.JSONDecodeError):return result
  profile=next((item for item in catalog.get("profiles") or [] if isinstance(item,dict) and str(item.get("id") or "").strip().lower()==profile_id),None)
  if not isinstance(profile,dict):return result
  if result.get("cpu_limit_cores") is None:result["cpu_limit_cores"]=number(profile,"cpu_cores",float)
  if result.get("memory_limit_bytes") is None:
   mb=number(profile,"memory_mb");result["memory_limit_bytes"]=mb*1024*1024 if mb is not None else None
  if result.get("storage_limit_bytes") is None:
   mb=number(profile,"storage_mb");result["storage_limit_bytes"]=mb*1024*1024 if mb is not None else None
  if result.get("player_limit") is None:result["player_limit"]=number(profile,"player_limit")
  return result
 def overview(self,user,instance_id):
  context=self.require(user,instance_id,"instance.view");runtime=self._runtime_projection(context);policy=self._resolved_resource_policy(context,self.repo.workspace_policy(instance_id));permissions=self.permissions(user,instance_id);telemetry=(self.repo.telemetry(instance_id,1) or [{}])[-1];location=self._location(str(context.get("agent_id") or ""));capabilities,content=self._contract_policy(context,policy);agent_meta=location.get("agent_metadata") if isinstance(location.get("agent_metadata"),dict) else {};latest={}
  for item in agent_meta.get("instance_telemetry") or []:
   if isinstance(item,dict) and str(item.get("instance_id"))==instance_id:latest=item
  telemetry={**latest,**telemetry};storage_limit=policy.get("storage_limit_bytes");used=telemetry.get("storage_used_bytes");storage_pct=(float(used)/float(storage_limit)*100) if used is not None and storage_limit else None;metadata=context.get("instance_metadata") if isinstance(context.get("instance_metadata"),dict) else {};legacy_provision=metadata.get("provision") if isinstance(metadata,dict) else None;distributed_provision=self.provisioning.latest_for_instance(instance_id);provision=dashboard_provision_state(distributed_provision) if distributed_provision is not None else legacy_provision
  if isinstance(provision,dict) and str(provision.get("stage") or "").lower()=="completed" and int(provision.get("progress") or 0)>=100:provision=None
  instance={k:context.get(k) for k in ("id","name","game_id","edition","runtime_id","variant","game_version","status","agent_id","contract_id")};instance["persisted_status"]=context.get("status");instance["status"]=runtime.get("state") or "unknown"
  return {"instance":instance,"runtime":runtime,"permissions":sorted(permissions),"policy":policy,"content_policy":content.as_dict(),"content_sections":content_ui_sections(content),"runtime_capabilities":capabilities,"ports":self._ports(instance_id),"location":{k:location.get(k) for k in ("public_host","datacenter_id","datacenter_name","city","country_code","region_id","region_name","region_country_code","agent_name")},"telemetry":telemetry,"storage":{"used_bytes":used,"limit_bytes":storage_limit,"percent":storage_pct},"provision":provision,"console":{"read":"console.read" in permissions,"execute":"console.execute" in permissions,"supported":bool((capabilities.get("console") or {}).get("supported"))},"upgrade":{"allowed":"contract.upgrade" in permissions,"current_profile_id":policy.get("resource_profile_id")}}
 def telemetry(self,user,instance_id,limit=240):self.require(user,instance_id,"instance.view");return self.repo.telemetry(instance_id,limit)
 def console_output(self,user,instance_id,limit=300):self.require(user,instance_id,"console.read");return self.repo.console_output(instance_id,limit)
 def console_command_status(self,user,instance_id,command_id):
  self.require(user,instance_id,"console.read");item=self.repo.console_command(str(command_id or "").strip())
  if str(item.get("instance_id") or "")!=str(instance_id):raise PermissionError("console command belongs to another instance")
  result=item.get("result") if isinstance(item.get("result"),dict) else {}
  return {"command_id":item.get("command_id"),"instance_id":item.get("instance_id"),"status":item.get("status"),"last_error":item.get("last_error"),"completed_at":item.get("completed_at"),"result":result}
 def agent_console_output(self,user,instance_id,limit=300):
  context=self.require(user,instance_id,"console.read");agent_id=str(context.get("agent_id") or "").strip();limit=max(1,min(int(limit),1000));location=self._location(agent_id) if agent_id else {};metadata=location.get("agent_metadata") if isinstance(location.get("agent_metadata"),dict) else {};state={}
  for item in metadata.get("instance_console_state") or []:
   if isinstance(item,dict) and str(item.get("instance_id") or "")==str(instance_id):state=item;break
  output=state.get("output") if isinstance(state.get("output"),list) else [];runtime={}
  if agent_id:
   try:runtime=self.agent_runtime.snapshot(agent_id,refresh_health=False)
   except Exception:runtime={}
  return {"lines":[str(line).replace("\x00","")[:2000] for line in output[-limit:]],"transport":state.get("transport"),"supported":bool(state.get("supported")),"agent_health":str(runtime.get("health_status") or "unknown"),"last_seen":runtime.get("last_seen")}
 def send_console(self,user,instance_id,command):
  context=self.require(user,instance_id,"console.execute");caps=runtime_workspace_capabilities(self.root,str(context.get("game_id") or ""),str(context.get("runtime_id") or ""))
  if not bool((caps.get("console") or {}).get("supported")):raise PermissionError("runtime game console is not available")
  text=str(command or "").strip();token=text.lstrip("/").split(None,1)[0].lower() if text else ""
  if str(context.get("game_id") or "").lower()=="palworld" and token=="adminpassword":raise PermissionError("/AdminPassword não pode ser enviado pelo Console do Capivara porque credenciais não podem entrar no histórico de comandos.")
  return self.repo.enqueue_console(agent_id=str(context.get("agent_id") or ""),instance_id=instance_id,command_text=text,requested_by=str(user.get("username") or ""))
 def startup(self,user,instance_id):
  context=self.require(user,instance_id,"startup.read");policy=self._resolved_resource_policy(context,self.repo.workspace_policy(instance_id));caps=runtime_workspace_capabilities(self.root,str(context.get("game_id") or ""),str(context.get("runtime_id") or ""));return {"values":policy.get("startup") or {},"declaration":caps.get("startup_parameters") or {},"resource_limits":{k:policy.get(k) for k in ("cpu_limit_cores","memory_limit_bytes","storage_limit_bytes","player_limit")}}
 def save_startup(self,user,instance_id,values):
  context=self.require(user,instance_id,"startup.write");policy=self._resolved_resource_policy(context,self.repo.workspace_policy(instance_id));caps=runtime_workspace_capabilities(self.root,str(context.get("game_id") or ""),str(context.get("runtime_id") or ""));policy["startup"]=validate_startup_values(values,caps.get("startup_parameters") or {});return self.repo.save_workspace_policy(instance_id,policy)
 def _server_settings_value(self,stored):
  raw=dict((stored or {}).get("value") or {})
  nested=raw.get("settings")
  return dict(nested) if isinstance(nested,dict) else {str(k):v for k,v in raw.items() if k not in {"declaration","runtime_id"}}
 def server_settings(self,user,instance_id):
  context=self.require(user,instance_id,"settings.read");policy=self._resolved_resource_policy(context,self.repo.workspace_policy(instance_id));caps=runtime_workspace_capabilities(self.root,str(context.get("game_id") or ""),str(context.get("runtime_id") or ""));declaration=dict(caps.get("server_settings") or {});repo=ConfigurationRepository(self.backend);repo.initialize();stored=repo.get(scope_type="instance",scope_id=instance_id,namespace="capivara.instance.server-settings");values=self._server_settings_value(stored);return {"values":values,"declaration":declaration,"revision":(stored or {}).get("revision"),"checksum":(stored or {}).get("checksum"),"restart_required":bool(declaration.get("restart_required",True)),"resource_limits":{"player_limit":policy.get("player_limit")}}
 def save_server_settings(self,user,instance_id,values):
  context=self.require(user,instance_id,"settings.write");policy=self._resolved_resource_policy(context,self.repo.workspace_policy(instance_id));caps=runtime_workspace_capabilities(self.root,str(context.get("game_id") or ""),str(context.get("runtime_id") or ""));declaration=dict(caps.get("server_settings") or {});partial=validate_server_settings(values,declaration,player_limit=policy.get("player_limit"));repo=ConfigurationRepository(self.backend);repo.initialize();current=repo.get(scope_type="instance",scope_id=instance_id,namespace="capivara.instance.server-settings");merged={**self._server_settings_value(current),**partial};merged=validate_server_settings(merged,declaration,player_limit=policy.get("player_limit"));actor=str((user or {}).get("username") or (user or {}).get("id") or "customer");runtime_id=str(context.get("runtime_id") or "").strip();payload={"runtime_id":runtime_id,"settings":merged,"declaration":declaration};stored=repo.put({"scope_type":"instance","scope_id":instance_id,"namespace":"capivara.instance.server-settings","value":payload},updated_by=actor);row=stored.get("configuration") or {};return {"values":merged,"declaration":declaration,"revision":row.get("revision"),"checksum":row.get("checksum"),"changed":bool(stored.get("changed")),"restart_required":bool(declaration.get("restart_required",True))}
 def _file_command_policy(self,context,policy):
  caps,content=self._contract_policy(context,policy);return {"storage_limit_bytes":policy.get("storage_limit_bytes"),"content_policy":content.as_dict(),"file_policy":dict(caps.get("file_policy") or {})}
 def queue_file(self,user,instance_id,action,*,path=None,target_path=None,payload=None):
  action=str(action or "").strip().lower();required={"list":"files.read","usage":"files.read","read_text":"files.read","download":"files.download","write_text":"files.edit","upload":"files.upload","mkdir":"files.upload","delete":"files.delete","rename":"files.move","move":"files.move","extract":"files.extract"}.get(action)
  if required is None:raise ValueError("invalid file action")
  context=self.require(user,instance_id,required);policy=self._resolved_resource_policy(context,self.repo.workspace_policy(instance_id));command_policy=self._file_command_policy(context,policy);file_policy=command_policy.get("file_policy") or {}
  mutation_paths=[]
  if action in {"write_text","upload","mkdir","delete"}:mutation_paths.append(path)
  elif action in {"rename","move"}:mutation_paths.extend((path,target_path))
  elif action=="extract":
   if target_path:mutation_paths.append(target_path)
   else:
    source=PurePosixPath(str(path or "").replace("\\","/"));mutation_paths.append(source.parent.as_posix() if source.parts else ".")
  for candidate in mutation_paths:enforce_managed_content_mutation(str(candidate or "."),runtime_rules=file_policy)
  return self.files.enqueue(agent_id=str(context.get("agent_id") or ""),instance_id=instance_id,action=action,requested_by=str(user.get("username") or ""),path=path,target_path=target_path,payload=payload if isinstance(payload,dict) else {},policy=command_policy)
 def file_status(self,user,instance_id,command_id):
  self.require(user,instance_id,"files.read");state=self.files.snapshot(str(command_id or ""))
  if str(state.get("instance_id") or "")!=str(instance_id):raise PermissionError("file command belongs to another instance")
  return state
 def backup_policy(self,user,instance_id):self.require(user,instance_id,"backup.read");return self.repo.backup_policy(instance_id)
 def save_backup_policy(self,user,instance_id,body):self.require(user,instance_id,"backup.create");return self.repo.save_backup_policy(instance_id,enabled=bool(body.get("enabled",True)),schedule_time=body.get("schedule_time") or "04:00",schedule_timezone=body.get("schedule_timezone") or "UTC",healthy_only=True)
 def backup_jobs(self,user,instance_id):self.require(user,instance_id,"backup.read");self.backups.initialize();return self.backups.list_effective_jobs(instance_id=instance_id,limit=100)
 def request_backup(self,user,instance_id,action,backup_id=None):
  action=str(action or "").lower();required={"create":"backup.create","restore":"backup.restore","delete":"backup.delete"}.get(action)
  if required is None:raise ValueError("invalid backup action")
  self.require(user,instance_id,required);self.backups.initialize();return self.backups.request(instance_id,action=action,backup_id=backup_id,reason="customer",requested_by=str(user.get("username") or "customer"))
 def upgrade_options(self,user,instance_id):
  context=self.require(user,instance_id,"contract.read");current=self._resolved_resource_policy(context,self.repo.workspace_policy(instance_id));catalog=catalog_resource_profiles(self.root,str(context.get("game_id") or ""));current_id=current.get("resource_profile_id");profiles=[]
  for item in catalog.get("profiles") or []:
   if not isinstance(item,dict):continue
   profile=dict(item);profile["current"]=str(profile.get("id"))==str(current_id);profile["upgrade"]=(not profile["current"] and (current.get("memory_limit_bytes") is None or int(profile.get("memory_mb") or 0)*1024*1024>=int(current.get("memory_limit_bytes") or 0)) and (current.get("storage_limit_bytes") is None or int(profile.get("storage_mb") or 0)*1024*1024>=int(current.get("storage_limit_bytes") or 0)));profiles.append(profile)
  return {"current_profile_id":current_id,"profiles":profiles,"billing_required":True}
 def request_upgrade(self,user,instance_id,profile_id):
  self.require(user,instance_id,"contract.upgrade");options=self.upgrade_options(user,instance_id);target=next((p for p in options["profiles"] if str(p.get("id"))==str(profile_id)),None)
  if target is None or not target.get("upgrade"):raise ValueError("requested resource profile is not an eligible upgrade")
  request=self.repo.create_contract_change(instance_id,str(profile_id),str(user.get("username") or ""));return self.repo.set_contract_change_status(str(request["request_id"]),"pending_billing")
 def runtime_options(self,user,instance_id):
  context=self.require(user,instance_id,"startup.read");return allowed_runtimes(self.root,str(context.get("game_id") or ""),context.get("contract_metadata") or {})

__all__=["CustomerInstanceWorkspaceService"]
