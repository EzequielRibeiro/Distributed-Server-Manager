"""DayZ DLC policy and Steam depot provenance verification.

Only filenames present in depots listed by the Steam 223350 app manifest
are eligible for privileged ownership repair. Unknown content stays untouched.
No third-party protobuf dependency or network access required.
"""
from __future__ import annotations

import os
import re
import struct
from pathlib import Path

_RESERVED = frozenset({
    "addons", "dta", "docs", "mpmissions", "battleye", "keys",
    "steamapps", "server_manager", "profiles", "config",
})
_PAYLOAD_MAGIC = 0x71F617D0
_METADATA_MAGIC = 0x1F4812BE
_END_MAGIC = 0x32C415AB
_MAX_MANIFEST = 32 * 1024 * 1024


def discover_dayz_dlc_paths(root: Path) -> list[Path]:
    """Structural preflight only, not an authorization to change ownership."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("DayZ content root must be a real directory")
    candidates: list[list[Path]] = []
    for dlc in root.iterdir():
        name = dlc.name
        if name.lower() in _RESERVED or name.startswith(("@", ".")):
            continue
        if dlc.is_symlink():
            raise ValueError("DayZ content root contains a symlink")
        if not dlc.is_dir():
            continue
        if (dlc / "mod.cpp").exists() or (dlc / "meta.cpp").exists():
            continue
        addons = dlc / "addons"
        if addons.is_symlink():
            raise ValueError("DayZ DLC addons must not be a symlink")
        if not addons.is_dir():
            continue
        if not any(child.is_file() and not child.is_symlink() and child.suffix.lower() == ".pbo"
                   for child in addons.iterdir()):
            continue
        paths = [dlc]
        for directory, directories, files in os.walk(dlc, followlinks=False):
            for entry in directories + files:
                path = Path(directory) / entry
                if path.is_symlink():
                    raise ValueError("DayZ DLC contains a symlink")
                paths.append(path)
        candidates.append(paths)
    return [p for paths in candidates for p in paths]


def _varint(raw: bytes, offset: int) -> tuple[int, int]:
    result = 0
    for shift in range(0, 70, 7):
        if offset >= len(raw):
            raise ValueError("truncated Steam depot manifest")
        value = raw[offset]
        offset += 1
        result |= (value & 0x7f) << shift
        if value < 128:
            return result, offset
    raise ValueError("invalid Steam depot manifest varint")


def _fields(raw: bytes):
    pos = 0
    while pos < len(raw):
        key, pos = _varint(raw, pos)
        field, wire = key >> 3, key & 7
        if field == 0:
            raise ValueError("invalid Steam depot manifest field")
        if wire == 2:
            size, pos = _varint(raw, pos)
            if size > len(raw) - pos:
                raise ValueError("truncated Steam depot manifest field")
            yield field, raw[pos:pos + size]
            pos += size
        elif wire == 0:
            value, pos = _varint(raw, pos)
            yield field, value
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            if size > len(raw) - pos:
                raise ValueError("truncated Steam depot manifest fixed field")
            pos += size
        else:
            raise ValueError("unsupported Steam depot manifest field")


def _depot_files(path: Path, expected_depot: int, expected_gid: int) -> set[str]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_MANIFEST:
        raise ValueError("untrusted Steam depot manifest")
    data = path.read_bytes()
    offset = 0
    payload = None
    metadata = None
    while offset + 4 <= len(data):
        magic = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if magic == _END_MAGIC:
            break
        if offset + 4 > len(data):
            raise ValueError("truncated Steam depot section")
        length = struct.unpack_from("<I", data, offset)[0]
        offset += 4
        if length > len(data) - offset:
            raise ValueError("truncated Steam depot section")
        chunk = data[offset:offset + length]
        offset += length
        if magic == _PAYLOAD_MAGIC:
            payload = chunk
        elif magic == _METADATA_MAGIC:
            metadata = chunk
    if payload is None or metadata is None:
        raise ValueError("incomplete Steam depot manifest")
    meta = dict(_fields(metadata))
    # Valve protobuf ContentManifestMetadata: depot_id=1, gid_manifest=2,
    # filenames_encrypted=4. Reject encrypted names.
    if meta.get(1) != expected_depot or meta.get(2) != expected_gid or meta.get(4):
        raise ValueError("Steam depot identity mismatch or encrypted filenames")
    paths = set()
    for field, mapping in _fields(payload):
        if field != 1 or not isinstance(mapping, bytes):
            continue
        filename = next((value for key, value in _fields(mapping) if key == 1), None)
        if not isinstance(filename, bytes):
            continue
        name = filename.decode("utf-8").replace("\\", "/")
        parts = name.split("/")
        if not parts or any(part in ("", ".", "..") for part in parts) or name.startswith("/"):
            raise ValueError("unsafe path in Steam depot manifest")
        paths.add(name)
    return paths


def _installed_depots(root: Path) -> dict[int, int]:
    manifest = root / "steamapps" / "appmanifest_223350.acf"
    if manifest.is_symlink() or not manifest.is_file():
        return {}
    # ACF's InstalledDepots section is verified against depot manifest metadata.
    text = manifest.read_text(encoding="utf-8", errors="replace")
    tokens = re.findall(r'"([^"]*)"|([{}])', text)
    stack: list[str] = []
    pending = None
    depots: dict[int, int] = {}
    appid = None
    for key, brace in tokens:
        if brace == "{":
            stack.append(pending or "")
            pending = None
        elif brace == "}":
            if stack:
                stack.pop()
            pending = None
        elif pending is None:
            pending = key
        else:
            if stack == ["AppState"] and pending == "appid":
                appid = key
            if len(stack) == 3 and stack[:2] == ["AppState", "InstalledDepots"] and pending == "manifest":
                if stack[2].isdigit() and key.isdigit():
                    depots[int(stack[2])] = int(key)
            pending = None
    return depots if appid == "223350" else {}


def verified_dayz_dlc_paths(root: Path, depotcache: Path) -> list[Path]:
    """Return only genuine manifest-listed DLC paths; skip unavailable depots.

    A path must be enumerated in a matching installed Steam depot manifest.
    Additional local files in the same DLC directory are never chowned.
    """
    root = Path(root)
    cache = Path(depotcache)
    if not root.is_dir() or root.is_symlink() or cache.is_symlink() or not cache.is_dir():
        return []
    manifest_files: set[str] = set()
    for depot, gid in _installed_depots(root).items():
        file = cache / f"{depot}_{gid}.manifest"
        if not file.is_file():
            continue
        manifest_files.update(_depot_files(file, depot, gid))
    eligible_roots = {
        name.split("/")[0] for name in manifest_files
        if len(name.split("/")) >= 3
        and name.split("/")[1].lower() == "addons"
        and name.lower().endswith(".pbo")
        and name.split("/")[0].lower() not in _RESERVED
        and not name.startswith(("@", "."))
    }
    selected: set[Path] = set()
    for relative in manifest_files:
        parts = relative.split("/")
        if parts[0] not in eligible_roots or len(parts) < 2:
            continue
        dlc = root / parts[0]
        if (dlc / "mod.cpp").exists() or (dlc / "meta.cpp").exists():
            continue
        target = root.joinpath(*parts)
        parents = [root.joinpath(*parts[:i]) for i in range(1, len(parts))]
        for path in [*parents, target]:
            if path.is_symlink():
                raise ValueError("symlink in Steam-listed DayZ DLC path")
            if path.exists():
                selected.add(path)
    return sorted(selected)

def verified_dayz_dlc_paths_from_steam_home(
    root: Path, steam_home: Path, agent_state: Path
) -> list[Path]:
    """Verify DLC provenance across supported SteamCMD layouts.

    SteamCMD may place its depotcache directly in ~/Steam (observed on
    Ubuntu 26.04) or under ~/.local/share/Steam. Managed SteamCMD may
    also keep its cache alongside the executable in Agent tools.
    These fixed locations are confined to the Agent account/state;
    no arbitrary filesystem search or untrusted config is permitted.
    """
    home = Path(steam_home)
    state = Path(agent_state)
    if not home.is_absolute() or not state.is_absolute():
        raise ValueError("SteamCMD cache roots must be absolute")
    caches = (
        home / "Steam" / "depotcache",
        home / ".local" / "share" / "Steam" / "depotcache",
        state / "tools" / "steamcmd" / "depotcache",
    )
    selected: set[Path] = set()
    for cache in caches:
        if not cache.exists() and not cache.is_symlink():
            continue
        # A missing cache is normal on new installations; an unexpected
        # symlink is not. Avoid accepting manifest content from outside
        # the Agent's trusted SteamCMD directories.
        if cache.is_symlink() or not cache.is_dir():
            raise ValueError("unsafe DayZ Steam depotcache location")
        selected.update(verified_dayz_dlc_paths(root, cache))
    return sorted(selected)
