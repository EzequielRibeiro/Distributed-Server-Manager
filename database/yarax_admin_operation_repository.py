#!/usr/bin/env python3
"""Persistence for allowlisted YARA-X administrative Agent operations."""
from __future__ import annotations

import json
import uuid
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from core.agent_health import utc_timestamp

ACTIONS = frozenset({"install_engine","install_rules","test_scan","rescan_content","rollback_rules"})
FINAL = frozenset({"completed","failed"})


class YaraXAdminOperationRepository:
    def __init__(self, backend):
        self.backend=backend
        self.dialect=dialect_for_backend(backend)

    def initialize(self):
        return self.backend.initialize()

    def create(self, *, agent_id:str, action:str, requested_by:str|None=None, instance_id:str|None=None, content_id:str|None=None, payload:dict[str,Any]|None=None)->dict[str,Any]:
        action=str(action or "").strip().lower()
        if action not in ACTIONS: raise ValueError("unsupported YARA-X administrative action")
        agent_id=str(agent_id or "").strip()
        if not agent_id: raise ValueError("agent_id is required")
        instance_id=str(instance_id or "").strip() or None
        content_id=str(content_id or "").strip() or None
        if action=="rescan_content" and (not instance_id or not content_id):
            raise ValueError("rescan_content requires instance_id and content_id")
        operation_id="yarax-"+uuid.uuid4().hex
        now=utc_timestamp();ph=self.dialect.placeholder
        with self.backend.transaction() as connection:
            session=AlertSession(self.backend,connection)
            try:
                exists=session.execute(f"SELECT 1 FROM agents WHERE id={ph}",(agent_id,)).fetchone()
                if exists is None: raise ValueError("Agent not found")
                pending=session.execute(
                    f"SELECT * FROM yarax_admin_operations WHERE agent_id={ph} AND action={ph} AND status IN ('queued','delivered','running') ORDER BY created_at DESC",
                    (agent_id,action),
                ).fetchone()
                if pending is not None:
                    return self._row(pending)
                session.execute(
                    "INSERT INTO yarax_admin_operations(operation_id,agent_id,action,instance_id,content_id,status,requested_by,payload_json,created_at,updated_at) "
                    f"VALUES ({self.dialect.parameters(10)})",
                    (operation_id,agent_id,action,instance_id,content_id,"queued",requested_by,json.dumps(payload or {},sort_keys=True,separators=(",",":")),now,now),
                )
            finally: session.close()
        return self.get(operation_id)

    def _row(self,row):
        value=dict(row)
        for src,dst in (("payload_json","payload"),("result_json","result")):
            raw=value.pop(src,None)
            try: value[dst]=json.loads(raw) if raw else None
            except (TypeError,ValueError,json.JSONDecodeError): value[dst]=None
        return value

    def get(self, operation_id:str)->dict[str,Any]:
        ph=self.dialect.placeholder
        with self.backend.connect() as connection:
            s=AlertSession(self.backend,connection)
            try: row=s.execute(f"SELECT * FROM yarax_admin_operations WHERE operation_id={ph}",(str(operation_id),)).fetchone()
            finally:s.close()
        if row is None: raise KeyError(operation_id)
        return self._row(row)

    def recent(self, *, agent_id:str|None=None, limit:int=100)->list[dict[str,Any]]:
        ph=self.dialect.placeholder;params=[];where=""
        if agent_id:
            where=f" WHERE agent_id={ph}";params.append(str(agent_id))
        params.append(max(1,min(int(limit),500)))
        with self.backend.connect() as connection:
            s=AlertSession(self.backend,connection)
            try:rows=s.execute(f"SELECT * FROM yarax_admin_operations{where} ORDER BY created_at DESC,operation_id DESC LIMIT {ph}",tuple(params)).fetchall()
            finally:s.close()
        return [self._row(row) for row in rows]

    def command_for_agent(self,agent_id:str)->dict[str,Any]|None:
        ph=self.dialect.placeholder
        with self.backend.transaction() as connection:
            s=AlertSession(self.backend,connection)
            try:
                row=s.execute(
                    f"SELECT * FROM yarax_admin_operations WHERE agent_id={ph} AND status='queued' ORDER BY created_at ASC LIMIT 1",
                    (str(agent_id),),
                ).fetchone()
                if row is None:return None
                now=utc_timestamp()
                s.execute(f"UPDATE yarax_admin_operations SET status={ph},delivered_at={ph},updated_at={ph} WHERE operation_id={ph}",("delivered",now,now,row["operation_id"]))
            finally:s.close()
        item=self._row(row)
        return {k:item.get(k) for k in ("operation_id","action","agent_id","instance_id","content_id","payload")}

    def apply_result(self,authenticated_agent_id:str,result:dict[str,Any])->dict[str,Any]|None:
        if not isinstance(result,dict):return None
        operation_id=str(result.get("operation_id") or "").strip()
        if not operation_id:return None
        current=self.get(operation_id)
        if str(current.get("agent_id"))!=str(authenticated_agent_id):raise PermissionError("YARA-X operation Agent mismatch")
        status=str(result.get("status") or "").lower()
        if status not in {"running","completed","failed"}:raise ValueError("invalid YARA-X operation status")
        now=utc_timestamp();ph=self.dialect.placeholder
        completed=now if status in FINAL else None
        safe_result={k:v for k,v in result.items() if k not in {"credential","secret","token","password"}}
        with self.backend.transaction() as connection:
            s=AlertSession(self.backend,connection)
            try:s.execute(
                f"UPDATE yarax_admin_operations SET status={ph},result_json={ph},last_error={ph},completed_at={ph},updated_at={ph} WHERE operation_id={ph}",
                (status,json.dumps(safe_result,sort_keys=True,separators=(",",":")),str(result.get("error") or "")[:2000] or None,completed,now,operation_id),
            )
            finally:s.close()
        return self.get(operation_id)


__all__=["ACTIONS","YaraXAdminOperationRepository"]
