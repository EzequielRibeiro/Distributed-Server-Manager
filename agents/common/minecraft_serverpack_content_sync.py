#!/usr/bin/env python3
"""Verified, replayable preparation of Agent-managed Server Pack sources.

This never modifies the live instance, Controller state or existing content
sources. The caller may later promote the prepared tree after a transactional
check against the Controller's published bundle revision.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Mapping

from core.minecraft_serverpack_pending_commit import authorize_after_agent_completion


class ServerPackContentSyncError(RuntimeError):
    pass


_SAFE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,190}$")
_SAFE_FILENAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9+(). _-]{0,254}$")


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ServerPackContentSyncError(message)


def _segment(value: Any, label: str) -> str:
    name = str(value or "")
    _need(bool(_SAFE.fullmatch(name)) and name not in {".", ".."}, f"unsafe {label}")
    return name


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _regular_file(root: Path, value: str) -> Path:
    file = root / value
    _need(file.is_file() and not file.is_symlink(), f"invalid Server Pack source: {value}")
    _need(file.parent == root, "unsafe Server Pack source path")
    return file


def _copy_regular_tree(source: Path, target: Path) -> None:
    _need(source.is_dir() and not source.is_symlink(), "invalid Server Pack stage")
    for item in source.rglob("*"):
        _need(not item.is_symlink() and (item.is_dir() or item.is_file()),
              "Server Pack stage has unsafe entry")
    shutil.copytree(source, target, symlinks=False)


def _candidate_inputs(
    pending: Mapping[str, Any],
    agent_result: Mapping[str, Any],
    *,
    instance_id: str,
    runtime: Path,
    serverpack_stage: Path,
    committed_journal: Mapping[str, Any],
) -> tuple[dict[str, Any], list[tuple[str, str, int, str]]]:
    try:
        proof = authorize_after_agent_completion(pending, agent_result)
    except Exception as exc:
        raise ServerPackContentSyncError("Agent completion has not been attested") from exc
    _need(proof["instance_id"] == instance_id, "instance identity mismatch")
    _need(committed_journal.get("phase") == "committed"
          and committed_journal.get("migration_plan_sha256") == proof["migration_plan_sha256"]
          and committed_journal.get("target_loader_version") == proof["bundle"]["loader_version"],
          "Server Pack transaction has not committed")
    _need(str(proof["parent"].get("target")) ==
          f"modpacks/{_segment(proof['content_id'],'parent content ID')}",
          "unexpected Server Pack parent target")
    _need(runtime.is_dir() and not runtime.is_symlink(), "missing active runtime")
    _need(serverpack_stage.is_dir() and not serverpack_stage.is_symlink(), "missing Server Pack stage")

    files: list[tuple[str, str, int, str]] = []
    seen_names: set[str] = set()
    seen_content: set[str] = set()
    for child in proof["children"]:
        cid = _segment(child["content_id"], "child content ID")
        artifact = child["artifact"]
        filename = str(artifact.get("filename") or "")
        _need(_SAFE_FILENAME.fullmatch(filename) is not None
              and filename.lower().endswith(".jar"), "invalid JAR filename")
        _need(child.get("target") == f"mods/{cid}", "invalid managed mod target")
        _need(cid not in seen_content and filename not in seen_names,
              "duplicate Server Pack child")
        seen_content.add(cid)
        seen_names.add(filename)
        sha = str(artifact.get("sha256") or "").lower()
        size = int(artifact.get("size_bytes") or 0)
        _need(re.fullmatch("[0-9a-f]{64}", sha) is not None and size > 0,
              "invalid artifact hash/size")
        for source in (runtime / "mods", serverpack_stage / "mods"):
            file = _regular_file(source, filename)
            _need(file.stat().st_size == size and _digest(file) == sha,
                  "active runtime and Server Pack stage do not match commit")
        files.append((cid, filename, size, sha))
    _need(len(files) == len(proof["bundle"]["members"]),
          "Server Pack child and manifest count differ")
    _need({p.name for p in (runtime / "mods").glob("*.jar")} == seen_names,
          "active JAR inventory differs from committed Server Pack")
    _need({p.name for p in (serverpack_stage / "mods").glob("*.jar")} == seen_names,
          "staged JAR inventory differs from committed Server Pack")
    return proof, files


def prepare_verified_sources(
    *,
    pending: Mapping[str, Any],
    agent_result: Mapping[str, Any],
    instance_id: str,
    runtime: Path,
    serverpack_stage: Path,
    committed_journal: Mapping[str, Any],
    destination: Path,
) -> dict[str, Any]:
    """Stage source trees from a committed runtime without changing live files.

    Replays of an already prepared candidate verify every original JAR and the
    prepared source files again. Failed staging is removed from its private
    scratch location; no existing source, world or configuration is deleted.
    """
    runtime = Path(runtime)
    serverpack_stage = Path(serverpack_stage)
    destination = Path(destination)
    proof, files = _candidate_inputs(
        pending, agent_result, instance_id=instance_id,
        runtime=runtime, serverpack_stage=serverpack_stage,
        committed_journal=committed_journal,
    )
    _need(destination.parent.is_dir() and not destination.parent.is_symlink(),
          "unsafe source staging parent")
    _need(not destination.is_symlink(), "symlink destination rejected")
    _need(not destination.exists() or destination.is_dir(),
          "source destination must be a directory")
    manifest = {
        "kind": "VerifiedServerPackContentSources",
        "schema_version": 1,
        "instance_id": instance_id,
        "candidate_sha256": proof["candidate_sha256"],
        "migration_plan_sha256": proof["migration_plan_sha256"],
        "loader_version": proof["bundle"]["loader_version"],
        "child_count": len(files),
        "files": [{"content_id": cid, "filename": name, "size_bytes": size, "sha256": sha}
                  for cid, name, size, sha in files],
    }

    def verify_prepared(target: Path) -> None:
        _need(target.is_dir() and not target.is_symlink(), "prepared tree invalid")
        current = json.loads((target / "verified-source-manifest.json").read_text())
        _need(current == manifest, "prepared manifest differs from committed revision")
        parent = target / "parent"
        children = target / "children"
        _need(parent.is_dir() and children.is_dir(), "prepared source directories missing")
        _need({p.name for p in (parent / "mods").iterdir()} == {f[1] for f in files},
              "prepared parent inventory mismatch")
        _need({p.name for p in children.iterdir()} == {f[0] for f in files},
              "prepared child inventory mismatch")
        for cid, name, size, sha in files:
            for path in (parent / "mods" / name, children / cid / name):
                _need(path.is_file() and not path.is_symlink()
                      and path.stat().st_size == size and _digest(path) == sha,
                      "prepared source hash mismatch")
        _need(not any(p.is_symlink() for p in target.rglob("*")),
              "prepared source contains symlinks")

    if destination.exists():
        verify_prepared(destination)
        return {"status": "already_prepared", **manifest}

    scratch = Path(tempfile.mkdtemp(prefix=".serverpack-source-", dir=destination.parent))
    try:
        _copy_regular_tree(serverpack_stage, scratch / "parent")
        (scratch / "children").mkdir()
        for cid, name, _, _ in files:
            child_dir = scratch / "children" / cid
            child_dir.mkdir()
            shutil.copy2(scratch / "parent" / "mods" / name, child_dir / name)
        (scratch / "verified-source-manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        verify_prepared(scratch)
        os.rename(scratch, destination)
        return {"status": "prepared", **manifest}
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)
