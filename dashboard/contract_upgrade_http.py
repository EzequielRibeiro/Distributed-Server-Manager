#!/usr/bin/env python3
"""Administrative/Billing bridge for confirmed Customer Resource Profile upgrades."""
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse
from catalog_resource_profiles_http import catalog_resource_profiles
from contract_upgrade_repository import ContractUpgradeRepository
from instance_workspace_repository import InstanceWorkspaceRepository

PATH="/api/admin/contract-upgrades/confirm"

def install_contract_upgrade_api(legacy,authenticate,root:Path):
 previous=legacy.DashboardHandler.do_POST
 def post(self):
  if urlparse(self.path).path!=PATH:return previous(self)
  user=authenticate(self.headers)
  if user is None:self.unauthorized();return
  if str(user.get("role") or "").lower() not in {"admin","controller"}:self.send_json(403,{"error":"forbidden"});return
  try:
   body=self.read_json_body();request_id=str(body.get("request_id") or "").strip();billing_reference=str(body.get("billing_reference") or "").strip()
   workspace=InstanceWorkspaceRepository(legacy.dashboard_repository(legacy.DATABASE_FILE).backend);change=workspace.contract_change(request_id);context=workspace.instance_context(str(change["instance_id"]));catalog=catalog_resource_profiles(Path(root),str(context.get("game_id") or ""));profile=next((dict(x) for x in catalog.get("profiles") or [] if isinstance(x,dict) and str(x.get("id"))==str(change.get("requested_profile_id"))),None)
   if profile is None:raise LookupError("requested resource profile is no longer available")
   result=ContractUpgradeRepository(legacy.dashboard_repository(legacy.DATABASE_FILE).backend).apply_profile(request_id,profile,billing_reference=billing_reference,applied_by=str(user.get("username") or "billing"));self.send_json(202,result)
  except PermissionError as exc:self.send_json(403,{"error":"forbidden","message":str(exc)})
  except KeyError:self.send_json(404,{"error":"not_found"})
  except (ValueError,LookupError) as exc:self.send_json(400,{"error":"invalid_request","message":str(exc)})
  except Exception:self.send_json(500,{"error":"contract_upgrade_failed","message":"Não foi possível aplicar o upgrade contratado."})
 legacy.DashboardHandler.do_POST=post

__all__=["PATH","install_contract_upgrade_api"]
