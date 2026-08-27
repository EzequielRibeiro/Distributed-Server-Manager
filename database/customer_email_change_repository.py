#!/usr/bin/env python3
"""Migration-free persistence for verified Customer e-mail changes."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from alert_repository import AlertSession

_OPERATION = "customer_email_change"
_PENDING = {"pending", "delivery_failed"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


class CustomerEmailChangeRepository:
    def __init__(self, backend):
        self.backend = backend
        self.ph = "?" if backend.name == "sqlite" else "%s"

    def initialize(self) -> None:
        self.backend.initialize()

    @staticmethod
    def _payload(row) -> dict[str, Any]:
        value = dict(row)
        try:
            request = json.loads(str(value.get("request_json") or "{}"))
        except (TypeError, json.JSONDecodeError):
            request = {}
        value["request"] = request if isinstance(request, dict) else {}
        return value

    def recent_count(self, *, customer_id: str, username: str, seconds: int = 900) -> int:
        self.initialize()
        cutoff = _iso(_now() - timedelta(seconds=max(60, int(seconds))))
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(
                    f"SELECT request_json FROM operations WHERE operation_type={self.ph} AND created_at>={self.ph}",
                    (_OPERATION, cutoff),
                ).fetchall()
            finally:
                session.close()
        count = 0
        for row in rows:
            try:
                payload = json.loads(str(row["request_json"] or "{}"))
            except (TypeError, json.JSONDecodeError):
                continue
            if str(payload.get("customer_id")) == str(customer_id) and str(payload.get("username")) == str(username):
                count += 1
        return count

    def email_in_use(self, email: str, *, except_username: str | None = None) -> bool:
        self.initialize()
        sql = f"SELECT username FROM customer_user_identities WHERE LOWER(email)=LOWER({self.ph})"
        params: tuple[Any, ...] = (str(email),)
        if except_username:
            sql += f" AND username<>{self.ph}"
            params += (str(except_username),)
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                return session.execute(sql, params).fetchone() is not None
            finally:
                session.close()

    def create(self, *, customer_id: str, customer_code: str, username: str, target_email: str, raw_token: str,
               correlation_id: str, ttl_seconds: int = 1800) -> dict[str, Any]:
        self.initialize()
        challenge_id = str(uuid.uuid4())
        expires_at = _iso(_now() + timedelta(seconds=max(300, min(int(ttl_seconds), 86400))))
        request = {
            "customer_id": str(customer_id),
            "customer_code": str(customer_code),
            "username": str(username),
            "target_email": str(target_email).strip().lower(),
            "token_hash": token_hash(raw_token),
            "expires_at": expires_at,
            "correlation_id": str(correlation_id),
        }
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                rows = session.execute(
                    f"SELECT id,request_json,status FROM operations WHERE operation_type={self.ph} AND status IN ('pending','delivery_failed')",
                    (_OPERATION,),
                ).fetchall()
                for row in rows:
                    try:
                        old = json.loads(str(row["request_json"] or "{}"))
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if str(old.get("customer_id")) == str(customer_id) and str(old.get("username")) == str(username):
                        session.execute(
                            f"UPDATE operations SET status='superseded',completed_at=CURRENT_TIMESTAMP WHERE id={self.ph}",
                            (str(row["id"]),),
                        )
                session.execute(
                    f"INSERT INTO operations(id,operation_type,status,request_json,created_at) VALUES ({self.ph},{self.ph},'pending',{self.ph},CURRENT_TIMESTAMP)",
                    (challenge_id, _OPERATION, json.dumps(request, sort_keys=True, separators=(",", ":"))),
                )
            finally:
                session.close()
        return {"challenge_id": challenge_id, "expires_at": expires_at, "correlation_id": correlation_id}

    def mark_delivery_failed(self, challenge_id: str, code: str = "email_delivery_failed") -> None:
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(
                    f"UPDATE operations SET status='delivery_failed',error_code={self.ph} WHERE id={self.ph} AND operation_type={self.ph} AND status='pending'",
                    (str(code)[:128], str(challenge_id), _OPERATION),
                )
            finally:
                session.close()

    def cancel(self, *, challenge_id: str, customer_id: str, username: str) -> bool:
        challenge = self.get(challenge_id)
        if not challenge or str(challenge["request"].get("customer_id")) != str(customer_id) or str(challenge["request"].get("username")) != str(username):
            return False
        if str(challenge.get("status")) not in _PENDING:
            return False
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                session.execute(
                    f"UPDATE operations SET status='cancelled',completed_at=CURRENT_TIMESTAMP WHERE id={self.ph} AND status IN ('pending','delivery_failed')",
                    (str(challenge_id),),
                )
            finally:
                session.close()
        return True

    def get(self, challenge_id: str) -> dict[str, Any] | None:
        self.initialize()
        with self.backend.connect() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT * FROM operations WHERE id={self.ph} AND operation_type={self.ph}",
                    (str(challenge_id), _OPERATION),
                ).fetchone()
                return None if row is None else self._payload(row)
            finally:
                session.close()

    def verify_and_commit(self, *, challenge_id: str, customer_id: str, username: str, raw_token: str) -> dict[str, Any]:
        self.initialize()
        with self.backend.transaction() as connection:
            session = AlertSession(self.backend, connection)
            try:
                row = session.execute(
                    f"SELECT * FROM operations WHERE id={self.ph} AND operation_type={self.ph}",
                    (str(challenge_id), _OPERATION),
                ).fetchone()
                if row is None:
                    raise ValueError("invalid_or_expired_challenge")
                challenge = self._payload(row)
                request = challenge["request"]
                if str(request.get("customer_id")) != str(customer_id) or str(request.get("username")) != str(username):
                    raise PermissionError("challenge_owner_mismatch")
                if str(challenge.get("status")) != "pending":
                    raise ValueError("invalid_or_expired_challenge")
                if _parse(request.get("expires_at")) <= _now():
                    session.execute(
                        f"UPDATE operations SET status='expired',completed_at=CURRENT_TIMESTAMP WHERE id={self.ph}",
                        (str(challenge_id),),
                    )
                    raise ValueError("invalid_or_expired_challenge")
                expected = str(request.get("token_hash") or "")
                if not expected or not hmac.compare_digest(expected, token_hash(raw_token)):
                    raise ValueError("invalid_or_expired_challenge")
                target = str(request.get("target_email") or "").strip().lower()
                if not target:
                    raise ValueError("invalid_or_expired_challenge")
                duplicate = session.execute(
                    f"SELECT username FROM customer_user_identities WHERE LOWER(email)=LOWER({self.ph}) AND username<>{self.ph}",
                    (target, str(username)),
                ).fetchone()
                if duplicate is not None:
                    raise ValueError("email_unavailable")
                session.execute(
                    f"UPDATE customer_user_identities SET email={self.ph},email_verified_at=CURRENT_TIMESTAMP WHERE username={self.ph}",
                    (target, str(username)),
                )
                session.execute(
                    f"UPDATE customers SET account_email={self.ph},email_verified_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id={self.ph}",
                    (target, customer_id),
                )
                session.execute(
                    f"UPDATE operations SET status='verified',result_json={self.ph},completed_at=CURRENT_TIMESTAMP WHERE id={self.ph} AND status='pending'",
                    (json.dumps({"verified": True}, separators=(",", ":")), str(challenge_id)),
                )
                return {
                    "challenge_id": str(challenge_id),
                    "customer_id": str(customer_id),
                    "username": str(username),
                    "email": target,
                    "correlation_id": str(request.get("correlation_id") or ""),
                }
            finally:
                session.close()


__all__ = ["CustomerEmailChangeRepository", "token_hash"]
