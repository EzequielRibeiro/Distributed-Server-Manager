#!/usr/bin/env python3
"""Read-only evidence that a modpack upgrade preserved existing Minecraft worlds.

Record a baseline while the instance is stopped, then compare immediately
after content reconciliation. The script never writes inside the game root.
It checks the configured level-name, existing overworld, Nether, End, and
other dimension directories and all files beneath them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


class WorldAuditError(ValueError):
    pass


def _world_name(root: Path) -> str:
    config = root / "server.properties"
    if config.is_symlink():
        raise WorldAuditError("server.properties is a symbolic link")
    name = "world"
    if config.is_file():
        if config.stat().st_size > 256 * 1024:
            raise WorldAuditError("server.properties exceeds safety limit")
        for line in config.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if not value or value.startswith(("#", "!")) or "=" not in value:
                continue
            key, actual = value.split("=", 1)
            if key.strip().lower() == "level-name":
                name = actual.strip()
    if (not name or name in {".", ".."} or "/" in name or "\\" in name
            or any(ord(char) < 32 for char in name)):
        raise WorldAuditError("invalid Minecraft world name")
    return name


def _hash_file(file: Path) -> str:
    digest = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def capture(root: Path) -> dict:
    root = root.resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise WorldAuditError("instance game root must be a regular directory")
    world = _world_name(root)
    roots = sorted({world, world + "_nether", world + "_the_end",
                    "world", "world_nether", "world_the_end",
                    "worlds", "dimensions", "DIM-1", "DIM1"})
    files = {}
    actual_roots = []
    for name in roots:
        candidate = root / name
        if not candidate.exists() and not candidate.is_symlink():
            continue
        if candidate.is_symlink() or not candidate.is_dir():
            raise WorldAuditError("unexpected world directory type: " + name)
        actual_roots.append(name)
        for directory, dirs, filenames in os.walk(candidate, followlinks=False):
            folder = Path(directory)
            for sub in dirs:
                if (folder / sub).is_symlink():
                    raise WorldAuditError("world contains a symlink: " + str(folder / sub))
            for basename in filenames:
                file = folder / basename
                if file.is_symlink() or not file.is_file():
                    raise WorldAuditError("world file is unsafe: " + str(file))
                relative = file.relative_to(root).as_posix()
                files[relative] = {"sha256": _hash_file(file), "bytes": file.stat().st_size}
    return {"schema_version": 1, "instance_root": str(root),
            "level_name": world, "world_roots": actual_roots,
            "files": dict(sorted(files.items()))}


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance-root", required=True, type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--save-baseline", type=Path)
    action.add_argument("--compare-baseline", type=Path)
    args = parser.parse_args()
    try:
        current = capture(args.instance_root)
        file = args.save_baseline or args.compare_baseline
        destination = file.resolve()
        root = args.instance_root.resolve(strict=True)
        if args.save_baseline:
            if destination == root or root in destination.parents:
                raise WorldAuditError("baseline must be outside the instance directory")
            if destination.exists():
                raise WorldAuditError("refusing to replace an existing world audit baseline")
            file.parent.mkdir(parents=True, exist_ok=True)
            text = json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True)
            with file.open("x", encoding="utf-8") as stream:
                os.chmod(file, 0o600)
                stream.write(text)
            print("BASELINE_CREATED", str(file), "files", len(current["files"]))
            return 0
        prior = json.loads(file.read_text(encoding="utf-8"))
        if (not isinstance(prior, dict) or prior.get("schema_version") != 1
                or prior.get("instance_root") != current["instance_root"]
                or prior.get("level_name") != current["level_name"]):
            raise WorldAuditError("baseline belongs to another instance or world name changed")
        before = prior.get("files")
        if not isinstance(before, dict):
            raise WorldAuditError("invalid baseline file hashes")
        after = current["files"]
        missing = sorted(set(before) - set(after))
        added = sorted(set(after) - set(before))
        changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
        if missing or added or changed or prior.get("world_roots") != current["world_roots"]:
            print("WORLD_PRESERVATION_FAILED")
            print("missing files:", missing[:20], "total", len(missing))
            print("added files:", added[:20], "total", len(added))
            print("modified files:", changed[:20], "total", len(changed))
            return 1
        print("WORLD_UNCHANGED", current["level_name"], "verified files", len(after))
        return 0
    except (WorldAuditError, OSError, UnicodeError, ValueError) as exc:
        print("WORLD_AUDIT_ERROR:", exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
