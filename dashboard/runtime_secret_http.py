#!/usr/bin/env python3
"""Admin-only HTTP boundary for one-time runtime secret delivery."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse
from runtime_secret_repository import RuntimeSecretOutbox, RuntimeSecretOutboxError

RUNTIME_SECRETS_PATH = "/api/runtime-secrets"


def _admin(user):
    return isinstance(user, dict) and str(user.get("role") or "").strip().lower() == "admin"


def dispatch_runtime_secret_get(query_string, *, user, backend):
    if not _admin(user):
        return 403, {"error": "forbidden", "message": "Administrator access required."}
    query = parse_qs(query_string, keep_blank_values=True)
    instance_id = (query.get("instance_id") or [None])[0]
    try:
        return 200, {"pending": RuntimeSecretOutbox(backend).list_pending(instance_id=instance_id)}
    except (RuntimeSecretOutboxError, ValueError):
        return 400, {"error": "invalid_request", "message": "Requisição inválida."}
    except Exception:
        return 500, {"error": "runtime_secret_status_failed", "message": "Não foi possível consultar secrets de runtime."}


def dispatch_runtime_secret_post(payload, *, user, backend):
    if not _admin(user):
        return 403, {"error": "forbidden", "message": "Administrator access required."}
    body = payload if isinstance(payload, dict) else {}
    action = str(body.get("action") or "put").strip().lower()
    value = body.get("value") if action == "put" else None
    try:
        job = RuntimeSecretOutbox(backend).enqueue(
            instance_id=body.get("instance_id"),
            name=body.get("name"),
            action=action,
            value=value,
            requested_by=str(user.get("username") or user.get("id") or "admin"),
        )
        # Never echo value, hashes or source spool paths to the caller.
        return 202, {"job": job}
    except KeyError:
        return 404, {"error": "instance_not_found", "message": "Instância não encontrada."}
    except (RuntimeSecretOutboxError, ValueError, TypeError):
        return 400, {"error": "invalid_request", "message": "Requisição inválida."}
    except Exception:
        return 500, {"error": "runtime_secret_failed", "message": "Não foi possível processar o secret de runtime."}


def install_runtime_secret_http(legacy, authenticate, root: Path):
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST

    def do_get(self):
        parsed = urlparse(self.path)
        if parsed.path != RUNTIME_SECRETS_PATH:
            return previous_get(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized(); return
        backend = legacy.dashboard_repository(legacy.DATABASE_FILE).backend
        status, body = dispatch_runtime_secret_get(parsed.query, user=user, backend=backend)
        self.send_json(status, body)

    def do_post(self):
        parsed = urlparse(self.path)
        if parsed.path != RUNTIME_SECRETS_PATH:
            return previous_post(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized(); return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."}); return
        backend = legacy.dashboard_repository(legacy.DATABASE_FILE).backend
        status, body = dispatch_runtime_secret_post(payload, user=user, backend=backend)
        self.send_json(status, body)

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post


__all__ = ["RUNTIME_SECRETS_PATH", "dispatch_runtime_secret_get", "dispatch_runtime_secret_post", "install_runtime_secret_http"]
