#!/usr/bin/env python3
from __future__ import annotations

import json
from urllib.parse import urlsplit

import customer_workspace_functional_deployment_test as functional

FINAL_PASSWORD = "Functional-Customer-Final-2026"
original_login = functional.Browser.login


def tracked_login(self, username: str, password: str):
    self._functional_username = username
    self._functional_password = password
    return original_login(self, username, password)


def traced_page(self, path: str, *, expected=(200,)) -> str:
    def fetch_page():
        with self._open(path, headers={"Accept": "text/html,application/xhtml+xml"}) as response:
            return int(response.status), response.read(), response.geturl()

    status, raw, final_url = fetch_page()
    final_path = urlsplit(final_url).path
    print(
        "FUNCTIONAL_PAGE_TRACE",
        f"requested={path}",
        f"final={final_path}",
        f"status={status}",
        f"title_fragment={raw[:180]!r}",
        flush=True,
    )

    if final_path == "/customer-change-password.html":
        username = getattr(self, "_functional_username", "")
        temporary_password = getattr(self, "_functional_password", "")
        if not username or not temporary_password:
            raise AssertionError("temporary-password redirect without tracked credentials")
        with self._open(
            "/api/customer/password/change-temporary",
            method="POST",
            body={"password": FINAL_PASSWORD, "password_confirmation": FINAL_PASSWORD},
            headers={
                "Authorization": functional.auth_value(username, temporary_password),
                "Accept": "application/json",
            },
        ) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
            if response.status != 200:
                raise AssertionError(f"temporary password change failed: {response.status} {payload}")
        self.cookies.clear()
        self.login(username, FINAL_PASSWORD)
        status, raw, final_url = fetch_page()
        final_path = urlsplit(final_url).path
        print(
            "FUNCTIONAL_PAGE_TRACE_AFTER_PASSWORD_CHANGE",
            f"requested={path}",
            f"final={final_path}",
            f"status={status}",
            flush=True,
        )

    if status not in expected:
        raise AssertionError(f"GET {path}: expected {expected}, got {status}")
    return raw.decode("utf-8", "replace")


functional.Browser.login = tracked_login
functional.Browser.page = traced_page
raise SystemExit(functional.main())
