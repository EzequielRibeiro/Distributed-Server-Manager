#!/usr/bin/env python3
"""Backend-neutral persistence for E2 High Availability & Disaster Recovery."""
from __future__ import annotations
import json, sys
from pathlib import Path
from typing import Any, Mapping
ROOT=Path(__file__).resolve().parents[1]; CORE=ROOT/'core'
if str(CORE) not in sys.path: sys.path.insert(0,str(CORE))
from alert_repository import AlertSession
from ha_dr import FAILOVER_STATES,HACluster,HAClusterMember,failover_operation_id,next_fencing_epoch,quorum_satisfied,recovery_point_id,select_failover_candidate,utc_now,validate_id

class HADisasterRecoveryRepository:
    def __init__(self,backend): self.backend=backend
    def initialize(self): return self.backend.initialize()
    @property
    def ph(self): return '?' if self.backend.name=='sqlite' else '%s'
    def _rows(self,sql,args=()):
        with self.backend.connect() as c:
            s=AlertSession(self.backend,c)
            try: return [dict(x) for x in s.execute(sql,args).fetchall()]
            finally: s.close()
    def put_cluster(self,raw:Mapping[str,Any]):
        x=HACluster(raw.get('cluster_id'),raw.get('name'),raw.get('mode','manual'),raw.get('rpo_seconds',300),raw.get('rto_seconds',900),raw.get('quorum_size',2),bool(raw.get('auto_failback',False))).normalized(); now=utc_now()
        with self.backend.transaction() as c:
            s=AlertSession(self.backend,c)
            try:
                old=s.execute(f'SELECT cluster_id FROM ha_clusters WHERE cluster_id={self.ph}',(x['cluster_id'],)).fetchone()
                if old: s.execute(f'UPDATE ha_clusters SET name={self.ph},mode={self.ph},rpo_seconds={self.ph},rto_seconds={self.ph},quorum_size={self.ph},auto_failback={self.ph},updated_at={self.ph} WHERE cluster_id={self.ph}',(x['name'],x['mode'],x['rpo_seconds'],x['rto_seconds'],x['quorum_size'],int(x['auto_failback']),now,x['cluster_id']))
                else: s.execute(f"INSERT INTO ha_clusters(cluster_id,name,mode,rpo_seconds,rto_seconds,quorum_size,auto_failback,fencing_epoch,created_at,updated_at) VALUES ({','.join([self.ph]*10)})",(x['cluster_id'],x['name'],x['mode'],x['rpo_seconds'],x['rto_seconds'],x['quorum_size'],int(x['auto_failback']),0,now,now))
            finally:s.close()
        return x
    def put_member(self,raw:Mapping[str,Any]):
        x=HAClusterMember(raw.get('cluster_id'),raw.get('controller_id'),raw.get('role'),raw.get('state','unknown'),raw.get('priority',100)).normalized(); now=utc_now()
        with self.backend.transaction() as c:
            s=AlertSession(self.backend,c)
            try:
                old=s.execute(f'SELECT controller_id FROM ha_cluster_members WHERE cluster_id={self.ph} AND controller_id={self.ph}',(x['cluster_id'],x['controller_id'])).fetchone()
                if old:s.execute(f'UPDATE ha_cluster_members SET role={self.ph},state={self.ph},priority={self.ph},last_seen_at={self.ph},updated_at={self.ph} WHERE cluster_id={self.ph} AND controller_id={self.ph}',(x['role'],x['state'],x['priority'],now,now,x['cluster_id'],x['controller_id']))
                else:s.execute(f"INSERT INTO ha_cluster_members(cluster_id,controller_id,role,state,priority,last_seen_at,created_at,updated_at) VALUES ({','.join([self.ph]*8)})",(x['cluster_id'],x['controller_id'],x['role'],x['state'],x['priority'],now,now,now))
            finally:s.close()
        return x
    def list_members(self,cluster_id):
        cluster_id=validate_id(cluster_id,'cluster_id'); return self._rows(f'SELECT * FROM ha_cluster_members WHERE cluster_id={self.ph} ORDER BY priority,controller_id',(cluster_id,))
    def cluster_status(self,cluster_id):
        cluster_id=validate_id(cluster_id,'cluster_id'); rows=self._rows(f'SELECT * FROM ha_clusters WHERE cluster_id={self.ph}',(cluster_id,))
        if not rows: raise ValueError('HA cluster not found')
        cluster=rows[0]; members=self.list_members(cluster_id); primary=next((m for m in members if m['role']=='primary' and m['state'] not in {'fenced','disabled'}),None); candidate=select_failover_candidate(members,exclude_controller_id=primary['controller_id'] if primary else None)
        return {'cluster':cluster,'members':members,'quorum':quorum_satisfied(members,int(cluster['quorum_size'])),'primary':primary,'candidate':candidate}
    def mark_member_state(self,cluster_id,controller_id,state):
        cluster_id=validate_id(cluster_id,'cluster_id'); controller_id=validate_id(controller_id,'controller_id'); state=str(state).lower()
        if state not in {'unknown','healthy','degraded','offline','fenced','disabled'}: raise ValueError('invalid HA member state')
        now=utc_now()
        with self.backend.transaction() as c:
            s=AlertSession(self.backend,c)
            try:s.execute(f'UPDATE ha_cluster_members SET state={self.ph},updated_at={self.ph} WHERE cluster_id={self.ph} AND controller_id={self.ph}',(state,now,cluster_id,controller_id))
            finally:s.close()
        return {'cluster_id':cluster_id,'controller_id':controller_id,'state':state}
    def promote_member(self,cluster_id,controller_id,*,fencing_epoch:int):
        cluster_id=validate_id(cluster_id,'cluster_id'); controller_id=validate_id(controller_id,'controller_id'); now=utc_now()
        with self.backend.transaction() as c:
            s=AlertSession(self.backend,c)
            try:
                row=s.execute(f'SELECT fencing_epoch FROM ha_clusters WHERE cluster_id={self.ph}',(cluster_id,)).fetchone()
                if row is None or int(row['fencing_epoch'])!=int(fencing_epoch): raise RuntimeError('stale fencing epoch; promotion refused')
                s.execute(f"UPDATE ha_cluster_members SET role='standby',updated_at={self.ph} WHERE cluster_id={self.ph} AND role='primary' AND controller_id<>{self.ph}",(now,cluster_id,controller_id))
                s.execute(f"UPDATE ha_cluster_members SET role='primary',state='healthy',last_seen_at={self.ph},updated_at={self.ph} WHERE cluster_id={self.ph} AND controller_id={self.ph}",(now,now,cluster_id,controller_id))
            finally:s.close()
        return {'cluster_id':cluster_id,'controller_id':controller_id,'role':'primary','fencing_epoch':int(fencing_epoch)}
    def create_recovery_point(self,cluster_id,*,source_controller_id,kind,location,checksum=None,metadata=None):
        cluster_id=validate_id(cluster_id,'cluster_id'); source_controller_id=validate_id(source_controller_id,'source_controller_id'); kind=str(kind or 'database').lower()
        if kind not in {'database','configuration','control_plane'}: raise ValueError('invalid recovery point kind')
        if not str(location or '').strip(): raise ValueError('recovery point location is required')
        pid=recovery_point_id(cluster_id); now=utc_now(); payload=json.dumps(dict(metadata or {}),sort_keys=True,separators=(',',':'))
        with self.backend.transaction() as c:
            s=AlertSession(self.backend,c)
            try:s.execute(f"INSERT INTO dr_recovery_points(recovery_point_id,cluster_id,source_controller_id,kind,state,location,checksum,metadata_json,created_at,validated_at) VALUES ({','.join([self.ph]*10)})",(pid,cluster_id,source_controller_id,kind,'ready',str(location),checksum,payload,now,now))
            finally:s.close()
        return {'recovery_point_id':pid,'cluster_id':cluster_id,'state':'ready','created_at':now}
    def get_recovery_point(self,recovery_point_id):
        recovery_point_id=validate_id(recovery_point_id,'recovery_point_id'); rows=self._rows(f'SELECT * FROM dr_recovery_points WHERE recovery_point_id={self.ph}',(recovery_point_id,));
        if not rows: raise ValueError('recovery point not found')
        return rows[0]
    def request_failover(self,cluster_id,*,target_controller_id=None,reason='manual',requested_by=None,automatic=False):
        status=self.cluster_status(cluster_id)
        if not status['quorum']: raise RuntimeError('HA quorum not satisfied')
        if automatic and str(status['cluster']['mode'])!='automatic': raise RuntimeError('automatic failover is disabled')
        candidate=status['candidate']
        if target_controller_id:
            target_controller_id=validate_id(target_controller_id,'target_controller_id'); candidate=next((m for m in status['members'] if m['controller_id']==target_controller_id and m['role']=='standby' and m['state'] in {'healthy','degraded'}),None)
        if candidate is None: raise RuntimeError('no eligible standby controller')
        op=failover_operation_id(cluster_id); now=utc_now()
        with self.backend.transaction() as c:
            s=AlertSession(self.backend,c)
            try:
                row=s.execute(f'SELECT fencing_epoch FROM ha_clusters WHERE cluster_id={self.ph}',(cluster_id,)).fetchone(); epoch=next_fencing_epoch(row['fencing_epoch'] if row else 0)
                s.execute(f'UPDATE ha_clusters SET fencing_epoch={self.ph},updated_at={self.ph} WHERE cluster_id={self.ph}',(epoch,now,cluster_id))
                s.execute(f"INSERT INTO ha_failover_operations(operation_id,cluster_id,source_controller_id,target_controller_id,state,reason,requested_by,automatic,fencing_epoch,created_at,updated_at) VALUES ({','.join([self.ph]*11)})",(op,cluster_id,status['primary']['controller_id'] if status['primary'] else None,candidate['controller_id'],'requested',str(reason)[:512],requested_by,int(automatic),epoch,now,now))
            finally:s.close()
        return {'operation_id':op,'cluster_id':cluster_id,'target_controller_id':candidate['controller_id'],'state':'requested','fencing_epoch':epoch}
    def get_failover_operation(self,operation_id):
        operation_id=validate_id(operation_id,'operation_id'); rows=self._rows(f'SELECT * FROM ha_failover_operations WHERE operation_id={self.ph}',(operation_id,));
        if not rows: raise ValueError('failover operation not found')
        return rows[0]
    def transition_failover(self,operation_id,state,*,message=None):
        operation_id=validate_id(operation_id,'operation_id'); state=str(state or '').lower()
        if state not in FAILOVER_STATES: raise ValueError('invalid failover state')
        now=utc_now()
        with self.backend.transaction() as c:
            s=AlertSession(self.backend,c)
            try:
                if s.execute(f'SELECT operation_id FROM ha_failover_operations WHERE operation_id={self.ph}',(operation_id,)).fetchone() is None: raise ValueError('failover operation not found')
                s.execute(f'UPDATE ha_failover_operations SET state={self.ph},message={self.ph},updated_at={self.ph},completed_at={self.ph} WHERE operation_id={self.ph}',(state,message,now,now if state in {'completed','failed','rolled_back'} else None,operation_id))
            finally:s.close()
        return {'operation_id':operation_id,'state':state,'updated_at':now}
