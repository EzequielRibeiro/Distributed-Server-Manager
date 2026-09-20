#!/usr/bin/env python3
"""Controller persistence for sanitized technical operation diagnostics."""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from alert_repository import AlertSession, dialect_for_backend
from core.agent_health import utc_timestamp

_SECRET_KEYS = re.compile(r"(password|passwd|secret|token|credential|authorization|cookie|api[_-]?key)", re.I)
_MAX_ERROR = 12000
_MAX_TRACEBACK = 64000
_MAX_DETAIL = 24000
_MAX_PAYLOAD = 128000


def _clean_text(value: Any, limit: int) -> str | None:
    text = str(value or "").replace("\x00", "").strip()
    if not text:
        return None
    replacements = (
        ("/opt/dsm", "<DSM_ROOT>"),
        ("/var/lib/capivara-agent", "<AGENT_STATE>"),
        ("C:\\ProgramData\\CapivaraAgent", "<AGENT_STATE>"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text[:limit]


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "<truncated>"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            label = str(key)
            if _SECRET_KEYS.search(label):
                out[label] = "<redacted>"
            else:
                out[label] = _sanitize(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_sanitize(item, depth=depth + 1) for item in value[:200]]
    if isinstance(value, str):
        return _clean_text(value, 16000)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return _clean_text(value, 4000)


class OperationDiagnosticRepository:
    def __init__(self, backend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def initialize(self):
        return self.backend.initialize()

    def create(
        self,
        *,
        correlation_id: str | None,
        operation: str,
        source: str | None,
        agent_id: str | None,
        instance_id: str | None,
        current_step: str | None,
        error: Any,
        exception_type: Any = None,
        traceback: Any = None,
        error_code: Any = None,
        technical_detail: Any = None,
        compensation: Any = None,
        payload: dict[str, Any] | None = None,
        severity: str = "critical",
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        self.initialize()
        diagnostic_id = "diag-" + uuid.uuid4().hex
        safe_payload = _sanitize(payload or {})
        safe_compensation = _sanitize(compensation if isinstance(compensation, list) else [])
        values = (
            diagnostic_id,
            _clean_text(correlation_id, 191),
            _clean_text(operation, 128) or "operation",
            _clean_text(source, 191),
            _clean_text(agent_id, 191),
            _clean_text(instance_id, 191),
            _clean_text(severity, 32) or "critical",
            _clean_text(current_step, 128),
            _clean_text(error_code, 191),
            _clean_text(exception_type, 191),
            _clean_text(error, _MAX_ERROR),
            _clean_text(traceback, _MAX_TRACEBACK),
            _clean_text(technical_detail, _MAX_DETAIL),
            json.dumps(safe_compensation, ensure_ascii=False, separators=(",", ":")),
            json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":"))[:_MAX_PAYLOAD],
            _clean_text(occurred_at, 64) or utc_timestamp(),
        )
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(
                    "INSERT INTO operation_diagnostics("
                    "diagnostic_id,correlation_id,operation,source,agent_id,instance_id,severity,"
                    "current_step,error_code,exception_type,error,traceback,technical_detail,"
                    "compensation_json,payload_json,occurred_at) "
                    f"VALUES ({self.dialect.parameters(16)})",
                    values,
                )
            finally:
                session.close()
        return self.get(diagnostic_id)

    def get(self, diagnostic_id: str) -> dict[str, Any]:
        self.initialize()
        ph = self.dialect.placeholder
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT * FROM operation_diagnostics WHERE diagnostic_id={ph}",
                    (str(diagnostic_id or "").strip(),),
                ).fetchone()
            finally:
                session.close()
        if row is None:
            raise KeyError(diagnostic_id)
        result = dict(row)
        for source, target, fallback in (
            ("compensation_json", "compensation", []),
            ("payload_json", "payload", {}),
        ):
            raw = result.pop(source, None)
            try:
                result[target] = json.loads(raw) if raw else fallback
            except (TypeError, ValueError):
                result[target] = fallback
        return result


__all__ = ["OperationDiagnosticRepository"]
