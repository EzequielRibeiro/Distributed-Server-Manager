#!/usr/bin/env python3
"""Restricted administration contract for Capivara system users."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from users import (
    generate_temporary_password,
    hash_password,
    hash_temporary_password,
    is_temporary_password_hash,
)

SYSTEM_ROLES = {"admin", "controller", "operator"}
USERS_PATH = "/api/users"
USERS_SAVE_PATH = "/api/users/save"
USERS_DELETE_PATH = "/api/users/delete"
PASSWORD_CHANGE_PATH = "/api/system-users/change-password"
CHANGE_PASSWORD_PAGE = "/system-change-password.html"

_USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}")


def _role(value: Any) -> str:
    role = str(value or "").strip().lower()
    if role not in SYSTEM_ROLES:
        raise ValueError("perfil de usuário do sistema inválido")
    return role


def _username(value: Any) -> str:
    username = str(value or "").strip().lower()
    if not _USERNAME_RE.fullmatch(username):
        raise ValueError("login inválido")
    return username


def _users_by_name(repository) -> dict[str, dict[str, Any]]:
    return {str(item["username"]): dict(item) for item in repository.load_users()}


def _admin_count(users: dict[str, dict[str, Any]]) -> int:
    return sum(1 for item in users.values() if str(item.get("role") or "").lower() == "admin")


def _active_admin_count(users: dict[str, dict[str, Any]]) -> int:
    return sum(
        1 for item in users.values()
        if str(item.get("role") or "").lower() == "admin" and bool(item.get("active", True))
    )


def _safe_user(item: dict[str, Any], *, admin_count: int) -> dict[str, Any]:
    role = str(item.get("role") or "").lower()
    return {
        "username": str(item.get("username") or ""),
        "role": role,
        "scope_id": item.get("scope_id") or "",
        "active": bool(item.get("active", True)),
        "must_change_password": is_temporary_password_hash(item.get("password_hash")),
        "delete_allowed": not (role == "admin" and admin_count <= 1),
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

    def repository():
        return legacy.dashboard_repository(legacy.DATABASE_FILE)

    def authenticated(self):
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized()
            return None
        return user

    def temporary_required(username: str) -> bool:
        users = _users_by_name(repository())
        item = users.get(str(username or "").strip().lower())
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
            scopes = legacy.user_scope_options()
            body = {
                "users": [_safe_user(item, admin_count=count) for item in users.values() if str(item.get("role") or "").lower() in SYSTEM_ROLES],
                "scopes": {"controllers": scopes.get("controllers", [])},
                "security": {"admin_count": count, "active_admin_count": _active_admin_count(users)},
            }
            self.send_json(200, body)
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
                users = _users_by_name(repo)
                username = str(user.get("username") or "").strip().lower()
                current = users.get(username)
                if current is None:
                    raise ValueError("Usuário não encontrado.")
                if not is_temporary_password_hash(current.get("password_hash")):
                    raise ValueError("A conta não possui senha temporária pendente.")
                repo.save_user(
                    username,
                    hash_password(new_password),
                    str(current.get("role") or ""),
                    current.get("scope_id") or None,
                    bool(current.get("active", True)),
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
                    username = _username(body.get("username"))
                    existing = users.get(username)
                    if existing is None:
                        raise ValueError("Usuário não encontrado.")
                    if username == current_username:
                        raise ValueError("O administrador conectado não pode excluir a própria conta.")
                    if str(existing.get("role") or "").lower() == "admin" and _admin_count(users) <= 1:
                        raise ValueError("O último administrador do sistema não pode ser excluído.")
                    repo.delete_user(username)
                    self.send_json(200, {"deleted": True, "username": username})
                    return

                username = _username(body.get("username"))
                role = _role(body.get("role"))
                active = bool(body.get("active", True))
                scope_id = _scope_for_role(legacy, role, body.get("scope_id"))
                existing = users.get(username)
                if username == current_username and (role != "admin" or not active):
                    raise ValueError("O administrador conectado não pode remover o próprio acesso administrativo.")
                if existing is not None:
                    projected = {key: dict(value) for key, value in users.items()}
                    projected[username]["role"] = role
                    projected[username]["active"] = active
                    if _admin_count(users) <= 1 and str(existing.get("role") or "").lower() == "admin" and role != "admin":
                        raise ValueError("O último administrador do sistema não pode perder o perfil Admin.")
                    if _active_admin_count(projected) < 1:
                        raise ValueError("O sistema deve manter pelo menos um administrador ativo.")
                    repo.save_user(username, existing["password_hash"], role, scope_id, active)
                    self.send_json(200, {"saved": True, "username": username, "created": False})
                    return

                temporary_password = generate_temporary_password()
                repo.save_user(username, hash_temporary_password(temporary_password), role, scope_id, active)
                self.send_json(201, {
                    "saved": True,
                    "username": username,
                    "created": True,
                    "temporary_password": temporary_password,
                    "must_change_password": True,
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
