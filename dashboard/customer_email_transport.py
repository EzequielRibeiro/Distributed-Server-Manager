#!/usr/bin/env python3
"""Synchronous SMTP transport for secrets that must never enter durable queues."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path


class EmailTransportError(RuntimeError):
    pass


def _secret(path: str | None) -> str | None:
    value = str(path or "").strip()
    if not value:
        return None
    try:
        return Path(value).read_text(encoding="utf-8").strip() or None
    except OSError as exc:
        raise EmailTransportError("SMTP credential file unavailable") from exc


class SmtpVerificationTransport:
    """Deliver a verification token directly; message bodies are never persisted by this class."""

    def __init__(self, *, host: str, port: int, sender: str, username: str | None = None,
                 password: str | None = None, security: str = "starttls", timeout: float = 10.0):
        self.host = str(host).strip()
        self.port = int(port)
        self.sender = str(sender).strip()
        self.username = str(username or "").strip() or None
        self.password = password
        self.security = str(security or "starttls").strip().lower()
        self.timeout = float(timeout)
        if not self.host or not self.sender:
            raise EmailTransportError("SMTP transport is not configured")
        if self.security not in {"starttls", "ssl", "none"}:
            raise EmailTransportError("unsupported SMTP security mode")
        if self.security == "none" and self.host not in {"localhost", "127.0.0.1", "::1"}:
            raise EmailTransportError("unencrypted remote SMTP is not allowed")

    @classmethod
    def from_environment(cls):
        host = os.environ.get("DSM_SMTP_HOST", "")
        sender = os.environ.get("DSM_SMTP_FROM", "")
        security = os.environ.get("DSM_SMTP_SECURITY", "starttls")
        default_port = "465" if security.strip().lower() == "ssl" else "587"
        return cls(
            host=host,
            port=int(os.environ.get("DSM_SMTP_PORT", default_port)),
            sender=sender,
            username=os.environ.get("DSM_SMTP_USER"),
            password=_secret(os.environ.get("DSM_SMTP_PASSWORD_FILE")),
            security=security,
            timeout=float(os.environ.get("DSM_SMTP_TIMEOUT", "10")),
        )

    def send_verification(self, *, destination: str, token: str, expires_minutes: int) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = str(destination).strip()
        message["Subject"] = "Confirme a alteração de e-mail do Capivara DSM"
        message.set_content(
            "Foi solicitada uma alteração de e-mail para sua conta Capivara DSM.\n\n"
            f"Código de verificação: {token}\n\n"
            f"Este código expira em {int(expires_minutes)} minutos. "
            "Se você não solicitou a alteração, ignore esta mensagem."
        )
        context = ssl.create_default_context()
        try:
            if self.security == "ssl":
                client = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
            else:
                client = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            with client:
                if self.security == "starttls":
                    client.ehlo()
                    client.starttls(context=context)
                    client.ehlo()
                if self.username:
                    client.login(self.username, self.password or "")
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailTransportError("verification email delivery failed") from exc


__all__ = ["EmailTransportError", "SmtpVerificationTransport"]
