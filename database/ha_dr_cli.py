#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from ha_dr_repository import HADisasterRecoveryRepository
from runtime_backend import backend_from_environment

def repo():
 r=HADisasterRecoveryRepository(backend_from_environment());r.initialize();return r

def main(argv=None):
 p=argparse.ArgumentParser(prog="cap ha");sub=p.add_subparsers(dest="command",required=True)
 c=sub.add_parser("cluster-set");c.add_argument("--cluster",required=True);c.add_argument("--name",required=True);c.add_argument("--mode",choices=("manual","automatic"),default="manual");c.add_argument("--rpo-seconds",type=int,default=300);c.add_argument("--rto-seconds",type=int,default=900);c.add_argument("--quorum",type=int,default=2);c.add_argument("--auto-failback",action="store_true");c.add_argument("--json",action="store_true")
 m=sub.add_parser("member-set");m.add_argument("--cluster",required=True);m.add_argument("--controller",required=True);m.add_argument("--role",choices=("primary","standby","witness"),required=True);m.add_argument("--state",choices=("unknown","healthy","degraded","offline","fenced","disabled"),default="healthy");m.add_argument("--priority",type=int,default=100);m.add_argument("--json",action="store_true")
 s=sub.add_parser("status");s.add_argument("--cluster",required=True);s.add_argument("--json",action="store_true")
 r=sub.add_parser("recovery-point-create");r.add_argument("--cluster",required=True);r.add_argument("--controller",required=True);r.add_argument("--kind",choices=("database","configuration","control_plane"),default="control_plane");r.add_argument("--location",required=True);r.add_argument("--checksum");r.add_argument("--json",action="store_true")
 f=sub.add_parser("failover-request");f.add_argument("--cluster",required=True);f.add_argument("--target");f.add_argument("--reason",default="manual");f.add_argument("--requested-by");f.add_argument("--automatic",action="store_true");f.add_argument("--json",action="store_true")
 t=sub.add_parser("failover-transition");t.add_argument("--operation",required=True);t.add_argument("--state",required=True,choices=("requested","validating","fencing","promoting","converging","completed","failed","rolled_back"));t.add_argument("--message");t.add_argument("--json",action="store_true")
 a=p.parse_args(argv);rpo=repo()
 if a.command=="cluster-set":out=rpo.put_cluster({"cluster_id":a.cluster,"name":a.name,"mode":a.mode,"rpo_seconds":a.rpo_seconds,"rto_seconds":a.rto_seconds,"quorum_size":a.quorum,"auto_failback":a.auto_failback})
 elif a.command=="member-set":out=rpo.put_member({"cluster_id":a.cluster,"controller_id":a.controller,"role":a.role,"state":a.state,"priority":a.priority})
 elif a.command=="status":out=rpo.cluster_status(a.cluster)
 elif a.command=="recovery-point-create":out=rpo.create_recovery_point(a.cluster,source_controller_id=a.controller,kind=a.kind,location=a.location,checksum=a.checksum)
 elif a.command=="failover-request":out=rpo.request_failover(a.cluster,target_controller_id=a.target,reason=a.reason,requested_by=a.requested_by,automatic=a.automatic)
 else:out=rpo.transition_failover(a.operation,a.state,message=a.message)
 if getattr(a,"json",False):print(json.dumps(out,indent=2,sort_keys=True,default=str))
 else:print(json.dumps(out,sort_keys=True,default=str))
 return 0
if __name__=="__main__":raise SystemExit(main())
