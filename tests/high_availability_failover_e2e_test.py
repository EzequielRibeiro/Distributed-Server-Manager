#!/usr/bin/env python3
"""Pure contract E2E tests for E2 operational failover."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'core'),str(ROOT/'database')]
from ha_dr_orchestrator import HADROrchestrator,FailoverHooks,member_is_stale

class Repo:
    def __init__(self,mode='automatic',quorum=True):
        self.cluster={'cluster_id':'ha1','mode':mode,'quorum_size':2,'fencing_epoch':0}
        self.members=[{'cluster_id':'ha1','controller_id':'a','role':'primary','state':'offline','priority':1,'last_seen_at':'2000-01-01T00:00:00Z'},{'cluster_id':'ha1','controller_id':'b','role':'standby','state':'healthy','priority':2,'last_seen_at':'2999-01-01T00:00:00Z'},{'cluster_id':'ha1','controller_id':'w','role':'witness','state':'healthy','priority':3,'last_seen_at':'2999-01-01T00:00:00Z'}]
        self.ops={}
    def cluster_status(self,c): return {'cluster':self.cluster,'members':self.members,'quorum':self.quorum,'primary':next((x for x in self.members if x['role']=='primary' and x['state'] not in {'fenced','disabled'}),None),'candidate':next((x for x in self.members if x['role']=='standby' and x['state']=='healthy'),None)}
    def request_failover(self,c,**kw):
        if not self.quorum: raise RuntimeError('HA quorum not satisfied')
        if kw.get('automatic') and self.cluster['mode']!='automatic': raise RuntimeError('automatic failover is disabled')
        target=kw.get('target_controller_id') or 'b'; self.cluster['fencing_epoch']+=1; op={'operation_id':'op1','cluster_id':c,'source_controller_id':'a','target_controller_id':target,'state':'requested','fencing_epoch':self.cluster['fencing_epoch']}; self.ops['op1']=op; return op
    def get_failover_operation(self,o): return self.ops[o]
    def transition_failover(self,o,state,**kw): self.ops[o]['state']=state; return {'operation_id':o,'state':state}
    def mark_member_state(self,c,i,state): next(x for x in self.members if x['controller_id']==i).update(state=state)
    def promote_member(self,c,i,**kw):
        assert kw['fencing_epoch']==self.cluster['fencing_epoch']
        for x in self.members:
            if x['role']=='primary': x['role']='standby'
        next(x for x in self.members if x['controller_id']==i).update(role='primary',state='healthy')

def test_success():
    calls=[]; r=Repo(); h=FailoverHooks(lambda i,e:calls.append(('fence',i,e)) or True,lambda i,e:calls.append(('promote',i,e)) or True,lambda i,e:calls.append(('converge',i,e)) or True); out=HADROrchestrator(r,h).automatic_failover('ha1'); assert out['state']=='completed'; assert [x[0] for x in calls]==['fence','promote','converge']; assert next(x for x in r.members if x['controller_id']=='b')['role']=='primary'
def test_split_brain_refused():
    r=Repo(quorum=False); h=FailoverHooks(lambda *_:True,lambda *_:True,lambda *_:True)
    try:HADROrchestrator(r,h).automatic_failover('ha1'); raise AssertionError('must refuse without quorum')
    except RuntimeError as e: assert 'quorum' in str(e)
def test_fencing_failure_refuses_promotion():
    r=Repo(); promoted=[]; h=FailoverHooks(lambda *_:False,lambda *_:promoted.append(1) or True,lambda *_:True)
    try:HADROrchestrator(r,h).automatic_failover('ha1'); raise AssertionError('must refuse')
    except RuntimeError as e: assert 'fencing failed' in str(e)
    assert not promoted and r.ops['op1']['state']=='failed'
def test_stale(): assert member_is_stale({'last_seen_at':'2000-01-01T00:00:00Z'})
if __name__=='__main__':
    test_success(); test_split_brain_refused(); test_fencing_failure_refuses_promotion(); test_stale(); print('E2 failover E2E: OK')
