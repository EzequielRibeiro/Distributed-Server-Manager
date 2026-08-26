#!/usr/bin/env python3
"""Deliver database-backed notification outbox rows to configured destinations."""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "database",):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from notification_outbox_repository import NotificationOutboxRepository
from notification_routing_repository import NotificationRoutingRepository
from runtime_backend import backend_from_environment


class NotificationDispatcher:
    def __init__(self, backend, *, timeout: int = 10, max_attempts: int = 5):
        self.backend = backend
        self.outbox = NotificationOutboxRepository(backend)
        self.routing = NotificationRoutingRepository(backend)
        self.timeout = max(1, int(timeout))
        self.max_attempts = max(1, int(max_attempts))

    def cycle(self, *, limit: int = 100) -> int:
        delivered = 0
        for row in self.outbox.pending(limit=limit):
            notification_id = str(row.get("notification_id") or "")
            attempts = int(row.get("attempts") or 0) + 1
            self.outbox.mark_processing(notification_id)
            try:
                destination = self.routing.delivery_destination(
                    channel=str(row.get("channel") or ""),
                    recipient=str(row.get("recipient") or ""),
                )
                if destination is None:
                    raise RuntimeError("configured notification destination is unavailable")
                self._deliver(row, destination)
            except Exception as exc:
                error = self._safe_error(exc)
                if attempts >= self.max_attempts:
                    self.outbox.mark_terminal_failed(notification_id, error)
                else:
                    self.outbox.mark_failed(
                        notification_id,
                        error,
                        next_attempt_at=self._retry_at(attempts),
                    )
            else:
                self.outbox.mark_delivered(notification_id)
                delivered += 1
        return delivered

    def _deliver(self, row: dict[str, Any], destination: dict[str, Any]) -> None:
        channel = str(destination.get("channel") or "").strip().lower()
        if channel == "discord":
            self._deliver_discord(row, destination)
            return
        if channel == "email":
            self._deliver_email(row, destination)
            return
        raise ValueError(f"unsupported notification channel: {channel}")

    def _deliver_discord(self, row: dict[str, Any], destination: dict[str, Any]) -> None:
        webhook_url = self._read_secret(destination, purpose="Discord webhook URL")
        subject = str(row.get("subject") or "").strip()
        message = str(row.get("message") or "").strip()
        content = f"**{subject}**\n{message}" if subject else message
        payload = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Capivara-DSM/notification-dispatcher"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            if not 200 <= int(response.status) < 300:
                raise RuntimeError(f"Discord returned HTTP {response.status}")

    def _deliver_email(self, row: dict[str, Any], destination: dict[str, Any]) -> None:
        config = destination.get("config") or {}
        host = str(config.get("host") or "").strip()
        sender = str(config.get("sender") or "").strip()
        recipient = str(destination.get("recipient") or "").strip()
        tls_mode = str(config.get("tls") or "starttls").strip().lower()
        if not host or not sender or not recipient:
            raise ValueError("email destination requires host, sender and recipient")
        if tls_mode not in {"starttls", "ssl", "none"}:
            raise ValueError("email tls must be starttls, ssl or none")
        default_port = 465 if tls_mode == "ssl" else (25 if tls_mode == "none" else 587)
        port = int(config.get("port") or default_port)
        username = str(config.get("username") or "").strip()
        password = self._read_secret(destination, purpose="SMTP password") if username else None

        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = str(row.get("subject") or "Capivara DSM")
        message.set_content(str(row.get("message") or ""))

        context = ssl.create_default_context()
        if tls_mode == "ssl":
            client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=self.timeout, context=context)
        else:
            client = smtplib.SMTP(host, port, timeout=self.timeout)
        try:
            if tls_mode == "starttls":
                client.starttls(context=context)
            if username:
                client.login(username, password or "")
            client.send_message(message)
        finally:
            try:
                client.quit()
            except Exception:
                client.close()

    @staticmethod
    def _read_secret(destination: dict[str, Any], *, purpose: str) -> str:
        secret_path = str(destination.get("secret_file") or "").strip()
        if not secret_path:
            raise ValueError(f"{purpose} secret_file is required")
        path = Path(secret_path)
        if not path.is_file():
            raise ValueError(f"{purpose} secret_file is unavailable")
        if path.stat().st_size > 16384:
            raise ValueError(f"{purpose} secret_file is too large")
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise ValueError(f"{purpose} secret_file is empty")
        return value

    @staticmethod
    def _retry_at(attempts: int) -> str:
        delay = min(3600, 30 * (2 ** max(0, attempts - 1)))
        when = datetime.now(timezone.utc) + timedelta(seconds=delay)
        return when.strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        if isinstance(exc, urllib.error.HTTPError):
            return f"HTTP delivery failed with status {exc.code}"
        if isinstance(exc, smtplib.SMTPResponseException):
            return f"SMTP delivery failed with status {exc.smtp_code}"
        if isinstance(exc, (ValueError, RuntimeError)):
            return str(exc)[:1000]
        return f"notification delivery failed ({type(exc).__name__})"


def run_forever() -> None:
    interval = max(1, int(os.environ.get("DSM_NOTIFICATION_CHECK_INTERVAL", "5")))
    limit = max(1, min(int(os.environ.get("DSM_NOTIFICATION_BATCH_SIZE", "100")), 1000))
    timeout = max(1, int(os.environ.get("DSM_NOTIFICATION_DELIVERY_TIMEOUT", "10")))
    max_attempts = max(1, int(os.environ.get("DSM_NOTIFICATION_MAX_ATTEMPTS", "5")))
    backend = backend_from_environment()
    dispatcher = NotificationDispatcher(backend, timeout=timeout, max_attempts=max_attempts)
    while True:
        try:
            dispatcher.cycle(limit=limit)
        except Exception as exc:
            print(f"notification dispatcher cycle failed: {type(exc).__name__}", file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    run_forever()
