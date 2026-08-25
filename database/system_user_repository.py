#!/usr/bin/env python3
"""Canonical persistence for privileged Capivara system users."""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Any, Iterator

from alert_repository import AlertSession, dialect_for_backend
from backend import DatabaseBackend

SYSTEM_ROLES = {"admin", "controller", "operator"}
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


def normalize_system_email(value: Any) -> str | None:
    email = str(value or "").strip().lower()
    if not email:
        return None
    if len(email) > 320 or not _EMAIL_RE.fullmatch(email):
        raise ValueError("e-mail corporativo inválido")
    return email


def normalize_system_username(value: Any) -> str:
    username = str(value or "").strip().lower()
    if not _USERNAME_RE.fullmatch(username):
        raise ValueError("login inválido")
    return username


def _optional_text(value: Any, *, limit: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) > limit:
        raise ValueError("campo funcional excede o tamanho permitido")
    return text


class SystemUserRepository:
    def __init__(self, backend: DatabaseBackend):
        self.backend = backend
        self.dialect = dialect_for_backend(backend)

    def initialize(self):
        return self.backend.initialize()

    @contextmanager
    def session(self, *, transaction: bool = False) -> Iterator[AlertSession]:
        context = self.backend.transaction() if transaction else self.backend.connect()
        with context as connection:
            session = AlertSession(self.backend, connection)
            try:
                yield session
            finally:
                session.close()

    def list_users(self) -> list[dict[str, Any]]:
        self.initialize()
        with self.session() as session:
            rows = session.execute(
                "SELECT username,password_hash,role,scope_id,active,full_name,"
                "corporate_email,phone,job_title,department,created_by,created_at,updated_at "
                "FROM dashboard_users WHERE role IN ('admin','controller','operator') "
                "ORDER BY LOWER(COALESCE(full_name,username)),username"
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, username: str) -> dict[str, Any] | None:
        self.initialize()
        username = normalize_system_username(username)
        ph = self.dialect.placeholder
        with self.session() as session:
            row = session.execute(
                "SELECT username,password_hash,role,scope_id,active,full_name,"
                "corporate_email,phone,job_title,department,created_by,created_at,updated_at "
                f"FROM dashboard_users WHERE username={ph} AND role IN ('admin','controller','operator')",
                (username,),
            ).fetchone()
        return None if row is None else dict(row)

    def save(
        self,
        *,
        username: str,
        password_hash: str,
        role: str,
        scope_id: str | None,
        active: bool,
        full_name: Any = None,
        corporate_email: Any = None,
        phone: Any = None,
        job_title: Any = None,
        department: Any = None,
        created_by: str | None = None,
        require_functional_identity: bool = False,
    ) -> dict[str, Any]:
        self.initialize()
        username = normalize_system_username(username)
        role = str(role or "").strip().lower()
        if role not in SYSTEM_ROLES:
            raise ValueError("perfil de usuário do sistema inválido")
        full_name = _optional_text(full_name, limit=255)
        corporate_email = normalize_system_email(corporate_email)
        phone = _optional_text(phone, limit=128)
        job_title = _optional_text(job_title, limit=255)
        department = _optional_text(department, limit=255)
        created_by = _optional_text(created_by, limit=128)
        if require_functional_identity:
            if not full_name:
                raise ValueError("nome completo é obrigatório")
            if not corporate_email:
                raise ValueError("e-mail corporativo é obrigatório")
        ph = self.dialect.placeholder
        active_value = active if self.backend.name == "postgresql" else int(bool(active))
        with self.session(transaction=True) as session:
            duplicate_email = None
            if corporate_email:
                duplicate_email = session.execute(
                    "SELECT username FROM dashboard_users "
                    f"WHERE LOWER(corporate_email)=LOWER({ph}) AND username<>{ph}",
                    (corporate_email, username),
                ).fetchone()
            if duplicate_email is not None:
                raise ValueError("e-mail corporativo já cadastrado")
            current = session.execute(
                f"SELECT username,created_by FROM dashboard_users WHERE username={ph}",
                (username,),
            ).fetchone()
            now = self.dialect.current_timestamp
            if current is None:
                session.execute(
                    "INSERT INTO dashboard_users("
                    "username,password_hash,role,scope_id,customer_id,active,full_name,"
                    "corporate_email,phone,job_title,department,created_by"
                    f") VALUES ({self.dialect.parameters(12)})",
                    (
                        username, password_hash, role, scope_id, None, active_value,
                        full_name, corporate_email, phone, job_title, department, created_by,
                    ),
                )
            else:
                creator = current["created_by"] or created_by
                session.execute(
                    f"UPDATE dashboard_users SET password_hash={ph},role={ph},scope_id={ph},"
                    f"customer_id=NULL,active={ph},full_name={ph},corporate_email={ph},phone={ph},"
                    f"job_title={ph},department={ph},created_by={ph},updated_at={now} "
                    f"WHERE username={ph}",
                    (
                        password_hash, role, scope_id, active_value, full_name,
                        corporate_email, phone, job_title, department, creator, username,
                    ),
                )
        result = self.get(username)
        assert result is not None
        return result

    def delete(self, username: str) -> None:
        self.initialize()
        username = normalize_system_username(username)
        ph = self.dialect.placeholder
        with self.session(transaction=True) as session:
            row = session.execute(
                f"SELECT role,active FROM dashboard_users WHERE username={ph}",
                (username,),
            ).fetchone()
            if row is None or str(row["role"] or "").lower() not in SYSTEM_ROLES:
                raise ValueError("usuário do sistema não encontrado")
            if str(row["role"] or "").lower() == "admin":
                count = session.execute(
                    "SELECT COUNT(*) AS total FROM dashboard_users "
                    "WHERE role='admin' AND active=" + ("TRUE" if self.backend.name == "postgresql" else "1")
                ).fetchone()
                if bool(row["active"]) and int(count["total"] or 0) <= 1:
                    raise ValueError("o último administrador ativo não pode ser excluído")
            session.execute(f"DELETE FROM dashboard_users WHERE username={ph}", (username,))


__all__ = [
    "SYSTEM_ROLES",
    "SystemUserRepository",
    "normalize_system_email",
    "normalize_system_username",
]
