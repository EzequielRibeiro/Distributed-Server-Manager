#!/usr/bin/env python3
"""Functional HTTP deployment gate for the final Dashboard composition."""
from __future__ import annotations

import base64
import http.cookiejar
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "database", ROOT / "dashboard", ROOT / "core"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from admin_management_repository import AdminManagementRepository
from customer_management_repository import CustomerManagementRepository
from dashboard_repository import DashboardRepository
from runtime_backend import backend_from_environment
from system_user_repository import SystemUserRepository
from users import hash_password

ADMIN_USER = "functional-admin"
ADMIN_PASSWORD = "Functional-Admin-Test-Only-2026"
CUSTOMER_USER = "functional-customer"
INSTANCE_ID_EXPECTED = "cli-000001-minecraft-001"


def require_isolated_target() -> None:
    if os.environ.get("CAPIVARA_ALLOW_ISOLATED_DB_TEST") != "1":
        raise RuntimeError("functional deployment requires CAPIVARA_ALLOW_ISOLATED_DB_TEST=1")
    if os.environ.get("DSM_DATABASE_DRIVER", "").strip().lower() not in {
        "postgres", "postgresql", "pgsql"
    }:
        raise RuntimeError("functional deployment gate requires PostgreSQL")
    name = os.environ.get("DSM_DATABASE_NAME", "").strip().lower()
    if not name or "test" not in name:
        raise RuntimeError("DSM_DATABASE_NAME must contain 'test'")
    if not str(ROOT).startswith("/tmp/"):
        raise RuntimeError(f"functional deployment must run from /tmp, got {ROOT}")


def auth_value(username: str, password: str) -> str:
    raw = f"{username}:{password}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Browser:
    """Tiny browser-like client preserving the Dashboard session cookie."""

    def __init__(self, base: str):
        self.base = base
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cookies))

    def _open(self, path: str, *, method: str = "GET", body=None, headers=None):
        request_headers = dict(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        req = Request(self.base + path, data=data, headers=request_headers, method=method)
        try:
            return self.opener.open(req, timeout=10)
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            raise AssertionError(f"{method} {path}: HTTP {exc.code}: {raw}") from exc

    def login(self, username: str, password: str) -> dict:
        with self._open(
            "/api/auth/login",
            method="POST",
            headers={"Authorization": auth_value(username, password), "Accept": "application/json"},
        ) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
        if not list(self.cookies):
            raise AssertionError(f"login for {username} did not issue a browser session cookie")
        return payload

    def json(self, path: str, *, method: str = "GET", body=None, expected=(200,)) -> dict:
        with self._open(path, method=method, body=body, headers={"Accept": "application/json"}) as response:
            status = int(response.status)
            raw = response.read()
        if status not in expected:
            raise AssertionError(f"{method} {path}: expected {expected}, got {status}: {raw!r}")
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise AssertionError(f"{method} {path}: invalid JSON: {raw[:300]!r}") from exc

    def page(self, path: str, *, expected=(200,)) -> str:
        with self._open(path, headers={"Accept": "text/html,application/xhtml+xml"}) as response:
            status = int(response.status)
            raw = response.read()
            final_url = response.geturl()
        if status not in expected:
            raise AssertionError(f"GET {path}: expected {expected}, got {status}")
        if path != "/login.html" and final_url.endswith("/login.html"):
            raise AssertionError(f"GET {path}: browser session was redirected to login")
        return raw.decode("utf-8", "replace")


def wait_dashboard(base: str, process: subprocess.Popen, log_path: Path) -> None:
    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
            raise AssertionError(f"Dashboard exited with {process.returncode}:\n{text[-5000:]}")
        try:
            req = Request(base + "/login.html", headers={"Accept": "text/html"})
            with urlopen(req, timeout=5) as response:
                if response.status == 200 and b"login" in response.read().lower():
                    return
        except (HTTPError, URLError, ConnectionError) as exc:
            last_error = exc
        time.sleep(0.25)
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    raise AssertionError(f"Dashboard did not become ready: {last_error}\n{text[-5000:]}")


def bootstrap():
    backend = backend_from_environment()
    if backend.name != "postgresql":
        raise AssertionError(f"unexpected backend {backend.name}")
    backend.initialize()
    admin = AdminManagementRepository(backend)
    customers = CustomerManagementRepository(backend)
    users = SystemUserRepository(backend)

    with admin.session(transaction=True) as session:
        session.execute(
            "INSERT INTO nodes(id,name,role,status) VALUES (%s,%s,%s,%s)",
            ("functional-controller-node", "Functional Controller", "controller", "active"),
        )
        session.execute(
            "INSERT INTO controllers(id,node_id,name,status) VALUES (%s,%s,%s,%s)",
            ("functional-controller", "functional-controller-node", "Functional Controller", "active"),
        )
        session.execute(
            "INSERT INTO nodes(id,name,role,status) VALUES (%s,%s,%s,%s)",
            ("functional-agent-node", "Functional Agent Node", "agent", "active"),
        )
        session.execute(
            "INSERT INTO agents(id,node_id,controller_id,name,status) VALUES (%s,%s,%s,%s,%s)",
            ("functional-agent", "functional-agent-node", "functional-controller", "Functional Agent", "active"),
        )

    users.save(
        username=ADMIN_USER,
        password_hash=hash_password(ADMIN_PASSWORD),
        role="admin",
        scope_id=None,
        active=True,
        full_name="Functional Test Administrator",
        corporate_email="functional.admin@example.invalid",
        job_title="Test Administrator",
        department="CI",
        require_functional_identity=True,
    )
    customer = customers.create_account(
        name="Functional Customer",
        legal_name="Functional Customer Ltda",
        document_type="cpf",
        document_number="98765432100",
        username=CUSTOMER_USER,
        email="functional.customer@example.invalid",
        controller_id="functional-controller",
        billing_provider="functional-ci",
        billing_customer_id="functional-billing-1",
        billing_status="active",
    )
    contract = admin.create_contract(
        customer_id=customer["id"],
        game_id="minecraft",
        instance_limit=1,
        contract_id="functional-minecraft-contract",
        resource_profile_id="standard",
        resource_profile_source="functional-ci",
    )
    plan = DashboardRepository(backend).create_customer_instance(
        customer_id=customer["id"],
        username=CUSTOMER_USER,
        game="minecraft",
        runtime_id="minecraft.java.vanilla",
        edition="java",
        variant="vanilla",
        version="1.21.8",
        build="1",
        instances_root=ROOT / "instances",
        contract_id=contract["id"],
        selected_agent_id="functional-agent",
        network_profile=None,
        resource_profile_id="standard",
    )
    if plan["instance_id"] != INSTANCE_ID_EXPECTED:
        raise AssertionError(f"unexpected instance id: {plan['instance_id']}")
    with admin.session(transaction=True) as session:
        session.execute("UPDATE instances SET status=%s WHERE id=%s", ("running", plan["instance_id"]))
    return backend, customer, contract, plan


def main() -> int:
    require_isolated_target()
    backend, customer, contract, plan = bootstrap()
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    log_path = Path("/tmp/capivara-functional-dashboard.log")
    env = os.environ.copy()
    env.update({"DSM_ROOT": str(ROOT), "DASHBOARD_HOST": "127.0.0.1", "DASHBOARD_PORT": str(port)})
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(ROOT / "dashboard" / "server_part17.py")],
            cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT, text=True,
        )
    try:
        wait_dashboard(base, process, log_path)
        admin = Browser(base)
        customer_browser = Browser(base)

        admin.login(ADMIN_USER, ADMIN_PASSWORD)
        who = admin.json("/api/whoami")
        if who.get("role") != "admin" or who.get("username") != ADMIN_USER:
            raise AssertionError(f"unexpected Admin identity: {who}")
        admin_page = admin.page("/dashboard-v3.html")
        for token in ("<h1>Dashboard</h1>", "controller-telemetry", "home-agent-total"):
            if token not in admin_page:
                raise AssertionError(f"Admin dashboard missing structural marker {token!r}")

        customer_browser.login(CUSTOMER_USER, str(customer["temporary_password"]))
        who = customer_browser.json("/api/whoami")
        if who.get("role") != "customer" or who.get("username") != CUSTOMER_USER:
            raise AssertionError(f"unexpected Customer identity: {who}")
        customer_browser.page("/customer.html")
        iid = plan["instance_id"]
        instance_page = customer_browser.page(f"/customer-instance.html?instance_id={iid}")
        for token in ("customer-instance-v2.js", "Console", "Backups", "Equipe"):
            if token not in instance_page:
                raise AssertionError(f"Customer Instance page missing {token!r}")

        prefix = "/api/customer/instance/workspace"
        overview = customer_browser.json(f"{prefix}?instance_id={iid}")
        if overview.get("instance", {}).get("id") != iid:
            raise AssertionError(f"wrong Workspace instance: {overview}")
        if overview.get("provision") is not None:
            raise AssertionError("running instance must not show static provisioning progress")

        for suffix in ("telemetry", "console", "startup", "backup-policy", "upgrade-options", "permissions"):
            customer_browser.json(f"{prefix}/{suffix}?instance_id={iid}")
        customer_browser.json(f"{prefix}/team?instance_id={iid}")

        customer_browser.json(
            f"{prefix}/files", method="POST",
            body={"instance_id": iid, "action": "list", "path": "."}, expected=(202,),
        )
        if overview.get("console", {}).get("supported"):
            customer_browser.json(
                f"{prefix}/console", method="POST",
                body={"instance_id": iid, "command": "list"}, expected=(202,),
            )
        customer_browser.json(
            f"{prefix}/backups", method="POST",
            body={"instance_id": iid, "action": "create"}, expected=(202,),
        )
        activity = admin.json("/api/admin/activity-log?limit=100")
        if not isinstance(activity, dict):
            raise AssertionError("Admin activity API did not return an object")

        customer_browser.json("/api/auth/logout", method="POST", expected=(200, 204))
        admin.json("/api/auth/logout", method="POST", expected=(200, 204))
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    with backend.connect() as connection:
        rows = connection.execute(
            "SELECT activity,username,result FROM dashboard_activity_log "
            "WHERE username IN (%s,%s) ORDER BY created_at,event_id",
            (ADMIN_USER, CUSTOMER_USER),
        ).fetchall()
        file_commands = connection.execute(
            "SELECT COUNT(*) AS total FROM instance_file_commands WHERE instance_id=%s", (plan["instance_id"],)
        ).fetchone()
        backup_jobs = connection.execute(
            "SELECT COUNT(*) AS total FROM backup_jobs WHERE instance_id=%s", (plan["instance_id"],)
        ).fetchone()
    activities = {(str(row["username"]), str(row["activity"])) for row in rows}
    for username in (ADMIN_USER, CUSTOMER_USER):
        if (username, "LOGIN") not in activities or (username, "LOGOUT") not in activities:
            raise AssertionError(f"login/logout audit missing for {username}: {activities}")
    if int(file_commands["total"] or 0) < 1:
        raise AssertionError("file command was not persisted")
    if int(backup_jobs["total"] or 0) < 1:
        raise AssertionError("backup request was not persisted")

    print(
        "customer_workspace_functional_deployment_test: ok "
        f"customer={customer['customer_code']} contract={contract['id']} instance={plan['instance_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
