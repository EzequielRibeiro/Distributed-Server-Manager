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

from customer_audit import audit_customer_event

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


def record_instance_creation_failure(
    failure: dict[str, Any], *, root: Path, backend,
    notify: Callable[[str, str, str], Any] | None = None,
) -> None:
    customer = str(failure.get("customer_id") or "desconhecido")
    game = str(failure.get("game") or "desconhecido")
    code = str(failure.get("code") or "instance_creation_failed")
    reason = str(failure.get("reason") or code)
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
    event = {
        "id": str(uuid.uuid4()),
        "type": "INSTANCE_CREATION_FAILED",
        "category": "server",
        "severity": "WARNING",
        "timestamp": int(time.time()),
        "title": "Falha ao criar instância",
        "message": message,
        "customer_id": customer,
        "contract_id": failure.get("contract_id"),
        "game": game,
        "reason": code,
    }
    try:
        _append_timeline(root, event)
    except Exception:
        _LOGGER.exception("could not append instance creation failure to timeline")
    if notify is not None:
        try:
            notify("warning", "Falha ao criar instância", message)
        except Exception:
            _LOGGER.exception("could not enqueue instance creation notification")
