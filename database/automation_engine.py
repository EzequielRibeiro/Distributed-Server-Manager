#!/usr/bin/env python3
"""Automation execution over existing Capivara universal services."""
from __future__ import annotations
import operator
from datetime import datetime,timezone
from automation_execution_repository import AutomationExecutionRepository
from automation_repository import AutomationRepository
from backup_repository import BackupRepository
_OPS={">":operator.gt,">=":operator.ge,"<":operator.lt,"<=":operator.le,"==":operator.eq,"!=":operator.ne}
def _epoch(value):
 try:return datetime.fromisoformat(str(value).replace("Z","+00:00")).timestamp()
 except Exception:return 0.0
class AutomationEngine:
 def __init__(self,backend):
  self.backend=backend;self.repo=AutomationRepository(backend);self.repo.initialize();self.execution=AutomationExecutionRepository(backend)
 def _matches(self,rule,trigger_type,context):
  trigger=rule.get("trigger") or {};tt=trigger.get("type")
  if tt!=trigger_type:return False
  if tt=="event":return str(context.get("event_type") or "").upper()==str(trigger.get("event_type") or "").upper()
  if tt=="metric":
   if str(context.get("metric_name") or "")!=str(trigger.get("metric_name") or ""):return False
   try:return _OPS[str(trigger.get("operator"))](float(context.get("value")),float(trigger.get("value")))
   except Exception:return False
  return True
 def _conditions(self,rule,context):
  for condition in rule.get("conditions") or []:
   if not isinstance(condition,dict):return False
   field=str(condition.get("field") or "");op=str(condition.get("operator") or "==");expected=condition.get("value");actual=context.get(field)
   if op=="in":
    if actual not in (expected or []):return False
   elif op=="not_in":
    if actual in (expected or []):return False
   elif op in _OPS:
    try:
     if not _OPS[op](actual,expected):return False
    except Exception:return False
   else:return False
  return True
 def _cooldown_allows(self,rule):
  cooldown=int(rule.get("cooldown_seconds") or 0)
  if cooldown<=0:return True
  runs=self.repo.list_runs(rule_id=rule.get("rule_id"),limit=1)
  if not runs:return True
  return datetime.now(timezone.utc).timestamp()-_epoch(runs[0].get("created_at"))>=cooldown
 def execute_rule(self,rule,*,trigger_type="manual",trigger_ref=None,context=None,requested_by="automation"):
  context=dict(context or {})
  if not self._cooldown_allows(rule):return {"run_id":None,"rule_id":rule.get("rule_id"),"status":"cooldown","actions":[]}
  run_id=self.execution.claim(rule_id=rule.get("rule_id"),trigger_type=trigger_type,trigger_ref=trigger_ref,context=context,requested_by=requested_by)
  if run_id is None:return {"run_id":None,"rule_id":rule.get("rule_id"),"status":"duplicate","actions":[]}
  results=[];status="completed"
  for action in rule.get("actions") or []:
   try:
    atype=action.get("type")
    if atype=="broadcast":results.append({"type":atype,"result":self.repo.create_broadcast(action["broadcast"],requested_by=requested_by)})
    elif atype=="backup":
     backups=BackupRepository(self.backend);backups.initialize();results.append({"type":atype,"result":backups.request(action["instance_id"],reason="automation",requested_by=requested_by)})
    else:results.append({"type":atype,"status":"deferred","reason":"action requires its universal service dispatcher"})
   except Exception as exc:status="failed";results.append({"type":action.get("type"),"status":"failed","error":str(exc)[:2000]});break
  self.execution.finish(run_id,status=status,result={"actions":results})
  return {"run_id":run_id,"rule_id":rule.get("rule_id"),"status":status,"actions":results}
 def fire(self,trigger_type,context=None,*,trigger_ref=None,requested_by="automation"):
  context=dict(context or {});runs=[]
  for rule in self.repo.list_rules(limit=2000):
   if not rule.get("enabled") or not self._matches(rule,trigger_type,context) or not self._conditions(rule,context):continue
   runs.append(self.execute_rule(rule,trigger_type=trigger_type,trigger_ref=trigger_ref,context=context,requested_by=requested_by))
  return runs
 def fire_rule(self,rule_id,*,context=None,requested_by="manual"):
  rule=self.repo.get_rule(rule_id)
  if not rule:raise LookupError("automation rule not found")
  return self.execute_rule(rule,trigger_type="manual",context=context or {},requested_by=requested_by)
__all__=["AutomationEngine"]
