#!/usr/bin/env python3
"""Administrative CLI for E1 Multi-Datacenter Federation."""
from __future__ import annotations
import argparse,json
from federation import FederationController,FederationPlacementRequest,FederationRoute
from federation_repository import FederationRepository
from runtime_backend import backend_from_environment

def main(argv=None):
 p=argparse.ArgumentParser(prog="cap federation");s=p.add_subparsers(dest="command",required=True)
 for name in ("status","members","inventory","policy-show","handoffs","credentials"):
  q=s.add_parser(name);q.add_argument("--json",action="store_true")
 q=s.add_parser("peer-add");q.add_argument("controller_id");q.add_argument("endpoint");q.add_argument("--region");q.add_argument("--datacenter");q.add_argument("--role",default="datacenter");q.add_argument("--priority",type=int,default=100);q.add_argument("--json",action="store_true")
 q=s.add_parser("peer-disable");q.add_argument("controller_id");q.add_argument("--json",action="store_true")
 q=s.add_parser("credential-issue");q.add_argument("controller_id");q.add_argument("--expires-at");q.add_argument("--json",action="store_true")
 q=s.add_parser("credential-revoke");q.add_argument("credential_id");q.add_argument("--json",action="store_true")
 q=s.add_parser("policy-set");q.add_argument("scope_type");q.add_argument("scope_id");q.add_argument("controller_id");q.add_argument("--priority",type=int,default=100);q.add_argument("--disabled",action="store_true");q.add_argument("--json",action="store_true")
 q=s.add_parser("handoff-create");q.add_argument("request_id");q.add_argument("instance_id");q.add_argument("game_id");q.add_argument("--customer");q.add_argument("--region");q.add_argument("--datacenter");q.add_argument("--mode",default="local_first");q.add_argument("--cross-region",action="store_true");q.add_argument("--json",action="store_true")
 a=p.parse_args(argv);r=FederationRepository(backend_from_environment());r.initialize()
 if a.command=="status":
  changed=r.refresh_health();members=r.list_controllers(include_disabled=True);out={"kind":"FederationStatus","controllers":len(members),"online":sum(1 for x in members if x["status"]=="online"),"changed":changed}
 elif a.command=="members":out=r.list_controllers(include_disabled=True)
 elif a.command=="inventory":out=r.global_inventory()
 elif a.command=="policy-show":out=r.list_routes()
 elif a.command=="handoffs":out=r.list_handoffs()
 elif a.command=="credentials":out=r.list_credentials()
 elif a.command=="peer-add":out=r.upsert_controller(FederationController(a.controller_id,a.endpoint,a.region,a.datacenter,a.role,"pending",a.priority))
 elif a.command=="peer-disable":out=r.set_controller_status(a.controller_id,"disabled")
 elif a.command=="credential-issue":out=r.issue_credential(a.controller_id,expires_at=a.expires_at)
 elif a.command=="credential-revoke":out=r.revoke_credential(a.credential_id)
 elif a.command=="policy-set":out=r.upsert_route(FederationRoute(a.scope_type,a.scope_id,a.controller_id,a.priority,not a.disabled))
 else:out=r.create_handoff(FederationPlacementRequest(a.request_id,a.instance_id,a.game_id,a.customer,a.region,a.datacenter,a.mode,a.cross_region))
 print(json.dumps(out,indent=2 if getattr(a,"json",False) else None,sort_keys=True,default=str));return 0
if __name__=="__main__":raise SystemExit(main())
