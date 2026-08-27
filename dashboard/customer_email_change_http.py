#!/usr/bin/env python3
"""HTTP composition for verified Customer e-mail changes."""
from __future__ import annotations

import uuid
from urllib.parse import urlparse

from customer_email_change_service import CustomerEmailChangeService
from customer_email_transport import SmtpVerificationTransport

INITIATE_PATH = "/api/customer/email-change/initiate"
VERIFY_PATH = "/api/customer/email-change/verify"
CANCEL_PATH = "/api/customer/email-change/cancel"
_PATHS = {INITIATE_PATH, VERIFY_PATH, CANCEL_PATH}


def _backend(legacy):
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def _service(backend):
    return CustomerEmailChangeService(backend, transport=SmtpVerificationTransport.from_environment())


def dispatch_customer_email_change_post(path: str, payload, *, user, backend, service=None):
    body = payload if isinstance(payload, dict) else {}
    correlation_id = str(body.get("correlation_id") or "").strip() or str(uuid.uuid4())
    try:
        svc = service or _service(backend)
        if path == INITIATE_PATH:
            result = svc.initiate(
                user=user,
                target_email=str(body.get("email") or ""),
                confirmed=body.get("confirmed") is True,
                correlation_id=correlation_id,
            )
            return 202, result
        if path == VERIFY_PATH:
            result = svc.verify(
                user=user,
                challenge_id=str(body.get("challenge_id") or ""),
                token=str(body.get("token") or ""),
                confirmed=body.get("confirmed") is True,
                correlation_id=correlation_id,
            )
            return 200, result
        if path == CANCEL_PATH:
            result = svc.cancel(
                user=user,
                challenge_id=str(body.get("challenge_id") or ""),
                correlation_id=correlation_id,
            )
            return 200, result
        return None
    except PermissionError:
        return 403, {"error": "forbidden", "message": "Acesso não autorizado."}
    except ValueError as exc:
        code = str(exc)
        if code in {"email_unavailable", "invalid_email"}:
            return 400, {"error": "email_change_unavailable", "message": "Não foi possível iniciar a alteração de e-mail."}
        if code == "explicit_confirmation_required":
            return 400, {"error": code, "message": "Confirme explicitamente a alteração de e-mail."}
        return 400, {"error": "invalid_or_expired_challenge", "message": "Código inválido, expirado ou já utilizado."}
    except RuntimeError as exc:
        code = str(exc)
        if code == "rate_limited":
            return 429, {"error": "rate_limited", "message": "Aguarde antes de solicitar um novo código."}
        return 503, {"error": "email_delivery_unavailable", "message": "Não foi possível enviar o código de verificação."}
    except Exception:
        return 500, {"error": "email_change_failed", "message": "Falha ao processar a alteração de e-mail."}


def install_customer_email_change(legacy, authenticate) -> None:
    previous_post = legacy.DashboardHandler.do_POST

    def do_post(self):
        parsed = urlparse(self.path)
        if parsed.path not in _PATHS:
            return previous_post(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."})
            return
        result = dispatch_customer_email_change_post(parsed.path, payload, user=user, backend=_backend(legacy))
        if result is None:
            return previous_post(self)
        status, response = result
        self.send_json(status, response)

    legacy.DashboardHandler.do_POST = do_post


__all__ = ["INITIATE_PATH", "VERIFY_PATH", "CANCEL_PATH", "dispatch_customer_email_change_post", "install_customer_email_change"]
