#!/usr/bin/env python3
"""HTTP integration for Customer Instance Workspace v2."""
from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

from agent_console_push import console_push_snapshot
from controller_log_journal_http import instance_journal_logs
from controller_session import session_user_from_headers
from customer_instance_workspace_service import CustomerInstanceWorkspaceService
from instance_activity_repository import InstanceActivityRepository
from json_serialization import to_json_compatible

PREFIX = "/api/customer/instance/workspace"
ROUTES = {
    PREFIX,
    PREFIX + "/telemetry",
    PREFIX + "/console",
    PREFIX + "/console/status",
    PREFIX + "/console/stream",
    PREFIX + "/startup",
    PREFIX + "/files/status",
    PREFIX + "/backup-policy",
    PREFIX + "/backups",
    PREFIX + "/upgrade-options",
    PREFIX + "/upgrade",
    PREFIX + "/runtime-options",
    PREFIX + "/permissions",
}
_FILE_ACTIVITY = {
    "write_text": "FILE_EDIT_REQUESTED",
    "upload": "FILE_UPLOAD_REQUESTED",
    "delete": "FILE_DELETE_REQUESTED",
    "move": "FILE_MOVE_REQUESTED",
    "rename": "FILE_RENAME_REQUESTED",
    "mkdir": "DIRECTORY_CREATE_REQUESTED",
    "extract": "ARCHIVE_EXTRACT_REQUESTED",
    "download": "FILE_DOWNLOAD_REQUESTED",
}


def _merge_console_output(live_lines, stored, limit: int, live_source: str) -> list[dict[str, str]]:
    cap = max(1, min(int(limit), 2000))
    live = []
    for item in live_lines or []:
        if isinstance(item, dict):
            line = str(item.get("line") or "")
            if not line:
                continue
            value = {"line": line, "source": live_source}
            for key in ("cursor", "priority", "timestamp"):
                if item.get(key) is not None:
                    value[key] = str(item.get(key))
            live.append(value)
        else:
            live.append({"line": str(item), "source": live_source})
    commands = []
    for item in stored or []:
        if isinstance(item, dict) and str(item.get("line") or ""):
            commands.append({"line": str(item.get("line")), "source": "command-history"})
    if not commands:
        return live[-cap:]
    command_cap = min(len(commands), max(1, min(80, cap // 4)))
    command_tail = commands[-command_cap:]
    live_cap = max(0, cap - command_cap - 1)
    return (live[-live_cap:] if live_cap else []) + [{"line": "── Respostas de comandos ──", "source": "command-history"}] + command_tail


def _console_payload(api, user, instance_id: str, limit: int) -> dict[str, object]:
    # Authorize first. Remote Agent push is the lowest-latency source; Hybrid
    # instances fall through to the local journal, then heartbeat snapshots.
    stored = api.console_output(user, instance_id, limit)
    pushed = console_push_snapshot(instance_id, limit=limit)
    if isinstance(pushed, dict) and pushed.get("lines"):
        return {
            "lines": _merge_console_output(pushed.get("lines"), stored, limit, "agent-push"),
            "source": "agent-push",
            "read_only": True,
            "transport": pushed.get("transport"),
            "agent_health": "online",
            "last_seen": pushed.get("last_seen"),
        }
    journal = instance_journal_logs(instance_id, limit)
    logs = journal.get("logs")
    if not journal.get("error") and isinstance(logs, list) and logs:
        return {
            "lines": _merge_console_output(logs, stored, limit, "systemd-journal"),
            "source": "systemd-journal",
            "read_only": True,
        }
    heartbeat = {}
    reader = getattr(api, "agent_console_output", None)
    if callable(reader):
        try:
            heartbeat = reader(user, instance_id, limit) or {}
        except Exception:
            heartbeat = {}
    heartbeat_lines = heartbeat.get("lines") if isinstance(heartbeat, dict) else None
    if isinstance(heartbeat_lines, list) and heartbeat_lines:
        return {
            "lines": _merge_console_output(heartbeat_lines, stored, limit, "agent-heartbeat"),
            "source": "agent-heartbeat",
            "read_only": True,
            "transport": heartbeat.get("transport"),
            "agent_health": heartbeat.get("agent_health"),
            "last_seen": heartbeat.get("last_seen"),
            "journal_error": journal.get("error"),
        }
    return {
        "lines": stored,
        "source": "command-history",
        "read_only": False,
        "journal_error": journal.get("error"),
        "agent_health": heartbeat.get("agent_health") if isinstance(heartbeat, dict) else None,
        "last_seen": heartbeat.get("last_seen") if isinstance(heartbeat, dict) else None,
    }


def _console_stream_signature(payload: dict[str, object]) -> str:
    relevant = {
        "lines": payload.get("lines") or [],
        "source": payload.get("source"),
        "agent_health": payload.get("agent_health"),
        "last_seen": payload.get("last_seen"),
    }
    encoded = json.dumps(relevant, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sse_frame(event: str, payload: dict[str, object], *, event_id: str | None = None) -> bytes:
    data = json.dumps(to_json_compatible(payload), ensure_ascii=False, separators=(",", ":"))
    parts = []
    if event_id:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event}")
    parts.extend(f"data: {line}" for line in data.splitlines() or [""])
    return ("\n".join(parts) + "\n\n").encode("utf-8")


def _serve_console_stream(handler, api, user, instance_id: str, limit: int, *, timeout: int = 25) -> None:
    # Authorize and fetch once before committing the SSE response headers.
    first = _console_payload(api, user, instance_id, limit)
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
    handler.send_header("Cache-Control", "no-cache, no-transform")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    deadline = time.monotonic() + max(5, min(int(timeout), 30))
    last_signature = ""
    last_ping = 0.0
    payload = first
    try:
        handler.wfile.write(_sse_frame("ready", {"kind": "CapivaraConsoleStream", "version": 1, "retry_ms": 1500}))
        handler.wfile.flush()
        while time.monotonic() < deadline:
            signature = _console_stream_signature(payload)
            if signature != last_signature:
                event_payload = dict(payload)
                event_payload["cursor"] = signature[:24]
                handler.wfile.write(_sse_frame("console-snapshot", event_payload, event_id=signature[:24]))
                handler.wfile.flush()
                last_signature = signature
                last_ping = time.monotonic()
            now = time.monotonic()
            if now - last_ping >= 10:
                handler.wfile.write(b": keepalive\n\n")
                handler.wfile.flush()
                last_ping = now
            time.sleep(0.75)
            payload = _console_payload(api, user, instance_id, limit)
    except (BrokenPipeError, ConnectionResetError, OSError):
        return


def install_customer_instance_workspace(legacy, authenticate):
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST
    previous_patch = getattr(legacy.DashboardHandler, "do_PATCH", None)
    legacy.STATIC_FILES.update(
        {
            "/customer-instance.html": legacy.WEB_DIR / "customer-instance.html",
            "/customer-instance-v2.js": legacy.WEB_DIR / "customer-instance-v2.js",
            "/customer-instance-runtime-live.js": legacy.WEB_DIR / "customer-instance-runtime-live.js",
            "/customer-instance-v2.css": legacy.WEB_DIR / "customer-instance-v2.css",
            "/customer-backup-transfer.js": legacy.WEB_DIR / "customer-backup-transfer.js",
            "/customer-instance-delete.js": legacy.WEB_DIR / "customer-instance-delete.js",
            "/customer-instance-activity.js": legacy.WEB_DIR / "customer-instance-activity.js",
        }
    )

    def backend():
        return legacy.dashboard_repository(legacy.DATABASE_FILE).backend

    def service():
        return CustomerInstanceWorkspaceService(backend(), legacy.DSM_ROOT)

    def activity_repo():
        return InstanceActivityRepository(backend())

    def send(self, status, payload):
        return self.send_json(status, to_json_compatible(payload))

    def user_for(self, area=None):
        explicit_area = str(area or self.headers.get("X-Capivara-Auth-Area") or "").strip().lower()
        if explicit_area in {"controller", "customer"}:
            value = session_user_from_headers(self.headers, area=explicit_area)
            if value is not None:
                return value
        elif not explicit_area:
            # Compatibility fallback for legacy callers that do not identify an area.
            value = session_user_from_headers(self.headers)
            if value is not None:
                return value
        try:
            return authenticate(self.headers)
        except Exception:
            return None

    def require_user(self, area=None):
        user = user_for(self, area=area)
        if user is None:
            self.unauthorized()
            return None
        if str(user.get("role") or "").lower() not in {"customer", "admin", "controller"}:
            self.forbidden()
            return None
        return user

    def one(parsed, name, default=None):
        return (parse_qs(parsed.query, keep_blank_values=True).get(name) or [default])[0]

    def iid(parsed, body=None):
        return str((body or {}).get("instance_id") or one(parsed, "instance_id", "") or "").strip()

    def record(
        api,
        user,
        instance_id,
        activity,
        category,
        *,
        target_type=None,
        target_name=None,
        details=None,
        result="accepted",
    ):
        try:
            context = api.repo.instance_context(instance_id)
            activity_repo().record(
                instance_id=instance_id,
                customer_id=context.get("customer_id"),
                username=str(user.get("username") or ""),
                role=str(user.get("role") or ""),
                activity=activity,
                category=category,
                result=result,
                target_type=target_type,
                target_name=target_name,
                details=details,
            )
        except Exception:
            pass

    def error(self, exc):
        if isinstance(exc, PermissionError):
            send(self, 403, {"error": "forbidden", "message": str(exc)})
            return
        if isinstance(exc, KeyError):
            send(self, 404, {"error": "not_found", "message": "Registro não encontrado."})
            return
        if isinstance(exc, (ValueError, LookupError)):
            send(self, 400, {"error": "invalid_request", "message": str(exc)})
            return
        internal = getattr(self, "_internal_error", None)
        if callable(internal):
            internal(exc)
            return
        send(
            self,
            500,
            {
                "error": "workspace_failed",
                "message": "Não foi possível concluir a operação da instância.",
            },
        )

    def get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path not in ROUTES:
            return previous_get(self)
        stream_area = one(parsed, "auth_area", "") if path == PREFIX + "/console/stream" else None
        user = require_user(self, area=stream_area)
        if user is None:
            return
        instance_id = iid(parsed)
        try:
            api = service()
            if path == PREFIX:
                data = api.overview(user, instance_id)
            elif path == PREFIX + "/telemetry":
                data = {"samples": api.telemetry(user, instance_id, int(one(parsed, "limit", 240) or 240))}
            elif path == PREFIX + "/console":
                data = _console_payload(api, user, instance_id, int(one(parsed, "limit", 300) or 300))
            elif path == PREFIX + "/console/stream":
                _serve_console_stream(
                    self,
                    api,
                    user,
                    instance_id,
                    int(one(parsed, "limit", 400) or 400),
                    timeout=int(one(parsed, "timeout", 25) or 25),
                )
                return
            elif path == PREFIX + "/console/status":
                data = api.console_command_status(user, instance_id, one(parsed, "command_id", ""))
            elif path == PREFIX + "/startup":
                data = api.startup(user, instance_id)
            elif path == PREFIX + "/files/status":
                data = api.file_status(user, instance_id, one(parsed, "command_id", ""))
            elif path == PREFIX + "/backup-policy":
                data = api.backup_policy(user, instance_id)
            elif path == PREFIX + "/backups":
                data = {"jobs": api.backup_jobs(user, instance_id)}
            elif path == PREFIX + "/upgrade-options":
                data = api.upgrade_options(user, instance_id)
            elif path == PREFIX + "/runtime-options":
                data = {"runtimes": api.runtime_options(user, instance_id)}
            elif path == PREFIX + "/permissions":
                data = {"permissions": sorted(api.permissions(user, instance_id))}
            else:
                data = {"changes": api.repo.list_contract_changes(instance_id)}
            send(self, 200, data)
        except Exception as exc:
            error(self, exc)

    def post(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path not in {PREFIX + "/console", PREFIX + "/upgrade", PREFIX + "/files", PREFIX + "/backups"}:
            return previous_post(self)
        user = require_user(self)
        if user is None:
            return
        try:
            body = self.read_json_body()
            instance_id = iid(parsed, body)
            api = service()
            if path == PREFIX + "/console":
                data = api.send_console(user, instance_id, body.get("command"))
                code = 202
                record(
                    api,
                    user,
                    instance_id,
                    "CONSOLE_COMMAND_REQUESTED",
                    "console",
                    details={"command_id": data.get("command_id")},
                )
            elif path == PREFIX + "/files":
                action = str(body.get("action") or "").lower()
                data = api.queue_file(
                    user,
                    instance_id,
                    action,
                    path=body.get("path"),
                    target_path=body.get("target_path"),
                    payload=body.get("payload"),
                )
                code = 202
                semantic = _FILE_ACTIVITY.get(action)
                if semantic:
                    record(
                        api,
                        user,
                        instance_id,
                        semantic,
                        "files",
                        target_type="file",
                        target_name=body.get("path"),
                        details={"command_id": data.get("command_id"), "target_path": body.get("target_path")},
                    )
            elif path == PREFIX + "/backups":
                action = str(body.get("action") or "").lower()
                data = api.request_backup(user, instance_id, action, body.get("backup_id"))
                code = 202
                record(
                    api,
                    user,
                    instance_id,
                    f"BACKUP_{action.upper()}_REQUESTED",
                    "backup",
                    target_type="backup",
                    target_name=body.get("backup_id"),
                    details={"job_id": data.get("job_id") or data.get("command_id")},
                )
            else:
                data = api.request_upgrade(user, instance_id, body.get("profile_id"))
                code = 202
                record(
                    api,
                    user,
                    instance_id,
                    "CONTRACT_UPGRADE_REQUESTED",
                    "contract",
                    target_type="resource_profile",
                    target_name=body.get("profile_id"),
                    details={"request_id": data.get("request_id")},
                )
            send(self, code, data)
        except Exception as exc:
            error(self, exc)

    def patch(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path not in {PREFIX + "/startup", PREFIX + "/backup-policy"}:
            if previous_patch is not None:
                return previous_patch(self)
            send(self, 404, {"error": "not_found"})
            return
        user = require_user(self)
        if user is None:
            return
        try:
            body = self.read_json_body()
            instance_id = iid(parsed, body)
            api = service()
            if path.endswith("startup"):
                data = api.save_startup(user, instance_id, body.get("values"))
                record(
                    api,
                    user,
                    instance_id,
                    "STARTUP_CONFIGURATION_CHANGED",
                    "configuration",
                    details={"fields": sorted((body.get("values") or {}).keys())},
                    result="success",
                )
            else:
                data = api.save_backup_policy(user, instance_id, body)
                record(
                    api,
                    user,
                    instance_id,
                    "BACKUP_SCHEDULE_CHANGED",
                    "backup",
                    details={
                        "enabled": bool(body.get("enabled", True)),
                        "schedule_time": body.get("schedule_time"),
                        "schedule_timezone": body.get("schedule_timezone"),
                    },
                    result="success",
                )
            send(self, 200, data)
        except Exception as exc:
            error(self, exc)

    legacy.DashboardHandler.do_GET = get
    legacy.DashboardHandler.do_POST = post
    legacy.DashboardHandler.do_PATCH = patch


__all__ = ["PREFIX", "ROUTES", "install_customer_instance_workspace"]
