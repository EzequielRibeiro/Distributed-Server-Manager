#!/usr/bin/env python3
"""Backend-neutral persistent history for Agent runtime logs."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from alert_repository import AlertSession

_LINE_RE = re.compile(r"^(?P<observed>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+(?P<severity>[A-Z]+)\s+(?P<message>.*)$")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_SECRET_RE = re.compile(
    r"(?i)\b(authorization|credential_secret|api[_-]?key|token|password|passwd|secret)\b(\s*[:=]\s*)([^\s,;]+)"
)
_HEADER_SECRET_RE = re.compile(r"(?i)(X-Capivara-Agent-Secret\s*[:=]\s*)([^\s,;]+)")
_CORRELATION_PATTERNS = {
    "instance_id": re.compile(r"(?i)\binstance(?:_id)?[=:]([^\s,;]+)"),
    "command_id": re.compile(r"(?i)\bcommand(?:_id)?[=:]([^\s,;]+)"),
    "job_id": re.compile(r"(?i)\bjob(?:_id)?[=:]([^\s,;]+)"),
    "provisioning_id": re.compile(r"(?i)\bprovisioning(?:_id)?[=:]([^\s,;]+)"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redact_log_text(value: Any) -> str:
    text = str(value).replace("\x00", "")[:8000]
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _HEADER_SECRET_RE.sub(r"\1[REDACTED]", text)
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


def normalize_agent_log(agent_id: str, raw: Any, *, source: str = "agent-runtime") -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    original = raw.replace("\x00", "")[:8000]
    match = _LINE_RE.match(original)
    if match:
        observed_at = match.group("observed")
        severity = match.group("severity")[:16]
        original_message = match.group("message")
    else:
        # Legacy/unstructured lines remain ingestible, but their identity is the
        # exact original line. The current Agents always emit timestamped lines.
        observed_at = "1970-01-01T00:00:00Z"
        severity = "UNKNOWN"
        original_message = original
    event_id = hashlib.sha256(
        (str(agent_id) + "\0" + source + "\0" + original).encode("utf-8", errors="replace")
    ).hexdigest()
    correlations: dict[str, str | None] = {}
    for key, pattern in _CORRELATION_PATTERNS.items():
        found = pattern.search(original_message)
        correlations[key] = found.group(1)[:191] if found else None
    redacted_line = redact_log_text(original)
    redacted_message = redact_log_text(original_message)
    return {
        "event_id": event_id,
        "agent_id": str(agent_id),
        "source": source,
        "severity": severity,
        "message": redacted_message[:8000],
        "line_text": redacted_line[:8000],
        "observed_at": observed_at,
        **correlations,
    }


class AgentLogEventRepository:
    def __init__(self, backend):
        self.backend = backend

    def initialize(self) -> None:
        self.backend.initialize()

    @property
    def ph(self) -> str:
        return "?" if self.backend.name == "sqlite" else "%s"

    def ingest_agent_logs(self, agent_id: str, raw_logs: list[Any], *, source: str = "agent-runtime") -> dict[str, int]:
        accepted = created = rejected = 0
        now = utc_now()
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                for raw in raw_logs[-200:]:
                    event = normalize_agent_log(agent_id, raw, source=source)
                    if event is None:
                        rejected += 1
                        continue
                    accepted += 1
                    exists = session.execute(
                        f"SELECT event_id FROM agent_log_events WHERE event_id={self.ph}",
                        (event["event_id"],),
                    ).fetchone()
                    if exists is not None:
                        continue
                    columns = (
                        "event_id", "agent_id", "source", "severity", "message", "line_text",
                        "observed_at", "ingested_at", "instance_id", "command_id", "job_id", "provisioning_id",
                    )
                    values = (
                        event["event_id"], event["agent_id"], event["source"], event["severity"],
                        event["message"], event["line_text"], event["observed_at"], now,
                        event["instance_id"], event["command_id"], event["job_id"], event["provisioning_id"],
                    )
                    session.execute(
                        f"INSERT INTO agent_log_events({','.join(columns)}) VALUES ({','.join([self.ph] * len(columns))})",
                        values,
                    )
                    created += 1
            finally:
                session.close()
        return {"accepted": accepted, "created": created, "rejected": rejected}

    def history(
        self, *, agent_id: str | None = None, severity: str | None = None,
        instance_id: str | None = None, command_id: str | None = None,
        job_id: str | None = None, provisioning_id: str | None = None,
        since: str | None = None, until: str | None = None, limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("agent_id", agent_id), ("severity", severity), ("instance_id", instance_id),
            ("command_id", command_id), ("job_id", job_id), ("provisioning_id", provisioning_id),
        ):
            if value:
                clauses.append(f"{column}={self.ph}")
                params.append(value)
        if since:
            clauses.append(f"observed_at>={self.ph}"); params.append(since)
        if until:
            clauses.append(f"observed_at<={self.ph}"); params.append(until)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(max(1, min(int(limit), 5000)))
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(
                    f"SELECT * FROM agent_log_events{where} ORDER BY observed_at DESC,event_id DESC LIMIT {self.ph}",
                    tuple(params),
                ).fetchall()
                return [dict(row) for row in rows]
            finally:
                session.close()


__all__ = ["AgentLogEventRepository", "normalize_agent_log", "redact_log_text"]
