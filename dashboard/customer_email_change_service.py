#!/usr/bin/env python3
"""Secure Customer e-mail change orchestration."""
from __future__ import annotations

import re
import secrets
import uuid
from typing import Any

from customer_audit import audit_customer_event
from customer_email_change_repository import CustomerEmailChangeRepository
from customer_profile_self_service_http import _membership
from universal_event_repository import UniversalEventRepository

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _domain(email: str) -> str:
    parts = str(email).rsplit("@", 1)
    return parts[1].lower()[:191] if len(parts) == 2 else ""


def _publish(backend, *, event_type: str, membership: dict[str, Any], correlation_id: str,
             challenge_id: str, actor: str) -> None:
    try:
        UniversalEventRepository(backend).publish({
            "event_type": event_type,
            "source": "dashboard.customer-email-change",
            "source_id": str(membership.get("customer_code") or membership.get("customer_id")),
            "severity": "info",
            "correlation_id": correlation_id,
            "actor_type": "user",
            "actor_id": actor,
            "data": {
                "customer_id": str(membership.get("customer_id")),
                "challenge_id": challenge_id,
            },
        })
    except Exception:
        pass


def _audit(backend, *, membership: dict[str, Any], actor: str, action: str, result: str,
           correlation_id: str, challenge_id: str | None = None, target_domain: str | None = None) -> None:
    try:
        details = {
            "actor": actor,
            "role": "customer",
            "account_role": str(membership.get("account_role") or ""),
            "customer_id": str(membership.get("customer_id")),
            "customer_code": str(membership.get("customer_code") or ""),
            "correlation_id": correlation_id,
        }
        if challenge_id:
            details["challenge_id"] = challenge_id
        if target_domain:
            details["target_email_domain"] = target_domain
        audit_customer_event(backend, username=actor, action=action, result=result, details=details)
    except Exception:
        pass


class CustomerEmailChangeService:
    def __init__(self, backend, *, transport=None, max_requests: int = 3, rate_window_seconds: int = 900,
                 ttl_seconds: int = 1800):
        self.backend = backend
        self.repository = CustomerEmailChangeRepository(backend)
        self.transport = transport
        self.max_requests = max(1, int(max_requests))
        self.rate_window_seconds = max(60, int(rate_window_seconds))
        self.ttl_seconds = max(300, min(int(ttl_seconds), 86400))

    def _owner(self, user: dict[str, Any]) -> dict[str, Any]:
        membership = _membership(user, self.backend)
        if str(membership.get("account_role") or "").lower() != "owner":
            raise PermissionError("only Customer account owner can change e-mail")
        return membership

    def initiate(self, *, user: dict[str, Any], target_email: str, confirmed: bool,
                 correlation_id: str | None = None) -> dict[str, Any]:
        membership = self._owner(user)
        actor = str(membership.get("username") or user.get("username") or "customer")
        correlation_id = str(correlation_id or "").strip() or str(uuid.uuid4())
        if confirmed is not True:
            raise ValueError("explicit_confirmation_required")
        email = str(target_email or "").strip().lower()
        if len(email) > 320 or not _EMAIL_RE.fullmatch(email):
            raise ValueError("invalid_email")
        current = str(membership.get("login_email") or membership.get("account_email") or "").strip().lower()
        if email == current:
            raise ValueError("email_unavailable")
        if self.repository.recent_count(
            customer_id=str(membership["customer_id"]), username=actor, seconds=self.rate_window_seconds
        ) >= self.max_requests:
            _audit(self.backend, membership=membership, actor=actor, action="CUSTOMER_EMAIL_CHANGE_REQUESTED",
                   result="rate_limited", correlation_id=correlation_id)
            raise RuntimeError("rate_limited")
        if self.repository.email_in_use(email, except_username=actor):
            # Authenticated response deliberately does not disclose which account owns the e-mail.
            raise ValueError("email_unavailable")
        if self.transport is None:
            raise RuntimeError("email_delivery_unavailable")

        raw_token = secrets.token_urlsafe(32)
        challenge = self.repository.create(
            customer_id=str(membership["customer_id"]),
            customer_code=str(membership.get("customer_code") or ""),
            username=actor,
            target_email=email,
            raw_token=raw_token,
            correlation_id=correlation_id,
            ttl_seconds=self.ttl_seconds,
        )
        try:
            self.transport.send_verification(
                destination=email,
                token=raw_token,
                expires_minutes=max(1, self.ttl_seconds // 60),
            )
        except Exception:
            self.repository.mark_delivery_failed(challenge["challenge_id"])
            _audit(self.backend, membership=membership, actor=actor, action="CUSTOMER_EMAIL_CHANGE_REQUESTED",
                   result="delivery_failed", correlation_id=correlation_id, challenge_id=challenge["challenge_id"],
                   target_domain=_domain(email))
            raise RuntimeError("email_delivery_failed")
        finally:
            raw_token = ""  # keep the clear token process-local only for the SMTP call above.

        _audit(self.backend, membership=membership, actor=actor, action="CUSTOMER_EMAIL_CHANGE_REQUESTED",
               result="success", correlation_id=correlation_id, challenge_id=challenge["challenge_id"],
               target_domain=_domain(email))
        _publish(self.backend, event_type="CUSTOMER_EMAIL_CHANGE_REQUESTED", membership=membership,
                 correlation_id=correlation_id, challenge_id=challenge["challenge_id"], actor=actor)
        return {
            "accepted": True,
            "challenge_id": challenge["challenge_id"],
            "expires_at": challenge["expires_at"],
            "correlation_id": correlation_id,
        }

    def verify(self, *, user: dict[str, Any], challenge_id: str, token: str,
               confirmed: bool, correlation_id: str | None = None) -> dict[str, Any]:
        membership = self._owner(user)
        actor = str(membership.get("username") or user.get("username") or "customer")
        if confirmed is not True:
            raise ValueError("explicit_confirmation_required")
        if not str(challenge_id or "").strip() or not str(token or "").strip():
            raise ValueError("invalid_or_expired_challenge")
        result = self.repository.verify_and_commit(
            challenge_id=str(challenge_id).strip(),
            customer_id=str(membership["customer_id"]),
            username=actor,
            raw_token=str(token).strip(),
        )
        corr = str(correlation_id or result.get("correlation_id") or "").strip() or str(uuid.uuid4())
        _audit(self.backend, membership=membership, actor=actor, action="CUSTOMER_EMAIL_CHANGED",
               result="success", correlation_id=corr, challenge_id=str(challenge_id),
               target_domain=_domain(result["email"]))
        _publish(self.backend, event_type="CUSTOMER_EMAIL_CHANGED", membership=membership,
                 correlation_id=corr, challenge_id=str(challenge_id), actor=actor)
        return {"changed": True, "correlation_id": corr}

    def cancel(self, *, user: dict[str, Any], challenge_id: str, correlation_id: str | None = None) -> dict[str, Any]:
        membership = self._owner(user)
        actor = str(membership.get("username") or user.get("username") or "customer")
        corr = str(correlation_id or "").strip() or str(uuid.uuid4())
        cancelled = self.repository.cancel(
            challenge_id=str(challenge_id or "").strip(),
            customer_id=str(membership["customer_id"]), username=actor,
        )
        _audit(self.backend, membership=membership, actor=actor, action="CUSTOMER_EMAIL_CHANGE_CANCELLED",
               result="success" if cancelled else "rejected", correlation_id=corr,
               challenge_id=str(challenge_id or "").strip() or None)
        if cancelled:
            _publish(self.backend, event_type="CUSTOMER_EMAIL_CHANGE_CANCELLED", membership=membership,
                     correlation_id=corr, challenge_id=str(challenge_id), actor=actor)
        return {"cancelled": bool(cancelled), "correlation_id": corr}


__all__ = ["CustomerEmailChangeService"]
