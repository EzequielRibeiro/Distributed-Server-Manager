#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from federation_repository import FederationRepository
from runtime_backend import backend_from_environment

def repo():
 r=FederationRepository(backend_from_environment());r.initialize();return r

def main(argv=None):
 p=argparse.ArgumentParser(prog="cap federation");sub=p.add_subparsers(dest="command",required=True)
 ls=sub.add_parser("member-list");ls.add_argument("--status");ls.add_argument("--json",action="store_true")
 add=sub.add_parser("member-set");add.add_argument("--controller",required=True);add.add_argument("--role",required=True,choices=("global","regional","datacenter"));add.add_argument("--region");add.add_argument("--datacenter");add.add_argument("--endpoint");add.add_argument("--status",default="active");add.add_argument("--json",action="store_true")
 cred=sub.add_parser("credential-issue");cred.add_argument("--controller",required=True);cred.add_argument("--json",action="store_true")
 inv=sub.add_parser("inventory");inv.add_argument("--json",action="store_true")
 pol=sub.add_parser("policy-set");pol.add_argument("--scope",required=True,choices=("global","region","datacenter","customer"));pol.add_argument("--scope-id");pol.add_argument("--mode",choices=("local_first","region_first","global"),default="local_first");pol.add_argument("--cross-region-fallback",action="store_true");pol.add_argument("--max-latency-ms",type=int);pol.add_argument("--json",action="store_true")
 a=p.parse_args(argv);r=repo()
 if a.command=="member-list":out=r.list_members(a.status)
 elif a.command=="member-set":out=r.put_member({"controller_id":a.controller,"role":a.role,"region_id":a.region,"datacenter_id":a.datacenter,"public_endpoint":a.endpoint,"status":a.status})
 elif a.command=="credential-issue":out=r.issue_credential(a.controller)
 elif a.command=="inventory":out=r.latest_inventory()
 else:out=r.put_policy({"scope_type":a.scope,"scope_id":a.scope_id,"mode":a.mode,"cross_region_fallback":a.cross_region_fallback,"max_latency_ms":a.max_latency_ms})
 if getattr(a,"json",False):print(json.dumps(out,indent=2,sort_keys=True,default=str))
 elif isinstance(out,list):
  for x in out:print(f"{x.get('controller_id',''):<28} {x.get('role',''):<12} {x.get('status','')} {x.get('datacenter_id','') or ''}")
 elif a.command=="credential-issue":print(out["credential"])
 else:print(json.dumps(out,sort_keys=True,default=str))
 return 0
if __name__=="__main__":raise SystemExit(main())
