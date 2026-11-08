#!/usr/bin/env python3
"""Crash-safe promotion of committed Server Pack sources, without Controller writes."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Callable
from minecraft_serverpack_content_sync import _need, _digest, _segment, _SAFE_FILENAME, ServerPackContentSyncError


def _persist(path: Path, value: dict) -> None:
    temp = path.with_name("." + path.name + ".tmp")
    with temp.open("w") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)
    _fsync(path.parent)


def _fsync(folder: Path) -> None:
    handle = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def _rename(src: Path, dst: Path) -> None:
    _need(src.exists() and not src.is_symlink(), "missing source")
    _need(not dst.exists() and not dst.is_symlink(), "target occupied")
    os.rename(src, dst)
    _fsync(src.parent)
    if src.parent != dst.parent:
        _fsync(dst.parent)


def _check_tree(tree: Path, manifest: dict, parent: bool) -> bool:
    try:
        if not tree.is_dir() or tree.is_symlink():
            return False
        files = manifest["files"]
        expected = {f["filename"] if parent else f["content_id"] for f in files}
        folder = tree / "mods" if parent else tree
        if {p.name for p in folder.iterdir()} != expected:
            return False
        for f in files:
            path = folder / f["filename"] if parent else folder / f["content_id"] / f["filename"]
            if not path.is_file() or path.is_symlink() or path.stat().st_size != f["size_bytes"]:
                return False
            if _digest(path) != f["sha256"]:
                return False
        return not any(p.is_symlink() for p in tree.rglob("*"))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def recover_source_promotion(journal_path: Path) -> str:
    journal_path = Path(journal_path)
    _need(journal_path.is_file() and not journal_path.is_symlink(), "journal missing")
    record = json.loads(journal_path.read_text())
    _need(record.get("kind") == "VerifiedSourcePromotion" and
          record.get("phase") in ("promoting", "committed", "rolled_back"), "invalid journal")
    if record["phase"] != "promoting":
        return record["phase"]
    for entry in reversed(record["entries"]):
        active, staged, backup = (Path(entry[k]) for k in ("active", "staged", "backup"))
        _need(not any(p.is_symlink() for p in (active, staged, backup)), "recovery symlink")
        if backup.exists():
            if active.exists():
                _need(not staged.exists(), "ambiguous recovery state")
                _rename(active, staged)
            _rename(backup, active)
        else:
            _need(active.is_dir() and staged.is_dir(), "missing original source")
    record["phase"] = "rolled_back"
    _persist(journal_path, record)
    return "rolled_back"


def promote_verified_sources(*, prepared: Path, parent_live: Path, children_live: Path,
                             recovery: Path, instance_id: str, candidate_sha256: str,
                             revision: int, controller_state: Callable[[], tuple[int,str]],
                             checkpoint: Callable[[str], None] | None = None) -> dict:
    prepared, parent_live, children_live, recovery = map(
        Path, (prepared, parent_live, children_live, recovery))
    _need(recovery.is_dir() and not recovery.is_symlink(), "invalid recovery location")
    _need(prepared.is_dir() and not prepared.is_symlink(), "invalid prepared directory")
    manifest_file = prepared / "verified-source-manifest.json"
    _need(manifest_file.is_file() and not manifest_file.is_symlink(), "missing manifest")
    manifest = json.loads(manifest_file.read_text())
    _need(manifest.get("kind") == "VerifiedServerPackContentSources" and
          manifest.get("instance_id") == instance_id and
          manifest.get("candidate_sha256") == candidate_sha256, "candidate mismatch")
    _segment(instance_id, "instance ID")
    _need(isinstance(revision, int) and revision > 0, "invalid Controller revision")
    _need(isinstance(manifest.get("files"), list) and bool(manifest["files"]),
          "empty prepared manifest")
    content_ids = set()
    names = set()
    for item in manifest["files"]:
        cid = _segment(item.get("content_id"), "child content ID")
        filename = str(item.get("filename") or "")
        _need(_SAFE_FILENAME.fullmatch(filename) is not None
              and filename.lower().endswith(".jar"), "unsafe prepared JAR filename")
        _need(cid not in content_ids and filename not in names,
              "duplicate prepared child")
        content_ids.add(cid)
        names.add(filename)
    _need(_check_tree(prepared/"parent", manifest, True) and
          _check_tree(prepared/"children", manifest, False), "prepared source hash mismatch")
    _need(controller_state() == (revision, candidate_sha256), "Controller CAS mismatch")
    _need(parent_live.is_dir() and children_live.is_dir() and
          not parent_live.is_symlink() and not children_live.is_symlink(), "existing sources missing")
    _need(parent_live != children_live and
          prepared.resolve() not in (parent_live.resolve(), children_live.resolve()) and
          recovery.resolve() not in (parent_live.resolve(), children_live.resolve()),
          "overlapping source directories")
    _need(not any(p.is_symlink() for p in
          (prepared/"parent", prepared/"children", parent_live, children_live)),
          "unsafe symlink source")
    journal = recovery / "promotion.json"
    entries = [
        {"active": str(parent_live), "staged": str(prepared/"parent"),
         "backup": str(recovery/"previous-parent")},
        {"active": str(children_live), "staged": str(prepared/"children"),
         "backup": str(recovery/"previous-children")},
    ]
    _need(not journal.exists() and all(not Path(e["backup"]).exists() for e in entries),
          "previous promotion needs recovery")
    record = {"kind": "VerifiedSourcePromotion", "phase": "promoting",
              "instance_id": instance_id, "candidate_sha256": candidate_sha256,
              "revision": revision, "entries": entries}
    _persist(journal, record)
    try:
        for number, entry in enumerate(entries):
            active, staged, backup = (Path(entry[k]) for k in ("active", "staged", "backup"))
            _rename(active, backup)
            if checkpoint:
                checkpoint("backup_" + str(number))
            _rename(staged, active)
            if checkpoint:
                checkpoint("promoted_" + str(number))
        _need(_check_tree(parent_live, manifest, True) and
              _check_tree(children_live, manifest, False), "promoted source hash mismatch")
        _need(controller_state() == (revision, candidate_sha256), "Controller CAS changed")
        record["phase"] = "committed"
        _persist(journal, record)
        return {"status": "committed", "child_count": len(manifest["files"])}
    except Exception:
        recover_source_promotion(journal)
        raise
