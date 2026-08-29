#!/usr/bin/env python3
"""Persistent HTTP contract for game resource profiles stored in Catalog v2."""
from __future__ import annotations

import json
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

RESOURCE_PROFILES_PATH = "/api/catalog/resource-profiles"
_GAME_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_THEME_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ALLOWED_TAGS = {"section", "div", "article", "header", "footer", "h1", "h2", "h3", "h4", "p", "span", "strong", "em", "small", "ul", "ol", "li", "dl", "dt", "dd", "img", "br"}
_VOID_TAGS = {"img", "br"}
_ALLOWED_ATTRS = {"class", "title", "alt", "src"}
_TOKEN = re.compile(r"\{\{(?:profile\.(?:name|description|cpu_cores|memory_gb|storage_gb)|game\.name|asset:[a-zA-Z0-9._-]{1,64})\}\}")


class _SafeFragmentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in _ALLOWED_TAGS:
            return
        clean: list[str] = []
        for name, value in attrs:
            name = name.lower()
            value = str(value or "")
            if name not in _ALLOWED_ATTRS or name.startswith("on"):
                continue
            if name == "src":
                # Images are referenced through the managed asset placeholder only.
                if not re.fullmatch(r"\{\{asset:[a-zA-Z0-9._-]{1,64}\}\}", value):
                    continue
            clean.append(f'{name}="{escape(value, quote=True)}"')
        suffix = (" " + " ".join(clean)) if clean else ""
        self.parts.append(f"<{tag}{suffix}>")
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _VOID_TAGS or tag not in _ALLOWED_TAGS:
            return
        if tag in self.stack:
            while self.stack:
                current = self.stack.pop()
                self.parts.append(f"</{current}>")
                if current == tag:
                    break

    def handle_data(self, data: str) -> None:
        # Preserve only the supported template tokens; escape everything else.
        cursor = 0
        for match in _TOKEN.finditer(data):
            self.parts.append(escape(data[cursor:match.start()]))
            self.parts.append(match.group(0))
            cursor = match.end()
        self.parts.append(escape(data[cursor:]))

    def result(self) -> str:
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")
        return "".join(self.parts)


def _sanitize_html_fragment(value: Any) -> str:
    source = str(value or "").strip()
    if not source:
        return ""
    if len(source) > 20000:
        raise ValueError("profile presentation HTML is too large")
    parser = _SafeFragmentParser()
    parser.feed(source)
    parser.close()
    return parser.result()


def _sanitize_css(value: Any) -> str:
    css = str(value or "").strip()
    if not css:
        return ""
    if len(css) > 20000:
        raise ValueError("profile presentation CSS is too large")
    lowered = css.lower()
    forbidden = ("@import", "javascript:", "expression(", "behavior:", "-moz-binding", "url(data:text/html")
    if any(token in lowered for token in forbidden):
        raise ValueError("profile presentation CSS contains unsafe content")
    # Keep presentation inside its sandbox card and prevent network-loaded CSS assets.
    css = re.sub(r"url\s*\((?!\s*['\"]?\{\{asset:)[^)]+\)", "none", css, flags=re.I)
    return css


def _normalize_presentation(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    theme_id = str(item.get("theme_id") or "").strip().lower()
    if theme_id and not _THEME_ID.fullmatch(theme_id):
        raise ValueError("presentation theme ID must be valid")
    html = _sanitize_html_fragment(item.get("html"))
    css = _sanitize_css(item.get("css"))
    assets = item.get("assets") if isinstance(item.get("assets"), list) else []
    normalized_assets = []
    for asset in assets[:20]:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").strip()
        path = str(asset.get("path") or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,64}", name):
            continue
        # Managed assets may only use the dedicated application path.
        if not re.fullmatch(r"/profile-assets/[a-zA-Z0-9._/-]{1,180}", path):
            continue
        normalized_assets.append({"name": name, "path": path})
    if not (theme_id or html or css or normalized_assets):
        return None
    return {"theme_id": theme_id or None, "html": html, "css": css, "assets": normalized_assets}


def _normalize_profile(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("invalid resource profile")
    identifier = str(item.get("id") or "").strip().lower()
    name = str(item.get("name") or "").strip()
    if not _PROFILE_ID.fullmatch(identifier):
        raise ValueError("resource profile ID must be valid")
    if not name:
        raise ValueError("resource profile name is required")
    try:
        memory_mb = int(item.get("memory_mb"))
        storage_mb = int(item.get("storage_mb"))
        cpu_cores = float(item.get("cpu_cores"))
        swap_mb = int(item.get("swap_mb") or 0)
        pids_limit = int(item.get("pids_limit") or 512)
    except (TypeError, ValueError) as exc:
        raise ValueError("resource profile values must be numeric") from exc
    if memory_mb < 256 or storage_mb < 1024 or cpu_cores <= 0 or swap_mb < 0 or pids_limit < 1:
        raise ValueError("resource profile values are outside the allowed range")
    result = {
        "id": identifier,
        "name": name,
        "description": str(item.get("description") or "").strip(),
        "memory_mb": memory_mb,
        "storage_mb": storage_mb,
        "cpu_cores": cpu_cores,
        "swap_mb": swap_mb,
        "pids_limit": pids_limit,
    }
    presentation = _normalize_presentation(item.get("presentation"))
    if presentation:
        result["presentation"] = presentation
    return result


def _comparable_profiles(profiles: Any) -> list[dict[str, Any]] | None:
    if not isinstance(profiles, list):
        return None
    try:
        return [_normalize_profile(item) for item in profiles if isinstance(item, dict)]
    except ValueError:
        return None


def catalog_resource_profiles(root: Path, game: str) -> dict[str, Any]:
    game = str(game or "").strip().lower()
    if not _GAME_ID.fullmatch(game):
        raise ValueError("valid game is required")
    overrides_root = (root / "config" / "catalog-resource-profiles").resolve()
    override = (overrides_root / f"{game}.json").resolve()
    games_root = (root / "catalog" / "v2" / "games").resolve()
    catalog_path = (games_root / game / "resource-profiles.json").resolve()
    path = override if override.is_file() else catalog_path
    allowed_root = overrides_root if path == override else games_root
    try:
        path.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError("invalid catalog path") from exc
    if not path.is_file():
        return {"schema_version": 2, "kind": "GameResourceProfiles", "game": game,
                "default_profile_id": None, "profiles": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("kind") != "GameResourceProfiles" or payload.get("game") != game:
        raise RuntimeError("invalid resource profile catalog")
    profiles = payload.get("profiles") if isinstance(payload.get("profiles"), list) else []
    identifiers = {str(item.get("id") or "") for item in profiles if isinstance(item, dict)}
    default_profile_id = str(payload.get("default_profile_id") or "").strip().lower()
    if not default_profile_id and profiles:
        default_profile_id = str(profiles[0].get("id") or "").strip().lower()
    if default_profile_id and default_profile_id not in identifiers:
        raise RuntimeError("invalid default resource profile")
    payload["default_profile_id"] = default_profile_id or None
    return payload


def save_catalog_resource_profiles(root: Path, game: str, profiles: Any, default_profile_id: Any = None) -> dict[str, Any]:
    game = str(game or "").strip().lower()
    if not _GAME_ID.fullmatch(game):
        raise ValueError("valid game is required")
    game_dir = root / "catalog" / "v2" / "games" / game
    if not game_dir.is_dir():
        raise ValueError("game is not registered in Catalog")
    if not isinstance(profiles, list):
        raise ValueError("profiles must be a list")
    if not profiles:
        raise ValueError("at least one resource profile is required")
    normalized: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for item in profiles:
        profile = _normalize_profile(item)
        if profile["id"] in identifiers:
            raise ValueError("resource profile IDs must be unique and valid")
        identifiers.add(profile["id"])
        normalized.append(profile)
    default_profile_id = str(default_profile_id or "").strip().lower() or normalized[0]["id"]
    if default_profile_id not in identifiers:
        raise ValueError("default resource profile must reference an existing profile")
    payload = {"schema_version": 2, "kind": "GameResourceProfiles", "game": game,
               "default_profile_id": default_profile_id, "profiles": normalized}
    target = root / "config" / "catalog-resource-profiles" / f"{game}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(target)
    return payload


def create_catalog_resource_profile(root: Path, game: str, profile: Any) -> dict[str, Any]:
    current = catalog_resource_profiles(root, game)
    item = _normalize_profile(profile)
    profiles = list(current.get("profiles") or [])
    if any(str(existing.get("id") or "").lower() == item["id"] for existing in profiles):
        raise ValueError("resource profile ID already exists")
    profiles.append(item)
    default_id = current.get("default_profile_id") or item["id"]
    return save_catalog_resource_profiles(root, game, profiles, default_id)


def update_catalog_resource_profile(root: Path, game: str, profile_id: str, profile: Any) -> dict[str, Any]:
    current = catalog_resource_profiles(root, game)
    original = str(profile_id or "").strip().lower()
    item = _normalize_profile(profile)
    profiles = list(current.get("profiles") or [])
    index = next((i for i, existing in enumerate(profiles) if str(existing.get("id") or "").lower() == original), None)
    if index is None:
        raise LookupError("resource profile not found")
    if item["id"] != original and any(str(existing.get("id") or "").lower() == item["id"] for i, existing in enumerate(profiles) if i != index):
        raise ValueError("resource profile ID already exists")
    profiles[index] = item
    default_id = current.get("default_profile_id")
    if default_id == original:
        default_id = item["id"]
    return save_catalog_resource_profiles(root, game, profiles, default_id)


def delete_catalog_resource_profile(root: Path, game: str, profile_id: str) -> dict[str, Any]:
    current = catalog_resource_profiles(root, game)
    identifier = str(profile_id or "").strip().lower()
    profiles = list(current.get("profiles") or [])
    if not any(str(item.get("id") or "").lower() == identifier for item in profiles):
        raise LookupError("resource profile not found")
    if len(profiles) <= 1:
        raise ValueError("the last resource profile cannot be deleted")
    if str(current.get("default_profile_id") or "").lower() == identifier:
        raise ValueError("choose another default profile before deleting this profile")
    profiles = [item for item in profiles if str(item.get("id") or "").lower() != identifier]
    return save_catalog_resource_profiles(root, game, profiles, current.get("default_profile_id"))


def set_catalog_default_profile(root: Path, game: str, profile_id: str) -> dict[str, Any]:
    current = catalog_resource_profiles(root, game)
    identifier = str(profile_id or "").strip().lower()
    profiles = list(current.get("profiles") or [])
    if not any(str(item.get("id") or "").lower() == identifier for item in profiles):
        raise LookupError("resource profile not found")
    return save_catalog_resource_profiles(root, game, profiles, identifier)


def _role(user: dict[str, Any] | None) -> str:
    return str((user or {}).get("role") or "").lower()


def dispatch_catalog_resource_profiles_get(path: str, query_string: str, *, user: dict[str, Any] | None, root: Path):
    if path != RESOURCE_PROFILES_PATH:
        return None
    if _role(user) not in {"admin", "controller", "operator", "customer"}:
        return 403, {"error": "forbidden", "message": "catalog administration access required"}
    query = parse_qs(query_string, keep_blank_values=True)
    try:
        return 200, catalog_resource_profiles(root, (query.get("game") or [""])[0])
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except json.JSONDecodeError:
        return 500, {"error": "invalid_catalog", "message": "Resource profile catalog contains invalid JSON."}
    except Exception:
        return 500, {"error": "resource_profiles_failed", "message": "Não foi possível carregar os perfis de recursos."}


def dispatch_catalog_resource_profiles_put(path: str, payload: dict[str, Any] | None, *, user: dict[str, Any] | None, root: Path):
    """Compatibility whole-list PUT. New UI uses item-level methods below."""
    if path != RESOURCE_PROFILES_PATH:
        return None
    role = _role(user)
    if role not in {"admin", "controller", "operator"}:
        return 403, {"error": "forbidden", "message": "catalog write access required"}
    body = payload if isinstance(payload, dict) else {}
    try:
        if role == "operator":
            current = catalog_resource_profiles(root, body.get("game"))
            if _comparable_profiles(body.get("profiles")) != _comparable_profiles(current.get("profiles")):
                return 403, {"error": "forbidden", "message": "operators can only change the default profile"}
        return 200, save_catalog_resource_profiles(root, body.get("game"), body.get("profiles"), body.get("default_profile_id"))
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "resource_profiles_failed", "message": "Não foi possível salvar os perfis de recursos."}


def dispatch_catalog_resource_profiles_post(path: str, payload: dict[str, Any] | None, *, user: dict[str, Any] | None, root: Path):
    if path != RESOURCE_PROFILES_PATH:
        return None
    if _role(user) not in {"admin", "controller"}:
        return 403, {"error": "forbidden", "message": "profile editing requires admin or controller"}
    body = payload if isinstance(payload, dict) else {}
    try:
        return 201, create_catalog_resource_profile(root, body.get("game"), body.get("profile"))
    except (ValueError, LookupError) as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "resource_profiles_failed", "message": "Não foi possível criar o perfil."}


def dispatch_catalog_resource_profiles_patch(path: str, payload: dict[str, Any] | None, *, user: dict[str, Any] | None, root: Path):
    if path != RESOURCE_PROFILES_PATH:
        return None
    role = _role(user)
    body = payload if isinstance(payload, dict) else {}
    try:
        operation = str(body.get("operation") or "update").strip().lower()
        if operation == "set_default":
            if role not in {"admin", "controller", "operator"}:
                return 403, {"error": "forbidden", "message": "catalog write access required"}
            return 200, set_catalog_default_profile(root, body.get("game"), body.get("profile_id"))
        if role not in {"admin", "controller"}:
            return 403, {"error": "forbidden", "message": "profile editing requires admin or controller"}
        return 200, update_catalog_resource_profile(root, body.get("game"), body.get("profile_id"), body.get("profile"))
    except LookupError as exc:
        return 404, {"error": "not_found", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "resource_profiles_failed", "message": "Não foi possível atualizar o perfil."}


def dispatch_catalog_resource_profiles_delete(path: str, query_string: str, *, user: dict[str, Any] | None, root: Path):
    if path != RESOURCE_PROFILES_PATH:
        return None
    if _role(user) not in {"admin", "controller"}:
        return 403, {"error": "forbidden", "message": "profile editing requires admin or controller"}
    query = parse_qs(query_string, keep_blank_values=True)
    try:
        return 200, delete_catalog_resource_profile(
            root,
            (query.get("game") or [""])[0],
            (query.get("profile_id") or [""])[0],
        )
    except LookupError as exc:
        return 404, {"error": "not_found", "message": str(exc)}
    except ValueError as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}
    except Exception:
        return 500, {"error": "resource_profiles_failed", "message": "Não foi possível excluir o perfil."}


__all__ = [
    "RESOURCE_PROFILES_PATH",
    "catalog_resource_profiles",
    "create_catalog_resource_profile",
    "delete_catalog_resource_profile",
    "dispatch_catalog_resource_profiles_delete",
    "dispatch_catalog_resource_profiles_get",
    "dispatch_catalog_resource_profiles_patch",
    "dispatch_catalog_resource_profiles_post",
    "dispatch_catalog_resource_profiles_put",
    "save_catalog_resource_profiles",
    "set_catalog_default_profile",
    "update_catalog_resource_profile",
]
