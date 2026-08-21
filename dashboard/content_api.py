#!/usr/bin/env python3
"""Administrative service boundary for Universal Content."""
from __future__ import annotations
from typing import Any
from content_repository import ContentRepository
from universal_event_repository import UniversalEventRepository

def _admin(user):
 actor=user if isinstance(user,dict) else {}
 if str(actor.get("role") or "").lower() not in {"admin","controller"}:raise PermissionError("administrator access required")
 return actor
def list_content(*,user,backend,filters=None):
 _admin(user);v=filters if isinstance(filters,dict) else {};repo=ContentRepository(backend);repo.initialize();rows=repo.list(agent_id=v.get("agent_id"),instance_id=v.get("instance_id"),desired_state=v.get("desired_state"),limit=int(v.get("limit") or 500));return {"schema_version":1,"kind":"CapivaraContentAssignmentList","assignments":rows,"count":len(rows)}
def set_content(payload,*,user,backend):
 actor=_admin(user);repo=ContentRepository(backend);repo.initialize();actor_id=str(actor.get("username") or actor.get("id") or "admin");result=repo.put(dict(payload or {}),requested_by=actor_id)
 if result["changed"]:
  row=result["assignment"];events=UniversalEventRepository(backend);events.initialize();events.publish({"event_type":"CONTENT_ASSIGNMENT_UPDATED","source":"controller.content","severity":"info","actor_type":"dashboard_user","actor_id":actor_id,"agent_id":row.get("agent_id"),"instance_id":row.get("instance_id"),"data":{"assignment_id":row["assignment_id"],"content_id":row["content_id"],"desired_state":row["desired_state"],"version":row["version"],"revision":row["revision"],"checksum":row["checksum"]}})
 return result
def content_history(assignment_id,*,user,backend):
 _admin(user);repo=ContentRepository(backend);repo.initialize();return {"assignment_id":assignment_id,"revisions":repo.history(assignment_id)}
__all__=["content_history","list_content","set_content"]
