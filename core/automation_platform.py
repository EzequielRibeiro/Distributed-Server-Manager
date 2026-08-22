#!/usr/bin/env python3
"""Canonical contracts for Capivara automation and universal broadcast."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,191}$")
_TRIGGER_TYPES = {"event", "schedule", "manual", "metric"}
_ACTION_TYPES = {"broadcast", "backup", "instance", "content", "configuration", "administrative"}
_BROADCAST_SCOPES = {"instance", "agent", "game", "customer", "region", "datacenter", "global"}
_ADMIN_OPERATIONS = {"infrastructure_doctor", "agent_health_check"}


class AutomationValidationError(ValueError):
    pass


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _token(value, label):
    text = str(value or "").strip()
    if not _TOKEN.fullmatch(text):
        raise AutomationValidationError(f"invalid {label}")
    return text


def normalize_broadcast(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise AutomationValidationError("broadcast must be an object")
    scope = str(raw.get("scope") or "instance").strip().lower()
    if scope not in _BROADCAST_SCOPES:
        raise AutomationValidationError("invalid broadcast scope")
    message = str(raw.get("message") or "").strip()
    if not message or len(message) > 4000:
        raise AutomationValidationError("invalid broadcast message")
    target = str(raw.get("target") or "").strip()
    if scope != "global":
        target = _token(target, "broadcast target")
    ttl = max(1, min(int(raw.get("ttl_seconds") or 300), 86400))
    priority = str(raw.get("priority") or "normal").lower()
    if priority not in {"low", "normal", "high", "critical"}:
        raise AutomationValidationError("invalid broadcast priority")
    return {
        "schema_version": 1,
        "kind": "CapivaraBroadcast",
        "scope": scope,
        "target": target or None,
        "message": message,
        "priority": priority,
        "ttl_seconds": ttl,
        "require_ack": bool(raw.get("require_ack", True)),
    }


def normalize_rule(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise AutomationValidationError("automation rule must be an object")
    rule_id = _token(raw.get("rule_id"), "rule_id")
    name = str(raw.get("name") or rule_id).strip()[:191]
    enabled = bool(raw.get("enabled", True))
    trigger = dict(raw.get("trigger") or {})
    trigger_type = str(trigger.get("type") or "").strip().lower()
    if trigger_type not in _TRIGGER_TYPES:
        raise AutomationValidationError("invalid trigger type")
    if trigger_type == "event":
        trigger["event_type"] = _token(trigger.get("event_type"), "event_type").upper()
    elif trigger_type == "schedule":
        expression = str(trigger.get("expression") or "").strip()
        if not expression or len(expression) > 191:
            raise AutomationValidationError("invalid schedule expression")
        trigger["expression"] = expression
        timezone_name = str(trigger.get("timezone") or "UTC").strip()
        if not timezone_name or len(timezone_name) > 64:
            raise AutomationValidationError("invalid schedule timezone")
        trigger["timezone"] = timezone_name
    elif trigger_type == "metric":
        trigger["metric_name"] = _token(trigger.get("metric_name"), "metric_name")
        trigger["operator"] = str(trigger.get("operator") or ">=")
        if trigger["operator"] not in {">", ">=", "<", "<=", "==", "!="}:
            raise AutomationValidationError("invalid metric operator")
        try:
            trigger["value"] = float(trigger.get("value"))
        except (TypeError, ValueError) as exc:
            raise AutomationValidationError("invalid metric threshold") from exc

    actions = []
    for raw_action in raw.get("actions") or []:
        if not isinstance(raw_action, Mapping):
            raise AutomationValidationError("action must be an object")
        action = dict(raw_action)
        action_type = str(action.get("type") or "").strip().lower()
        if action_type not in _ACTION_TYPES:
            raise AutomationValidationError("invalid action type")
        if action_type == "broadcast":
            action = {"type": "broadcast", "broadcast": normalize_broadcast(action.get("broadcast") or {})}
        elif action_type == "instance":
            operation = str(action.get("operation") or "").strip().lower()
            if operation not in {"start", "stop", "restart"}:
                raise AutomationValidationError("invalid instance operation")
            action = {"type": "instance", "operation": operation, "instance_id": _token(action.get("instance_id"), "instance_id")}
        elif action_type == "backup":
            action = {"type": "backup", "instance_id": _token(action.get("instance_id"), "instance_id")}
        elif action_type == "content":
            assignment = action.get("assignment")
            if not isinstance(assignment, Mapping):
                raise AutomationValidationError("content action requires assignment")
            action = {"type": "content", "assignment": dict(assignment)}
        elif action_type == "configuration":
            configuration = action.get("configuration")
            if not isinstance(configuration, Mapping):
                raise AutomationValidationError("configuration action requires configuration")
            action = {"type": "configuration", "configuration": dict(configuration)}
        elif action_type == "administrative":
            operation = str(action.get("operation") or "").strip().lower()
            if operation not in _ADMIN_OPERATIONS:
                raise AutomationValidationError("invalid administrative operation")
            target = str(action.get("target_id") or "").strip()
            if operation == "agent_health_check":
                target = _token(target, "target_id")
            action = {
                "type": "administrative",
                "operation": operation,
                "target_id": target or None,
            }
        actions.append(action)

    if not actions:
        raise AutomationValidationError("rule requires actions")
    conditions = list(raw.get("conditions") or [])
    if any(not isinstance(item, Mapping) for item in conditions):
        raise AutomationValidationError("conditions must be objects")
    identity = {
        "rule_id": rule_id,
        "name": name,
        "enabled": enabled,
        "trigger": trigger,
        "conditions": conditions,
        "actions": actions,
        "cooldown_seconds": max(0, min(int(raw.get("cooldown_seconds") or 0), 86400)),
    }
    return {
        "schema_version": 1,
        "kind": "CapivaraAutomationRule",
        **identity,
        "checksum": hashlib.sha256(_json(identity).encode()).hexdigest(),
    }


__all__ = ["AutomationValidationError", "normalize_rule", "normalize_broadcast"]
