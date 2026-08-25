#!/usr/bin/env python3
"""Customer-visible activity timeline backed by the canonical Dashboard audit log."""
from __future__ import annotations
from typing import Any
from dashboard_activity_repository import DashboardActivityRepository

class InstanceActivityRepository:
    def __init__(self, backend):
        self.backend=backend
        self.audit=DashboardActivityRepository(backend)
        self.dialect=self.audit.dialect

    def record(self, *, instance_id:str, customer_id:int|None, username:str|None, role:str|None,
               activity:str, category:str, result:str="success", target_type:str|None=None,
               target_name:str|None=None, details:dict[str,Any]|None=None)->str:
        payload=dict(details or {})
        payload["instance_id"]=str(instance_id)
        if customer_id is not None: payload["customer_id"]=int(customer_id)
        if target_type: payload["resource_type"]=str(target_type)
        if target_name: payload["resource_name"]=str(target_name)[:512]
        return self.audit.record(username=username,role=role,session_id=None,activity=activity,category=category,
                                 result=result,target_type="instance",target_id=str(instance_id),details=payload)

    def search(self, *, instance_id:str, username:str|None=None, category:str|None=None,
               activity:str|None=None, result:str|None=None, start_at:str|None=None,
               end_at:str|None=None, limit:int=200)->list[dict[str,Any]]:
        self.audit.initialize(); ph=self.dialect.placeholder
        clauses=[f"target_type={ph}",f"target_id={ph}"];params:[Any]=["instance",str(instance_id)]
        for column,value in (("username",username),("category",category),("activity",activity),("result",result)):
            value=str(value or "").strip()
            if value: clauses.append(f"{column}={ph}");params.append(value)
        if start_at: clauses.append(f"created_at>={ph}");params.append(start_at)
        if end_at: clauses.append(f"created_at<={ph}");params.append(end_at)
        limit=max(1,min(int(limit or 200),1000))
        sql=("SELECT event_id,username,role,activity,category,result,target_type,target_id,details_json,created_at "
             "FROM dashboard_activity_log WHERE "+" AND ".join(clauses)+" ORDER BY created_at DESC,event_id DESC LIMIT "+str(limit))
        import json
        with self.audit.session() as session: rows=session.execute(sql,tuple(params)).fetchall()
        out=[]
        for row in rows:
            item=dict(row)
            try:item["details"]=json.loads(item.pop("details_json") or "{}")
            except (TypeError,ValueError):item["details"]={}
            out.append(item)
        return out

    def options(self, instance_id:str)->dict[str,list[str]]:
        rows=self.search(instance_id=instance_id,limit=1000)
        return {
            "users":sorted({str(x.get("username")) for x in rows if x.get("username")}),
            "categories":sorted({str(x.get("category")) for x in rows if x.get("category")}),
            "activities":sorted({str(x.get("activity")) for x in rows if x.get("activity")}),
            "results":sorted({str(x.get("result")) for x in rows if x.get("result")}),
        }

__all__=["InstanceActivityRepository"]
