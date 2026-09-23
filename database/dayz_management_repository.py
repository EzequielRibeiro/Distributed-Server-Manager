#!/usr/bin/env python3
"""Controller-side DayZ map discovery/change and wipe operation queue."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime,timezone
import json,uuid
from typing import Any,Iterator
from alert_repository import AlertSession,dialect_for_backend
from backend import DatabaseBackend
from core.agent_health import utc_timestamp

VALID_ACTIONS={"discover_missions","change_mission","wipe"}
ACTIVE_STATES={"queued","delivered"}
FINAL_STATES={"completed","failed","canceled"}
MUTATING_ACTIONS={"change_mission","wipe"}

def _stamp(value: Any|None=None)->str:
    if value in {None,""}:dt=datetime.now(timezone.utc)
    elif isinstance(value,datetime):dt=value
    else:dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None:raise ValueError("scheduled_at must be timezone-aware")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

class DayZOperationConflict(RuntimeError):pass

class DayZManagementRepository:
    def __init__(self,backend:DatabaseBackend):self.backend=backend;self.dialect=dialect_for_backend(backend)
    def initialize(self):return self.backend.initialize()
    @contextmanager
    def session(self,transaction:bool=False)->Iterator[AlertSession]:
        ctx=self.backend.transaction() if transaction else self.backend.connect()
        with ctx as connection:
            s=AlertSession(self.backend,connection)
            try:yield s
            finally:s.close()
    def enqueue(self,*,agent_id:str,instance_id:str,action:str,payload:dict[str,Any]|None=None,scheduled_at:Any|None=None,requested_by:str|None=None)->dict[str,Any]:
        agent_id=str(agent_id or "").strip();instance_id=str(instance_id or "").strip();action=str(action or "").strip().lower()
        if not agent_id or not instance_id:raise ValueError("agent_id and instance_id are required")
        if action not in VALID_ACTIONS:raise ValueError("invalid DayZ operation")
        due=_stamp(scheduled_at);body=dict(payload or {});ph=self.dialect.placeholder
        with self.session(transaction=True) as s:
            agent=s.execute(f"SELECT status FROM agents WHERE id={ph}",(agent_id,)).fetchone()
            if agent is None or str(agent["status"] or "").lower()!="active":raise ValueError("Agent must be active")
            instance=s.execute(f"SELECT agent_id,game_id FROM instances WHERE id={ph}",(instance_id,)).fetchone()
            if instance is None:raise KeyError(instance_id)
            if str(instance["agent_id"] or "")!=agent_id:raise PermissionError("Instance belongs to another Agent")
            if str(instance["game_id"] or "").lower()!="dayz":raise ValueError("DayZ operation requires a DayZ instance")
            if action in MUTATING_ACTIONS:
                active=s.execute("SELECT operation_id,action FROM dayz_operations "+f"WHERE instance_id={ph} AND action IN ('change_mission','wipe') AND status IN ('queued','delivered') ORDER BY created_at LIMIT 1",(instance_id,)).fetchone()
                if active is not None:raise DayZOperationConflict(f"DayZ operation already active: {active['action']} ({active['operation_id']})")
            operation_id="dayz-op-"+uuid.uuid4().hex;now=utc_timestamp()
            s.execute("INSERT INTO dayz_operations(operation_id,agent_id,instance_id,action,status,requested_by,scheduled_at,payload_json,created_at,updated_at) "+f"VALUES ({self.dialect.parameters(10)})",(operation_id,agent_id,instance_id,action,"queued",str(requested_by or "").strip() or None,due,json.dumps(body,separators=(",",":"),sort_keys=True),now,now))
        return self.snapshot(operation_id)
    def snapshot(self,operation_id:str)->dict[str,Any]:
        ph=self.dialect.placeholder
        with self.session() as s:row=s.execute(f"SELECT * FROM dayz_operations WHERE operation_id={ph}",(str(operation_id),)).fetchone()
        if row is None:raise KeyError(operation_id)
        value=dict(row)
        for source,target in (("payload_json","payload"),("result_json","result")):
            raw=value.pop(source,None)
            try:value[target]=json.loads(raw) if raw else None
            except (TypeError,ValueError):value[target]=None
        return value
    def command_for_agent(self,agent_id:str)->dict[str,Any]|None:
        ph=self.dialect.placeholder;now=utc_timestamp()
        with self.session() as s:
            row=s.execute("SELECT operation_id FROM dayz_operations "+f"WHERE agent_id={ph} AND status IN ('queued','delivered') AND scheduled_at<={ph} ORDER BY scheduled_at,created_at LIMIT 1",(str(agent_id),now)).fetchone()
        if row is None:return None
        state=self.snapshot(str(row["operation_id"]))
        return {k:state.get(k) for k in ("operation_id","agent_id","instance_id","action","scheduled_at","payload")}
    def mark_delivered(self,operation_id:str)->dict[str,Any]:
        ph=self.dialect.placeholder;now=utc_timestamp()
        with self.session(transaction=True) as s:s.execute("UPDATE dayz_operations SET status=CASE WHEN status='queued' THEN 'delivered' ELSE status END,"+f"delivered_at=COALESCE(delivered_at,{ph}),updated_at={ph} WHERE operation_id={ph} AND status IN ('queued','delivered')",(now,now,operation_id))
        return self.snapshot(operation_id)
    def apply_result(self,agent_id:str,result:dict[str,Any]|None)->dict[str,Any]|None:
        if not isinstance(result,dict):return None
        oid=str(result.get("operation_id") or "").strip()
        if not oid:return None
        current=self.snapshot(oid)
        if str(current.get("agent_id") or "")!=str(agent_id):raise PermissionError("DayZ operation belongs to another Agent")
        if str(result.get("instance_id") or "")!=str(current.get("instance_id") or ""):raise ValueError("DayZ operation instance mismatch")
        status=str(result.get("status") or "").lower()
        if status not in {"completed","failed"}:raise ValueError("invalid DayZ operation result status")
        now=utc_timestamp();ph=self.dialect.placeholder;error=str(result.get("error") or "").strip()[:2000] or None
        with self.session(transaction=True) as s:s.execute("UPDATE dayz_operations SET "+f"status={ph},result_json={ph},last_error={ph},completed_at={ph},updated_at={ph} WHERE operation_id={ph} AND status IN ('queued','delivered')",(status,json.dumps(result,separators=(",",":"),sort_keys=True),error,now,now,oid))
        return self.snapshot(oid)
    def cancel(self,operation_id:str)->dict[str,Any]:
        current=self.snapshot(operation_id)
        if str(current.get("status") or "")!="queued":raise RuntimeError("only queued DayZ operations can be canceled")
        ph=self.dialect.placeholder;now=utc_timestamp()
        with self.session(transaction=True) as s:s.execute(f"UPDATE dayz_operations SET status='canceled',canceled_at={ph},updated_at={ph} WHERE operation_id={ph} AND status='queued'",(now,now,operation_id))
        return self.snapshot(operation_id)
    def list_for_instance(self,instance_id:str,limit:int=25)->list[dict[str,Any]]:
        ph=self.dialect.placeholder
        with self.session() as s:rows=s.execute(f"SELECT operation_id FROM dayz_operations WHERE instance_id={ph} ORDER BY created_at DESC LIMIT {max(1,min(int(limit),100))}",(str(instance_id),)).fetchall()
        return [self.snapshot(str(row["operation_id"])) for row in rows]

__all__=["DayZManagementRepository","DayZOperationConflict","VALID_ACTIONS"]
