#!/usr/bin/env python3
"""RBAC-aware administrative YARA-X operations."""
from __future__ import annotations
from typing import Any

from activity_audit_repository import ActivityAuditRepository
from alert_repository import AlertSession, dialect_for_backend
from yarax_admin_operation_repository import ACTIONS, YaraXAdminOperationRepository


def _role(user):
    if not isinstance(user,dict): raise PermissionError("authentication required")
    role=str(user.get("role") or "").strip().lower()
    if role not in {"admin","controller"}: raise PermissionError("YARA-X administration is not permitted")
    return role


def _authorize_agent(user,backend,agent_id):
    role=_role(user);agent_id=str(agent_id or "").strip()
    if not agent_id:raise ValueError("agent_id is required")
    ph=dialect_for_backend(backend).placeholder
    with backend.connect() as connection:
        s=AlertSession(backend,connection)
        try:row=s.execute(f"SELECT id,controller_id FROM agents WHERE id={ph}",(agent_id,)).fetchone()
        finally:s.close()
    if row is None:raise ValueError("Agent not found")
    if role=="controller":
        scope=str(user.get("scope_id") or "").strip()
        if not scope or str(row["controller_id"] or "")!=scope:raise PermissionError("Agent is outside controller scope")
    return agent_id


def _actor(user):
    return str(user.get("username") or user.get("id") or "").strip() or "admin"


def create_operation(*,user,backend,payload):
    if not isinstance(payload,dict):raise ValueError("payload must be an object")
    agent_id=_authorize_agent(user,backend,payload.get("agent_id"))
    action=str(payload.get("action") or "").strip().lower()
    if action not in ACTIONS:raise ValueError("unsupported YARA-X administrative action")
    repo=YaraXAdminOperationRepository(backend);repo.initialize()
    result=repo.create(
        agent_id=agent_id,action=action,requested_by=_actor(user),
        instance_id=payload.get("instance_id"),content_id=payload.get("content_id"),payload={},
    )
    ActivityAuditRepository(backend).record_action(
        actor_id=_actor(user),actor_name=str(user.get("display_name") or user.get("name") or _actor(user)),
        actor_role=str(user.get("role") or ""),action=f"security.yarax.{action}",category="security",
        result="queued",summary=f"Operação YARA-X {action} agendada para {agent_id}.",
        target_type="agent",target_id=agent_id,target_name=agent_id,
        changes={"operation_id":result.get("operation_id"),"instance_id":result.get("instance_id"),"content_id":result.get("content_id")},
        correlation_id=str(result.get("operation_id") or ""),
    )
    return result


def list_operations(*,user,backend,agent_id=None,limit=100):
    if agent_id:agent_id=_authorize_agent(user,backend,agent_id)
    else:_role(user)
    repo=YaraXAdminOperationRepository(backend);repo.initialize()
    rows=repo.recent(agent_id=agent_id,limit=limit)
    if _role(user)=="controller" and not agent_id:
        allowed=[]
        for row in rows:
            try:_authorize_agent(user,backend,row.get("agent_id"));allowed.append(row)
            except PermissionError:pass
        rows=allowed
    return {"schema_version":1,"kind":"CapivaraYaraXOperationList","operations":rows,"count":len(rows)}


__all__=["create_operation","list_operations"]
