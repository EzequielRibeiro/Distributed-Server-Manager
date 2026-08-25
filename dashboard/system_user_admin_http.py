#!/usr/bin/env python3
"""Restricted administration contract for Capivara system users."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from system_user_repository import SYSTEM_ROLES, SystemUserRepository
from users import (
    generate_temporary_password,
    hash_password,
    hash_temporary_password,
    is_temporary_password_hash,
)

USERS_PATH = "/api/users"
USERS_SAVE_PATH = "/api/users/save"
USERS_DELETE_PATH = "/api/users/delete"
PASSWORD_CHANGE_PATH = "/api/system-users/change-password"
CHANGE_PASSWORD_PAGE = "/system-change-password.html"


def _users_by_name(repository: SystemUserRepository) -> dict[str, dict[str, Any]]:
    return {str(item["username"]): dict(item) for item in repository.list_users()}


def _admin_count(users: dict[str, dict[str, Any]]) -> int:
    return sum(1 for item in users.values() if str(item.get("role") or "").lower() == "admin")


def _active_admin_count(users: dict[str, dict[str, Any]]) -> int:
    return sum(
        1 for item in users.values()
        if str(item.get("role") or "").lower() == "admin" and bool(item.get("active", True))
    )


def _safe_user(item: dict[str, Any], *, admin_count: int, active_admin_count: int) -> dict[str, Any]:
    role = str(item.get("role") or "").lower()
    active = bool(item.get("active", True))
    protected_admin = role == "admin" and (admin_count <= 1 or (active and active_admin_count <= 1))
    return {
        "username": str(item.get("username") or ""),
        "full_name": item.get("full_name"),
        "corporate_email": item.get("corporate_email"),
        "phone": item.get("phone"),
        "job_title": item.get("job_title"),
        "department": item.get("department"),
        "created_by": item.get("created_by"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "role": role,
        "scope_id": item.get("scope_id") or "",
        "active": active,
        "must_change_password": is_temporary_password_hash(item.get("password_hash")),
        "delete_allowed": not protected_admin,
    }


def _require_admin(user: dict[str, Any] | None):
    if not user or str(user.get("role") or "").lower() != "admin":
        raise PermissionError("admin access required")


def _scope_for_role(legacy, role: str, raw_scope: Any) -> str | None:
    scope = str(raw_scope or "").strip()
    if role in {"admin", "operator"}:
        return None
    if role != "controller":
        raise ValueError("invalid system role")
    if not scope:
        raise ValueError("controlador exige vínculo com um Controller")
    options = legacy.user_scope_options()
    valid = {str(item.get("id") or "") for item in options.get("controllers", [])}
    if scope not in valid:
        raise ValueError("Controller vinculado não existe")
    return scope


def install_system_user_administration(legacy, authenticate) -> None:
    """Install final route wrappers without growing the legacy server module."""
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST
    previous_put = getattr(legacy.DashboardHandler, "do_PUT", None)

    legacy.STATIC_FILES.update({
        CHANGE_PASSWORD_PAGE: legacy.WEB_DIR / "system-change-password.html",
        "/system-change-password.js": legacy.WEB_DIR / "system-change-password.js",
    })

    def repository() -> SystemUserRepository:
        backend = legacy.dashboard_repository(legacy.DATABASE_FILE).backend
        return SystemUserRepository(backend)

    def authenticated(self):
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return None
        return user

    def temporary_required(username: str) -> bool:
        item = repository().get(str(username or "").strip().lower())
        return bool(item and is_temporary_password_hash(item.get("password_hash")))

    def redirect(self, location: str):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/users.html":
            user = authenticated(self)
            if user is None:
                return
            if str(user.get("role") or "").lower() != "admin":
                self.send_json(403, {"error": "forbidden", "message": "Acesso exclusivo de administradores."})
                return
            if temporary_required(user.get("username")):
                redirect(self, CHANGE_PASSWORD_PAGE)
                return
            return self.send_file(legacy.WEB_DIR / "users.html")
        if path == CHANGE_PASSWORD_PAGE:
            user = authenticated(self)
            if user is None:
                return
            if not temporary_required(user.get("username")):
                redirect(self, "/dashboard-v3.html")
                return
            return self.send_file(legacy.WEB_DIR / "system-change-password.html")
        if path == USERS_PATH:
            user = authenticated(self)
            if user is None:
                return
            try:
                _require_admin(user)
            except PermissionError:
                self.send_json(403, {"error": "forbidden", "message": "Acesso exclusivo de administradores."})
                return
            if temporary_required(user.get("username")):
                self.send_json(428, {"error": "password_change_required", "message": "Troque a senha temporária antes de continuar."})
                return
            repo = repository()
            users = _users_by_name(repo)
            count = _admin_count(users)
            active_count = _active_admin_count(users)
            scopes = legacy.user_scope_options()
            self.send_json(200, {
                "users": [
                    _safe_user(item, admin_count=count, active_admin_count=active_count)
                    for item in users.values()
                ],
                "scopes": {"controllers": scopes.get("controllers", [])},
                "security": {"admin_count": count, "active_admin_count": active_count},
            })
            return
        user = authenticate(self.headers)
        if user is not None and temporary_required(user.get("username")):
            if path.endswith(".html") or path in {"/", "/index.html"}:
                redirect(self, CHANGE_PASSWORD_PAGE)
                return
        return previous_get(self)

    def do_post(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == PASSWORD_CHANGE_PATH:
            user = authenticated(self)
            if user is None:
                return
            try:
                body = self.read_json_body()
                new_password = str((body or {}).get("new_password") or "")
                if len(new_password) < 8:
                    raise ValueError("A nova senha deve ter pelo menos 8 caracteres.")
                repo = repository()
                username = str(user.get("username") or "").strip().lower()
                current = repo.get(username)
                if current is None:
                    raise ValueError("Usuário não encontrado.")
                if not is_temporary_password_hash(current.get("password_hash")):
                    raise ValueError("A conta não possui senha temporária pendente.")
                repo.save(
                    username=username,
                    password_hash=hash_password(new_password),
                    role=str(current.get("role") or ""),
                    scope_id=current.get("scope_id") or None,
                    active=bool(current.get("active", True)),
                    full_name=current.get("full_name"),
                    corporate_email=current.get("corporate_email"),
                    phone=current.get("phone"),
                    job_title=current.get("job_title"),
                    department=current.get("department"),
                    created_by=current.get("created_by"),
                )
                self.send_json(200, {"changed": True, "username": username, "must_change_password": False})
            except ValueError as exc:
                self.send_json(400, {"error": "invalid_request", "message": str(exc)})
            return

        if path in {USERS_SAVE_PATH, USERS_DELETE_PATH}:
            user = authenticated(self)
            if user is None:
                return
            try:
                _require_admin(user)
            except PermissionError:
                self.send_json(403, {"error": "forbidden", "message": "Acesso exclusivo de administradores."})
                return
            if temporary_required(user.get("username")):
                self.send_json(428, {"error": "password_change_required", "message": "Troque a senha temporária antes de continuar."})
                return
            try:
                body = self.read_json_body() or {}
                repo = repository()
                users = _users_by_name(repo)
                current_username = str(user.get("username") or "").lower()

                if path == USERS_DELETE_PATH:
                    username = str(body.get("username") or "").strip().lower()
                    existing = users.get(username)
                    if existing is None:
                        raise ValueError("Usuário não encontrado.")
                    if username == current_username:
                        raise ValueError("O administrador conectado não pode excluir a própria conta.")
                    projected = {key: dict(value) for key, value in users.items() if key != username}
                    if str(existing.get("role") or "").lower() == "admin" and _admin_count(users) <= 1:
                        raise ValueError("O último administrador do sistema não pode ser excluído.")
                    if _active_admin_count(projected) < 1:
                        raise ValueError("A exclusão deixaria o sistema sem administrador ativo.")
                    repo.delete(username)
                    self.send_json(200, {"deleted": True, "username": username})
                    return

                username = str(body.get("username") or "").strip().lower()
                role = str(body.get("role") or "").strip().lower()
                if role not in SYSTEM_ROLES:
                    raise ValueError("perfil de usuário do sistema inválido")
                active = bool(body.get("active", True))
                scope_id = _scope_for_role(legacy, role, body.get("scope_id"))
                existing = users.get(username)
                if username == current_username and (role != "admin" or not active):
                    raise ValueError("O administrador conectado não pode remover o próprio acesso administrativo.")

                profile = {
                    "full_name": body.get("full_name"),
                    "corporate_email": body.get("corporate_email"),
                    "phone": body.get("phone"),
                    "job_title": body.get("job_title"),
                    "department": body.get("department"),
                }

                if existing is not None:
                    projected = {key: dict(value) for key, value in users.items()}
                    projected[username]["role"] = role
                    projected[username]["active"] = active
                    if _admin_count(users) <= 1 and str(existing.get("role") or "").lower() == "admin" and role != "admin":
                        raise ValueError("O último administrador do sistema não pode perder o perfil Admin.")
                    if _active_admin_count(projected) < 1:
                        raise ValueError("O sistema deve manter pelo menos um administrador ativo.")
                    saved = repo.save(
                        username=username,
                        password_hash=existing["password_hash"],
                        role=role,
                        scope_id=scope_id,
                        active=active,
                        created_by=existing.get("created_by") or current_username,
                        require_functional_identity=True,
                        **profile,
                    )
                    self.send_json(200, {"saved": True, "username": username, "created": False, "user": _safe_user(saved, admin_count=_admin_count(projected), active_admin_count=_active_admin_count(projected))})
                    return

                temporary_password = generate_temporary_password()
                saved = repo.save(
                    username=username,
                    password_hash=hash_temporary_password(temporary_password),
                    role=role,
                    scope_id=scope_id,
                    active=active,
                    created_by=current_username,
                    require_functional_identity=True,
                    **profile,
                )
                projected = users | {username: saved}
                self.send_json(201, {
                    "saved": True,
                    "username": username,
                    "created": True,
                    "temporary_password": temporary_password,
                    "must_change_password": True,
                    "user": _safe_user(saved, admin_count=_admin_count(projected), active_admin_count=_active_admin_count(projected)),
                })
            except ValueError as exc:
                self.send_json(400, {"error": "invalid_request", "message": str(exc)})
            return

        user = authenticate(self.headers)
        if user is not None and temporary_required(user.get("username")):
            self.send_json(428, {"error": "password_change_required", "message": "Troque a senha temporária antes de continuar."})
            return
        return previous_post(self)

    def do_put(self):
        user = authenticate(self.headers)
        if user is not None and temporary_required(user.get("username")):
            self.send_json(428, {"error": "password_change_required", "message": "Troque a senha temporária antes de continuar."})
            return
        if previous_put is not None:
            return previous_put(self)
        self.send_json(404, {"error": "not_found"})

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post
    legacy.DashboardHandler.do_PUT = do_put


__all__ = [
    "SYSTEM_ROLES",
    "USERS_PATH",
    "USERS_SAVE_PATH",
    "USERS_DELETE_PATH",
    "PASSWORD_CHANGE_PATH",
    "CHANGE_PASSWORD_PAGE",
    "install_system_user_administration",
]
