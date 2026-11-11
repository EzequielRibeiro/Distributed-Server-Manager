#!/usr/bin/env python3
"""Read-only, fail-closed final convergence attestation for a Server Pack.

A Controller publication alone is not an ACK: every managed source, reported
Agent state and activation snapshot must agree with the *published* candidate.
No lifecycle actions, state changes or database writes are performed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from minecraft_serverpack_content_receipt import confirmed_serverpack_receipt
from core.minecraft_serverpack_pending_commit import validate_pending_bundle_commit


class ServerPackConvergenceError(RuntimeError):
    pass


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ServerPackConvergenceError(message)


def _sha(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _json_file(path: Path) -> dict[str, Any]:
    _need(path.is_file() and not path.is_symlink(), f"missing or unsafe state: {path.name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ServerPackConvergenceError(f"corrupt state file: {path.name}") from exc
    _need(isinstance(data, dict), "invalid state object")
    return data


def _file_matches(path: Path, size: int, sha256: str) -> bool:
    return path.is_file() and not path.is_symlink() and path.stat().st_size == size and _sha(path) == sha256


def verify_serverpack_content_convergence(
    *,
    backend,
    provisioning_id: str,
    agent_id: str,
    instance_id: str,
    candidate_sha256: str,
    managed_content_dir: Path,
    activation_snapshot_path: Path,
    runtime_dir: Path,
) -> dict[str, Any]:
    """Produce a final read-only receipt; call again immediately before ACK.

    The caller must independently prevent concurrent writers during promotion;
    this verifier never grants authorization to change a file or SQL state.
    """
    receipt = confirmed_serverpack_receipt(
        backend=backend, provisioning_id=provisioning_id,
        agent_id=agent_id, instance_id=instance_id,
        candidate_sha256=candidate_sha256,
    )
    ph = "?" if backend.name == "sqlite" else "%s"
    with backend.connect() as conn:
        if backend.name == "postgresql":
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        elif backend.name == "sqlite":
            conn.execute("BEGIN")
        op = conn.execute(
            f"SELECT request_json FROM agent_instance_provisioning WHERE provisioning_id={ph}"
            f" AND agent_id={ph} AND instance_id={ph} AND status='completed'",
            (provisioning_id, agent_id, instance_id),
        ).fetchone()
        _need(op is not None, "provisioning changed before acknowledgement")
        pending = validate_pending_bundle_commit(
            json.loads(op["request_json"])["configuration"]["minecraft_serverpack_pending_bundle"])
        _need(pending["candidate_sha256"] == receipt["candidate_sha256"],
              "published candidate changed")
        assignments = conn.execute(
            f"SELECT content_id,revision,checksum,version,desired_state,artifact_json "
            f"FROM content_assignments WHERE instance_id={ph}", (instance_id,),
        ).fetchall()
        reports = conn.execute(
            f"SELECT content_id,desired_revision,applied_revision,desired_checksum,"
            f"applied_checksum,status,installed_version,security_state "
            f"FROM agent_content_state WHERE instance_id={ph} AND agent_id={ph}",
            (instance_id,agent_id),
        ).fetchall()
        bundle = conn.execute(
            f"SELECT revision,manifest_sha256 FROM content_bundles "
            f"WHERE instance_id={ph} AND parent_content_id={ph}",
            (instance_id,pending["content_id"]),
        ).fetchone()
        _need(bundle is not None and bundle["revision"] == receipt["bundle_revision"]
              and bundle["manifest_sha256"] == receipt["manifest_sha256"],
              "bundle changed during state verification")
    assigned = {str(r["content_id"]):dict(r) for r in assignments}
    reported = {str(r["content_id"]):dict(r) for r in reports}
    _need(len(assigned) == len(assignments) == len(reported) == len(reports),
          "incomplete or duplicated Agent content states")
    expected_active = {pending["content_id"], *(child["content_id"] for child in pending["children"])}
    actual_active = {cid for cid,row in assigned.items() if row["desired_state"] == "installed"}
    _need(actual_active == expected_active, "installed content differs from published bundle")

    managed_content_dir = Path(managed_content_dir)
    runtime_dir = Path(runtime_dir)
    _need(managed_content_dir.is_dir() and not managed_content_dir.is_symlink(),
          "managed states directory missing")
    _need(runtime_dir.is_dir() and not runtime_dir.is_symlink(), "runtime missing")
    paths = list(managed_content_dir.glob("*.json"))
    _need(len(paths) == len(assigned), "Agent local state count differs from Controller")
    local: dict[str, dict[str, Any]] = {}
    for path in paths:
        _need(path.stem in assigned and path.stem not in local, "foreign Agent state")
        state = _json_file(path)
        _need(state.get("content_id") == path.stem
              and state.get("instance_id") == instance_id, "Agent state identity mismatch")
        local[path.stem] = state

    for cid,assignment in assigned.items():
        report = reported[cid]
        state = local[cid]
        installed = assignment["desired_state"] == "installed"
        _need(report["status"] == "applied"
              and report["desired_revision"] == assignment["revision"]
              and report["applied_revision"] == assignment["revision"]
              and report["desired_checksum"] == assignment["checksum"]
              and report["applied_checksum"] == assignment["checksum"],
              f"Controller Agent report not converged: {cid}")
        _need(state.get("status") == "applied"
              and state.get("applied_revision") == assignment["revision"]
              and state.get("desired_revision") == assignment["revision"]
              and state.get("applied_checksum") == assignment["checksum"]
              and state.get("desired_checksum") == assignment["checksum"]
              and state.get("desired_state") == assignment["desired_state"],
              f"local Agent state not converged: {cid}")
        _need(report["installed_version"] == (assignment["version"] if installed else None)
              and state.get("installed_version") == (assignment["version"] if installed else None),
              f"installed version not converged: {cid}")
        if installed:
            _need(report["security_state"] == "clean"
                  and state.get("security_state") == "clean"
                  and state.get("applied_security_state") == "clean",
                  f"unverified security state: {cid}")
            _need(state.get("attestation_candidate_sha256") == candidate_sha256,
                  f"Agent attestation candidate mismatch: {cid}")
        else:
            _need(not state.get("managed_path") and report["security_state"] == "unscanned",
                  f"removed content retained a managed source: {cid}")

    parent_dir = runtime_dir / "content" / "modpacks" / pending["content_id"]
    child_root = runtime_dir / "content" / "mods"
    _need(parent_dir.is_dir() and not parent_dir.is_symlink()
          and (parent_dir/"mods").is_dir() and not (parent_dir/"mods").is_symlink()
          and child_root.is_dir() and not child_root.is_symlink()
          and (runtime_dir/"mods").is_dir() and not (runtime_dir/"mods").is_symlink(),
          "managed source trees missing")
    filenames: set[str] = set()
    for child in pending["children"]:
        cid = child["content_id"]
        artifact = child["artifact"]
        filename = str(artifact.get("filename") or "")
        sha = str(artifact.get("sha256") or "")
        size = int(artifact.get("size_bytes") or 0)
        _need(filename and filename.endswith(".jar") and "/" not in filename and "\\" not in filename,
              "unsafe mod filename")
        _need(filename not in filenames and size > 0, "duplicate or empty mod")
        filenames.add(filename)
        managed_path = child_root / cid
        _need(managed_path.is_dir() and not managed_path.is_symlink(),
              f"unsafe managed mod directory: {cid}")
        _need(local[cid].get("managed_path") == str(managed_path),
              f"managed mod path incorrect: {cid}")
        for path in (runtime_dir/"mods"/filename,parent_dir/"mods"/filename,managed_path/filename):
            _need(_file_matches(path,size,sha), f"mod content differs from committed version: {filename}")
    _need({p.name for p in (runtime_dir/"mods").glob("*.jar")} == filenames
          and {p.name for p in (parent_dir/"mods").glob("*.jar")} == filenames
          and {p.name for p in child_root.iterdir()} == expected_active-{pending["content_id"]},
          "actual managed mod inventory incomplete")
    _need(local[pending["content_id"]].get("managed_path") == str(parent_dir),
          "parent managed path differs")

    snapshot = _json_file(Path(activation_snapshot_path))
    checksum = snapshot.get("checksum")
    identity = {k:v for k,v in snapshot.items() if k != "checksum"}
    computed = hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(",",":"),
                                         ensure_ascii=False).encode("utf-8")).hexdigest()
    _need(snapshot.get("kind") == "CapivaraContentActivationSnapshot"
          and snapshot.get("instance_id") == instance_id
          and checksum == computed, "activation snapshot checksum mismatch")
    entries = snapshot.get("entries")
    _need(isinstance(entries,list) and len(entries) == len(expected_active)
          and {item.get("content_id") for item in entries if isinstance(item,dict)} == expected_active,
          "activation snapshot does not match installed content")
    for entry in entries:
        cid = entry["content_id"]
        _need(entry.get("managed_path") == local[cid]["managed_path"],
              "activation snapshot points to another source")

    # Revalidate the durable Controller publication after filesystem checks.
    last = confirmed_serverpack_receipt(
        backend=backend,provisioning_id=provisioning_id,
        agent_id=agent_id,instance_id=instance_id,candidate_sha256=candidate_sha256,
    )
    _need(last == receipt, "Controller receipt changed during convergence verification")
    return {
        "kind": "VerifiedServerPackContentConvergence", "status": "ready",
        "instance_id": instance_id, "candidate_sha256":candidate_sha256,
        "bundle_revision": receipt["bundle_revision"],
        "manifest_sha256":receipt["manifest_sha256"],
        "installed_content":len(expected_active),
        "mods_verified":len(filenames),
        "removed_content":len(assigned)-len(expected_active),
        "activation_checksum":checksum,
    }
