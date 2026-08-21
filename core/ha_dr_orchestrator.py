#!/usr/bin/env python3
"""Operational orchestration for E2 HA/DR."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

def _parse_time(value:str|None)->datetime|None:
    if not value:return None
    try:dt=datetime.fromisoformat(str(value).strip().replace('Z','+00:00'))
    except ValueError:return None
    if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def member_is_stale(member:Mapping[str,Any],*,now:datetime|None=None,timeout_seconds:int=45)->bool:
    now=now or datetime.now(timezone.utc);seen=_parse_time(member.get('last_seen_at'))
    return True if seen is None else (now-seen).total_seconds()>max(5,int(timeout_seconds))

def recovery_point_within_rpo(point:Mapping[str,Any],rpo_seconds:int,*,now:datetime|None=None)->bool:
    now=now or datetime.now(timezone.utc);created=_parse_time(point.get('created_at'))
    return bool(created and (now-created).total_seconds()<=max(0,int(rpo_seconds)))

@dataclass
class FailoverHooks:
    fence:Callable[[str,int],bool]
    promote:Callable[[str,int],bool]
    converge:Callable[[str,int],bool]
    demote:Callable[[str,int],bool]|None=None
    restore:Callable[[Mapping[str,Any]],bool]|None=None
    emit:Callable[[str,Mapping[str,Any]],None]|None=None

class HADROrchestrator:
    def __init__(self,repository:Any,hooks:FailoverHooks):self.repository=repository;self.hooks=hooks
    def _emit(self,event_type:str,data:Mapping[str,Any]):
        if self.hooks.emit:self.hooks.emit(event_type,dict(data))
    def detect_primary_failure(self,cluster_id:str,*,timeout_seconds:int=45)->dict[str,Any]:
        status=self.repository.cluster_status(cluster_id);primary=status.get('primary');failed=primary is None or str(primary.get('state')) in {'offline','fenced','disabled'}
        if primary and not failed:failed=member_is_stale(primary,timeout_seconds=timeout_seconds)
        out={'cluster_id':cluster_id,'failed':failed,'primary':primary,'quorum':bool(status.get('quorum')),'candidate':status.get('candidate')}
        if failed:self._emit('HA_PRIMARY_FAILURE_DETECTED',out)
        return out
    def automatic_failover(self,cluster_id:str,*,timeout_seconds:int=45,requested_by:str='ha-monitor'):
        detected=self.detect_primary_failure(cluster_id,timeout_seconds=timeout_seconds)
        if not detected['failed']:return None
        if not detected['quorum']:raise RuntimeError('primary failure detected but quorum is unavailable; refusing promotion')
        op=self.repository.request_failover(cluster_id,reason='primary failure detected',requested_by=requested_by,automatic=True);return self.execute_failover(op['operation_id'])
    def execute_failover(self,operation_id:str):
        op=self.repository.get_failover_operation(operation_id);source=op.get('source_controller_id');target=op.get('target_controller_id');epoch=int(op.get('fencing_epoch') or 0)
        if not target or epoch<=0:raise RuntimeError('invalid failover operation')
        self._emit('HA_FAILOVER_STARTED',op);self.repository.transition_failover(operation_id,'validating',message='quorum and target validated')
        if source:
            self.repository.transition_failover(operation_id,'fencing',message='fencing former primary')
            if not self.hooks.fence(source,epoch):
                self.repository.transition_failover(operation_id,'failed',message='fencing failed; promotion refused');self._emit('HA_FAILOVER_FAILED',{'operation_id':operation_id,'reason':'fencing'});raise RuntimeError('fencing failed; promotion refused')
            self.repository.mark_member_state(op['cluster_id'],source,'fenced')
        self.repository.transition_failover(operation_id,'promoting',message='promoting standby')
        if not self.hooks.promote(target,epoch):
            self.repository.transition_failover(operation_id,'failed',message='standby promotion failed');self._emit('HA_FAILOVER_FAILED',{'operation_id':operation_id,'reason':'promotion'});raise RuntimeError('standby promotion failed')
        self.repository.promote_member(op['cluster_id'],target,fencing_epoch=epoch);self.repository.transition_failover(operation_id,'converging',message='converging control-plane services')
        if not self.hooks.converge(target,epoch):
            self.repository.transition_failover(operation_id,'failed',message='post-promotion convergence failed');self._emit('HA_FAILOVER_FAILED',{'operation_id':operation_id,'reason':'convergence'});raise RuntimeError('post-promotion convergence failed')
        out=self.repository.transition_failover(operation_id,'completed',message='failover completed');self._emit('HA_FAILOVER_COMPLETED',{'operation_id':operation_id,'cluster_id':op['cluster_id'],'target_controller_id':target,'fencing_epoch':epoch});return out
    def failback(self,cluster_id:str,target_controller_id:str,*,requested_by:str='operator'):
        op=self.repository.request_failover(cluster_id,target_controller_id=target_controller_id,reason='controlled failback',requested_by=requested_by,automatic=False);return self.execute_failover(op['operation_id'])
    def restore_recovery_point(self,recovery_point:Mapping[str,Any],*,rpo_seconds:int|None=None)->bool:
        if str(recovery_point.get('state'))!='ready':raise RuntimeError('recovery point is not ready')
        if rpo_seconds is not None and not recovery_point_within_rpo(recovery_point,rpo_seconds):raise RuntimeError('recovery point exceeds configured RPO')
        if self.hooks.restore is None:raise RuntimeError('restore hook is not configured')
        self._emit('DR_RESTORE_STARTED',{'recovery_point_id':recovery_point.get('recovery_point_id')});ok=bool(self.hooks.restore(recovery_point));self._emit('DR_RESTORE_COMPLETED' if ok else 'DR_RESTORE_FAILED',{'recovery_point_id':recovery_point.get('recovery_point_id')});return ok
