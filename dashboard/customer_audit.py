#!/usr/bin/env python3
"""Audit writer for customer identity/team security events."""
from __future__ import annotations
import json
from alert_repository import AlertSession,dialect_for_backend

def audit_customer_event(backend, *, username:str, action:str, result:str="success", instance_id:str|None=None, details:dict|None=None)->None:
    backend.initialize(); dialect=dialect_for_backend(backend)
    with backend.transaction() as connection:
        s=AlertSession(backend,connection)
        try:
            s.execute("INSERT INTO audit_log(username,instance_id,action,result,details) "+f"VALUES ({dialect.parameters(5)})",(username,instance_id,action,result,None if details is None else json.dumps(details,ensure_ascii=False,sort_keys=True)))
        finally:s.close()
