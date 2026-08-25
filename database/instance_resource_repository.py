#!/usr/bin/env python3
"""Controller queue for applying purchased Resource Profiles on Agents."""
from __future__ import annotations
import json,uuid
from alert_repository import AlertSession,dialect_for_backend

class InstanceResourceRepository:
    def __init__(self,backend):self.backend=backend;self.dialect=dialect_for_backend(backend)
    def initialize(self):return self.backend.initialize()
    def _session(self,c):return AlertSession(self.backend,c)
    @staticmethod
    def _decode(value):
        if isinstance(value,dict):return value
        try:v=json.loads(str(value or "{}"))
        except (TypeError,ValueError):return {}
        return v if isinstance(v,dict) else {}
    def enqueue(self,agent_id,instance_id,profile_id,resources,requested_by=None):
        agent_id=str(agent_id or "").strip();instance_id=str(instance_id or "").strip();profile_id=str(profile_id or "").strip()
        if not all((agent_id,instance_id,profile_id)):raise ValueError("agent_id, instance_id and profile_id are required")
        resources=dict(resources or {});self.initialize();ph=self.dialect.placeholder;cid="resource-cmd-"+uuid.uuid4().hex
        with self.backend.transaction() as c:
            s=self._session(c)
            try:
                row=s.execute(f"SELECT agent_id FROM instances WHERE id={ph}",(instance_id,)).fetchone()
                if row is None:raise LookupError("instance not found")
                if str(row["agent_id"] or "")!=agent_id:raise PermissionError("instance belongs to another Agent")
                s.execute("INSERT INTO instance_resource_commands(command_id,agent_id,instance_id,resource_profile_id,resources_json,status,requested_by) "+f"VALUES ({self.dialect.parameters(7)})",(cid,agent_id,instance_id,profile_id,json.dumps(resources,separators=(",",":"),sort_keys=True),"queued",str(requested_by or "") or None))
            finally:s.close()
        return self.snapshot(cid)
    def snapshot(self,cid):
        ph=self.dialect.placeholder
        with self.backend.connect() as c:
            s=self._session(c)
            try:row=s.execute(f"SELECT * FROM instance_resource_commands WHERE command_id={ph}",(cid,)).fetchone()
            finally:s.close()
        if row is None:raise KeyError(cid)
        item=dict(row);item["resources"]=self._decode(item.pop("resources_json",None));item["result"]=self._decode(item.pop("result_json",None));return item
    def command_for_agent(self,agent_id):
        ph=self.dialect.placeholder
        with self.backend.transaction() as c:
            s=self._session(c)
            try:
                row=s.execute(f"SELECT command_id FROM instance_resource_commands WHERE agent_id={ph} AND status='queued' ORDER BY created_at ASC LIMIT 1",(agent_id,)).fetchone()
                if row is None:return None
                cid=str(row["command_id"]);s.execute(f"UPDATE instance_resource_commands SET status='delivered',delivered_at={self.dialect.current_timestamp},updated_at={self.dialect.current_timestamp} WHERE command_id={ph} AND status='queued'",(cid,))
            finally:s.close()
        item=self.snapshot(cid);return {k:item.get(k) for k in ("command_id","instance_id","resource_profile_id","resources")}
    def apply_result(self,agent_id,report):
        if not isinstance(report,dict) or not report.get("command_id"):return None
        item=self.snapshot(str(report["command_id"]))
        if str(item.get("agent_id"))!=str(agent_id):raise PermissionError("resource command belongs to another Agent")
        if str(report.get("instance_id") or "")!=str(item.get("instance_id") or ""):raise ValueError("resource result instance mismatch")
        status=str(report.get("status") or "").lower()
        if status not in {"completed","failed"}:raise ValueError("invalid resource command result")
        ph=self.dialect.placeholder;error=str(report.get("error") or "")[:2000] or None
        with self.backend.transaction() as c:
            s=self._session(c)
            try:
                s.execute(f"UPDATE instance_resource_commands SET status={ph},result_json={ph},last_error={ph},completed_at={self.dialect.current_timestamp},updated_at={self.dialect.current_timestamp} WHERE command_id={ph}",(status,json.dumps(report.get("result") or {},separators=(",",":"),sort_keys=True),error,item["command_id"]))
                # Complete only the matching applying request. This keeps Billing
                # confirmation separate from actual distributed enforcement.
                target_status="applied" if status=="completed" else "failed"
                row=s.execute(
                    "SELECT request_id FROM contract_change_requests "
                    f"WHERE instance_id={ph} AND requested_profile_id={ph} AND status='applying' ORDER BY requested_at DESC LIMIT 1",
                    (item["instance_id"],item["resource_profile_id"]),
                ).fetchone()
                if row is not None:
                    if target_status=="applied":
                        s.execute(f"UPDATE contract_change_requests SET status='applied',applied_at=COALESCE(applied_at,{self.dialect.current_timestamp}),updated_at={self.dialect.current_timestamp} WHERE request_id={ph}",(row["request_id"],))
                    else:
                        s.execute(f"UPDATE contract_change_requests SET status='failed',failure_reason={ph},updated_at={self.dialect.current_timestamp} WHERE request_id={ph}",(error or "Agent resource reconciliation failed",row["request_id"]))
            finally:s.close()
        return self.snapshot(item["command_id"])

__all__=["InstanceResourceRepository"]
