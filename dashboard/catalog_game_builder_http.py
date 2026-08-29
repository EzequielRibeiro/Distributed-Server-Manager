#!/usr/bin/env python3
"""Safe provider-aware verification contract for the Catalog game builder."""
from __future__ import annotations

import ipaddress
import json
import re
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

GAME_BUILDER_VERIFY_PATH = "/api/catalog/game-builder/verify"
_GAME_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_RUNTIME_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
PROVIDERS = {
    "steam": {"label": "Steam", "kind": "artifact", "verification": "manifest"},
    "http": {"label": "HTTP / arquivo", "kind": "artifact", "verification": "remote"},
    "github": {"label": "GitHub Release", "kind": "artifact", "verification": "remote"},
    "local": {"label": "Jogo local", "kind": "artifact", "verification": "filesystem"},
    "minecraft": {"label": "Minecraft (assistente)", "kind": "assistant", "verification": "derived"},
}


def _role(user: dict[str, Any] | None) -> str:
    return str((user or {}).get("role") or "").strip().lower()


def _public_http_url(value: str) -> str:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("uma URL HTTP/HTTPS válida é obrigatória")
    host = parsed.hostname
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("não foi possível resolver o host informado") from exc
    for entry in addresses:
        raw = entry[4][0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if not ip.is_global:
            raise ValueError("URLs para redes privadas, loopback ou link-local não são permitidas")
    return parsed.geturl()


def _probe_remote(url: str) -> dict[str, Any]:
    safe = _public_http_url(url)
    request = Request(safe, method="HEAD", headers={"User-Agent": "CapivaraDSM-CatalogVerifier/1"})
    try:
        with urlopen(request, timeout=6) as response:  # nosec B310: host is public-address validated above
            length = response.headers.get("Content-Length")
            return {
                "ok": 200 <= int(response.status) < 400,
                "status": int(response.status),
                "content_type": response.headers.get("Content-Type"),
                "content_length": int(length) if length and length.isdigit() else None,
                "final_url": response.geturl(),
                "mode": "HEAD",
            }
    except Exception as exc:
        return {"ok": False, "mode": "HEAD", "message": str(exc)[:220]}


def _normalize(payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("provider") or "").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError("provedor não suportado")
    game_id = str(payload.get("game_id") or "").strip().lower()
    runtime_id = str(payload.get("runtime_id") or "").strip()
    name = str(payload.get("name") or "").strip()
    executable = str(payload.get("executable") or "").strip()
    if not _GAME_ID.fullmatch(game_id):
        raise ValueError("ID do jogo inválido")
    if not _RUNTIME_ID.fullmatch(runtime_id):
        raise ValueError("ID do runtime inválido")
    if not name:
        raise ValueError("nome do jogo é obrigatório")
    result = {
        "provider": provider,
        "game_id": game_id,
        "runtime_id": runtime_id,
        "name": name,
        "executable": executable,
        "edition": str(payload.get("edition") or "default").strip().lower() or "default",
        "variant": str(payload.get("variant") or "stable").strip().lower() or "stable",
    }
    if provider == "steam":
        package_id = str(payload.get("package_id") or "").strip()
        if not package_id.isdigit():
            raise ValueError("Steam App ID / package ID deve ser numérico")
        result.update(package_id=package_id, auth=str(payload.get("auth") or "anonymous").strip().lower())
    elif provider in {"http", "github"}:
        result["url"] = _public_http_url(str(payload.get("url") or ""))
        result["archive"] = str(payload.get("archive") or "auto").strip().lower() or "auto"
    elif provider == "local":
        path = Path(str(payload.get("path") or "").strip()).expanduser()
        if not path.is_absolute():
            raise ValueError("o caminho do jogo local deve ser absoluto")
        result["path"] = str(path)
    elif provider == "minecraft":
        edition = str(payload.get("minecraft_edition") or "java").strip().lower()
        if edition not in {"java", "bedrock"}:
            raise ValueError("edição Minecraft inválida")
        result["minecraft_edition"] = edition
        result["server_type"] = str(payload.get("server_type") or ("vanilla" if edition == "bedrock" else "paper")).strip().lower()
    return result


def verify_catalog_game(payload: dict[str, Any], *, root: Path) -> dict[str, Any]:
    spec = _normalize(payload)
    checks: list[dict[str, Any]] = [
        {"id": "definition", "ok": True, "message": "Definição básica válida."},
        {"id": "game_id", "ok": not (root / "catalog" / "v2" / "games" / spec["game_id"]).exists(), "message": "ID disponível no catálogo."},
    ]
    provider = spec["provider"]
    if provider in {"http", "github"}:
        remote = _probe_remote(spec["url"])
        checks.append({"id": "remote", "ok": bool(remote.get("ok")), "message": "Origem remota acessível." if remote.get("ok") else "Não foi possível validar a origem remota.", "details": remote})
    elif provider == "local":
        path = Path(spec["path"])
        checks.append({"id": "local_path", "ok": path.exists() and path.is_dir(), "message": "Diretório local encontrado." if path.exists() and path.is_dir() else "Diretório local não encontrado."})
        if spec.get("executable") and path.exists():
            candidate = path / spec["executable"]
            checks.append({"id": "executable", "ok": candidate.is_file(), "message": "Executável encontrado." if candidate.is_file() else "Executável não encontrado no diretório."})
    elif provider == "steam":
        checks.append({"id": "steam_manifest", "ok": True, "message": f"Steam App ID {spec['package_id']} aceito para simulação."})
        checks.append({"id": "agent_probe", "ok": True, "warning": True, "message": "Download Steam real deve ser verificado em um Agent com SteamCMD e credencial compatível."})
    elif provider == "minecraft":
        derived = "http" if spec["minecraft_edition"] == "bedrock" else "http/github"
        checks.append({"id": "minecraft_provider", "ok": True, "message": f"Assistente Minecraft resolvido para estratégia {derived}; Minecraft não é um provedor de artefato isolado."})
    ok = all(item.get("ok") for item in checks if not item.get("warning"))
    return {"ok": ok, "mode": "dry-run", "provider": provider, "spec": spec, "checks": checks, "message": "Verificação concluída sem instalar o jogo."}


def dispatch_catalog_game_builder_verify(path: str, payload: dict[str, Any] | None, *, user: dict[str, Any] | None, root: Path):
    if path != GAME_BUILDER_VERIFY_PATH:
        return None
    if _role(user) not in {"admin", "controller"}:
        return 403, {"error": "forbidden", "message": "criação de jogos requer Admin ou Controller"}
    try:
        return 200, verify_catalog_game(payload if isinstance(payload, dict) else {}, root=root)
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "catalog_game_verify_failed", "message": "Não foi possível verificar a definição do jogo."}


__all__ = ["GAME_BUILDER_VERIFY_PATH", "PROVIDERS", "dispatch_catalog_game_builder_verify", "verify_catalog_game"]
