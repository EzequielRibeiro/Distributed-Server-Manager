#!/usr/bin/env python3
"""One-shot migration of legacy browser Basic-auth state to cookie sessions.

This codemod is intentionally scoped to dashboard/web JavaScript. It removes
browser authentication state from sessionStorage, replaces legacy Basic
Authorization headers with an explicit auth-area hint, and fixes Customer 401
routing. Login modules remain the only browser code allowed to construct Basic
credentials, and only for their initial credential-exchange request.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"

CUSTOMER_FILES = {
    "create-server-wizard.js",
    "customer-backup-transfer.js",
    "customer-change-password.js",
    "customer-deleted-backups.js",
    "customer-deletion-v2.js",
    "customer-email-change.js",
    "customer-instance-activity.js",
    "customer-instance-connection.js",
    "customer-instance-delete.js",
    "customer-instance-events.js",
    "customer-instance-v2.js",
    "customer-instance.js",
    "customer-members.js",
    "customer-navigation.js",
    "customer-placement-selector.js",
    "customer-profile.js",
    "customer-shell.js",
    "customer.js",
    "customer-backups.js",
    "customer-integrations.js",
    "customer-account.js",
    "runtime-selector.js",
}

LOGIN_EXEMPT = {"auth.js", "customer-auth.js"}


def area_for(path: Path) -> str:
    return "customer" if path.name in CUSTOMER_FILES else "controller"


def replace_authorization(text: str, area: str) -> str:
    area_prop = f'"X-Capivara-Auth-Area":"{area}"'
    patterns = [
        r'Authorization\s*:\s*`Basic \$\{auth\(\)\}`',
        r'Authorization\s*:\s*`Basic \$\{auth\}`',
        r'Authorization\s*:\s*["\']Basic ["\']\s*\+\s*auth\(\)',
        r'Authorization\s*:\s*["\']Basic ["\']\s*\+\s*auth\b',
        r'Authorization\s*:\s*["\']Basic ["\']\s*\+\s*\(sessionStorage\.getItem\(["\']dsm_auth["\']\)\s*\|\|\s*["\']["\']\)',
        r'Authorization\s*:\s*`Basic \$\{sessionStorage\.getItem\(["\']dsm_auth["\']\)\s*\|\|\s*["\']["\']\}`',
    ]
    for pattern in patterns:
        text = re.sub(pattern, area_prop, text)
    return text


def remove_auth_state(text: str) -> str:
    # Dedicated legacy auth declarations. Any remaining uses are detected by
    # the audit at the end instead of being silently hidden.
    text = re.sub(
        r'(?:const|let|var)\s+auth\s*=\s*\(\)\s*=>\s*sessionStorage\.getItem\(["\']dsm_auth["\']\)\s*\|\|\s*["\']["\']\s*;?',
        '', text,
    )
    text = re.sub(
        r'(?:const|let|var)\s+auth\s*=\s*sessionStorage\.getItem\(["\']dsm_auth["\']\)\s*\|\|\s*["\']["\']\s*;?',
        '', text,
    )
    # Authentication state cleanup is obsolete; there is no browser auth state
    # outside HttpOnly cookies anymore.
    text = re.sub(r'sessionStorage\.removeItem\(["\']dsm_auth["\']\)\s*;?', '', text)
    text = re.sub(r'sessionStorage\.removeItem\(["\']dsm_customer_auth["\']\)\s*;?', '', text)
    return text


def remove_preflight_guards(text: str) -> str:
    # Compact guards used by old modules before they even made an API request.
    guards = [
        r'if\s*\(\s*!auth\(\)\s*\)\s*\{\s*(?:window\.)?location\.(?:href|replace)\s*(?:=\s*["\']/login\.html["\']|\(["\']/login\.html["\']\))\s*;?\s*return\s*;?\s*\}',
        r'if\s*\(\s*!auth\s*\)\s*\{\s*(?:window\.)?location\.(?:href|replace)\s*(?:=\s*["\']/login\.html["\']|\(["\']/login\.html["\']\))\s*;?\s*return\s*;?\s*\}',
    ]
    for guard in guards:
        text = re.sub(guard, '', text)
    return text


def migrate(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    text = original
    area = area_for(path)

    if path.name not in LOGIN_EXEMPT:
        text = replace_authorization(text, area)
        text = remove_auth_state(text)
        text = remove_preflight_guards(text)

    # Login modules may clear historical browser state today, but those calls
    # themselves become a dependency/documentation trap. Remove them too.
    text = re.sub(r'sessionStorage\.removeItem\(["\']dsm_auth["\']\)\s*;?', '', text)
    text = re.sub(r'sessionStorage\.removeItem\(["\']dsm_customer_auth["\']\)\s*;?', '', text)

    if area == "customer":
        text = text.replace('location.href="/login.html"', 'location.href="/customer-login.html"')
        text = text.replace("location.href='/login.html'", "location.href='/customer-login.html'")
        text = text.replace('location.replace("/login.html")', 'location.replace("/customer-login.html")')
        text = text.replace("location.replace('/login.html')", "location.replace('/customer-login.html')")

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def audit() -> list[str]:
    findings: list[str] = []
    for path in sorted(WEB.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for needle in ("dsm_auth", "dsm_customer_auth"):
            if needle in text:
                findings.append(f"{rel}: legacy auth state {needle}")
        if path.name not in LOGIN_EXEMPT and re.search(r'Authorization\s*:\s*(?:`|["\'])Basic', text):
            findings.append(f"{rel}: legacy Basic Authorization")
        if area_for(path) == "customer" and re.search(r'location\.(?:href|replace).*?/login\.html', text):
            findings.append(f"{rel}: Customer redirects to Controller login")
    return findings


def main() -> int:
    changed = [path for path in sorted(WEB.rglob("*.js")) if migrate(path)]
    print(f"migrated_files={len(changed)}")
    for path in changed:
        print(path.relative_to(ROOT))
    findings = audit()
    if findings:
        print("\nResidual legacy browser-auth dependencies:")
        for finding in findings:
            print(f"- {finding}")
        return 2
    print("browser_auth_legacy_dependencies=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
