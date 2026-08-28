#!/usr/bin/env python3
"""Migrate and audit every authenticated browser module to cookie sessions.

The final browser model has no authentication state in Web Storage and sends no
Basic credential after the credential-exchange request. Controller and Customer
modules use their dedicated HttpOnly cookies; shared API routes are disambiguated
with X-Capivara-Auth-Area.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "dashboard" / "web"

CUSTOMER_FILES = {
    "create-server-wizard.js", "customer-backup-transfer.js",
    "customer-change-password.js", "customer-deleted-backups.js",
    "customer-deletion-v2.js", "customer-email-change.js",
    "customer-instance-activity.js", "customer-instance-connection.js",
    "customer-instance-delete.js", "customer-instance-events.js",
    "customer-instance-v2.js", "customer-instance.js", "customer-members.js",
    "customer-navigation.js", "customer-placement-selector.js",
    "customer-profile.js", "customer-shell.js", "customer.js",
    "customer-backups.js", "customer-integrations.js", "customer-account.js",
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
        r'Authorization\s*:\s*["\']Basic ["\']\s*\+\s*getAuth\(\)',
        r'Authorization\s*:\s*`Basic \$\{getAuth\(\)\}`',
        r'Authorization\s*:\s*["\']Basic ["\']\s*\+\s*token\b',
        r'Authorization\s*:\s*`Basic \$\{token\}`',
        r'Authorization\s*:\s*["\']Basic ["\']\s*\+\s*\(sessionStorage\.getItem\(["\']dsm_auth["\']\)\s*\|\|\s*["\']["\']\)',
        r'Authorization\s*:\s*`Basic \$\{sessionStorage\.getItem\(["\']dsm_auth["\']\)\s*\|\|\s*["\']["\']\}`',
    ]
    for pattern in patterns:
        text = re.sub(pattern, area_prop, text)
    return text


def remove_auth_state(text: str) -> str:
    empty_auth = r'sessionStorage\.getItem\(["\']dsm_auth["\']\)\s*\|\|\s*["\']["\']'
    text = re.sub(rf'(?:const|let|var)\s+auth\s*=\s*\(\)\s*=>\s*{empty_auth}\s*;?', '', text)
    text = re.sub(rf'(?:const|let|var)\s+auth\s*=\s*{empty_auth}\s*;?', '', text)
    text = re.sub(rf',\s*auth\s*=\s*\(\)\s*=>\s*{empty_auth}', '', text)
    text = re.sub(rf'\n?\s*const\s+auth\s*=\s*\(\)\s*=>\s*\{{\s*return\s+{empty_auth}\s*;?\s*\}}\s*;?', '', text)
    text = re.sub(r'function\s+getAuth\s*\(\s*\)\s*\{\s*return\s+sessionStorage\.getItem\(["\']dsm_auth["\']\)\s*;?\s*\}', '', text)
    text = re.sub(r'(?:const|let|var)\s+token\s*=\s*sessionStorage\.getItem\(["\']dsm_auth["\']\)\s*;?', '', text)
    text = re.sub(r'sessionStorage\.clear\(\)\s*;?', '', text)
    text = re.sub(r'sessionStorage\.removeItem\(["\']dsm_auth["\']\)\s*;?', '', text)
    text = re.sub(r'sessionStorage\.removeItem\(["\']dsm_customer_auth["\']\)\s*;?', '', text)
    return text


def remove_preflight_guards(text: str) -> str:
    guards = [
        r'if\s*\(\s*!auth\(\)\s*\)\s*\{\s*(?:window\.)?location\.(?:href|replace)\s*(?:=\s*["\']/login\.html["\']|\(["\']/login\.html["\']\))\s*;?\s*return\s*;?\s*\}',
        r'if\s*\(\s*!auth\s*\)\s*\{\s*(?:window\.)?location\.(?:href|replace)\s*(?:=\s*["\']/login\.html["\']|\(["\']/login\.html["\']\))\s*;?\s*return\s*;?\s*\}',
        r'if\s*\(\s*!token\s*\)\s*\{\s*(?:window\.)?location\.replace\(["\']/login\.html["\']\)\s*;?\s*throw\s+new\s+Error\([^)]*\)\s*;?\s*\}',
        r'if\s*\(\s*!token\s*\)\s*\{\s*return\s+null\s*;?\s*\}',
    ]
    for guard in guards:
        text = re.sub(guard, '', text)
    return text


def semantic_fixes(path: Path, text: str) -> str:
    area = area_for(path)
    area_header = f'"X-Capivara-Auth-Area": "{area}"'

    # Customer core uses shared whoami/runtime routes, so its identity must be
    # explicit when Controller and Customer cookies coexist.
    if path.name == "customer.js":
        text = text.replace('Accept: "application/json",\n      ...(options.headers || {}),', f'Accept: "application/json",\n      {area_header},\n      ...(options.headers || {}),')
        text = re.sub(
            r'if\s*\(\s*!\[\s*"customer",\s*"admin",\s*"controller",\s*\]\.includes\(\s*user\.role\s*\)\s*\)\s*\{\s*location\.href\s*=\s*"/index\.html";\s*return;\s*\}',
            'if (user.role !== "customer") {\n      location.replace("/customer-login.html");\n      return;\n    }',
            text,
            flags=re.S,
        )

    # Main Controller landing page also calls shared endpoints.
    if path.name == "dashboard-home-v3.js":
        if 'const controllerHeaders' not in text:
            text = text.replace('const $ = id => document.getElementById(id);', 'const $ = id => document.getElementById(id);\nconst controllerHeaders = () => ({Accept: "application/json", "X-Capivara-Auth-Area": "controller"});')
        text = text.replace('headers: {Accept: "application/json"},', 'headers: controllerHeaders(),')
        text = text.replace('const response=await fetch("/components/sidebar-v3.html",{cache:"no-store"});', 'const response=await fetch("/components/sidebar-v3.html",{headers:controllerHeaders(),credentials:"same-origin",cache:"no-store"});')
        text = text.replace('if(logout)logout.onclick=()=>{window.location.replace("/login.html")};', 'if(logout)logout.onclick=async()=>{try{await fetch("/api/auth/logout",{method:"POST",headers:controllerHeaders(),credentials:"same-origin",cache:"no-store"});}finally{window.location.replace("/login.html")}};')

    # Older Agents page remains routable. Make its cookie use explicit and make
    # logout revoke the Controller session instead of merely navigating away.
    if path.name == "agents.js":
        text = text.replace('fetch(`${API}${endpoint}`, {...options, headers})', 'fetch(`${API}${endpoint}`, {...options, headers, credentials:"same-origin", cache:options.cache||"no-store"})')
        text = text.replace('const response = await fetch("/components/sidebar.html");', 'const response = await fetch("/components/sidebar.html", {credentials:"same-origin", cache:"no-store"});')
        text = text.replace('logout.addEventListener("click", () => {\n            \n            window.location.replace("/login.html");\n        });', 'logout.addEventListener("click", async () => {\n            try { await fetch("/api/auth/logout", {method:"POST", headers:authHeader(), credentials:"same-origin", cache:"no-store"}); }\n            finally { window.location.replace("/login.html"); }\n        });')

    if path.name == "runtime-selector.js":
        text = text.replace('...(options.headers || {}),\n                },\n            }', '...(options.headers || {}),\n                },\n                credentials: "same-origin",\n                cache: options.cache || "no-store",\n            }')

    if path.name == "customer-instance.js":
        text = text.replace('fetch(path,{...options,headers})', 'fetch(path,{...options,headers,credentials:"same-origin",cache:options.cache||"no-store"})')
        text = text.replace('$("customer-logout").addEventListener("click",()=>{location.href="/customer-login.html"});', '$("customer-logout").addEventListener("click",async()=>{try{await fetch("/api/customer/auth/logout",{method:"POST",headers:{Accept:"application/json","X-Capivara-Auth-Area":"customer"},credentials:"same-origin",cache:"no-store"})}finally{location.href="/customer-login.html"}});')

    return text


def migrate(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    text = original
    area = area_for(path)
    if path.name not in LOGIN_EXEMPT:
        text = replace_authorization(text, area)
        text = remove_auth_state(text)
        text = remove_preflight_guards(text)
    text = re.sub(r'sessionStorage\.clear\(\)\s*;?', '', text)
    text = re.sub(r'sessionStorage\.removeItem\(["\']dsm_auth["\']\)\s*;?', '', text)
    text = re.sub(r'sessionStorage\.removeItem\(["\']dsm_customer_auth["\']\)\s*;?', '', text)
    if area == "customer":
        text = re.sub(r'((?:window\.)?location\.(?:href|replace)\s*(?:=\s*|\(\s*)["\'])/login\.html(["\'])', r'\1/customer-login.html\2', text)
    text = semantic_fixes(path, text)
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
        if "sessionStorage.clear()" in text:
            findings.append(f"{rel}: broad sessionStorage.clear in auth-era frontend")
        if path.name not in LOGIN_EXEMPT and re.search(r'Authorization\s*:\s*(?:`|["\'])Basic', text):
            findings.append(f"{rel}: legacy Basic Authorization")
        if area_for(path) == "customer" and re.search(r'location\.(?:href|replace)[^\n;]*?/login\.html', text):
            findings.append(f"{rel}: Customer redirects to Controller login")
        if "!token" in text and "X-Capivara-Auth-Area" in text and "sessionStorage.getItem" not in text:
            findings.append(f"{rel}: orphan token guard after migration")

    required_area = {
        "dashboard-home-v3.js": "controller",
        "agents-v3.js": "controller",
        "agents.js": "controller",
        "users.js": "controller",
        "operations.js": "controller",
        "observability.js": "controller",
        "system.js": "controller",
        "infrastructure-v3.js": "controller",
        "customer.js": "customer",
        "customer-instance-v2.js": "customer",
        "runtime-selector.js": "customer",
    }
    for name, area in required_area.items():
        text = (WEB / name).read_text(encoding="utf-8")
        if f'X-Capivara-Auth-Area' not in text or area not in text:
            findings.append(f"dashboard/web/{name}: missing explicit {area} auth area")

    customer_core = (WEB / "customer.js").read_text(encoding="utf-8")
    if 'user.role !== "customer"' not in customer_core:
        findings.append("dashboard/web/customer.js: Customer portal still accepts non-Customer roles")

    change_password = (WEB / "system-change-password.js").read_text(encoding="utf-8")
    if "sessionStorage" in change_password or "Authorization" in change_password:
        findings.append("dashboard/web/system-change-password.js: credential persistence remains")

    bridge = (WEB / "browser-session-bridge.js").read_text(encoding="utf-8")
    if "sessionStorage" in bridge or "dsm_auth" in bridge or "COMPAT_VALUE" in bridge:
        findings.append("dashboard/web/browser-session-bridge.js: legacy compatibility state remains")
    return findings


def main() -> int:
    changed = [path for path in sorted(WEB.rglob("*.js")) if migrate(path)]
    print(f"migrated_files={len(changed)}")
    for path in changed:
        print(path.relative_to(ROOT))
    findings = audit()
    if findings:
        print("\nResidual browser-auth migration findings:")
        for finding in findings:
            print(f"- {finding}")
        return 2
    print("browser_auth_legacy_dependencies=0")
    print("browser_auth_semantic_area_isolation=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
