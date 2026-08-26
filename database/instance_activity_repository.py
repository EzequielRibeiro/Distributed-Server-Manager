#!/usr/bin/env python3
"""Customer-visible instance activity backed by semantic operator audit."""
from __future__ import annotations
from typing import Any

from activity_audit_repository import ActivityAuditRepository


class InstanceActivityRepository:
    def __init__(self, backend):
        self.backend = backend
        self.audit = ActivityAuditRepository(backend)

    def record(
        self,
        *,
        instance_id: str,
        customer_id: int | None,
        username: str | None,
        role: str | None,
        activity: str,
        category: str,
        result: str = "success",
        target_type: str | None = None,
        target_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> str:
        context = dict(details or {})
        if customer_id is not None:
            context["customer_id"] = int(customer_id)
        if target_type:
            context["resource_type"] = str(target_type)
        if target_name:
            context["resource_name"] = str(target_name)[:512]
        summary = str(context.pop("summary", "") or "").strip()
        if not summary:
            subject = str(target_name or instance_id)
            summary = f"{username or 'Usuário'} executou {activity} no servidor {subject}."
        changes = context.pop("changes", None)
        return self.audit.record_action(
            actor_id=username,
            actor_name=username,
            actor_role=role,
            action=str(activity),
            category=str(category),
            result=str(result),
            summary=summary,
            target_type="instance",
            target_id=str(instance_id),
            target_name=target_name or str(instance_id),
            changes=changes if isinstance(changes, dict) else None,
        )

    def search(
        self,
        *,
        instance_id: str,
        username: str | None = None,
        category: str | None = None,
        activity: str | None = None,
        result: str | None = None,
        start_at: str | None = None,
        end_at: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        rows = self.audit.search(
            actor_id=username,
            category=category,
            action=activity,
            result=result,
            target_type="instance",
            target_id=str(instance_id),
            start_at=start_at,
            end_at=end_at,
            limit=limit,
        )
        out: list[dict[str, Any]] = []
        for item in rows:
            resource_name = item.get("target_name")
            details = {
                "changes": item.get("changes") or {},
                "resource_name": resource_name,
                "resource_type": "instance",
            }
            out.append({
                "event_id": item.get("activity_id"),
                "username": item.get("actor_id"),
                "role": item.get("actor_role"),
                "activity": item.get("action"),
                "category": item.get("category"),
                "result": item.get("result"),
                "target_type": item.get("target_type"),
                "target_id": item.get("target_id"),
                "target_name": resource_name,
                "summary": item.get("summary"),
                "details": details,
                "created_at": item.get("occurred_at"),
            })
        return out

    def options(self, instance_id: str) -> dict[str, list[str]]:
        rows = self.search(instance_id=instance_id, limit=1000)
        return {
            "users": sorted({str(x.get("username")) for x in rows if x.get("username")}),
            "categories": sorted({str(x.get("category")) for x in rows if x.get("category")}),
            "activities": sorted({str(x.get("activity")) for x in rows if x.get("activity")}),
            "results": sorted({str(x.get("result")) for x in rows if x.get("result")}),
        }


__all__ = ["InstanceActivityRepository"]
