#!/usr/bin/env python3
"""C4 Universal Content HTTP composition layer."""
from __future__ import annotations
from urllib.parse import urlparse
import server_part13 as integration
from content_http import CONTENT_PATH,dispatch_content_get,dispatch_content_post
legacy=integration.legacy
_previous_get=legacy.DashboardHandler.do_GET;_previous_post=legacy.DashboardHandler.do_POST
_authenticate=integration._authenticate

def _backend():return legacy.dashboard_repository(legacy.DATABASE_FILE).backend
def _user(self):
 user=_authenticate(self.headers)
 if user is None:self.unauthorized()
 return user
def integrated_get(self):
 parsed=urlparse(self.path)
 if parsed.path!=CONTENT_PATH:return _previous_get(self)
 user=_user(self)
 if user is None:return
 status,body=dispatch_content_get(parsed.path,parsed.query,user=user,backend=_backend());self.send_json(status,body)
def integrated_post(self):
 parsed=urlparse(self.path)
 if parsed.path!=CONTENT_PATH:return _previous_post(self)
 user=_user(self)
 if user is None:return
 try:payload=self.read_json_body()
 except ValueError:self.send_json(400,{"error":"invalid_request","message":"Requisição inválida."});return
 status,body=dispatch_content_post(parsed.path,payload,user=user,backend=_backend());self.send_json(status,body)
legacy.DashboardHandler.do_GET=integrated_get;legacy.DashboardHandler.do_POST=integrated_post
def run():legacy.run()
if __name__=="__main__":run()
