#!/usr/bin/env python3
"""Catalog architecture stages 5-10, Customer Workspace and final audit layer."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import parse_qs,urlparse
import server_part16 as integration
import server_part8 as browser_login_base
from admin_observability_http import install_admin_observability
from agent_admin_http import install_agent_administration
from agent_public_network_http import install_agent_public_network
from agent_storage_pool_admin_http import install_agent_storage_pool_administration
from alert_management_http import install_alert_management
from artifact_transfer_http import install_artifact_transfer_http
from backup_clone_http import install_backup_clone_http
from browser_session_http import install_browser_session_http
from catalog_runtime_policy_http import RUNTIME_POLICY_PATH,dispatch_catalog_runtime_policy_get,dispatch_catalog_runtime_policy_put
from contract_upgrade_http import install_contract_upgrade_api
from controller_telemetry import controller_telemetry
from customer_discord_http import install_customer_discord
from customer_discord_oauth_http import install_customer_discord_oauth_callback
from customer_discord_schema_runtime import ensure_customer_discord_schema
from customer_email_change_http import install_customer_email_change
from customer_health_http import install_customer_health_http
from customer_instance_activity_http import install_customer_instance_activity
from customer_instance_connection_http import install_customer_instance_connection
from customer_instance_creation import install_customer_instance_creation
from customer_instance_team_http import install_customer_instance_team
from customer_instance_workspace_http import install_customer_instance_workspace
from customer_management_http import install_customer_management_dashboard
from customer_placement_locations_http import install_customer_placement_locations
from customer_profile_admin_http import install_customer_profile_administration
from customer_profile_self_service_http import install_customer_profile_self_service
from dashboard_activity_http import install_dashboard_activity_audit
from deleted_backup_vault_http import install_deleted_backup_vault_http
from json_serialization import normalize_json_value
from portal_navigation_session_http import install_portal_navigation_session_guard
from storage_pool_source_cleanup_http import install_storage_pool_source_cleanup
from system_user_admin_http import install_system_user_administration
from tls_runtime import run_dashboard
legacy=integration.legacy
install_customer_instance_creation(legacy);install_customer_management_dashboard(legacy)
_previous_get=legacy.DashboardHandler.do_GET;_previous_put=getattr(legacy.DashboardHandler,"do_PUT",None);_previous_send_json=legacy.DashboardHandler.send_json;_controller_authenticate=integration._controller_authenticate;_customer_authenticate=integration._customer_authenticate;_legacy_ambiguous_authenticate=browser_login_base.integrated_authenticate;_ROOT=Path(__file__).resolve().parents[1];_CONTROLLER_TELEMETRY_PATH="/api/controller/telemetry"


def _area_aware_authenticate(headers):
    """Resolve shared endpoints without guessing when both cookies coexist."""
    area=str(headers.get("X-Capivara-Auth-Area") or "").strip().lower()
    if area=="controller":return _controller_authenticate(headers)
    if area=="customer":return _customer_authenticate(headers)
    return _legacy_ambiguous_authenticate(headers)


browser_login_base.integrated_authenticate=_area_aware_authenticate
legacy.authenticate=_area_aware_authenticate
legacy.STATIC_FILES.update({"/browser-auth-client.js":legacy.WEB_DIR/"browser-auth-client.js","/telemetry-widgets.css":legacy.WEB_DIR/"telemetry-widgets.css","/telemetry-widgets.js":legacy.WEB_DIR/"telemetry-widgets.js","/dashboard-node-overview.css":legacy.WEB_DIR/"dashboard-node-overview.css","/dashboard-node-overview.js":legacy.WEB_DIR/"dashboard-node-overview.js","/customer-placement-selector.js":legacy.WEB_DIR/"customer-placement-selector.js","/customer-profile.js":legacy.WEB_DIR/"customer-profile.js","/customer-email-change.js":legacy.WEB_DIR/"customer-email-change.js","/customer-navigation.js":legacy.WEB_DIR/"customer-navigation.js","/customer.js":legacy.WEB_DIR/"customer-shell.js","/customer-core.js":legacy.WEB_DIR/"customer.js","/customer-integrations.html":legacy.WEB_DIR/"customer-integrations.html","/customer-integrations.js":legacy.WEB_DIR/"customer-integrations.js","/customer-integrations.css":legacy.WEB_DIR/"customer-integrations.css","/customer-backups.html":legacy.WEB_DIR/"customer-backups.html","/customer-backups.js":legacy.WEB_DIR/"customer-backups.js","/customer-account.html":legacy.WEB_DIR/"customer-account.html","/customer-account.js":legacy.WEB_DIR/"customer-account.js"})
def json_safe_send_json(self,code,payload):return _previous_send_json(self,code,normalize_json_value(payload))
def _controller_telemetry_get(self,parsed):
 user=_controller_authenticate(self.headers)
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
 user=_controller_authenticate(self.headers)
 if user is None:self.unauthorized();return
 status,body=dispatch_catalog_runtime_policy_get(parsed.path,parsed.query,user=user,root=_ROOT);self.send_json(status,body)
def catalog_architecture_put(self):
 parsed=urlparse(self.path)
 if parsed.path!=RUNTIME_POLICY_PATH:
  if _previous_put is not None:return _previous_put(self)
  self.send_json(404,{"error":"not_found"});return
 user=_controller_authenticate(self.headers)
 if user is None:self.unauthorized();return
 try:payload=self.read_json_body()
 except ValueError:self.send_json(400,{"error":"invalid_request","message":"Requisição inválida."});return
 status,body=dispatch_catalog_runtime_policy_put(parsed.path,payload,user=user,root=_ROOT);self.send_json(status,body)
legacy.DashboardHandler.send_json=json_safe_send_json;legacy.DashboardHandler.do_GET=catalog_architecture_get;legacy.DashboardHandler.do_PUT=catalog_architecture_put
install_system_user_administration(legacy,_controller_authenticate)
install_customer_instance_workspace(legacy,_customer_authenticate)
install_customer_instance_connection(legacy,_customer_authenticate)
install_customer_instance_team(legacy,_customer_authenticate)
install_customer_instance_activity(legacy,_customer_authenticate)
install_contract_upgrade_api(legacy,_controller_authenticate,_ROOT)
install_artifact_transfer_http(legacy,_customer_authenticate)
install_deleted_backup_vault_http(legacy,_customer_authenticate)
install_backup_clone_http(legacy,_customer_authenticate)
install_dashboard_activity_audit(legacy,_controller_authenticate)
install_alert_management(legacy,_controller_authenticate)
install_customer_health_http(legacy,_customer_authenticate)
install_agent_administration(legacy,_controller_authenticate)
install_agent_public_network(legacy,_controller_authenticate)
install_agent_storage_pool_administration(legacy,_controller_authenticate)
install_storage_pool_source_cleanup(legacy,_controller_authenticate)
install_customer_profile_administration(legacy,_controller_authenticate)
install_customer_profile_self_service(legacy,_customer_authenticate)
install_customer_email_change(legacy,_controller_authenticate)
install_customer_placement_locations(legacy,_customer_authenticate)
ensure_customer_discord_schema(legacy)
install_customer_discord(legacy,_customer_authenticate)
install_customer_discord_oauth_callback(legacy)
install_admin_observability(legacy,_controller_authenticate)
install_browser_session_http(legacy,browser_login_base.credential_authenticate)
install_portal_navigation_session_guard(legacy)
def run():run_dashboard(legacy)
if __name__=="__main__":run()
