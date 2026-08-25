#!/usr/bin/env python3
"""Transactional application of paid Customer instance Resource Profile changes."""
from __future__ import annotations
import json,uuid
from typing import Any
from alert_repository import AlertSession,dialect_for_backend

class ContractUpgradeRepository:
    def __init__(self,backend):self.backend=backend;self.dialect=dialect_for_backend(backend)
    def _session(self,c):return AlertSession(self.backend,c)
    def _bool(self,value):return bool(value) if self.backend.name=="postgresql" else int(bool(value))
    @staticmethod
    def _decode(value):
        if isinstance(value,dict):return dict(value)
        try:value=json.loads(str(value or "{}"))
        except (TypeError,ValueError):return {}
        return value if isinstance(value,dict) else {}
    def apply_profile(self,request_id:str,profile:dict[str,Any],*,billing_reference:str,applied_by:str)->dict[str,Any]:
        request_id=str(request_id or "").strip();billing_reference=str(billing_reference or "").strip();applied_by=str(applied_by or "").strip();profile=dict(profile or {});profile_id=str(profile.get("id") or "").strip()
        if not request_id or not profile_id or not billing_reference:raise ValueError("request_id, profile and billing_reference are required")
        try:memory_mb=int(profile["memory_mb"]);storage_mb=int(profile["storage_mb"]);cpu_cores=float(profile["cpu_cores"])
        except (KeyError,TypeError,ValueError) as exc:raise ValueError("resource profile is incomplete") from exc
        if memory_mb<=0 or storage_mb<=0 or cpu_cores<=0:raise ValueError("resource profile resources must be positive")
        self.backend.initialize();ph=self.dialect.placeholder;resource_command_id="resource-cmd-"+uuid.uuid4().hex
        with self.backend.transaction() as connection:
            session=self._session(connection)
            try:
                row=session.execute("SELECT r.*,c.metadata_json,i.game_id,i.agent_id FROM contract_change_requests r JOIN service_contracts c ON c.id=r.contract_id JOIN instances i ON i.id=r.instance_id "+f"WHERE r.request_id={ph}",(request_id,)).fetchone()
                if row is None:raise LookupError("contract change request not found")
                state=dict(row)
                if str(state.get("requested_profile_id") or "")!=profile_id:raise ValueError("billing confirmation profile mismatch")
                if str(state.get("status") or "")=="applied":return {"request_id":request_id,"status":"applied","instance_id":state["instance_id"],"profile_id":profile_id,"idempotent":True}
                if str(state.get("status") or "") not in {"pending_billing","paid","approved","applying"}:raise ValueError("contract change is not eligible for application")
                metadata=self._decode(state.get("metadata_json"));resources=metadata.get("resources") if isinstance(metadata.get("resources"),dict) else {};entitlements=metadata.get("entitlements") if isinstance(metadata.get("entitlements"),dict) else {}
                previous_profile=metadata.get("resource_profile_id") or metadata.get("profile_id") or state.get("current_profile_id");previous_resources=dict(resources)
                new_resources={**resources,"cpu_cores":cpu_cores,"memory_mb":memory_mb,"memory_bytes":memory_mb*1024*1024,"storage_mb":storage_mb,"storage_bytes":storage_mb*1024*1024}
                if profile.get("player_limit") is not None:new_resources["player_limit"]=int(profile["player_limit"])
                if profile.get("pids_limit") is not None:new_resources["pids_limit"]=int(profile["pids_limit"])
                revisions=session.execute(f"SELECT COALESCE(MAX(revision_number),0) AS n FROM service_contract_revisions WHERE contract_id={ph}",(state["contract_id"],)).fetchone();number=int(revisions["n"] or 0)
                if number==0:
                    session.execute("INSERT INTO service_contract_revisions(revision_id,contract_id,instance_id,revision_number,resource_profile_id,resources_json,entitlements_json,reason,billing_reference,created_by) "+f"VALUES ({self.dialect.parameters(10)})",("contract-rev-"+uuid.uuid4().hex,state["contract_id"],state["instance_id"],1,str(previous_profile or "") or None,json.dumps(previous_resources,separators=(",",":"),sort_keys=True),json.dumps(entitlements,separators=(",",":"),sort_keys=True),"baseline",None,applied_by or None));number=1
                session.execute(f"UPDATE service_contract_revisions SET effective_until={self.dialect.current_timestamp} WHERE contract_id={ph} AND revision_number={ph} AND effective_until IS NULL",(state["contract_id"],number))
                metadata["resource_profile_id"]=profile_id;metadata["resources"]=new_resources
                session.execute(f"UPDATE service_contracts SET metadata_json={ph},updated_at={self.dialect.current_timestamp} WHERE id={ph}",(json.dumps(metadata,separators=(",",":"),sort_keys=True),state["contract_id"]))
                current=session.execute(f"SELECT 1 FROM instance_workspace_policy WHERE instance_id={ph}",(state["instance_id"],)).fetchone();policy_values=(profile_id,cpu_cores,memory_mb*1024*1024,storage_mb*1024*1024,int(new_resources.get("player_limit")) if new_resources.get("player_limit") is not None else None)
                if current is None:
                    session.execute("INSERT INTO instance_workspace_policy(instance_id,resource_profile_id,cpu_limit_cores,memory_limit_bytes,storage_limit_bytes,player_limit,content_mode,mods_allowed,plugins_allowed,workshop_allowed,external_upload_allowed,custom_runtime_allowed,startup_json) "+f"VALUES ({self.dialect.parameters(13)})",(state["instance_id"],*policy_values,"modified" if any(bool(entitlements.get(x)) for x in ("mods","plugins","workshop")) else "standard",self._bool(bool(entitlements.get("mods"))),self._bool(bool(entitlements.get("plugins"))),self._bool(bool(entitlements.get("workshop"))),self._bool(bool(entitlements.get("external_upload",True))),self._bool(bool(entitlements.get("custom_runtime",False))),"{}"))
                else:session.execute(f"UPDATE instance_workspace_policy SET resource_profile_id={ph},cpu_limit_cores={ph},memory_limit_bytes={ph},storage_limit_bytes={ph},player_limit={ph},updated_at={self.dialect.current_timestamp} WHERE instance_id={ph}",(*policy_values,state["instance_id"]))
                session.execute("INSERT INTO service_contract_revisions(revision_id,contract_id,instance_id,revision_number,resource_profile_id,resources_json,entitlements_json,reason,billing_reference,created_by) "+f"VALUES ({self.dialect.parameters(10)})",("contract-rev-"+uuid.uuid4().hex,state["contract_id"],state["instance_id"],number+1,profile_id,json.dumps(new_resources,separators=(",",":"),sort_keys=True),json.dumps(entitlements,separators=(",",":"),sort_keys=True),"resource_upgrade",billing_reference,applied_by or None))
                session.execute("INSERT INTO instance_resource_commands(command_id,agent_id,instance_id,resource_profile_id,resources_json,status,requested_by) "+f"VALUES ({self.dialect.parameters(7)})",(resource_command_id,state["agent_id"],state["instance_id"],profile_id,json.dumps(new_resources,separators=(",",":"),sort_keys=True),"queued",applied_by or "billing"))
                # Billing is complete, but runtime application is asynchronous.
                session.execute(f"UPDATE contract_change_requests SET status='applying',billing_reference={ph},approved_at=COALESCE(approved_at,{self.dialect.current_timestamp}),updated_at={self.dialect.current_timestamp} WHERE request_id={ph}",(billing_reference,request_id))
            finally:session.close()
        return {"request_id":request_id,"status":"applying","instance_id":state["instance_id"],"profile_id":profile_id,"resources":new_resources,"resource_command_id":resource_command_id,"idempotent":False}

__all__=["ContractUpgradeRepository"]
