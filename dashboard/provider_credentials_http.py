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

CURSEFORGE_PROVIDER_PATH = "/api/admin/providers/curseforge"
CURSEFORGE_API_BASE = "https://api.curseforge.com/v1"
CURSEFORGE_MINECRAFT_GAME_ID = 432


def _allowed(user):
    return isinstance(user, dict) and str(user.get("role") or "").strip().lower() in {"admin", "controller"}


def _key_path(root: Path) -> Path:
    return Path(root) / "config" / "providers" / "curseforge.key"


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
        if parsed.path != CURSEFORGE_PROVIDER_PATH:
            return previous_get(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized(); return
        status, body = dispatch_curseforge_provider_get(user=user, root=legacy.DSM_ROOT)
        self.send_json(status, body)

    def do_post(self):
        parsed = urlparse(self.path)
        if parsed.path != CURSEFORGE_PROVIDER_PATH:
            return previous_post(self)
        user = authenticate(self.headers)
        if user is None:
            self.unauthorized(); return
        try:
            payload = self.read_json_body()
        except ValueError:
            self.send_json(400, {"error": "invalid_request", "message": "Requisição inválida."}); return
        status, body = dispatch_curseforge_provider_post(payload, user=user, root=legacy.DSM_ROOT)
        self.send_json(status, body)

    legacy.DashboardHandler.do_GET = do_get
    legacy.DashboardHandler.do_POST = do_post


__all__ = [
    "CURSEFORGE_PROVIDER_PATH",
    "dispatch_curseforge_provider_get",
    "dispatch_curseforge_provider_post",
    "install_curseforge_provider_http",
]
