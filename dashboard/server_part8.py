#!/usr/bin/env python3
"""Customer HTTP integration wrapper for Capivara DSM.

Keeps the legacy dashboard server focused on transport while customer account
routing and RBAC stay in dedicated modules.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import server as legacy
from customer_account_http import AUTHENTICATED_PATHS, PUBLIC_PATHS, dispatch_customer_account
from customer_rbac import can_access_instance as customer_can_access_instance, instance_profile as customer_instance_profile, may_create_instance
from customer_team_repository import CustomerTeamRepository

CUSTOMER_PUBLIC_FILES = {
    "/customer-login.html": legacy.WEB_DIR / "customer-login.html",
    "/customer-register.html": legacy.WEB_DIR / "customer-register.html",
    "/customer-forgot-password.html": legacy.WEB_DIR / "customer-forgot-password.html",
    "/customer-reset-password.html": legacy.WEB_DIR / "customer-reset-password.html",
    "/customer-auth.css": legacy.WEB_DIR / "customer-auth.css",
    "/customer-auth.js": legacy.WEB_DIR / "customer-auth.js",
}
CUSTOMER_AUTHENTICATED_FILES = {
    "/customer-members.html": legacy.WEB_DIR / "customer-members.html",
    "/customer-members.js": legacy.WEB_DIR / "customer-members.js",
}
legacy.STATIC_FILES.update(CUSTOMER_PUBLIC_FILES)
legacy.STATIC_FILES.update(CUSTOMER_AUTHENTICATED_FILES)

_original_get = legacy.DashboardHandler.do_GET
_original_post = legacy.DashboardHandler.do_POST
_original_can_access_instance = legacy.can_access_instance
_original_instance_permission_profile = legacy.instance_permission_profile
_original_create_customer_instance = legacy.create_customer_instance


def _backend():
    return legacy.dashboard_repository(legacy.DATABASE_FILE).backend


def _dispatch(handler, method: str, path: str, *, user, payload=None) -> bool:
    result = dispatch_customer_account(method, path, payload=payload, user=user, backend=_backend())
    if result is None: return False
    status, body = result; handler.send_json(status, body); return True


def integrated_instance_permission_profile(user, instance_path, database_path=legacy.DATABASE_FILE):
    if user and user.get("role") == "customer":
        profile = customer_instance_profile(user, Path(instance_path).name, _backend())
        if profile:
            return profile
        # Compatibility for instances created before explicit instance_access rows:
        # only the recorded creator gets manager rights, never every customer user.
        metadata = legacy.instance_metadata(instance_path)
        owner = metadata.get("owner", {}) if isinstance(metadata, dict) else {}
        if isinstance(owner, dict) and owner.get("username") == user.get("username") and legacy.instance_customer_id(metadata) == user.get("scope_id"):
            return "manager"
        return None
    return _original_instance_permission_profile(user, instance_path, database_path)


def integrated_can_access_instance(user, instance_path, write=False):
    if user and user.get("role") == "customer":
        profile = integrated_instance_permission_profile(user, instance_path)
        if not profile: return False
        return profile in {"operator", "manager"} if write else True
    return _original_can_access_instance(user, instance_path, write=write)


def integrated_create_customer_instance(user, payload, root=legacy.DSM_ROOT, database_path=legacy.DATABASE_FILE):
    if user and user.get("role") == "customer" and not may_create_instance(user, _backend()):
        raise PermissionError("customer account role cannot create instances")
    result = _original_create_customer_instance(user, payload, root=root, database_path=database_path)
    if user and user.get("role") == "customer" and result.get("instance_id"):
        CustomerTeamRepository(_backend()).set_instance_access(
            str(user["scope_id"]), str(user["username"]), str(result["instance_id"]), "manager"
        )
    return result


legacy.instance_permission_profile = integrated_instance_permission_profile
legacy.can_access_instance = integrated_can_access_instance
legacy.create_customer_instance = integrated_create_customer_instance


def integrated_get(self):
    path = urlparse(self.path).path
    if path in CUSTOMER_PUBLIC_FILES:
        self.send_file(CUSTOMER_PUBLIC_FILES[path]); return
    if path in AUTHENTICATED_PATHS:
        user = legacy.authenticate(self.headers)
        if not legacy.can_read(user): self.unauthorized(); return
        if _dispatch(self, "GET", path, user=user): return
    _original_get(self)


def integrated_post(self):
    path = urlparse(self.path).path
    if path in PUBLIC_PATHS:
        try: payload = self.read_json_body()
        except ValueError as exc: self.send_json(400, {"error": str(exc)}); return
        if _dispatch(self, "POST", path, user=None, payload=payload): return
    if path in AUTHENTICATED_PATHS:
        user = legacy.authenticate(self.headers)
        if user is None: self.unauthorized(); return
        if not legacy.can_write(user): self.forbidden(); return
        try: payload = self.read_json_body()
        except ValueError as exc: self.send_json(400, {"error": str(exc)}); return
        if _dispatch(self, "POST", path, user=user, payload=payload): return
    _original_post(self)


legacy.DashboardHandler.do_GET = integrated_get
legacy.DashboardHandler.do_POST = integrated_post


def run(): legacy.run()


if __name__ == "__main__": run()
