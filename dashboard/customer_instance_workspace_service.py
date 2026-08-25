#!/usr/bin/env python3
"""Service layer for Customer Instance Workspace v2."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from catalog_resource_profiles_http import catalog_resource_profiles
from instance_file_repository import InstanceFileRepository
from instance_workspace_policy import INSTANCE_PERMISSIONS, effective_content_policy, require_permission, validate_startup_values
from instance_workspace_repository import InstanceWorkspaceRepository
from runtime_workspace_catalog import allowed_runtimes, contract_entitlements, runtime_workspace_capabilities


def _json(value, default):
    if isinstance(value, (dict, list)): return value
    try: result=json.loads(str(value))
    except (TypeError, ValueError): return default
    return result if isinstance(result, type(default)) else default


class CustomerInstanceWorkspaceService:
    def __init__(self, backend, root: Path):
        self.backend=backend;self.root=Path(root);self.repo=InstanceWorkspaceRepository(backend);self.files=InstanceFileRepository(backend);self.dialect=dialect_for_backend(backend)

    def _session(self, connection): return AlertSession(self.backend,connection)

    def permissions(self,user:dict[str,Any],instance_id:str)->set[str]:
        role=str((user or {}).get("role") or "").lower()
        if role in {"admin","controller"}: return set(INSTANCE_PERMISSIONS)
        if role!="customer": return set()
        # Instance grants are intentionally independent from the user's primary
        # Customer account. A person may own one account and administer an
        # instance shared by another Customer.
        return self.repo.effective_permissions_for(str(user.get("username") or ""),instance_id)

    def require(self,user,instance_id,permission):
        require_permission(self.permissions(user,instance_id),permission)
        return self.repo.instance_context(instance_id)

    def _ports(self,instance_id):
        ph=self.dialect.placeholder
        with self.backend.connect() as connection:
            session=self._session(connection)
            try: rows=session.execute(f"SELECT name,protocol,port,bind_address FROM instance_ports WHERE instance_id={ph} ORDER BY port,name",(instance_id,)).fetchall()
            finally:session.close()
        return [dict(row) for row in rows]

    def _location(self,agent_id):
        ph=self.dialect.placeholder
        with self.backend.connect() as connection:
            session=self._session(connection)
            try:
                row=session.execute(
                    "SELECT a.name AS agent_name,a.metadata_json,l.public_host,l.latitude,l.longitude,d.id AS datacenter_id,d.name AS datacenter_name,d.city,d.country_code,r.id AS region_id,r.name AS region_name,r.country_code AS region_country_code "
                    "FROM agents a LEFT JOIN agent_locations l ON l.agent_id=a.id LEFT JOIN datacenters d ON d.id=l.datacenter_id LEFT JOIN regions r ON r.id=d.region_id "
                    f"WHERE a.id={ph}",(agent_id,)).fetchone()
            finally:session.close()
        if row is None:return {}
        value=dict(row);value["agent_metadata"]=_json(value.pop("metadata_json",None),{});return value

    def _latest_telemetry(self,instance_id):
        rows=self.repo.telemetry(instance_id,1);return rows[-1] if rows else {}

    def _contract_policy(self,context,policy):
        metadata=context.get("contract_metadata") or {};runtime_id=str(context.get("runtime_id") or "")
        capabilities=runtime_workspace_capabilities(self.root,str(context.get("game_id") or ""),runtime_id) if runtime_id else {}
        entitlements=contract_entitlements(metadata)
        # Persisted policy can only further restrict commercial entitlements.
        for key,column in (("mods","mods_allowed"),("plugins","plugins_allowed"),("workshop","workshop_allowed"),("external_upload","external_upload_allowed"),("custom_runtime","custom_runtime_allowed")):
            if column in policy:entitlements[key]=bool(entitlements.get(key)) and bool(policy.get(column))
        return capabilities,effective_content_policy(entitlements,capabilities)

    def overview(self,user,instance_id):
        context=self.require(user,instance_id,"instance.view");policy=self.repo.workspace_policy(instance_id);permissions=self.permissions(user,instance_id);telemetry=self._latest_telemetry(instance_id);location=self._location(str(context.get("agent_id") or ""));capabilities,content=self._contract_policy(context,policy)
        agent_meta=location.get("agent_metadata") if isinstance(location.get("agent_metadata"),dict) else {}
        latest_from_agent={}
        for item in agent_meta.get("instance_telemetry") or []:
            if isinstance(item,dict) and str(item.get("instance_id"))==instance_id:latest_from_agent=item
        telemetry={**latest_from_agent,**telemetry}
        storage_limit=policy.get("storage_limit_bytes");used=telemetry.get("storage_used_bytes")
        storage_pct=(float(used)/float(storage_limit)*100.0) if used is not None and storage_limit else None
        metadata=context.get("instance_metadata") if isinstance(context.get("instance_metadata"),dict) else {}
        provision=metadata.get("provision") if isinstance(metadata,dict) else None
        completed=bool(isinstance(provision,dict) and str(provision.get("stage") or "").lower()=="completed" and int(provision.get("progress") or 0)>=100)
        if completed: provision=None
        return {
            "instance":{k:context.get(k) for k in ("id","name","game_id","edition","runtime_id","variant","game_version","status","agent_id","contract_id")},
            "permissions":sorted(permissions),"policy":policy,"content_policy":content.as_dict(),"content_sections":[x for x in ("mods","plugins","workshop") if content.as_dict().get(f"{x}_allowed")],
            "runtime_capabilities":capabilities,"ports":self._ports(instance_id),"location":{k:location.get(k) for k in ("public_host","datacenter_id","datacenter_name","city","country_code","region_id","region_name","region_country_code","agent_name")},
            "telemetry":telemetry,"storage":{"used_bytes":used,"limit_bytes":storage_limit,"percent":storage_pct},"provision":provision,
            "console":{"read":"console.read" in permissions,"execute":"console.execute" in permissions,"supported":bool((capabilities.get("console") or {}).get("supported"))},
            "upgrade":{"allowed":"contract.upgrade" in permissions,"current_profile_id":policy.get("resource_profile_id")},
        }

    def telemetry(self,user,instance_id,limit=240):
        self.require(user,instance_id,"instance.view");return self.repo.telemetry(instance_id,limit)

    def console_output(self,user,instance_id,limit=300):
        self.require(user,instance_id,"console.read");return self.repo.console_output(instance_id,limit)

    def send_console(self,user,instance_id,command):
        context=self.require(user,instance_id,"console.execute")
        capabilities=runtime_workspace_capabilities(self.root,str(context.get("game_id") or ""),str(context.get("runtime_id") or ""))
        if not bool((capabilities.get("console") or {}).get("supported")):raise PermissionError("runtime game console is not available")
        return self.repo.enqueue_console(agent_id=str(context.get("agent_id") or ""),instance_id=instance_id,command_text=command,requested_by=str(user.get("username") or ""))

    def startup(self,user,instance_id):
        context=self.require(user,instance_id,"startup.read");policy=self.repo.workspace_policy(instance_id);caps=runtime_workspace_capabilities(self.root,str(context.get("game_id") or ""),str(context.get("runtime_id") or ""));return {"values":policy.get("startup") or {},"declaration":caps.get("startup_parameters") or {},"resource_limits":{k:policy.get(k) for k in ("cpu_limit_cores","memory_limit_bytes","storage_limit_bytes","player_limit")}}

    def save_startup(self,user,instance_id,values):
        context=self.require(user,instance_id,"startup.write");policy=self.repo.workspace_policy(instance_id);caps=runtime_workspace_capabilities(self.root,str(context.get("game_id") or ""),str(context.get("runtime_id") or ""));policy["startup"]=validate_startup_values(values,caps.get("startup_parameters") or {});return self.repo.save_workspace_policy(instance_id,policy)

    # ----------------------------------------------------------- File Manager v2
    def _file_command_policy(self, context, policy):
        capabilities,content=self._contract_policy(context,policy)
        return {
            "storage_limit_bytes":policy.get("storage_limit_bytes"),
            "content_policy":content.as_dict(),
            "file_policy":dict(capabilities.get("file_policy") or {}),
        }

    def queue_file(self,user,instance_id,action,*,path=None,target_path=None,payload=None):
        action=str(action or "").strip().lower()
        required={
            "list":"files.read","usage":"files.read","read_text":"files.read","download":"files.download",
            "write_text":"files.edit","upload":"files.upload","mkdir":"files.upload","delete":"files.delete",
            "rename":"files.move","move":"files.move","extract":"files.extract",
        }.get(action)
        if required is None:raise ValueError("invalid file action")
        context=self.require(user,instance_id,required);policy=self.repo.workspace_policy(instance_id)
        return self.files.enqueue(
            agent_id=str(context.get("agent_id") or ""),instance_id=instance_id,action=action,
            requested_by=str(user.get("username") or ""),path=path,target_path=target_path,
            payload=payload if isinstance(payload,dict) else {},policy=self._file_command_policy(context,policy),
        )

    def file_status(self,user,instance_id,command_id):
        self.require(user,instance_id,"files.read");state=self.files.snapshot(str(command_id or ""))
        if str(state.get("instance_id") or "")!=str(instance_id):raise PermissionError("file command belongs to another instance")
        return state

    def backup_policy(self,user,instance_id):self.require(user,instance_id,"backup.read");return self.repo.backup_policy(instance_id)
    def save_backup_policy(self,user,instance_id,body):self.require(user,instance_id,"backup.create");return self.repo.save_backup_policy(instance_id,enabled=bool(body.get("enabled",True)),schedule_time=body.get("schedule_time") or "04:00",healthy_only=True)

    def upgrade_options(self,user,instance_id):
        context=self.require(user,instance_id,"contract.read");current=self.repo.workspace_policy(instance_id);catalog=catalog_resource_profiles(self.root,str(context.get("game_id") or ""));current_id=current.get("resource_profile_id");profiles=[]
        for item in catalog.get("profiles") or []:
            if not isinstance(item,dict):continue
            profile=dict(item);profile["current"]=str(profile.get("id"))==str(current_id);profile["upgrade"]=(not profile["current"] and (current.get("memory_limit_bytes") is None or int(profile.get("memory_mb") or 0)*1024*1024>=int(current.get("memory_limit_bytes") or 0)) and (current.get("storage_limit_bytes") is None or int(profile.get("storage_mb") or 0)*1024*1024>=int(current.get("storage_limit_bytes") or 0)))
            profiles.append(profile)
        return {"current_profile_id":current_id,"profiles":profiles,"billing_required":True}

    def request_upgrade(self,user,instance_id,profile_id):
        self.require(user,instance_id,"contract.upgrade");options=self.upgrade_options(user,instance_id);target=next((p for p in options["profiles"] if str(p.get("id"))==str(profile_id)),None)
        if target is None or not target.get("upgrade"):raise ValueError("requested resource profile is not an eligible upgrade")
        request=self.repo.create_contract_change(instance_id,str(profile_id),str(user.get("username") or ""));return self.repo.set_contract_change_status(str(request["request_id"]),"pending_billing")

    def runtime_options(self,user,instance_id):
        context=self.require(user,instance_id,"startup.read");return allowed_runtimes(self.root,str(context.get("game_id") or ""),context.get("contract_metadata") or {})


__all__=["CustomerInstanceWorkspaceService"]
