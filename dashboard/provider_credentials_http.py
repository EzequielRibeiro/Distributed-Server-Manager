#!/usr/bin/env python3
"""Controller-side configuration surface for CurseForge credentials."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

PROVIDERS_PATH = "/api/admin/providers"
CURSEFORGE_PROVIDER_PATH = PROVIDERS_PATH + "/curseforge"
GITHUB_PROVIDER_PATH = PROVIDERS_PATH + "/github"
MODRINTH_PROVIDER_PATH = PROVIDERS_PATH + "/modrinth"
STEAM_PROVIDER_PATH = PROVIDERS_PATH + "/steam"
CURSEFORGE_API_BASE = "https://api.curseforge.com/v1"
CURSEFORGE_MINECRAFT_GAME_ID = 432
GITHUB_API_BASE = "https://api.github.com"
MODRINTH_API_BASE = "https://api.modrinth.com/v2"


def _allowed(user):
    return isinstance(user, dict) and str(user.get("role") or "").strip().lower() in {"admin", "controller"}


def _key_path(root: Path) -> Path:
    return Path(root) / "config" / "providers" / "curseforge.key"


def _github_token_path(root: Path) -> Path:
    return Path(root) / "config" / "providers" / "github.token"


def _steam_conf_path(root: Path) -> Path:
    return Path(root) / "config" / "providers" / "steam.conf"


def _read_key(root: Path) -> str:
    path = _key_path(root)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("CurseForge não está configurado no Controller.") from exc
    if not value or "\n" in value or "\r" in value:
        raise ValueError("A chave CurseForge configurada é inválida.")
    return value


def _validate_key(value) -> str:
    key = str(value or "").strip()
    if not key or len(key) < 8 or len(key) > 512 or any(ch.isspace() for ch in key):
        raise ValueError("Informe uma API key CurseForge válida.")
    return key


def _write_key(root: Path, value) -> None:
    key = _validate_key(value)
    path = _key_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o750)
    except OSError:
        pass
    fd, temporary = tempfile.mkstemp(prefix=".curseforge.", dir=str(path.parent), text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(key + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _remove_key(root: Path) -> None:
    _key_path(root).unlink(missing_ok=True)


def _write_secret(path: Path, value, *, label: str) -> None:
    secret = str(value or "").strip()
    if not secret or len(secret) > 4096 or any(ch.isspace() for ch in secret):
        raise ValueError(f"Informe um {label} válido.")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o750)
    except OSError:
        pass
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(secret + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        Path(temporary).unlink(missing_ok=True)
        raise


def _read_optional_secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return value if value and "\n" not in value and "\r" not in value else ""


def _status(root: Path) -> dict:
    path = _key_path(root)
    configured = False
    modified_at = None
    if path.is_file():
        try:
            value = path.read_text(encoding="utf-8").strip()
            configured = bool(value) and "\n" not in value and "\r" not in value
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            configured = False
    return {
        "provider": "curseforge",
        "configured": configured,
        "modified_at": modified_at,
        "secret_exposed": False,
    }


def _test_key(key: str, requester=None) -> dict:
    if requester is not None:
        payload = requester(key)
    else:
        request = Request(
            f"{CURSEFORGE_API_BASE}/games/{CURSEFORGE_MINECRAFT_GAME_ID}",
            headers={"Accept": "application/json", "User-Agent": "Capivara-DSM/2", "x-api-key": key},
        )
        try:
            with urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in {401, 403}:
                return {"ok": False, "message": "A API key CurseForge foi recusada."}
            return {"ok": False, "message": f"CurseForge respondeu com HTTP {exc.code}."}
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            return {"ok": False, "message": "Não foi possível validar a conexão com o CurseForge."}
    data = payload.get("data") if isinstance(payload, dict) else None
    valid = isinstance(data, dict) and int(data.get("id") or 0) == CURSEFORGE_MINECRAFT_GAME_ID
    return {
        "ok": bool(valid),
        "message": "Conexão com CurseForge validada." if valid else "Resposta inesperada da API CurseForge.",
    }




def _github_status(root: Path) -> dict:
    path = _github_token_path(root)
    configured = bool(_read_optional_secret(path))
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat() if configured else None
    return {
        "provider": "github",
        "configured": configured,
        "credential_required": False,
        "credential_kind": "token_optional",
        "modified_at": modified_at,
        "secret_exposed": False,
    }


def _modrinth_status() -> dict:
    return {
        "provider": "modrinth",
        "configured": True,
        "credential_required": False,
        "credential_kind": "none",
        "secret_exposed": False,
    }


def _steam_status(root: Path) -> dict:
    path = _steam_conf_path(root)
    user = "anonymous"
    if path.is_file():
        try:
            import re
            match = re.search(r'^\s*DSM_STEAM_USER\s*=\s*["\']?([^"\'\s#]+)', path.read_text(encoding="utf-8", errors="ignore"), re.M)
            if match:
                user = match.group(1)
        except OSError:
            pass
    return {
        "provider": "steam",
        "configured": True,
        "credential_required": False,
        "credential_kind": "steamcmd_session",
        "steam_user": user,
        "interactive_auth_required": user not in {"", "anonymous"},
        "secret_exposed": False,
    }


def _json_request(url: str, headers: dict[str, str] | None = None) -> dict:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Capivara-DSM/2", **(headers or {})})
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _test_github(token: str | None = None, requester=None) -> dict:
    try:
        if requester is not None:
            payload = requester(token or "")
        else:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            payload = _json_request(f"{GITHUB_API_BASE}/rate_limit", headers)
        ok = isinstance(payload, dict) and isinstance(payload.get("resources"), dict)
        return {"ok": ok, "message": "Conexão com GitHub validada." if ok else "Resposta inesperada da API GitHub."}
    except HTTPError as exc:
        if exc.code in {401, 403}:
            return {"ok": False, "message": "Token GitHub recusado ou sem permissão."}
        return {"ok": False, "message": f"GitHub respondeu com HTTP {exc.code}."}
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {"ok": False, "message": "Não foi possível validar a conexão com o GitHub."}


def _test_modrinth(requester=None) -> dict:
    try:
        payload = requester() if requester is not None else _json_request(f"{MODRINTH_API_BASE}/search?query=minecraft&limit=1")
        ok = isinstance(payload, dict) and isinstance(payload.get("hits"), list)
        return {"ok": ok, "message": "Conexão com Modrinth validada." if ok else "Resposta inesperada da API Modrinth."}
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return {"ok": False, "message": "Não foi possível validar a conexão com o Modrinth."}


def dispatch_provider_overview_get(*, user, root: Path):
    if not _allowed(user):
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    return 200, {
        "providers": [
            _status(root),
            _github_status(root),
            _modrinth_status(),
            _steam_status(root),
        ]
    }


def dispatch_github_provider_post(payload, *, user, root: Path, requester=None):
    if not _allowed(user):
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    body = payload if isinstance(payload, dict) else {}
    action = str(body.get("action") or "save").strip().lower()
    path = _github_token_path(root)
    try:
        if action == "save":
            _write_secret(path, body.get("token"), label="token GitHub")
            return 200, {**_github_status(root), "message": "Token GitHub salvo com segurança."}
        if action == "test":
            token = str(body.get("token") or "").strip() or _read_optional_secret(path)
            result = _test_github(token or None, requester=requester)
            return (200 if result["ok"] else 400), {**_github_status(root), **result}
        if action == "remove":
            path.unlink(missing_ok=True)
            return 200, {**_github_status(root), "message": "Token GitHub removido. O provider seguirá usando acesso público."}
        raise ValueError("Ação GitHub inválida.")
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc), **_github_status(root)}
    except OSError:
        return 500, {"error": "provider_secret_write_failed", "message": "Não foi possível persistir o token GitHub."}


def dispatch_modrinth_provider_post(payload, *, user, root: Path, requester=None):
    if not _allowed(user):
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    action = str((payload or {}).get("action") or "test").strip().lower()
    if action != "test":
        return 400, {"error": "invalid_request", "message": "Ação Modrinth inválida.", **_modrinth_status()}
    result = _test_modrinth(requester=requester)
    return (200 if result["ok"] else 400), {**_modrinth_status(), **result}


def dispatch_curseforge_provider_get(*, user, root: Path):
    if not _allowed(user):
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    return 200, _status(root)


def dispatch_curseforge_provider_post(payload, *, user, root: Path, requester=None):
    if not _allowed(user):
        return 403, {"error": "forbidden", "message": "Acesso administrativo necessário."}
    body = payload if isinstance(payload, dict) else {}
    action = str(body.get("action") or "save").strip().lower()
    try:
        if action == "save":
            _write_key(root, body.get("api_key"))
            return 200, {**_status(root), "message": "API key CurseForge salva com segurança."}
        if action == "test":
            key = _validate_key(body.get("api_key")) if body.get("api_key") else _read_key(root)
            result = _test_key(key, requester=requester)
            return (200 if result["ok"] else 400), {**_status(root), **result}
        if action == "remove":
            _remove_key(root)
            return 200, {**_status(root), "message": "API key CurseForge removida."}
        raise ValueError("Ação CurseForge inválida.")
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc), **_status(root)}
    except PermissionError:
        return 500, {"error": "provider_secret_write_failed", "message": "O Controller não possui permissão para gravar a credencial CurseForge."}
    except OSError:
        return 500, {"error": "provider_secret_write_failed", "message": "Não foi possível persistir a credencial CurseForge."}


def install_curseforge_provider_http(legacy, authenticate) -> None:
    previous_get = legacy.DashboardHandler.do_GET
    previous_post = legacy.DashboardHandler.do_POST

    def do_get(self):
        parsed = urlparse(self.path)
        if parsed.path not in {PROVIDERS_PATH, CURSEFORGE_PROVIDER_PATH, GITHUB_PROVIDER_PATH, MODRINTH_PROVIDER_PATH, STEAM_PROVIDER_PATH}:
            return previous_get(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized(); return
        if parsed.path == PROVIDERS_PATH:
            status, body = dispatch_provider_overview_get(user=user, root=legacy.DSM_ROOT)
        elif parsed.path == CURSEFORGE_PROVIDER_PATH:
            status, body = dispatch_curseforge_provider_get(user=user, root=legacy.DSM_ROOT)
        elif parsed.path == GITHUB_PROVIDER_PATH:
            status, body = (200, _github_status(legacy.DSM_ROOT)) if _allowed(user) else (403, {"error":"forbidden","message":"Acesso administrativo necessário."})
        elif parsed.path == MODRINTH_PROVIDER_PATH:
            status, body = (200, _modrinth_status()) if _allowed(user) else (403, {"error":"forbidden","message":"Acesso administrativo necessário."})
        else:
            status, body = (200, _steam_status(legacy.DSM_ROOT)) if _allowed(user) else (403, {"error":"forbidden","message":"Acesso administrativo necessário."})
        self.send_json(status, body)

    def do_post(self):
        parsed = urlparse(self.path)
        if parsed.path not in {CURSEFORGE_PROVIDER_PATH, GITHUB_PROVIDER_PATH, MODRINTH_PROVIDER_PATH}:
            return previous_post(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized(); return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."}); return
        if parsed.path == CURSEFORGE_PROVIDER_PATH:
            status, body = dispatch_curseforge_provider_post(payload, user=user, root=legacy.DSM_ROOT)
        elif parsed.path == GITHUB_PROVIDER_PATH:
            status, body = dispatch_github_provider_post(payload, user=user, root=legacy.DSM_ROOT)
        else:
            status, body = dispatch_modrinth_provider_post(payload, user=user, root=legacy.DSM_ROOT)
        self.send_json(status, body)

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post


__all__ = [
    "PROVIDERS_PATH",
    "CURSEFORGE_PROVIDER_PATH",
    "GITHUB_PROVIDER_PATH",
    "MODRINTH_PROVIDER_PATH",
    "STEAM_PROVIDER_PATH",
    "dispatch_provider_overview_get",
    "dispatch_curseforge_provider_get",
    "dispatch_curseforge_provider_post",
    "dispatch_github_provider_post",
    "dispatch_modrinth_provider_post",
    "install_curseforge_provider_http",
]
