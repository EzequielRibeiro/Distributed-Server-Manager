#!/usr/bin/env python3
"""Safe provider-aware verification, publication and rollback for Catalog game builder."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import shutil
import socket
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

GAME_BUILDER_VERIFY_PATH = "/api/catalog/game-builder/verify"
GAME_BUILDER_PUBLISH_PATH = "/api/catalog/game-builder/publish"
GAME_BUILDER_ROLLBACK_PATH = "/api/catalog/game-builder/rollback"
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
        with urlopen(request, timeout=6) as response:  # nosec B310: host validated above
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
    os_name = str(payload.get("os") or "linux").strip().lower()
    if os_name not in {"linux", "windows"}:
        raise ValueError("sistema operacional deve ser linux ou windows")
    architecture = str(payload.get("architecture") or "x86_64").strip().lower()
    if architecture not in {"x86_64", "amd64", "arm64", "aarch64"}:
        raise ValueError("arquitetura não suportada")
    protocol = str(payload.get("protocol") or "udp").strip().lower()
    if protocol not in {"udp", "tcp"}:
        raise ValueError("protocolo deve ser UDP ou TCP")
    try:
        default_port = int(payload.get("default_port") or 27015)
    except (TypeError, ValueError) as exc:
        raise ValueError("porta padrão inválida") from exc
    if default_port < 1 or default_port > 65535:
        raise ValueError("porta padrão fora do intervalo permitido")
    args = [item.strip() for item in str(payload.get("args") or "").splitlines() if item.strip()]
    result = {
        "provider": provider,
        "game_id": game_id,
        "runtime_id": runtime_id,
        "name": name,
        "executable": executable,
        "edition": str(payload.get("edition") or "default").strip().lower() or "default",
        "variant": str(payload.get("variant") or "stable").strip().lower() or "stable",
        "os": os_name,
        "architecture": architecture,
        "protocol": protocol,
        "default_port": default_port,
        "args": args,
    }
    if provider == "steam":
        package_id = str(payload.get("package_id") or "").strip()
        if not package_id.isdigit():
            raise ValueError("Steam App ID / package ID deve ser numérico")
        auth = str(payload.get("auth") or "anonymous").strip().lower()
        if auth not in {"anonymous", "required"}:
            raise ValueError("modo de autenticação Steam inválido")
        result.update(package_id=package_id, auth=auth)
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


def _runtime_path(root: Path, spec: dict[str, Any]) -> Path:
    return root / "catalog" / "v2" / "games" / spec["game_id"] / "runtimes" / f"{spec['runtime_id'].replace('/', '_')}.json"


def _minecraft_template(root: Path, spec: dict[str, Any]) -> dict[str, Any] | None:
    if spec["provider"] != "minecraft":
        return None
    edition = spec["minecraft_edition"]
    server_type = spec["server_type"]
    candidates = [f"{edition}-{server_type}.json", f"{edition}-vanilla.json"]
    for name in candidates:
        path = root / "catalog" / "v2" / "games" / "minecraft" / "runtimes" / name
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    raise ValueError("não existe runtime Minecraft compatível para usar como base")


def build_runtime_definition(spec: dict[str, Any], *, root: Path) -> dict[str, Any]:
    template = _minecraft_template(root, spec)
    if template is not None:
        runtime = json.loads(json.dumps(template))
        runtime["id"] = spec["runtime_id"]
        runtime["name"] = spec["name"]
        runtime["game"] = spec["game_id"]
        runtime["edition"] = spec["edition"] if spec["edition"] != "default" else spec["minecraft_edition"]
        runtime["variant"] = spec["variant"]
        runtime.setdefault("installation", {})["directory"] = f"/opt/dsm/game-data/{spec['game_id']}/{spec['variant']}"
        return runtime

    provider = spec["provider"]
    artifact: dict[str, Any]
    if provider == "steam":
        artifact = {"provider": "steam", "auth": spec["auth"], "package_id": spec["package_id"]}
    elif provider in {"http", "github"}:
        archive = spec.get("archive") or "auto"
        artifact = {
            "provider": "http-archive" if archive != "none" else "http",
            "auth": "anonymous",
            "url": spec["url"],
        }
        if archive not in {"auto", "none"}:
            artifact["archive_type"] = archive
        if provider == "github":
            artifact["source"] = "github-release"
    elif provider == "local":
        artifact = {"provider": "local", "auth": "none", "path": spec["path"]}
    else:
        raise ValueError("provedor não pode ser publicado")

    executable = spec.get("executable") or ("server.exe" if spec["os"] == "windows" else "server")
    return {
        "schema_version": 2,
        "kind": "RuntimeDefinition",
        "id": spec["runtime_id"],
        "name": spec["name"],
        "game": spec["game_id"],
        "edition": spec["edition"],
        "variant": spec["variant"],
        "loader": None,
        "version": {"strategy": "static", "value": "current", "build": "catalog-builder"},
        "process": {"engine": "native", "executable": executable, "artifact_mode": "executable", "args": spec.get("args") or []},
        "requirements": {"os": [spec["os"]], "architectures": [spec["architecture"]], "java": None},
        "artifact": artifact,
        "installation": {"directory": f"/opt/dsm/game-data/{spec['game_id']}/{spec['variant']}"},
        "network": {
            "allocation": "block",
            "block_size": 1,
            "ports": [{"name": "game", "protocol": spec["protocol"], "offset": 0, "default": spec["default_port"]}],
            "apply": [{"kind": "argument", "template": "-port={game}"}],
        },
    }


def verify_catalog_game(payload: dict[str, Any], *, root: Path) -> dict[str, Any]:
    spec = _normalize(payload)
    target = _runtime_path(root, spec)
    game_exists = (root / "catalog" / "v2" / "games" / spec["game_id"]).is_dir()
    checks: list[dict[str, Any]] = [
        {"id": "definition", "ok": True, "message": "Definição básica válida."},
        {"id": "game", "ok": True, "warning": game_exists, "message": "Jogo existente; um novo runtime será acrescentado." if game_exists else "Novo ID de jogo disponível no catálogo."},
        {"id": "runtime_id", "ok": not target.exists(), "message": "ID de runtime disponível." if not target.exists() else "Já existe um runtime com esse ID neste jogo."},
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
        try:
            _minecraft_template(root, spec)
            checks.append({"id": "minecraft_template", "ok": True, "message": "Runtime Minecraft compatível localizado e pronto para clonagem segura."})
        except ValueError as exc:
            checks.append({"id": "minecraft_template", "ok": False, "message": str(exc)})
    try:
        runtime = build_runtime_definition(spec, root=root)
        checks.append({"id": "runtime_definition", "ok": runtime.get("kind") == "RuntimeDefinition", "message": "RuntimeDefinition gerada com sucesso."})
    except ValueError as exc:
        checks.append({"id": "runtime_definition", "ok": False, "message": str(exc)})
        runtime = None
    ok = all(item.get("ok") for item in checks if not item.get("warning"))
    return {"ok": ok, "mode": "dry-run", "provider": provider, "spec": spec, "runtime": runtime, "checks": checks, "message": "Verificação concluída sem instalar o jogo."}


def _history_root(root: Path) -> Path:
    return root / "config" / "catalog-game-builder" / "history"


def publish_catalog_game(payload: dict[str, Any], *, root: Path) -> dict[str, Any]:
    verification = verify_catalog_game(payload, root=root)
    if not verification["ok"]:
        raise ValueError("a definição precisa passar pelo Verificar antes da publicação")
    spec = verification["spec"]
    runtime = verification["runtime"]
    target = _runtime_path(root, spec)
    if target.exists():
        raise ValueError("runtime já existe no catálogo")
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(runtime, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    checksum = hashlib.sha256(encoded).hexdigest()
    temporary = target.with_suffix(target.suffix + ".tmp")
    try:
        temporary.write_bytes(encoded)
        parsed = json.loads(temporary.read_text(encoding="utf-8"))
        if parsed.get("kind") != "RuntimeDefinition" or parsed.get("id") != spec["runtime_id"]:
            raise ValueError("RuntimeDefinition gerada é inválida")
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    publication_id = f"pub-{int(time.time())}-{checksum[:12]}"
    history_root = _history_root(root)
    history_root.mkdir(parents=True, exist_ok=True)
    history = {
        "publication_id": publication_id,
        "created_at": int(time.time()),
        "game_id": spec["game_id"],
        "runtime_id": spec["runtime_id"],
        "target": str(target.relative_to(root)),
        "sha256": checksum,
        "provider": spec["provider"],
    }
    (history_root / f"{publication_id}.json").write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "publication": history, "runtime": runtime, "message": "Jogo/runtime publicado atomicamente no catálogo."}


def rollback_catalog_game(publication_id: str, *, root: Path) -> dict[str, Any]:
    publication_id = str(publication_id or "").strip()
    if not re.fullmatch(r"pub-[0-9]+-[a-f0-9]{12}", publication_id):
        raise ValueError("ID de publicação inválido")
    history_path = _history_root(root) / f"{publication_id}.json"
    if not history_path.is_file():
        raise LookupError("publicação não encontrada")
    history = json.loads(history_path.read_text(encoding="utf-8"))
    target = (root / str(history.get("target") or "")).resolve()
    catalog_root = (root / "catalog" / "v2" / "games").resolve()
    try:
        target.relative_to(catalog_root)
    except ValueError as exc:
        raise ValueError("destino de rollback inválido") from exc
    if not target.is_file():
        raise LookupError("runtime publicado já não existe")
    current_checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    if current_checksum != history.get("sha256"):
        raise ValueError("runtime foi alterado após a publicação; rollback automático recusado")
    target.unlink()
    runtime_dir = target.parent
    game_dir = runtime_dir.parent
    if runtime_dir.is_dir() and not any(runtime_dir.iterdir()):
        runtime_dir.rmdir()
    if game_dir.is_dir() and not any(game_dir.iterdir()):
        game_dir.rmdir()
    history["rolled_back_at"] = int(time.time())
    history_path.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "publication": history, "message": "Publicação revertida com segurança."}


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


def dispatch_catalog_game_builder_publish(path: str, payload: dict[str, Any] | None, *, user: dict[str, Any] | None, root: Path):
    if path != GAME_BUILDER_PUBLISH_PATH:
        return None
    if _role(user) not in {"admin", "controller"}:
        return 403, {"error": "forbidden", "message": "publicação de jogos requer Admin ou Controller"}
    try:
        return 201, publish_catalog_game(payload if isinstance(payload, dict) else {}, root=root)
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "catalog_game_publish_failed", "message": "Não foi possível publicar o jogo no catálogo."}


def dispatch_catalog_game_builder_rollback(path: str, payload: dict[str, Any] | None, *, user: dict[str, Any] | None, root: Path):
    if path != GAME_BUILDER_ROLLBACK_PATH:
        return None
    if _role(user) not in {"admin", "controller"}:
        return 403, {"error": "forbidden", "message": "rollback de catálogo requer Admin ou Controller"}
    try:
        return 200, rollback_catalog_game(str((payload or {}).get("publication_id") or ""), root=root)
    except LookupError as exc:
        return 404, {"error": "not_found", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "catalog_game_rollback_failed", "message": "Não foi possível reverter a publicação."}


__all__ = [
    "GAME_BUILDER_VERIFY_PATH", "GAME_BUILDER_PUBLISH_PATH", "GAME_BUILDER_ROLLBACK_PATH",
    "PROVIDERS", "build_runtime_definition", "dispatch_catalog_game_builder_publish",
    "dispatch_catalog_game_builder_rollback", "dispatch_catalog_game_builder_verify",
    "publish_catalog_game", "rollback_catalog_game", "verify_catalog_game",
]
