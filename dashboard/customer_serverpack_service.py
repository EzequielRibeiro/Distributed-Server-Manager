#!/usr/bin/env python3
"""Build an authenticated, read-only preview of an official Minecraft Server Pack.

Only the original uploaded ZIP is used. No launcher scripts run. Every server
mod is a separate hashed local child of the same ownership-controlled bundle.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

from minecraft_content_resolver import (
    CURSEFORGE_API_BASE, CURSEFORGE_MINECRAFT_GAME_ID,
    MinecraftContentResolverError, _request_json, _secret_file, provider_loaders,
)
from minecraft_modpack_update_resolver import _curseforge_pack_classes
from minecraft_serverpack import inspect_serverpack
from runtime_workspace_catalog import runtime_definition


def _sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _official_curseforge(path: Path, source: Mapping[str, Any],
                         game_version: str, requester, load_secret) -> dict[str, Any]:
    project = str(source.get("curseforge_project_id") or "").strip()
    file_id = str(source.get("curseforge_file_id") or "").strip()
    if not project.isdecimal() or not file_id.isdecimal():
        raise ValueError("Informe os IDs oficiais do projeto e arquivo no CurseForge.")
    key = load_secret(None)
    headers = {"x-api-key": key}
    classes = _curseforge_pack_classes(key, requester)
    payload = requester(f"{CURSEFORGE_API_BASE}/mods/{int(project)}", headers)
    project_data = payload.get("data") if isinstance(payload, Mapping) else None
    if (not isinstance(project_data, Mapping) or
            int(project_data.get("gameId") or 0) != CURSEFORGE_MINECRAFT_GAME_ID or
            int(project_data.get("classId") or 0) not in classes):
        raise ValueError("O projeto declarado não é um modpack oficial de Minecraft no CurseForge.")
    payload = requester(f"{CURSEFORGE_API_BASE}/mods/{int(project)}/files/{int(file_id)}", headers)
    file = payload.get("data") if isinstance(payload, Mapping) else None
    if (not isinstance(file, Mapping) or int(file.get("id") or 0) != int(file_id)
            or not bool(file.get("isAvailable", True))
            or not str(file.get("fileName") or "").lower().endswith(".zip")):
        raise ValueError("O arquivo indicado não é um Server Pack ZIP disponível no projeto informado.")
    name = str(file.get("fileName") or "")
    if Path(name).name != path.name:
        raise ValueError("O arquivo enviado não possui o nome do ZIP oficial declarado.")
    declared_size = file.get("fileLength")
    if declared_size is not None and int(declared_size) != path.stat().st_size:
        raise ValueError("O tamanho do arquivo diverge do ZIP publicado pelo CurseForge.")
    sha1 = next((str(h.get("value") or "").strip().lower()
                 for h in file.get("hashes") or []
                 if isinstance(h, Mapping) and int(h.get("algo") or 0) == 1), "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha1):
        raise ValueError("CurseForge não disponibilizou SHA-1 para comprovar a origem deste Server Pack.")
    if _sha1(path) != sha1:
        raise ValueError("SHA-1 do Server Pack não corresponde ao arquivo oficial publicado.")
    tags = [str(tag).strip().casefold() for tag in file.get("gameVersions") or []]
    minecraft_tags = [tag for tag in tags if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", tag)]
    if minecraft_tags and game_version.casefold() not in minecraft_tags:
        raise ValueError(f"O arquivo oficial não declara Minecraft {game_version}.")
    return {"provider": "curseforge", "project_id": project, "file_id": file_id,
            "file_name": name, "sha1": sha1, "publisher": str(project_data.get("name") or "")[:120],
            "minecraft_tag_confirmed": game_version.casefold() in minecraft_tags}


def build_serverpack_bundle(root: Path, context: Mapping[str, Any], item: Mapping[str, Any],
                            relative: str, content_id: str, metadata: Mapping[str, Any],
                            artifact_path: Path, *, requester=_request_json,
                            load_secret=_secret_file):
    if str(context.get("game_id") or "").lower() != "minecraft":
        raise ValueError("Importação de Server Pack disponível somente para Minecraft Java.")
    source = metadata.get("serverpack") if isinstance(metadata.get("serverpack"), Mapping) else {}
    if source.get("format") != "official-serverpack-v1":
        raise ValueError("Confirme explicitamente o formato de Server Pack oficial.")
    runtime_id = str(context.get("runtime_id") or "").strip()
    version = str(context.get("game_version") or "").strip()
    runtime = runtime_definition(Path(root), "minecraft", runtime_id)
    if not runtime or not version:
        raise ValueError("Runtime Minecraft não encontrado.")
    loaders = provider_loaders(runtime, "mod")
    if len(loaders) != 1 or loaders[0]!="neoforge":
        raise ValueError("A versão inicial do importador de Server Packs oferece suporte somente a Minecraft NeoForge.")
    loader = loaders[0]
    build_id = str(context.get("build_id") or "").strip()
    installed_build = build_id if re.fullmatch(r"\d+(?:\.\d+){2,5}", build_id) else ""
    declared_build = str(source.get("loader_version") or "").strip()
    inspected = inspect_serverpack(
        artifact_path, version, loader,
        embedded_loader_version=installed_build,
        declared_loader_version=declared_build)
    uploaded_sha = str(item.get("sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", uploaded_sha) or uploaded_sha != inspected["sha256"]:
        raise ValueError("SHA-256 do arquivo não corresponde à transferência validada pelo Agent.")
    official = _official_curseforge(artifact_path, source, version, requester, load_secret)
    if not official["minecraft_tag_confirmed"] and not inspected["documented_game_version"]:
        raise ValueError("Nem o arquivo oficial nem o manifesto interno comprovam a versão Minecraft deste Server Pack.")
    prefix = inspected["root_prefix"]
    members = []
    children = []
    for info in inspected["members"]:
        path = str(info["path"])
        member_id = "mb-" + hashlib.sha256((content_id + "\x00" + path).encode()).hexdigest()[:32]
        artifact = {
            "provider": "local", "package_id": f"serverpack:{content_id}:{member_id}",
            "serverpack_child_v1": True, "ephemeral_upload": True,
            "serverpack_loader": loader, "serverpack_loader_version": inspected["loader_version"],
            "bundle_parent_content_id": content_id, "bundle_member": path,
            "sha256": info["sha256"], "size_bytes": int(info["size_bytes"]),
            "filename": Path(path).name,
        }
        members.append({"content_id": member_id, "path": path,
                        "required": True, "artifact": artifact})
        children.append({
            "instance_id": str(context.get("id") or item.get("instance_id") or ""),
            "content_id": member_id, "content_type": "mod",
            "provider": "local", "version": official["file_id"],
            "artifact": artifact, "target": f"mods/{member_id}",
            "dependencies": [content_id],
            "provenance": {"kind": "official-serverpack-child",
                           "project_id": official["project_id"],
                           "file_id": official["file_id"],
                           "archive_member": info["archive_member"]},
        })
    name = str(item.get("filename") or "")
    parent_artifact = {
        "provider": "local", "package_id": relative, "resolved_path": relative,
        "sha256": inspected["sha256"], "filename": name,
        "archive": True, "ephemeral_upload": True, "serverpack_v1": True,
        "serverpack_prefix": prefix.rstrip("/"),
        "serverpack_mod_count": len(members),
        "serverpack_loader": loader,
        "serverpack_loader_version": inspected["loader_version"],
        "serverpack_override_dirs": inspected["override_dirs"],
    }
    parent = {
        "instance_id": str(context.get("id") or item.get("instance_id") or ""),
        "content_id": content_id, "content_type": "modpack",
        "provider": "local", "version": official["file_id"],
        "desired_state": "installed", "activation_state": "enabled",
        "target": f"modpacks/{content_id}",
        "artifact": parent_artifact,
        "provenance": {"kind": "official-customer-serverpack-upload",
                       "transfer_id": str(item["transfer_id"]),
                       "official": official},
        "metadata": {"display_name": str(metadata.get("display_name") or content_id)[:191],
                     "serverpack": {"format": "official-serverpack-v1",
                                    "mod_count": len(members),
                                    "ignored_launchers": inspected["ignored_executables"][:30],
                                    "source": official}},
    }
    bundle = {
        "provider": "local",
        "provider_project_id": "cf-" + official["project_id"],
        "provider_version_id": "file-" + official["file_id"],
        "minecraft_version": version, "loader_id": loader,
        "loader_version": inspected["loader_version"],
        "manifest_kind": "serverpack-local-v1",
        "members": members,
        "override_roots": ["server-overrides"] if inspected["override_dirs"] else [],
    }
    preview = {
        "kind": "CapivaraOfficialServerPackPreview", "source": official,
        "minecraft_version": version, "loader_id": loader,
        "loader_version": inspected["loader_version"],
        "mod_count": len(members), "override_dirs": inspected["override_dirs"],
        "ignored_launchers": inspected["ignored_executables"][:30],
        "archive_sha256": inspected["sha256"],
        "requires_stopped_instance": True,
        "requires_customer_confirmation": True,
        "loader_version_verified_in_zip": bool(inspected["documented_loader_version"]),
        "loader_version_manually_declared": not bool(inspected["documented_loader_version"]),
        "runs_pack_scripts": False,
    }
    return preview, parent, bundle, children


__all__ = ["build_serverpack_bundle"]
