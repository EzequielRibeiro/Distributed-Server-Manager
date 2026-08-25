#!/usr/bin/env python3
"""Catalog architecture stages 5-10, Customer Workspace and final audit layer."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import parse_qs,urlparse
import server_part16 as integration
from artifact_transfer_http import install_artifact_transfer_http
from catalog_runtime_policy_http import RUNTIME_POLICY_PATH,dispatch_catalog_runtime_policy_get,dispatch_catalog_runtime_policy_put
from contract_upgrade_http import install_contract_upgrade_api
from controller_telemetry import controller_telemetry
from customer_instance_creation import install_customer_instance_creation
from customer_instance_team_http import install_customer_instance_team
from customer_instance_workspace_http import install_customer_instance_workspace
from customer_management_http import install_customer_management_dashboard
from dashboard_activity_http import install_dashboard_activity_audit
from deleted_backup_vault_http import install_deleted_backup_vault_http
from json_serialization import normalize_json_value
from system_user_admin_http import install_system_user_administration
legacy=integration.legacy
install_customer_instance_creation(legacy);install_customer_management_dashboard(legacy)
_previous_get=legacy.DashboardHandler.do_GET;_previous_put=getattr(legacy.DashboardHandler,"do_PUT",None);_previous_send_json=legacy.DashboardHandler.send_json;_authenticate=integration._authenticate;_ROOT=Path(__file__).resolve().parents[1];_CONTROLLER_TELEMETRY_PATH="/api/controller/telemetry"
legacy.STATIC_FILES.update({"/telemetry-widgets.css":legacy.WEB_DIR/"telemetry-widgets.css","/telemetry-widgets.js":legacy.WEB_DIR/"telemetry-widgets.js"})
def json_safe_send_json(self,code,payload):return _previous_send_json(self,code,normalize_json_value(payload))
def _controller_telemetry_get(self,parsed):
 user=_authenticate(self.headers)
 if user is None:self.unauthorized();return
 if str(user.get("role") or "").lower() not in {"admin","controller"}:self.send_json(403,{"error":"forbidden"});return
 values=parse_qs(parsed.query or "")
 try:window=int((values.get("window_seconds") or ["3600"])[0])
 except ValueError:window=3600
 self.send_json(200,controller_telemetry(window))
def catalog_architecture_get(self):
 parsed=urlparse(self.path)
 if parsed.path==_CONTROLLER_TELEMETRY_PATH:return _controller_telemetry_get(self,parsed)
 if parsed.path!=RUNTIME_POLICY_PATH:return _previous_get(self)
 user=_authenticate(self.headers)
 if user is None:self.unauthorized();return
 status,body=dispatch_catalog_runtime_policy_get(parsed.path,parsed.query,user=user,root=_ROOT);self.send_json(status,body)
def catalog_architecture_put(self):
 parsed=urlparse(self.path)
 if parsed.path!=RUNTIME_POLICY_PATH:
  if _previous_put is not None:return _previous_put(self)
  self.send_json(404,{"error":"not_found"});return
 user=_authenticate(self.headers)
 if user is None:self.unauthorized();return
 try:payload=self.read_json_body()
 except ValueError:self.send_json(400,{"error":"invalid_request","message":"Requisição inválida."});return
 status,body=dispatch_catalog_runtime_policy_put(parsed.path,payload,user=user,root=_ROOT);self.send_json(status,body)
legacy.DashboardHandler.send_json=json_safe_send_json;legacy.DashboardHandler.do_GET=catalog_architecture_get;legacy.DashboardHandler.do_PUT=catalog_architecture_put
install_system_user_administration(legacy,_authenticate)
# Install every human-facing module before the outer audit wrapper.
install_customer_instance_workspace(legacy,_authenticate)
install_customer_instance_team(legacy,_authenticate)
install_contract_upgrade_api(legacy,_authenticate,_ROOT)
install_artifact_transfer_http(legacy,_authenticate)
install_deleted_backup_vault_http(legacy,_authenticate)
install_dashboard_activity_audit(legacy,_authenticate)
def run():legacy.run()
if __name__=="__main__":run()
