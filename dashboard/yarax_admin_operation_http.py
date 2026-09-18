#!/usr/bin/env python3
"""HTTP adapter for YARA-X administrative operations."""
from __future__ import annotations
from urllib.parse import parse_qs,urlparse
from yarax_admin_operation_api import create_operation,list_operations

OPERATIONS_PATH="/api/admin/security/yara-x/operations"


def install_yarax_admin_operations_http(legacy,authenticate):
    previous_get=legacy.DashboardHandler.do_GET;previous_post=legacy.DashboardHandler.do_POST
    def backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
    def do_get(self):
        parsed=urlparse(self.path)
        if parsed.path!=OPERATIONS_PATH:return previous_get(self)
        user=authenticate(self.headers)
        if user is None:self.unauthorized();return
        q=parse_qs(parsed.query or "");one=lambda key:(q.get(key) or [None])[0]
        try:body=list_operations(user=user,backend=backend(),agent_id=one("agent_id"),limit=int(one("limit") or 100));self.send_json(200,body)
        except PermissionError as exc:self.send_json(403,{"error":"forbidden","message":str(exc)})
        except (ValueError,TypeError) as exc:self.send_json(400,{"error":"invalid_request","message":str(exc)})
    def do_post(self):
        parsed=urlparse(self.path)
        if parsed.path!=OPERATIONS_PATH:return previous_post(self)
        user=authenticate(self.headers)
        if user is None:self.unauthorized();return
        try:payload=self.read_json_body();body=create_operation(user=user,backend=backend(),payload=payload);self.send_json(202,body)
        except PermissionError as exc:self.send_json(403,{"error":"forbidden","message":str(exc)})
        except (ValueError,TypeError) as exc:self.send_json(400,{"error":"invalid_request","message":str(exc)})
    legacy.DashboardHandler.do_GET=do_get;legacy.DashboardHandler.do_POST=do_post


__all__=["OPERATIONS_PATH","install_yarax_admin_operations_http"]
