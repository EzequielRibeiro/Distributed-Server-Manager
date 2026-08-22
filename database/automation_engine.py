#!/usr/bin/env python3
"""Automation execution over existing Capivara universal services."""
from __future__ import annotations

import operator
from datetime import datetime, timezone

from agent_instance_runtime_repository import AgentInstanceRuntimeRepository
from agent_runtime_repository import AgentRuntimeRepository
from automation_execution_repository import AutomationExecutionRepository
from automation_repository import AutomationRepository
from backup_repository import BackupRepository
from configuration_repository import ConfigurationRepository
from content_repository import ContentRepository
from infrastructure_doctor_contract import build_infrastructure_doctor_payload

_OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq, "!=": operator.ne}


def _epoch(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


class AutomationEngine:
    def __init__(self, backend):
        self.backend = backend
        self.repo = AutomationRepository(backend)
        self.repo.initialize()
        self.execution = AutomationExecutionRepository(backend)

    def _matches(self, rule, trigger_type, context):
        trigger = rule.get("trigger") or {}
        stored_type = trigger.get("type")
        if stored_type != trigger_type:
            return False
        if stored_type == "event":
            return str(context.get("event_type") or "").upper() == str(trigger.get("event_type") or "").upper()
        if stored_type == "metric":
            if str(context.get("metric_name") or "") != str(trigger.get("metric_name") or ""):
                return False
            try:
                return _OPS[str(trigger.get("operator"))](float(context.get("value")), float(trigger.get("value")))
            except Exception:
                return False
        return True

    def _conditions(self, rule, context):
        for condition in rule.get("conditions") or []:
            field = str(condition.get("field") or "")
            operation = str(condition.get("operator") or "==")
            expected = condition.get("value")
            actual = context.get(field)
            if operation == "in":
                if actual not in (expected or []):
                    return False
            elif operation == "not_in":
                if actual in (expected or []):
                    return False
            elif operation in _OPS:
                try:
                    if not _OPS[operation](actual, expected):
                        return False
                except Exception:
                    return False
            else:
                return False
        return True

    def _cooldown_allows(self, rule):
        cooldown = int(rule.get("cooldown_seconds") or 0)
        if cooldown <= 0:
            return True
        runs = self.repo.list_runs(rule_id=rule.get("rule_id"), limit=1)
        if not runs:
            return True
        return datetime.now(timezone.utc).timestamp() - _epoch(runs[0].get("created_at")) >= cooldown

    def _instance_agent(self, instance_id):
        placeholder = "?" if self.backend.name == "sqlite" else "%s"
        from alert_repository import AlertSession
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(f"SELECT agent_id FROM instances WHERE id={placeholder}", (instance_id,)).fetchone()
                if not row:
                    raise LookupError("instance not found")
                return str(row["agent_id"])
            finally:
                session.close()

    def _administrative_action(self, action):
        operation = str(action.get("operation") or "")
        target_id = action.get("target_id")
        if operation == "infrastructure_doctor":
            payload = build_infrastructure_doctor_payload(self.backend, reconcile=False)
            return {
                "kind": payload.get("kind"),
                "status": payload.get("status"),
                "ready": payload.get("ready"),
                "generated_at": payload.get("generated_at"),
                "findings": len(payload.get("findings") or []),
            }
        if operation == "agent_health_check":
            repository = AgentRuntimeRepository(self.backend)
            item = repository.snapshot(str(target_id), refresh_health=True)
            return {
                "agent_id": item.get("agent_id"),
                "health_status": item.get("health_status"),
                "last_seen": item.get("last_seen"),
            }
        raise ValueError("unsupported administrative automation action")

    def _action(self, action, requested_by):
        action_type = action.get("type")
        if action_type == "broadcast":
            return self.repo.create_broadcast(action["broadcast"], requested_by=requested_by)
        if action_type == "backup":
            repository = BackupRepository(self.backend)
            repository.initialize()
            return repository.request(action["instance_id"], reason="automation", requested_by=requested_by)
        if action_type == "instance":
            instance_id = action["instance_id"]
            repository = AgentInstanceRuntimeRepository(self.backend)
            repository.initialize()
            return repository.enqueue(
                agent_id=self._instance_agent(instance_id),
                instance_id=instance_id,
                action=action["operation"],
                requested_by=requested_by,
            )
        if action_type == "content":
            repository = ContentRepository(self.backend)
            repository.initialize()
            return repository.put(action["assignment"], requested_by=requested_by)
        if action_type == "configuration":
            repository = ConfigurationRepository(self.backend)
            repository.initialize()
            return repository.put(action["configuration"], updated_by=requested_by)
        if action_type == "administrative":
            return self._administrative_action(action)
        raise ValueError("unsupported automation action")

    def execute_rule(self, rule, *, trigger_type="manual", trigger_ref=None, context=None, requested_by="automation"):
        context = dict(context or {})
        if not self._cooldown_allows(rule):
            return {"run_id": None, "rule_id": rule.get("rule_id"), "status": "cooldown", "actions": []}
        run_id = self.execution.claim(
            rule_id=rule.get("rule_id"),
            trigger_type=trigger_type,
            trigger_ref=trigger_ref,
            context=context,
            requested_by=requested_by,
        )
        if run_id is None:
            return {"run_id": None, "rule_id": rule.get("rule_id"), "status": "duplicate", "actions": []}
        results = []
        status = "completed"
        for action in rule.get("actions") or []:
            try:
                results.append({"type": action.get("type"), "result": self._action(action, requested_by)})
            except Exception as exc:
                status = "failed"
                results.append({"type": action.get("type"), "status": "failed", "error": str(exc)[:2000]})
                break
        self.execution.finish(run_id, status=status, result={"actions": results})
        return {"run_id": run_id, "rule_id": rule.get("rule_id"), "status": status, "actions": results}

    def fire(self, trigger_type, context=None, *, trigger_ref=None, requested_by="automation"):
        context = dict(context or {})
        runs = []
        for rule in self.repo.list_rules(limit=2000):
            if not rule.get("enabled") or not self._matches(rule, trigger_type, context) or not self._conditions(rule, context):
                continue
            runs.append(self.execute_rule(rule, trigger_type=trigger_type, trigger_ref=trigger_ref, context=context, requested_by=requested_by))
        return runs

    def fire_rule(self, rule_id, *, context=None, requested_by="manual"):
        rule = self.repo.get_rule(rule_id)
        if not rule:
            raise LookupError("automation rule not found")
        return self.execute_rule(rule, trigger_type="manual", context=context or {}, requested_by=requested_by)


__all__ = ["AutomationEngine"]
