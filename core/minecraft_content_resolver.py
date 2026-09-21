#!/usr/bin/env python3
"""Canonical Minecraft provider resolution for Universal Content."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MODRINTH_API_BASE = "https://api.modrinth.com/v2"
CURSEFORGE_API_BASE = "https://api.curseforge.com/v1"
CURSEFORGE_MINECRAFT_GAME_ID = 432
_USER_AGENT = "Capivara-DSM/2"
Requester = Callable[[str, Mapping[str, str]], Any]


class MinecraftContentResolverError(ValueError):
    pass


def _request_json(url: str, headers: Mapping[str, str]) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT, **dict(headers)})
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if "api.curseforge.com" in url and exc.code in {401, 403}:
            raise MinecraftContentResolverError("CurseForge não autorizado: verifique a API key no Controller.") from exc
        if "api.curseforge.com" in url and exc.code == 429:
            raise MinecraftContentResolverError("CurseForge atingiu o limite temporário de requisições. Tente novamente em alguns instantes.") from exc
        raise MinecraftContentResolverError(f"provider HTTP request failed with status {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        if "api.curseforge.com" in url:
            raise MinecraftContentResolverError("Não foi possível conectar ao CurseForge a partir do Controller.") from exc
        raise MinecraftContentResolverError("content provider request failed") from exc
    except json.JSONDecodeError as exc:
        raise MinecraftContentResolverError("content provider returned invalid JSON") from exc


def _https(value: Any, label: str) -> str:
    url = str(value or "").strip()
    if not url.startswith("https://"):
        raise MinecraftContentResolverError(f"{label} must use HTTPS")
    return url


def _secret_file(path: str | None) -> str:
    default_path = Path(os.environ.get("DSM_ROOT", "/opt/dsm")) / "config" / "providers" / "curseforge.key"
    candidate = str(path or os.environ.get("DSM_CURSEFORGE_API_KEY_FILE") or default_path).strip()
    if not candidate:
        raise MinecraftContentResolverError("CurseForge API key file is not configured")
    try:
        key = Path(candidate).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise MinecraftContentResolverError("CurseForge API key file is unavailable") from exc
    if not key or "\n" in key or "\r" in key:
        raise MinecraftContentResolverError("CurseForge API key file is invalid")
    return key


def provider_loaders(runtime: Mapping[str, Any], content_type: str) -> tuple[str, ...]:
    loader = str(runtime.get("loader") or runtime.get("variant") or "").strip().lower()
    ctype = str(content_type or "").strip().lower()
    if ctype == "mod":
        if loader in {"fabric", "forge", "neoforge", "quilt"}:
            return (loader,)
        if loader == "youer":
            return ("neoforge",)
        raise MinecraftContentResolverError("runtime has no proven mod provider loader mapping")
    if ctype == "plugin":
        mapping = {
            "paper": ("paper", "bukkit", "spigot"),
            "purpur": ("purpur", "paper", "bukkit", "spigot"),
            "folia": ("folia",),
            "spongevanilla": ("sponge",),
            "arclight": ("bukkit", "spigot"),
            "youer": ("bukkit", "spigot"),
        }
        if loader in mapping:
            return mapping[loader]
        raise MinecraftContentResolverError("runtime has no proven plugin provider loader mapping")
    raise MinecraftContentResolverError("provider resolution currently supports Minecraft mods and plugins only")


def _version_rank(item: Mapping[str, Any]) -> tuple[int, str]:
    channel = str(item.get("version_type") or "").lower()
    return ({"release": 3, "beta": 2, "alpha": 1}.get(channel, 0), str(item.get("date_published") or ""))


def resolve_modrinth(project: str, game_version: str, loaders: tuple[str, ...], content_type: str = "mod", *, requester: Requester = _request_json) -> dict[str, Any]:
    project = str(project or "").strip()
    ctype = str(content_type or "mod").strip().lower()
    if ctype not in {"mod", "plugin"}:
        raise MinecraftContentResolverError("Modrinth resolution supports mods and plugins only")
    if not project or any(ch in project for ch in ("/", "\\", "?", "#")):
        raise MinecraftContentResolverError("invalid Modrinth project reference")
    encoded_project = quote(project, safe="")
    project_payload = requester(f"{MODRINTH_API_BASE}/project/{encoded_project}", {})
    project_type = str(project_payload.get("project_type") or "").lower() if isinstance(project_payload, Mapping) else ""
    all_project_types = {str(value).strip().lower() for value in (project_payload.get("all_project_types") or []) if str(value).strip()} if isinstance(project_payload, Mapping) else set()
    project_categories = {
        str(value).strip().lower()
        for field in ("categories", "additional_categories")
        for value in (project_payload.get(field) or [])
        if str(value).strip()
    } if isinstance(project_payload, Mapping) else set()
    if ctype == "plugin":
        plugin_compatible = (
            project_type == "plugin"
            or "plugin" in all_project_types
            or (project_type == "mod" and any(loader in project_categories for loader in loaders))
        )
        if not plugin_compatible:
            raise MinecraftContentResolverError("Modrinth project is not a compatible plugin project")
    elif project_type != ctype:
        raise MinecraftContentResolverError(f"Modrinth project is not an individual {ctype} project")
    if str(project_payload.get("status") or "unknown").lower() not in {"approved", "archived"}:
        raise MinecraftContentResolverError("Modrinth project is not available for managed installation")
    query = urlencode({"game_versions": json.dumps([game_version]), "loaders": json.dumps(list(loaders)), "include_changelog": "false"})
    url = f"{MODRINTH_API_BASE}/project/{encoded_project}/version?{query}"
    payload = requester(url, {})
    versions = payload if isinstance(payload, list) else []
    compatible = [item for item in versions if isinstance(item, Mapping) and str(item.get("status") or "listed") in {"listed", "unknown"} and game_version in (item.get("game_versions") or []) and any(loader in (item.get("loaders") or []) for loader in loaders)]
    if not compatible:
        raise MinecraftContentResolverError("no compatible Modrinth version for this Minecraft runtime")
    version = sorted(compatible, key=_version_rank, reverse=True)[0]
    files = [item for item in (version.get("files") or []) if isinstance(item, Mapping)]
    file = next((item for item in files if item.get("primary") is True), files[0] if files else None)
    if not isinstance(file, Mapping):
        raise MinecraftContentResolverError("Modrinth version has no downloadable file")
    hashes = file.get("hashes") if isinstance(file.get("hashes"), Mapping) else {}
    sha512 = str(hashes.get("sha512") or "").strip().lower()
    if len(sha512) != 128:
        raise MinecraftContentResolverError("Modrinth file is missing SHA-512")
    project_id = str(version.get("project_id") or project).strip()
    version_id = str(version.get("id") or "").strip()
    if not version_id:
        raise MinecraftContentResolverError("Modrinth version identity is missing")
    filename = str(file.get("filename") or "").strip()
    if not filename:
        raise MinecraftContentResolverError("Modrinth filename is missing")
    artifact = {"provider": "modrinth", "package_id": f"{project_id}:{version_id}", "url": _https(file.get("url"), "Modrinth download URL"), "filename": filename, "sha512": sha512, "archive": filename.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz"))}
    sha1 = str(hashes.get("sha1") or "").strip().lower()
    if len(sha1) == 40:
        artifact["sha1"] = sha1
    if file.get("size") is not None:
        artifact["size_bytes"] = int(file["size"])
    return {"provider": "modrinth", "version": str(version.get("version_number") or version_id), "artifact": artifact, "provenance": {"provider": "modrinth", "project_id": project_id, "version_id": version_id, "game_version": game_version, "loaders": list(version.get("loaders") or [])}, "metadata": {"provider_dependencies": list(version.get("dependencies") or []), "version_type": version.get("version_type")}}


def _curseforge_loader(loaders: tuple[str, ...]) -> int:
    values = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
    for loader in loaders:
        if loader in values:
            return values[loader]
    raise MinecraftContentResolverError("CurseForge provider requires a supported mod loader")


def _curseforge_sha1(file: Mapping[str, Any]) -> str:
    for item in file.get("hashes") or []:
        if isinstance(item, Mapping) and int(item.get("algo") or 0) == 1:
            value = str(item.get("value") or "").strip().lower()
            if len(value) == 40:
                return value
    raise MinecraftContentResolverError("CurseForge file is missing SHA-1")


def resolve_curseforge(project: str, game_version: str, loaders: tuple[str, ...], *, api_key: str | None = None, api_key_file: str | None = None, requester: Requester = _request_json) -> dict[str, Any]:
    try:
        mod_id = int(str(project).strip())
    except (TypeError, ValueError) as exc:
        raise MinecraftContentResolverError("CurseForge project reference must be a numeric mod id") from exc
    if mod_id <= 0:
        raise MinecraftContentResolverError("invalid CurseForge mod id")
    key = str(api_key or "").strip() or _secret_file(api_key_file)
    headers = {"x-api-key": key}
    project_payload = requester(f"{CURSEFORGE_API_BASE}/mods/{mod_id}", headers)
    project_data = project_payload.get("data") if isinstance(project_payload, Mapping) else None
    if not isinstance(project_data, Mapping) or int(project_data.get("gameId") or 0) != CURSEFORGE_MINECRAFT_GAME_ID:
        raise MinecraftContentResolverError("CurseForge project is not a Minecraft project")
    classes_payload = requester(f"{CURSEFORGE_API_BASE}/categories?{urlencode({'gameId':CURSEFORGE_MINECRAFT_GAME_ID,'classesOnly':'true'})}", headers)
    classes = classes_payload.get("data") if isinstance(classes_payload, Mapping) else None
    mod_class_ids = {int(item.get("id") or 0) for item in (classes or []) if isinstance(item, Mapping) and bool(item.get("isClass")) and (str(item.get("slug") or "").strip().lower() in {"mods","mc-mods"} or str(item.get("name") or "").strip().lower() == "mods")}
    if int(project_data.get("classId") or 0) not in mod_class_ids:
        raise MinecraftContentResolverError("CurseForge project is not an individual mod project")
    loader_type = _curseforge_loader(loaders)
    query = urlencode({"gameVersion": game_version, "modLoaderType": loader_type, "pageSize": 50})
    payload = requester(f"{CURSEFORGE_API_BASE}/mods/{mod_id}/files?{query}", headers)
    files = payload.get("data") if isinstance(payload, Mapping) else None
    compatible = [item for item in (files or []) if isinstance(item, Mapping) and bool(item.get("isAvailable", True)) and game_version in (item.get("gameVersions") or [])]
    if not compatible:
        raise MinecraftContentResolverError("no compatible CurseForge file for this Minecraft runtime")
    file = sorted(compatible, key=lambda item: (1 if int(item.get("releaseType") or 0) == 1 else 0, str(item.get("fileDate") or "")), reverse=True)[0]
    file_id = int(file.get("id") or 0)
    if file_id <= 0:
        raise MinecraftContentResolverError("CurseForge file identity is missing")
    url = str(file.get("downloadUrl") or "").strip()
    if not url:
        response = requester(f"{CURSEFORGE_API_BASE}/mods/{mod_id}/files/{file_id}/download-url", headers)
        url = str(response.get("data") if isinstance(response, Mapping) else "").strip()
    filename = str(file.get("fileName") or "").strip()
    if not filename:
        raise MinecraftContentResolverError("CurseForge filename is missing")
    artifact = {"provider": "curseforge", "package_id": f"{mod_id}:{file_id}", "url": _https(url, "CurseForge download URL"), "filename": filename, "sha1": _curseforge_sha1(file), "archive": filename.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz"))}
    if file.get("fileLength") is not None:
        artifact["size_bytes"] = int(file["fileLength"])
    return {"provider": "curseforge", "version": str(file.get("displayName") or file_id), "artifact": artifact, "provenance": {"provider": "curseforge", "project_id": mod_id, "file_id": file_id, "game_version": game_version, "loader": loaders[0]}, "metadata": {"provider_dependencies": list(file.get("dependencies") or []), "release_type": file.get("releaseType")}}


def resolve_minecraft_content(provider: str, project: str, game_version: str, runtime: Mapping[str, Any], content_type: str, *, requester: Requester = _request_json, curseforge_api_key: str | None = None, curseforge_api_key_file: str | None = None) -> dict[str, Any]:
    provider = str(provider or "").strip().lower()
    game_version = str(game_version or "").strip()
    if not game_version:
        raise MinecraftContentResolverError("Minecraft game version is unavailable")
    loaders = provider_loaders(runtime, content_type)
    if provider == "modrinth":
        return resolve_modrinth(project, game_version, loaders, content_type, requester=requester)
    if provider == "curseforge":
        if str(content_type).lower() != "mod":
            raise MinecraftContentResolverError("CurseForge modpack/plugin resolution is not enabled in this U6-M block")
        return resolve_curseforge(project, game_version, loaders, api_key=curseforge_api_key, api_key_file=curseforge_api_key_file, requester=requester)
    raise MinecraftContentResolverError("unsupported Minecraft content provider")


def _modpack_loader(runtime: Mapping[str, Any]) -> str:
    loader = str(runtime.get("loader") or runtime.get("variant") or "").strip().lower()
    if loader in {"fabric", "forge", "neoforge", "quilt"}:
        return loader
    if loader == "youer":
        return "neoforge"
    raise MinecraftContentResolverError("runtime has no proven modpack provider loader mapping")


def _search_limit(value: Any) -> int:
    try:
        return max(1, min(int(value), 50))
    except (TypeError, ValueError):
        return 20


def discover_modrinth(query: str, game_version: str, runtime: Mapping[str, Any], content_type: str, *, limit: int = 20, requester: Requester = _request_json) -> list[dict[str, Any]]:
    text = str(query or "").strip()
    ctype = str(content_type or "").strip().lower()
    if not text:
        raise MinecraftContentResolverError("search query is required")
    if ctype == "modpack":
        loaders = (_modpack_loader(runtime),); project_type = "modpack"; type_facet = "project_type:modpack"
    elif ctype == "mod":
        loaders = provider_loaders(runtime, ctype); project_type = "mod"; type_facet = "project_type:mod"
    elif ctype == "plugin":
        loaders = provider_loaders(runtime, ctype); project_type = "plugin"; type_facet = "all_project_types:plugin"
    else:
        raise MinecraftContentResolverError("Modrinth discovery does not support this content type")
    facets = [[type_facet], [f"versions:{game_version}"], [f"categories:{value}" for value in loaders]]
    url = f"{MODRINTH_API_BASE}/search?{urlencode({'query': text, 'limit': _search_limit(limit), 'facets': json.dumps(facets, separators=(',', ':'))})}"
    payload = requester(url, {})
    hits = payload.get("hits") if isinstance(payload, Mapping) else []
    out = []
    for item in hits or []:
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("project_type") or "").lower()
        all_types = {str(value).strip().lower() for value in (item.get("all_project_types") or []) if str(value).strip()}
        if ctype == "plugin":
            if item_type != "plugin" and "plugin" not in all_types:
                continue
        elif item_type != project_type:
            continue
        project_id = str(item.get("project_id") or "").strip()
        slug = str(item.get("slug") or "").strip()
        if not project_id or not slug:
            continue
        out.append({"provider":"modrinth","content_type":ctype,"content_id":f"modrinth:{project_id}","project_ref":slug,"project_id":project_id,"slug":slug,"name":str(item.get("title") or slug)[:300],"description":str(item.get("description") or "")[:1000],"author":str(item.get("author") or "")[:200],"downloads":int(item.get("downloads") or 0),"icon_url":str(item.get("icon_url") or "")[:1000],"project_type":project_type})
    return out


def _curseforge_class_id(content_type: str, api_key: str, requester: Requester) -> int:
    payload = requester(f"{CURSEFORGE_API_BASE}/categories?{urlencode({'gameId': CURSEFORGE_MINECRAFT_GAME_ID, 'classesOnly': 'true'})}", {"x-api-key": api_key})
    rows = payload.get("data") if isinstance(payload, Mapping) else []
    wanted = "modpacks" if content_type == "modpack" else "mods"
    for item in rows or []:
        if not isinstance(item, Mapping) or not bool(item.get("isClass")):
            continue
        slug = str(item.get("slug") or "").strip().lower(); name = str(item.get("name") or "").strip().lower()
        if wanted == "modpacks" and ("modpack" in slug or "modpack" in name):
            return int(item.get("id") or 0)
        if wanted == "mods" and (slug in {"mods", "mc-mods"} or name == "mods"):
            return int(item.get("id") or 0)
    raise MinecraftContentResolverError(f"CurseForge {wanted} class is unavailable")


def discover_curseforge(query: str, game_version: str, runtime: Mapping[str, Any], content_type: str, *, limit: int = 20, api_key: str | None = None, api_key_file: str | None = None, requester: Requester = _request_json) -> list[dict[str, Any]]:
    text = str(query or "").strip(); ctype = str(content_type or "").strip().lower()
    if not text:
        raise MinecraftContentResolverError("search query is required")
    if ctype not in {"mod", "modpack"}:
        raise MinecraftContentResolverError("CurseForge discovery supports mods and modpacks only")
    key = str(api_key or "").strip() or _secret_file(api_key_file)
    loader = _modpack_loader(runtime) if ctype == "modpack" else provider_loaders(runtime, ctype)[0]
    class_id = _curseforge_class_id(ctype, key, requester)
    query_args = {"gameId":CURSEFORGE_MINECRAFT_GAME_ID,"classId":class_id,"searchFilter":text,"gameVersion":game_version,"modLoaderType":_curseforge_loader((loader,)),"pageSize":_search_limit(limit),"sortField":2,"sortOrder":"desc"}
    payload = requester(f"{CURSEFORGE_API_BASE}/mods/search?{urlencode(query_args)}", {"x-api-key": key})
    rows = payload.get("data") if isinstance(payload, Mapping) else []
    out = []
    for item in rows or []:
        if not isinstance(item, Mapping):
            continue
        project_id = int(item.get("id") or 0)
        if project_id <= 0 or int(item.get("gameId") or 0) != CURSEFORGE_MINECRAFT_GAME_ID:
            continue
        slug = str(item.get("slug") or project_id); logo = item.get("logo") if isinstance(item.get("logo"), Mapping) else {}
        out.append({"provider":"curseforge","content_type":ctype,"content_id":f"curseforge:{project_id}","project_ref":str(project_id),"project_id":str(project_id),"slug":slug[:200],"name":str(item.get("name") or slug)[:300],"description":str(item.get("summary") or "")[:1000],"author":"","downloads":int(item.get("downloadCount") or 0),"icon_url":str(logo.get("thumbnailUrl") or logo.get("url") or "")[:1000],"project_type":ctype})
    return out


def discover_minecraft_content(provider: str, query: str, game_version: str, runtime: Mapping[str, Any], content_type: str, *, limit: int = 20, requester: Requester = _request_json, curseforge_api_key: str | None = None, curseforge_api_key_file: str | None = None) -> list[dict[str, Any]]:
    provider = str(provider or "").strip().lower(); game_version = str(game_version or "").strip()
    if not game_version:
        raise MinecraftContentResolverError("Minecraft game version is unavailable")
    if provider == "modrinth":
        return discover_modrinth(query, game_version, runtime, content_type, limit=limit, requester=requester)
    if provider == "curseforge":
        return discover_curseforge(query, game_version, runtime, content_type, limit=limit, api_key=curseforge_api_key, api_key_file=curseforge_api_key_file, requester=requester)
    raise MinecraftContentResolverError("unsupported Minecraft discovery provider")


__all__ = ["CURSEFORGE_API_BASE", "CURSEFORGE_MINECRAFT_GAME_ID", "MODRINTH_API_BASE", "MinecraftContentResolverError", "discover_curseforge", "discover_minecraft_content", "discover_modrinth", "provider_loaders", "resolve_curseforge", "resolve_minecraft_content", "resolve_modrinth"]
