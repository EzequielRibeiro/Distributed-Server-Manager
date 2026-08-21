#!/usr/bin/env python3
"""Transport adapter for Universal Content API."""
from __future__ import annotations
from urllib.parse import parse_qs
from content_api import content_history,list_content,set_content
CONTENT_PATH="/api/content"

def dispatch_content_get(path,query,*,user,backend):
 if path!=CONTENT_PATH:return 404,{"error":"not_found"}
 q=parse_qs(query,keep_blank_values=True)
 try:
  assignment=(q.get("assignment_id") or [None])[0]
  if assignment:return 200,content_history(str(assignment),user=user,backend=backend)
  filters={"agent_id":(q.get("agent_id") or [None])[0],"instance_id":(q.get("instance_id") or [None])[0],"desired_state":(q.get("desired_state") or [None])[0],"limit":(q.get("limit") or [500])[0]}
  return 200,list_content(user=user,backend=backend,filters=filters)
 except PermissionError as exc:return 403,{"error":"forbidden","message":str(exc)}
 except (ValueError,KeyError) as exc:return 400,{"error":"invalid_request","message":str(exc)}
def dispatch_content_post(path,payload,*,user,backend):
 if path!=CONTENT_PATH:return 404,{"error":"not_found"}
 try:return 200,set_content(payload,user=user,backend=backend)
 except PermissionError as exc:return 403,{"error":"forbidden","message":str(exc)}
 except (ValueError,KeyError) as exc:return 400,{"error":"invalid_request","message":str(exc)}
__all__=["CONTENT_PATH","dispatch_content_get","dispatch_content_post"]
