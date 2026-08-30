#!/usr/bin/env python3
"""PostgreSQL alert-scope rules for immutable historical Agent/node detachment."""
from __future__ import annotations


def alert_scope_history_ddl(backend_name: str) -> str:
    backend = str(backend_name or "").strip().lower()
    if backend == "postgres":
        backend = "postgresql"
    if backend != "postgresql":
        return ""
    return r"""
CREATE OR REPLACE FUNCTION validate_alert_scope()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    historical_agent_detach BOOLEAN := FALSE;
    historical_node_detach BOOLEAN := FALSE;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        historical_agent_detach :=
            OLD.scope = 'agent'
            AND NEW.scope = 'agent'
            AND OLD.state = 'RESOLVED'
            AND NEW.state = 'RESOLVED'
            AND OLD.controller_id IS NOT NULL
            AND NEW.controller_id = OLD.controller_id
            AND OLD.agent_id IS NOT NULL
            AND NEW.agent_id IS NULL;

        historical_node_detach :=
            OLD.scope = 'node'
            AND NEW.scope = 'node'
            AND OLD.state = 'RESOLVED'
            AND NEW.state = 'RESOLVED'
            AND OLD.controller_id IS NOT NULL
            AND NEW.controller_id = OLD.controller_id
            AND OLD.node_id IS NOT NULL
            AND NEW.node_id IS NULL;
    END IF;

    IF NEW.scope = 'controller'
       AND NEW.controller_id IS NULL
    THEN
        RAISE EXCEPTION
            'alert_controller_scope_requires_controller';
    END IF;

    IF NEW.scope = 'agent'
       AND (
           NEW.controller_id IS NULL
           OR (
               NEW.agent_id IS NULL
               AND NOT historical_agent_detach
           )
       )
    THEN
        RAISE EXCEPTION
            'alert_agent_scope_requires_controller_agent';
    END IF;

    IF NEW.scope = 'node'
       AND (
           NEW.controller_id IS NULL
           OR (
               NEW.node_id IS NULL
               AND NOT historical_node_detach
           )
       )
    THEN
        RAISE EXCEPTION
            'alert_node_scope_requires_controller_node';
    END IF;

    IF NEW.scope = 'instance'
       AND (
           NEW.controller_id IS NULL
           OR NEW.agent_id IS NULL
           OR NEW.node_id IS NULL
           OR NEW.instance_id IS NULL
       )
    THEN
        RAISE EXCEPTION
            'alert_instance_scope_requires_controller_agent_node_instance';
    END IF;

    IF NEW.agent_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM agents
           WHERE id = NEW.agent_id
             AND controller_id = NEW.controller_id
       )
    THEN
        RAISE EXCEPTION
            'alert_agent_controller_mismatch';
    END IF;

    IF NEW.instance_id IS NOT NULL
       AND NOT EXISTS (
           SELECT 1
           FROM instances
           WHERE id = NEW.instance_id
             AND controller_id = NEW.controller_id
             AND agent_id = NEW.agent_id
             AND node_id = NEW.node_id
       )
    THEN
        RAISE EXCEPTION
            'alert_instance_ownership_mismatch';
    END IF;

    RETURN NEW;
END;
$$;
""".strip()


def ensure_alert_scope_history_schema(sql: str, backend_name: str) -> str:
    ddl = alert_scope_history_ddl(backend_name)
    if not ddl:
        return sql
    return sql.rstrip() + "\n\n" + ddl + "\n"


__all__ = ["alert_scope_history_ddl", "ensure_alert_scope_history_schema"]
