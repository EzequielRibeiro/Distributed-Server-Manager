#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse
from server_update_http import SERVER_UPDATES_PATH,SERVER_UPDATE_OPERATION_PATH,dispatch_server_update_get,dispatch_server_update_post

def install_server_update_http(legacy,authenticate,root:Path):
 previous_get=legacy.DashboardHandler.do_GET;previous_post=legacy.DashboardHandler.do_POST
 legacy.STATIC_FILES['/server-updates.html']=legacy.WEB_DIR/'server-updates.html';legacy.STATIC_FILES['/server-updates.js']=legacy.WEB_DIR/'server-updates.js'
 def do_get(self):
  parsed=urlparse(self.path)
  if parsed.path not in {SERVER_UPDATES_PATH,'/server-updates.html'}:return previous_get(self)
  user=authenticate(self.headers)
  if user is None:self.unauthorized();return
  if parsed.path=='/server-updates.html':
   if str(user.get('role') or '').lower()!='admin':self.forbidden();return
   self.send_file(legacy.WEB_DIR/'server-updates.html');return
  result=dispatch_server_update_get(parsed.path,parsed.query,user=user,backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend);status,body=result;self.send_json(status,body)
 def do_post(self):
  parsed=urlparse(self.path)
  if parsed.path not in {SERVER_UPDATES_PATH,SERVER_UPDATE_OPERATION_PATH}:return previous_post(self)
  user=authenticate(self.headers)
  if user is None:self.unauthorized();return
  try:payload=self.read_json_body()
  except ValueError:self.send_json(400,{'error':'invalid_request','message':'Requisição inválida.'});return
  result=dispatch_server_update_post(parsed.path,payload,user=user,backend=legacy.dashboard_repository(legacy.DATABASE_FILE).backend,root=root);status,body=result;self.send_json(status,body)
 legacy.DashboardHandler.do_GET=do_get;legacy.DashboardHandler.do_POST=do_post

__all__=['install_server_update_http']
