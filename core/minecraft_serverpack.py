#!/usr/bin/env python3
"""Read-only, fail-closed inspection of manually supplied Minecraft server-pack ZIPs.

Does not download, extract to disk, execute scripts or assume that a filename
establishes the uploader's identity. Imported artifacts are subsequently scanned
by the Agent; a CurseForge attribution requires a separate verified file hash.
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path
from typing import Any, Mapping

_MAX_ENTRIES = 12000
_MAX_EXPANDED = 8 * 1024 * 1024 * 1024
_MAX_MODS = 1500
_MAX_MOD_BYTES = 256 * 1024 * 1024
_MAX_META = 128 * 1024
_ACCEPTED_OVERRIDES = frozenset({
    "config", "defaultconfigs", "kubejs", "global_packs", "openloader",
    "crafttweaker", "scripts", "ftbquests", "resources",
})
_ALLOWED_COMPRESSIONS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
_TOKEN = re.compile(r"^[a-zA-Z0-9._+-]{1,80}$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[+.-][A-Za-z0-9]+)*$")


class MinecraftServerPackError(ValueError):
    pass


def _relative(name: str) -> str:
    text = str(name or "").replace("\\", "/").rstrip("/")
    if (not text or text.startswith("/") or "\x00" in text
            or any(part in {"", ".", ".."} for part in text.split("/"))
            or ":" in text.split("/", 1)[0]):
        raise MinecraftServerPackError("Server Pack contém caminho inseguro.")
    return text


def _metadata_from_settings(contents: dict[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in ("settings.cfg", "variables.txt", "serverpack.json", "capivara-serverpack.json"):
        raw = contents.get(key)
        if not raw:
            continue
        if key.endswith(".json"):
            try: data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise MinecraftServerPackError("Metadados do Server Pack não são JSON válido.") from exc
            if not isinstance(data, dict):
                raise MinecraftServerPackError("Metadados do Server Pack inválidos.")
            for source, target in (("minecraft_version", "minecraft"), ("loader", "loader"),
                                   ("loader_version", "loader_version")):
                if source in data: values[target] = str(data[source]).strip()
            continue
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key_raw, raw_value = line.split("=", 1)
            var = key_raw.strip().upper()
            if var in {"MCVER", "MINECRAFT_VERSION", "MINECRAFTVERSION"}:
                values["minecraft"] = raw_value.strip().strip(' "\'')
            elif var in {"MODLOADER", "MOD_LOADER", "LOADER"}:
                values["loader"] = raw_value.strip().strip(' "\'').lower()
            elif var in {"FORGEVER", "NEOFORGE_VERSION", "MODLOADER_VERSION", "LOADER_VERSION"}:
                values["loader_version"] = raw_value.strip().strip(' "\'')
    return values


def inspect_serverpack(path: Path | str, minecraft_version: str, loader: str,
                       *, embedded_loader_version: str = "",
                       declared_loader_version: str = "") -> dict[str, Any]:
    """Inspect and hash every server mod without trusting unverified ZIP names.

    If upstream metadata is absent, an explicit loader version is mandatory;
    the Agent's installed loader must still agree with that declaration.
    """
    archive_path = Path(path)
    target_version = str(minecraft_version or "").strip()
    target_loader = str(loader or "").strip().lower()
    installed_loader = str(embedded_loader_version or "").strip()
    supplied_loader = str(declared_loader_version or "").strip()
    if not _VERSION.fullmatch(target_version) or target_loader not in {"forge", "neoforge", "fabric", "quilt"}:
        raise MinecraftServerPackError("Runtime Minecraft/loader inválido para Server Pack.")
    if not archive_path.is_file() or archive_path.is_symlink():
        raise MinecraftServerPackError("Arquivo ZIP do Server Pack indisponível.")
    if archive_path.stat().st_size > 4 * 1024 * 1024 * 1024:
        raise MinecraftServerPackError("Server Pack excede o limite de 4 GiB.")
    if not zipfile.is_zipfile(archive_path):
        raise MinecraftServerPackError("Server Pack deve ser um arquivo ZIP.")
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        if not infos or len(infos) > _MAX_ENTRIES:
            raise MinecraftServerPackError("Server Pack excede o limite de entradas.")
        files: dict[str, zipfile.ZipInfo] = {}
        seen: set[str] = set()
        expanded = 0
        for item in infos:
            name = _relative(item.filename)
            folded = name.casefold()
            if folded in seen:
                raise MinecraftServerPackError("Server Pack contém nomes repetidos.")
            seen.add(folded)
            mode = (item.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode))):
                raise MinecraftServerPackError("Server Pack contém entrada especial ou link.")
            if item.compress_type not in _ALLOWED_COMPRESSIONS or item.flag_bits & 0x1:
                raise MinecraftServerPackError("Server Pack usa compressão ou criptografia não suportada.")
            expanded += item.file_size
            if expanded > _MAX_EXPANDED:
                raise MinecraftServerPackError("Server Pack excede 8 GiB descompactado.")
            if not item.is_dir(): files[name] = item
        # Accept a single wrapper folder, but not nested/mixed layouts.
        wrapper = ""
        if not any(name.startswith("mods/") for name in files):
            roots = {name.split("/", 1)[0] for name in files if "/" in name}
            wrappers = [root for root in roots if any(name.startswith(root + "/mods/") for name in files)]
            if len(wrappers) != 1:
                raise MinecraftServerPackError("Server Pack deve conter a pasta mods/.")
            wrapper = wrappers[0] + "/"
            if any(not name.startswith(wrapper) for name in files):
                raise MinecraftServerPackError("Server Pack mistura múltiplos diretórios de origem.")
            files = {name[len(wrapper):]: info for name, info in files.items()}
        metadata_sources: dict[str, str] = {}
        for key in ("settings.cfg", "variables.txt", "serverpack.json", "capivara-serverpack.json"):
            info = files.get(key)
            if info:
                if info.file_size > _MAX_META:
                    raise MinecraftServerPackError("Metadados excedem o limite de segurança.")
                metadata_sources[key] = archive.read(info).decode("utf-8", errors="strict")
        metadata = _metadata_from_settings(metadata_sources)
        documented_version = metadata.get("minecraft", "")
        documented_loader = metadata.get("loader", "").lower()
        documented_build = metadata.get("loader_version", "")
        if documented_version and documented_version != target_version:
            raise MinecraftServerPackError(
                f"Server Pack declara Minecraft {documented_version}; instância utiliza {target_version}.")
        if documented_loader and documented_loader != target_loader:
            raise MinecraftServerPackError(
                f"Server Pack exige {documented_loader}; instância utiliza {target_loader}.")
        if documented_build and supplied_loader and documented_build != supplied_loader:
            raise MinecraftServerPackError("Versão do loader informada difere do manifesto do pacote.")
        build = documented_build or supplied_loader
        if not build or not _TOKEN.fullmatch(build):
            raise MinecraftServerPackError(
                "Versão exata do loader não encontrada; informe a versão publicada do Server Pack.")
        if installed_loader and installed_loader != build:
            raise MinecraftServerPackError(
                f"Server Pack exige {target_loader} {build}; instância possui {installed_loader}.")
        selected_overrides: set[str] = set()
        members = []
        executable_ignored = []
        other_ignored = []
        for name, info in sorted(files.items()):
            root = name.split("/", 1)[0]
            if name.startswith("mods/") and name.lower().endswith(".jar") and name.count("/") == 1:
                if info.file_size < 1 or info.file_size > _MAX_MOD_BYTES:
                    raise MinecraftServerPackError("Mod do Server Pack possui tamanho inválido.")
                digest = hashlib.sha256()
                with archive.open(info) as incoming:
                    for chunk in iter(lambda: incoming.read(1024 * 1024), b""):
                        digest.update(chunk)
                members.append({"path": name, "archive_member": info.filename,
                                "sha256": digest.hexdigest(), "size_bytes": info.file_size})
            elif root in _ACCEPTED_OVERRIDES and "/" in name:
                if Path(name).suffix.lower() in {".jar", ".exe", ".dll", ".so", ".bat", ".cmd", ".sh", ".ps1"}:
                    raise MinecraftServerPackError("Arquivo executável indevido em diretório de configuração.")
                selected_overrides.add(root)
            elif Path(name).suffix.lower() in {".sh", ".bat", ".cmd", ".ps1", ".exe", ".dll"}:
                executable_ignored.append(name)
            else:
                other_ignored.append(name)
        if not members or len(members) > _MAX_MODS:
            raise MinecraftServerPackError("Server Pack deve conter entre 1 e 1500 mods do servidor.")
        if any(name.startswith("mods/") and name not in {m["path"] for m in members}
               for name in files):
            raise MinecraftServerPackError("Há arquivos não reconhecidos na pasta mods/.")
        return {"kind": "MinecraftServerPackInspection", "minecraft_version": target_version,
                "loader": target_loader, "loader_version": build, "count": len(members),
                "members": members, "root_prefix": wrapper, "override_dirs": sorted(selected_overrides),
                "ignored_executables": executable_ignored[:200],
                "ignored_other_count": len(other_ignored),
                "size_bytes": archive_path.stat().st_size,
                "sha256": _hash_file(archive_path),
                "metadata_sources": sorted(metadata_sources),
                "documented_game_version": bool(documented_version),
                "documented_loader": bool(documented_loader),
                "documented_loader_version": bool(documented_build)}


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["MinecraftServerPackError", "inspect_serverpack"]
