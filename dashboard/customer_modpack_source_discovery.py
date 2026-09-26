#!/usr/bin/env python3
"""Discover allowed server-side modpack sources without acquiring or installing files.

The upstream provider decides whether its CDN download is permitted. A
CurseForge 403 on a *file download URL* is a manual-download result, not a
reason to bypass the author's distribution controls or skip dependencies.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlencode, urlparse

from minecraft_content_resolver import (
    CURSEFORGE_API_BASE, CURSEFORGE_MINECRAFT_GAME_ID, MODRINTH_API_BASE,
    MinecraftContentResolverError, _request_json, _secret_file,
)
from minecraft_modpack_update_resolver import _curseforge_pack_classes

Requester = Callable[[str, Mapping[str, str]], Any]
_SHA1 = re.compile(r"^[a-f0-9]{40}$")
_SHA512 = re.compile(r"^[a-f0-9]{128}$")
_MAX_AUTO_BYTES = 4 * 1024 * 1024 * 1024
_LOADER_TAGS = frozenset({"fabric", "forge", "neoforge", "quilt"})


def _cdn_url(value: Any, provider: str) -> str | None:
    url = str(value or "").strip()
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        allowed = (host.endswith(".forgecdn.net") and host != "forgecdn.net") if provider == "curseforge" else host == "cdn.modrinth.com"
        if (parsed.scheme != "https" or not allowed or parsed.port not in {None, 443}
                or parsed.username or parsed.password or parsed.fragment):
            return None
    except ValueError:
        return None
    return url


def _response_data(value: Any) -> Mapping[str, Any]:
    result = value.get("data") if isinstance(value, Mapping) else None
    return result if isinstance(result, Mapping) else {}


def _versions_match(item: Mapping[str, Any], version: str, loader: str, *, require_version: bool) -> bool:
    labels = {str(v).strip().lower() for v in (item.get("gameVersions") or [])}
    versions = {s for s in labels if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", s)}
    declared_loaders = labels & _LOADER_TAGS
    if declared_loaders and loader not in declared_loaders:
        return False
    if versions and version.lower() not in versions:
        return False
    return not (require_version and version.lower() not in versions)


def _file_identity(data: Mapping[str, Any], project: int) -> bool:
    return (int(data.get("id") or 0) > 0
            and int(data.get("modId") or project) == project
            and int(data.get("gameId") or CURSEFORGE_MINECRAFT_GAME_ID) == CURSEFORGE_MINECRAFT_GAME_ID
            and data.get("isAvailable") is not False)


def _official_page(project: int, file_id: int) -> str:
    return f"https://www.curseforge.com/minecraft/modpacks/{project}/files/{file_id}"


def discover_curseforge(project_ref: str, minecraft_version: str, loader: str,
                        version_ref: str = "", *,
                        requester: Requester = _request_json,
                        load_secret: Callable = _secret_file) -> dict[str, Any]:
    if not str(project_ref).isdigit() or int(project_ref) < 1:
        raise ValueError("O projeto CurseForge deve possuir um ID numérico válido.")
    project = int(project_ref)
    key = load_secret(None)
    headers = {"x-api-key": key}
    classes = _curseforge_pack_classes(key, requester)
    project_info = _response_data(requester(f"{CURSEFORGE_API_BASE}/mods/{project}", headers))
    if (int(project_info.get("gameId") or 0) != CURSEFORGE_MINECRAFT_GAME_ID
            or int(project_info.get("classId") or 0) not in classes):
        raise ValueError("O projeto não é um modpack oficial de Minecraft no CurseForge.")

    candidates: list[Mapping[str, Any]] = []
    if version_ref:
        if not version_ref.isdigit():
            raise ValueError("A versão CurseForge deve ser um ID de arquivo numérico.")
        requested = _response_data(requester(
            f"{CURSEFORGE_API_BASE}/mods/{project}/files/{int(version_ref)}", headers))
        if not _file_identity(requested, project) or not _versions_match(
                requested, minecraft_version, loader, require_version=True):
            raise ValueError("A versão selecionada não corresponde ao Minecraft e loader da instância.")
        candidates = [requested]
    else:
        for offset in (0, 50, 100):
            query = urlencode({"gameVersion": minecraft_version, "index": offset, "pageSize": 50})
            response = requester(f"{CURSEFORGE_API_BASE}/mods/{project}/files?{query}", headers)
            batch = response.get("data") if isinstance(response, Mapping) else []
            if not isinstance(batch, list):
                break
            candidates.extend(x for x in batch if isinstance(x, Mapping)
                              and _file_identity(x, project)
                              and _versions_match(x, minecraft_version, loader, require_version=True))
            if len(batch) < 50:
                break
        candidates.sort(key=lambda x: str(x.get("fileDate") or ""), reverse=True)

    chosen: Mapping[str, Any] | None = None
    for entry in candidates:
        if entry.get("isServerPack") is True:
            chosen = entry
            break
        linked = int(entry.get("serverPackFileId") or 0)
        if linked > 0:
            linked_file = _response_data(requester(
                f"{CURSEFORGE_API_BASE}/mods/{project}/files/{linked}", headers))
            if (_file_identity(linked_file, project)
                    and linked_file.get("isServerPack") is not False
                    and _versions_match(linked_file, minecraft_version, loader, require_version=False)):
                chosen = linked_file
                break
    if chosen is None:
        return {"provider": "curseforge", "mode": "no_official_serverpack",
                "project_id": str(project), "reason": "Nenhum Server Pack oficial compatível foi identificado."}

    file_id = int(chosen["id"])
    page = _official_page(project, file_id)
    name = str(chosen.get("fileName") or "").strip()
    hashes = chosen.get("hashes") if isinstance(chosen.get("hashes"), list) else []
    sha1 = next((str(h.get("value") or "").lower() for h in hashes
                 if isinstance(h, Mapping) and int(h.get("algo") or 0) == 1), "")
    length = int(chosen.get("fileLength") or 0)
    common = {"provider": "curseforge", "project_id": str(project),
              "serverpack_file_id": str(file_id), "file_name": name,
              "official_page": page, "sha1": sha1, "size_bytes": length}
    if project_info.get("allowModDistribution") is False:
        return {**common, "mode": "manual_required",
                "reason": "O autor bloqueou a distribuição por ferramentas externas."}
    if not name.lower().endswith(".zip") or not _SHA1.fullmatch(sha1) or not (0 < length <= _MAX_AUTO_BYTES):
        return {**common, "mode": "manual_required",
                "reason": "O arquivo oficial não oferece metadados suficientes para download verificado."}

    raw_download = str(chosen.get("downloadUrl") or "").strip()
    url = _cdn_url(raw_download, "curseforge")
    if raw_download and not url:
        return {**common, "mode": "manual_required",
                "reason": "O arquivo oficial oferece uma URL fora do CDN autorizado; importação automática recusada."}
    if not url:
        try:
            payload = requester(
                f"{CURSEFORGE_API_BASE}/mods/{project}/files/{file_id}/download-url", headers)
            url = _cdn_url(payload.get("data") if isinstance(payload, Mapping) else "", "curseforge")
        except MinecraftContentResolverError as exc:
            if getattr(exc.__cause__, "code", None) == 403:
                return {**common, "mode": "manual_required",
                        "reason": "O CurseForge recusou o download por terceiros (HTTP 403)."}
            raise
    if not url:
        return {**common, "mode": "manual_required",
                "reason": "O provedor não ofereceu uma URL de download autorizada no CDN oficial."}
    return {**common, "mode": "serverpack_auto", "download_url": url,
            "reason": "Server Pack oficial disponível para transferência verificada."}


def discover_modrinth(project_ref: str, minecraft_version: str, loader: str,
                      version_ref: str = "", *, requester: Requester = _request_json) -> dict[str, Any]:
    project = str(project_ref or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", project):
        raise ValueError("Referência Modrinth inválida.")
    encoded = quote(project, safe="")
    info = requester(f"{MODRINTH_API_BASE}/project/{encoded}", {})
    if (not isinstance(info, Mapping) or info.get("project_type") != "modpack"
            or str(info.get("status") or "").lower() not in {"approved", "archived"}):
        raise ValueError("O projeto não é um modpack público no Modrinth.")
    query = urlencode({"game_versions": json.dumps([minecraft_version]),
                       "loaders": json.dumps([loader]), "include_changelog": "false"})
    items = requester(f"{MODRINTH_API_BASE}/project/{encoded}/version?{query}", {})
    compatible = [v for v in (items if isinstance(items, list) else [])
                  if isinstance(v, Mapping) and minecraft_version in (v.get("game_versions") or [])
                  and loader in (v.get("loaders") or [])
                  and str(v.get("status") or "listed") in {"listed", "unknown"}]
    if version_ref:
        compatible = [v for v in compatible if v.get("id") == version_ref]
    compatible.sort(key=lambda v: str(v.get("date_published") or ""), reverse=True)
    for version in compatible:
        files = [f for f in (version.get("files") or []) if isinstance(f, Mapping)
                 and str(f.get("filename") or "").lower().endswith(".mrpack")]
        files.sort(key=lambda f: bool(f.get("primary")), reverse=True)
        for file in files:
            hashes = file.get("hashes") if isinstance(file.get("hashes"), Mapping) else {}
            if (_SHA1.fullmatch(str(hashes.get("sha1") or "").lower())
                    and _SHA512.fullmatch(str(hashes.get("sha512") or "").lower())
                    and _cdn_url(file.get("url"), "modrinth")):
                return {"provider": "modrinth", "mode": "managed_modrinth",
                        "project_id": str(info.get("id") or project),
                        "version_id": str(version.get("id") or ""),
                        "version_name": str(version.get("version_number") or ""),
                        "file_name": str(file["filename"]),
                        "reason": "O .mrpack pode ser instalado pelo resolvedor Modrinth já existente; componentes do servidor serão validados durante a instalação."}
    return {"provider": "modrinth", "mode": "no_compatible_mrpack",
            "project_id": str(info.get("id") or project),
            "reason": "O Modrinth não publicou um .mrpack compatível e verificável para este runtime."}


def discover_modpack(provider: str, project: str, minecraft_version: str, loader: str,
                     version_ref: str = "", *, requester: Requester = _request_json,
                     load_secret: Callable = _secret_file) -> dict[str, Any]:
    if provider == "curseforge":
        return discover_curseforge(project, minecraft_version, loader, version_ref,
                                  requester=requester, load_secret=load_secret)
    if provider == "modrinth":
        return discover_modrinth(project, minecraft_version, loader, version_ref,
                                requester=requester)
    raise ValueError("A descoberta automática aceita somente CurseForge ou Modrinth.")
