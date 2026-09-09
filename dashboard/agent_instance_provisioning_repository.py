#!/usr/bin/env python3
"""Dashboard-facing provisioning repository with safe failure diagnostics.

The canonical persistence implementation lives in ``database/``.  Dashboard
services historically import repositories as top-level modules while running
with ``dashboard`` first on ``sys.path``.  This adapter keeps that import
contract, adds diagnostics at the Controller trust boundary, and deliberately
projects sensitive traceback data only through an explicit Admin-only API.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any

DATABASE_DIR = Path(__file__).resolve().parents[1] / "database"
if str(DATABASE_DIR) not in sys.path:
    sys.path.append(str(DATABASE_DIR))

_BASE_PATH = DATABASE_DIR / "agent_instance_provisioning_repository.py"
_SPEC = importlib.util.spec_from_file_location(
    "_capivara_agent_instance_provisioning_repository_base",
    _BASE_PATH,
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - installation corruption
    raise ImportError(f"cannot load provisioning repository: {_BASE_PATH}")
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)

from alert_repository import AlertRepository  # noqa: E402
from core.agent_health import utc_timestamp  # noqa: E402

ACTIVE_STATES = _BASE.ACTIVE_STATES
FINAL_STATES = _BASE.FINAL_STATES
VALID_STATES = _BASE.VALID_STATES
VALID_DESIRED_STATES = _BASE.VALID_DESIRED_STATES
_request_storage_reservation = _BASE._request_storage_reservation

_MAX_ERROR = 2000
_MAX_TRACEBACK = 16000
_MAX_GENERIC_TEXT = 16000
_SENSITIVE_RESULT_FIELDS = {"traceback", "source_context"}
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(
        r"(?i)(\b(?:password|passwd|token|secret|api[_-]?key|steam[_-]?(?:password|token|guard))\b"
        r"\s*(?::|=)\s*)[^\s,;]+"
    ),
    re.compile(r"(?i)([?&](?:token|access_token|api_key|apikey|password|secret)=)[^&#\s]+"),
)


def _sanitize_text(value: Any, *, limit: int = _MAX_GENERIC_TEXT) -> str:
    text = str(value or "").replace("\x00", "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda match: match.group(1) + "[REDACTED]", text)
    text = re.sub(r"(?i)(\+login\s+)\S+(?:\s+\S+)?", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)/opt/dsm/", "<DSM_ROOT>/", text)
    text = re.sub(r"(?i)/home/[^/\s]+/", "<HOME>/", text)
    text = re.sub(r"(?i)[A-Z]:\\Users\\[^\\\s]+\\", "<USER_HOME>/", text)
    return text[:limit]


def _sanitize_value(value: Any, *, key: str | None = None) -> Any:
    """Recursively sanitize Agent-controlled data before Controller persistence."""
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            name = str(raw_key)[:128]
            lower = name.lower()
            if lower in {"password", "passwd", "token", "secret", "api_key", "apikey", "authorization"}:
                clean[name] = "[REDACTED]"
                continue
            clean[name] = _sanitize_value(raw_value, key=lower)
        return clean
    if isinstance(value, list):
        return [_sanitize_value(item, key=key) for item in value[:500]]
    if isinstance(value, tuple):
        return [_sanitize_value(item, key=key) for item in value[:500]]
    if isinstance(value, str):
        limit = _MAX_TRACEBACK if key == "traceback" else (_MAX_ERROR if key == "error" else _MAX_GENERIC_TEXT)
        return _sanitize_text(value, limit=limit)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_text(value)


def _public_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    result = dict(state)
    payload = result.get("result")
    if isinstance(payload, dict):
        public_result = dict(payload)
        for field in _SENSITIVE_RESULT_FIELDS:
            public_result.pop(field, None)
        result["result"] = public_result
    return result


class AgentInstanceProvisioningRepository(_BASE.AgentInstanceProvisioningRepository):
    """Provisioning repository with sanitization, rich alerts and role-safe projection."""

    def snapshot(self, provisioning_id: str, *, include_sensitive: bool = False) -> dict[str, Any]:
        state = _BASE.AgentInstanceProvisioningRepository.snapshot(self, provisioning_id)
        return state if include_sensitive else _public_snapshot(state)

    def diagnostics(self, provisioning_id: str) -> dict[str, Any]:
        """Return the persisted diagnostic projection for an authorized Admin."""
        state = self.snapshot(provisioning_id, include_sensitive=True)
        payload = state.get("result") if isinstance(state.get("result"), dict) else {}
        request = state.get("request") if isinstance(state.get("request"), dict) else {}
        instance = request.get("instance") if isinstance(request.get("instance"), dict) else {}
        return {
            "provisioning_id": str(state.get("provisioning_id") or provisioning_id),
            "correlation_id": str(payload.get("correlation_id") or state.get("provisioning_id") or provisioning_id),
            "status": str(state.get("status") or ""),
            "stage": str(state.get("current_step") or payload.get("current_step") or ""),
            "progress": int(state.get("progress") or 0),
            "agent_id": str(state.get("agent_id") or request.get("agent_id") or "") or None,
            "node_id": self._failure_context(str(state.get("instance_id") or "")).get("node_id"),
            "instance_id": str(state.get("instance_id") or request.get("instance_id") or "") or None,
            "game": str(instance.get("game_id") or "") or self._failure_context(str(state.get("instance_id") or "")).get("game_id"),
            "customer": self._failure_context(str(state.get("instance_id") or "")).get("customer_name"),
            "customer_id": self._failure_context(str(state.get("instance_id") or "")).get("customer_id"),
            "error": _sanitize_text(payload.get("error") or state.get("last_error") or "", limit=_MAX_ERROR) or None,
            "exception_type": _sanitize_text(payload.get("exception_type") or "", limit=256) or None,
            "source": _sanitize_text(payload.get("source") or "agent.provisioning", limit=256),
            "failed_at": _sanitize_text(payload.get("failed_at") or state.get("completed_at") or state.get("updated_at") or "", limit=128) or None,
            "traceback": _sanitize_text(payload.get("traceback") or "", limit=_MAX_TRACEBACK) or None,
        }

    def _failure_context(self, instance_id: str) -> dict[str, Any]:
        if not instance_id:
            return {}
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT i.node_id,i.game_id,"
                "COALESCE(NULLIF(i.controller_id,''),NULLIF(c.controller_id,''),NULLIF(a.controller_id,'')) AS controller_id,"
                "i.customer_id,c.name AS customer_name "
                "FROM instances i "
                "LEFT JOIN customers c ON c.id=i.customer_id "
                "LEFT JOIN agents a ON a.id=i.agent_id "
                f"WHERE i.id={ph}",
                (instance_id,),
            ).fetchone()
        return dict(row) if row is not None else {}

    def _open_failure_alert(self, state: dict[str, Any], result: dict[str, Any]) -> None:
        instance_id = str(state.get("instance_id") or "")
        context = self._failure_context(instance_id)
        controller_id = str(context.get("controller_id") or "").strip()
        if not controller_id:
            return
        provisioning_id = str(state.get("provisioning_id") or "")
        stage = str(state.get("current_step") or result.get("current_step") or "failed")
        game = str(context.get("game_id") or "unknown")
        customer = str(context.get("customer_name") or context.get("customer_id") or "unknown")
        exception_type = _sanitize_text(result.get("exception_type") or "Exception", limit=256)
        error = _sanitize_text(result.get("error") or state.get("last_error") or "", limit=_MAX_ERROR)
        message = _sanitize_text(
            f"Falha no provisionamento de {game}; cliente={customer}; instance={instance_id}; "
            f"agent={state.get('agent_id')}; node={context.get('node_id')}; etapa={stage}; "
            f"operation={provisioning_id}; exception={exception_type}; erro={error}",
            limit=4000,
        )
        AlertRepository(self.backend).open_alert(
            alert_id=f"instance-provisioning-failed:{provisioning_id}",
            rule_id="instance_provisioning_failed",
            level="CRITICAL",
            message=message,
            scope="INSTANCE",
            controller_id=controller_id,
            agent_id=str(state.get("agent_id") or "") or None,
            node_id=str(context.get("node_id") or "") or None,
            instance_id=instance_id or None,
        )

    def apply_result(self, agent_id: str, result: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(result, dict):
            return None
        sanitized = _sanitize_value(result)
        if not isinstance(sanitized, dict):
            return None
        provisioning_id = str(sanitized.get("provisioning_id") or "").strip()
        if not provisioning_id:
            return None
        current = self.snapshot(provisioning_id)
        if str(current.get("agent_id") or "") != str(agent_id):
            raise PermissionError("provisioning operation belongs to another Agent")
        if str(sanitized.get("instance_id") or "") != str(current.get("instance_id") or ""):
            raise ValueError("provisioning result instance_id mismatch")
        status = str(sanitized.get("status") or "").strip().lower()
        if status not in {"running", "completed", "failed"}:
            raise ValueError("invalid provisioning result status")
        try:
            requested_progress = int(sanitized.get("progress", current.get("progress", 0)))
        except (TypeError, ValueError):
            requested_progress = int(current.get("progress", 0) or 0)
        progress = 100 if status == "completed" else max(0, min(requested_progress, 99))
        current_step = _sanitize_text(
            sanitized.get("current_step") or current.get("current_step") or status,
            limit=128,
        ).strip()
        error = _sanitize_text(sanitized.get("error") or "", limit=_MAX_ERROR).strip() or None
        if status == "failed":
            sanitized["progress"] = progress
            sanitized["current_step"] = current_step
            sanitized["error"] = error
            sanitized["exception_type"] = _sanitize_text(sanitized.get("exception_type") or "Exception", limit=256)
            sanitized["source"] = _sanitize_text(sanitized.get("source") or "agent.provisioning", limit=256)
            sanitized["failed_at"] = _sanitize_text(sanitized.get("failed_at") or utc_timestamp(), limit=128)
            sanitized["correlation_id"] = _sanitize_text(
                sanitized.get("correlation_id") or provisioning_id,
                limit=256,
            )
            if sanitized.get("traceback") is not None:
                sanitized["traceback"] = _sanitize_text(sanitized["traceback"], limit=_MAX_TRACEBACK)
        now = utc_timestamp()
        payload = json.dumps(sanitized, separators=(",", ":"), sort_keys=True)
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            if status == "running":
                session.execute(
                    "UPDATE agent_instance_provisioning SET "
                    f"status={ph},current_step={ph},progress={ph},result_json={ph},last_error={ph},"
                    f"started_at=CASE WHEN started_at IS NULL THEN {ph} ELSE started_at END,updated_at={ph} "
                    f"WHERE provisioning_id={ph} AND status NOT IN ('completed','failed')",
                    (status, current_step, progress, payload, error, now, now, provisioning_id),
                )
            else:
                session.execute(
                    "UPDATE agent_instance_provisioning SET "
                    f"status={ph},current_step={ph},progress={ph},result_json={ph},last_error={ph},"
                    f"completed_at={ph},updated_at={ph} WHERE provisioning_id={ph} AND status NOT IN ('completed','failed')",
                    (status, current_step, progress, payload, error, now, now, provisioning_id),
                )

        state = self.snapshot(provisioning_id)
        pool_id, reserved_bytes = _request_storage_reservation(current.get("request"))
        if status == "running":
            self._publish_event(
                event_id=f"{provisioning_id}:running:{current_step}:{progress}",
                event_type="INSTANCE_PROVISION_STARTED",
                severity="info",
                provisioning=state,
                data={"message": "O Agent iniciou o provisionamento da instância."},
            )
        elif status == "completed":
            self._publish_event(
                event_id=f"{provisioning_id}:completed",
                event_type="INSTANCE_PROVISION_COMPLETED",
                severity="info",
                provisioning=state,
                data={"message": "Provisionamento da instância concluído com sucesso."},
            )
        else:
            context = self._failure_context(str(state.get("instance_id") or ""))
            failure_data = {
                "message": "Falha durante o provisionamento da instância.",
                "error": error,
                "exception_type": sanitized.get("exception_type"),
                "stage": current_step,
                "source": sanitized.get("source"),
                "failed_at": sanitized.get("failed_at"),
                "correlation_id": sanitized.get("correlation_id") or provisioning_id,
                "node_id": context.get("node_id"),
                "game": context.get("game_id"),
                "customer": context.get("customer_name"),
                "customer_id": context.get("customer_id"),
            }
            self._publish_event(
                event_id=f"{provisioning_id}:failed",
                event_type="INSTANCE_PROVISION_FAILED",
                severity="critical",
                provisioning=state,
                data=failure_data,
            )
            self._open_failure_alert(state, sanitized)
            if self._steam_auth_required(error, sanitized):
                self._publish_event(
                    event_id=f"{provisioning_id}:steam-auth-required",
                    event_type="STEAM_AUTH_REQUIRED",
                    severity="critical",
                    provisioning=state,
                    data={
                        "message": "Autenticação Steam necessária no Agent para continuar o provisionamento.",
                        "error": error,
                        "correlation_id": sanitized.get("correlation_id") or provisioning_id,
                    },
                )
        if status in FINAL_STATES and pool_id and reserved_bytes:
            self._publish_event(
                event_id=f"{provisioning_id}:storage-capacity-released",
                event_type="INSTANCE_STORAGE_POOL_CAPACITY_RELEASED",
                severity="info",
                provisioning=state,
                data={
                    "storage_pool_id": pool_id,
                    "released_bytes": reserved_bytes,
                    "final_status": status,
                    "message": "Reserva lógica de capacidade do Storage Pool foi liberada ao finalizar o provisionamento.",
                },
            )
        return state


__all__ = [
    "ACTIVE_STATES",
    "FINAL_STATES",
    "VALID_STATES",
    "VALID_DESIRED_STATES",
    "AgentInstanceProvisioningRepository",
    "_request_storage_reservation",
]
