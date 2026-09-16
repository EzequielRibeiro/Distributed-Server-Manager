#!/usr/bin/env python3
"""Persist customer instance-creation failures for operators."""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from alert_repository import AlertSession
from customer_audit import audit_customer_event
from customer_health_service import CustomerHealthService
from customer_reference import resolve_customer_reference

_QUEUE_LOCK = threading.Lock()
_LOGGER = logging.getLogger("capivara.instance_creation_feedback")


def _append_timeline(root: Path, event: dict[str, Any]) -> None:
    path = root / "runtime" / "events" / "queue.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _QUEUE_LOCK:
        try:
            queue = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        except (OSError, json.JSONDecodeError):
            queue = []
        if not isinstance(queue, list):
            queue = []
        queue.append(event)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)


def _placement_dedupe(customer_id: str, failure: dict[str, Any]) -> str:
    contract = str(failure.get("contract_id") or failure.get("game") or "general").strip()
    runtime = str(failure.get("runtime_id") or failure.get("game") or "runtime").strip()
    placement = failure.get("placement") if isinstance(failure.get("placement"), dict) else {}
    region = str(failure.get("region_id") or placement.get("region_id") or "automatic").strip()
    return f"instance-placement:{customer_id}:{contract}:{runtime}:{region}"


def _placement_severity(reason: str | None) -> str:
    return "WARNING" if str(reason or "").strip() == "requested_region_unavailable" else "CRITICAL"


def _customer_context(backend, reference: Any) -> dict[str, Any] | None:
    try:
        customer_id = resolve_customer_reference(reference, public_only=isinstance(reference, str))
        ph = "?" if backend.name == "sqlite" else "%s"
        with backend.connect() as connection:
            session = AlertSession(backend, connection)
            try:
                row = session.execute(
                    f"SELECT id,controller_id,name,customer_code FROM customers WHERE id={ph}",
                    (customer_id,),
                ).fetchone()
            finally:
                session.close()
        return None if row is None else dict(row)
    except Exception:
        return None


def _region_context(backend, region_id: str | None) -> dict[str, Any] | None:
    if not region_id:
        return None
    try:
        ph = "?" if backend.name == "sqlite" else "%s"
        with backend.connect() as connection:
            session = AlertSession(backend, connection)
            try:
                row = session.execute(
                    f"SELECT id,name,country_code FROM regions WHERE id={ph}",
                    (region_id,),
                ).fetchone()
            finally:
                session.close()
        return None if row is None else dict(row)
    except Exception:
        return None


def _technical_rejections(backend, raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    ph = "?" if getattr(backend, "name", "") == "sqlite" else "%s"
    result: list[dict[str, Any]] = []
    for agent_id, reasons in sorted(raw.items()):
        item = {
            "agent_id": str(agent_id),
            "reasons": [str(value) for value in (reasons or [])],
        }
        try:
            with backend.connect() as connection:
                session = AlertSession(backend, connection)
                try:
                    row = session.execute(
                        f"SELECT id,name,node_id,status FROM agents WHERE id={ph}",
                        (str(agent_id),),
                    ).fetchone()
                finally:
                    session.close()
            if row is not None:
                item.update({key: dict(row).get(key) for key in ("name", "node_id", "status")})
        except Exception:
            pass
        result.append(item)
    return result


def _placement_admin_details(
    backend,
    failure: dict[str, Any],
    customer: dict[str, Any],
) -> dict[str, Any]:
    placement = failure.get("placement") if isinstance(failure.get("placement"), dict) else {}
    region_id = str(failure.get("region_id") or placement.get("region_id") or "").strip() or None
    region = _region_context(backend, region_id)
    return {
        "kind": "customer_instance_placement_blocked",
        "impact": "customer_blocked",
        "customer_id": str(customer.get("id") or failure.get("customer_id") or ""),
        "customer_name": customer.get("name"),
        "customer_code": customer.get("customer_code"),
        "contract_id": failure.get("contract_id"),
        "game": failure.get("game"),
        "runtime_id": failure.get("runtime_id"),
        "region_id": region_id,
        "region_name": None if region is None else region.get("name"),
        "country_code": None if region is None else region.get("country_code"),
        "placement_reason": failure.get("placement_reason") or failure.get("code"),
        "agents_evaluated": int(failure.get("agents_evaluated") or 0),
        "eligible_agents": 0,
        "allow_cross_region": bool(placement.get("allow_cross_region")),
        "technical_rejections": _technical_rejections(backend, failure.get("technical_rejections")),
    }


def _record_placement_incident(failure: dict[str, Any], *, backend) -> dict[str, Any] | None:
    customer = _customer_context(backend, failure.get("customer_id"))
    if customer is None:
        return None
    severity = _placement_severity(failure.get("placement_reason"))
    runtime = str(failure.get("runtime_id") or failure.get("game") or "servidor")
    placement = failure.get("placement") if isinstance(failure.get("placement"), dict) else {}
    region = str(failure.get("region_id") or placement.get("region_id") or "automática")
    message = (
        f"Provisionamento bloqueado para {runtime} na localização {region}. "
        "Intervenção operacional necessária."
    )
    details = _placement_admin_details(backend, failure, customer)
    return CustomerHealthService(backend).failure(
        customer_id=str(customer["id"]),
        controller_id=str(customer["controller_id"]),
        dedupe_key=_placement_dedupe(str(customer["id"]), failure),
        event_type="CUSTOMER_INSTANCE_PLACEMENT_BLOCKED",
        severity=severity,
        safe_code="instance_placement_blocked",
        message=message,
        actor_id=str(failure.get("username") or "") or None,
        actor_role="customer",
        action="customer.instance.create",
        contract_id=str(failure.get("contract_id") or "") or None,
        admin_details=details,
    )


def record_instance_creation_failure(
    failure: dict[str, Any], *, root: Path, backend,
    notify: Callable[[str, str, str], Any] | None = None,
) -> None:
    customer = str(failure.get("customer_id") or "desconhecido")
    game = str(failure.get("game") or "desconhecido")
    code = str(failure.get("code") or "instance_creation_failed")
    reason = str(failure.get("placement_reason") or failure.get("reason") or code)
    message = f"Cliente {customer} não conseguiu criar servidor {game}: {reason}"
    details = dict(failure)
    try:
        audit_customer_event(
            backend,
            username=str(failure.get("username") or "customer"),
            action="customer.instance_creation_failed",
            result="failure",
            details=details,
        )
    except Exception:
        _LOGGER.exception("could not audit instance creation failure")

    incident = None
    if code == "placement_unavailable":
        try:
            incident = _record_placement_incident(failure, backend=backend)
        except Exception:
            _LOGGER.exception("could not persist Customer placement incident")

    severity = str((incident or {}).get("level") or "WARNING").upper()
    event = {
        "id": str(uuid.uuid4()),
        "type": (
            "CUSTOMER_INSTANCE_PLACEMENT_BLOCKED"
            if code == "placement_unavailable"
            else "INSTANCE_CREATION_FAILED"
        ),
        "category": "customer-health" if code == "placement_unavailable" else "server",
        "severity": severity,
        "timestamp": int(time.time()),
        "title": (
            "Cliente impedido de criar instância"
            if code == "placement_unavailable"
            else "Falha ao criar instância"
        ),
        "message": message,
        "customer_id": customer,
        "contract_id": failure.get("contract_id"),
        "game": game,
        "runtime_id": failure.get("runtime_id"),
        "region_id": failure.get("region_id") or (failure.get("placement") or {}).get("region_id"),
        "reason": reason,
        "agents_evaluated": int(failure.get("agents_evaluated") or 0),
        "incident_id": None if incident is None else incident.get("id"),
    }
    try:
        _append_timeline(root, event)
    except Exception:
        _LOGGER.exception("could not append instance creation failure to timeline")

    should_notify = (
        incident is None
        or str(incident.get("transition") or "").upper() in {"OPEN", "REOPEN", "ESCALATE"}
    )
    if notify is not None and should_notify:
        try:
            notify(severity.lower(), event["title"], message)
        except Exception:
            _LOGGER.exception("could not enqueue instance creation notification")


def record_instance_creation_success(
    success: dict[str, Any], *, root: Path, backend,
    notify: Callable[[str, str, str], Any] | None = None,
) -> None:
    customer = _customer_context(backend, success.get("customer_id"))
    if customer is None:
        return
    failure_shape = {
        "contract_id": success.get("contract_id"),
        "game": success.get("game"),
        "runtime_id": success.get("runtime_id"),
        "placement": success.get("placement") if isinstance(success.get("placement"), dict) else {},
    }
    incident = CustomerHealthService(backend).recovered(
        customer_id=str(customer["id"]),
        controller_id=str(customer["controller_id"]),
        dedupe_key=_placement_dedupe(str(customer["id"]), failure_shape),
        actor_id=str(success.get("username") or "") or None,
        actor_role="customer",
        instance_id=str(success.get("instance_id") or "") or None,
    )
    if incident is None:
        return
    message = (
        f"Capacidade confirmada: cliente {customer.get('name') or customer['id']} "
        "criou a instância com sucesso."
    )
    try:
        _append_timeline(root, {
            "id": str(uuid.uuid4()),
            "type": "CUSTOMER_ERROR_RESOLVED",
            "category": "customer-health",
            "severity": "INFO",
            "timestamp": int(time.time()),
            "title": "Bloqueio de provisionamento resolvido",
            "message": message,
            "customer_id": str(customer["id"]),
            "instance_id": success.get("instance_id"),
            "incident_id": incident.get("id"),
        })
    except Exception:
        _LOGGER.exception("could not append instance creation recovery to timeline")
    if notify is not None:
        try:
            notify("info", "Bloqueio de provisionamento resolvido", message)
        except Exception:
            _LOGGER.exception("could not enqueue instance creation recovery notification")


__all__ = ["record_instance_creation_failure", "record_instance_creation_success"]
