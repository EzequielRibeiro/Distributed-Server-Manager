"""Crash-consistent filesystem swap for staged Minecraft Server Pack migrations.

The caller must already hold the per-instance runtime-operation lock. This
module owns only the migration-specific durable journal and filesystem rename
protocol. It never starts/stops a server, installs content or publishes
Controller state.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from minecraft_serverpack_agent import verify_installed_neoforge

_PHASES={"prepared","swapping","swapped","recovering","recovered","committed"}


class MinecraftServerPackMigrationSwapError(RuntimeError):
    pass


def _sync_dir(path:Path)->None:
    fd=os.open(str(path),os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
    try:os.fsync(fd)
    finally:os.close(fd)


def _safe_root(root:Path)->Path:
    root=Path(root)
    if not root.is_dir() or root.is_symlink():
        raise MinecraftServerPackMigrationSwapError("instance state root must be a regular directory")
    return root.resolve()


def _paths(root:Path)->dict[str,Path]:
    root=_safe_root(root)
    control=root/".dsm"
    if control.exists() and (not control.is_dir() or control.is_symlink()):
        raise MinecraftServerPackMigrationSwapError("instance control directory is unsafe")
    control.mkdir(exist_ok=True)
    return {
        "root":root,
        "control":control,
        "active":root/"runtime",
        "stage":root/"runtime.migration-stage",
        "rollback":root/"runtime.migration-rollback",
        "failed":root/"runtime.migration-failed",
        "journal":control/"minecraft-serverpack-migration.json",
        "temp":control/".minecraft-serverpack-migration.json.tmp",
    }


def _tree_hash(root:Path)->str:
    if not root.is_dir() or root.is_symlink():
        raise MinecraftServerPackMigrationSwapError("runtime tree is missing or unsafe")
    digest=hashlib.sha256()
    for current in sorted(root.rglob("*")):
        if current.is_symlink() or (not current.is_dir() and not current.is_file()):
            raise MinecraftServerPackMigrationSwapError("runtime tree contains unsafe filesystem entries")
        if current.is_dir():continue
        rel=current.relative_to(root).as_posix().encode("utf-8")
        file_hash=hashlib.sha256()
        with current.open("rb") as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b""):file_hash.update(chunk)
        digest.update(len(rel).to_bytes(4,"big"));digest.update(rel);digest.update(file_hash.digest())
    return digest.hexdigest()

_MANAGED_ROOTS=frozenset({"libraries","mods"})
_MANAGED_FILES=frozenset({"capivara-launch.args","user_jvm_args.txt","run.sh","run.bat","eula.txt"})


def _managed_hash(root:Path)->str:
    """Hash only provider/pack-owned runtime material allowed to stay immutable.

    A successful readiness boot is expected to modify world data, logs, caches,
    server.properties and sometimes mod configuration. Those instance-private
    writes must not invalidate commit. Loader libraries, launch metadata and
    managed mod JARs, however, must remain byte-identical to the staged
    checkpoint.
    """
    if not root.is_dir() or root.is_symlink():
        raise MinecraftServerPackMigrationSwapError("runtime tree is missing or unsafe")
    digest=hashlib.sha256();found=False
    for current in sorted(root.rglob("*")):
        if current.is_symlink() or (not current.is_dir() and not current.is_file()):
            raise MinecraftServerPackMigrationSwapError("runtime tree contains unsafe filesystem entries")
        if current.is_dir():continue
        relative=current.relative_to(root)
        if not relative.parts:
            continue
        if relative.parts[0] not in _MANAGED_ROOTS and relative.as_posix() not in _MANAGED_FILES:
            continue
        found=True
        encoded=relative.as_posix().encode("utf-8")
        file_hash=hashlib.sha256()
        with current.open("rb") as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b""):file_hash.update(chunk)
        digest.update(len(encoded).to_bytes(4,"big"));digest.update(encoded);digest.update(file_hash.digest())
    if not found:
        raise MinecraftServerPackMigrationSwapError("managed runtime checkpoint is empty")
    return digest.hexdigest()


def _atomic(paths:dict[str,Path],payload:dict[str,Any])->None:
    journal=paths["journal"];temp=paths["temp"]
    if temp.exists():
        raise MinecraftServerPackMigrationSwapError("orphan migration journal temporary file requires recovery")
    temp.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    os.chmod(temp,0o600)
    fd=os.open(str(temp),os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    os.replace(temp,journal);_sync_dir(paths["control"])


def _read(paths:dict[str,Path])->dict[str,Any]:
    try:value=json.loads(paths["journal"].read_text(encoding="utf-8"))
    except (OSError,ValueError) as exc:
        raise MinecraftServerPackMigrationSwapError("migration swap journal is absent or corrupted") from exc
    if not isinstance(value,dict) or value.get("phase") not in _PHASES:
        raise MinecraftServerPackMigrationSwapError("migration swap journal is invalid")
    return value


def _backup_evidence(value:Mapping[str,Any])->dict[str,Any]:
    if not isinstance(value,Mapping):
        raise MinecraftServerPackMigrationSwapError("verified backup evidence is required")
    backup_id=str(value.get("backup_id") or "").strip()
    sha=str(value.get("sha256") or "").strip().lower()
    try:size=int(value.get("size_bytes") or 0)
    except (TypeError,ValueError):size=0
    if not backup_id or len(sha)!=64 or any(c not in "0123456789abcdef" for c in sha) or size<=0 or value.get("integrity_verified") is not True:
        raise MinecraftServerPackMigrationSwapError("verified backup evidence is required")
    return {"backup_id":backup_id,"sha256":sha,"size_bytes":size,"integrity_verified":True}


def prepare(instance_state_root:Path,*,migration_plan_sha256:str,target_loader_version:str,backup:Mapping[str,Any])->dict[str,Any]:
    paths=_paths(instance_state_root)
    if paths["journal"].exists() or paths["temp"].exists():
        raise MinecraftServerPackMigrationSwapError("previous migration journal exists; recover or archive it first")
    if paths["rollback"].exists() or paths["failed"].exists():
        raise MinecraftServerPackMigrationSwapError("migration rollback/quarantine path is occupied")
    if not paths["active"].is_dir() or paths["active"].is_symlink():
        raise MinecraftServerPackMigrationSwapError("active runtime is missing or unsafe")
    if not paths["stage"].is_dir() or paths["stage"].is_symlink():
        raise MinecraftServerPackMigrationSwapError("staged runtime is missing or unsafe")
    plan=str(migration_plan_sha256 or "").strip().lower()
    if len(plan)!=64 or any(c not in "0123456789abcdef" for c in plan):
        raise MinecraftServerPackMigrationSwapError("migration plan fingerprint is invalid")
    proof=verify_installed_neoforge(paths["stage"],str(target_loader_version or ""))
    backup_verified=_backup_evidence(backup)
    payload={
        "schema_version":1,"kind":"CapivaraMinecraftServerPackMigrationSwap",
        "phase":"prepared","migration_plan_sha256":plan,
        "target_loader_version":str(target_loader_version),
        "original_tree_sha256":_tree_hash(paths["active"]),
        "staged_tree_sha256":_tree_hash(paths["stage"]),
        "staged_managed_sha256":_managed_hash(paths["stage"]),
        "backup":backup_verified,"loader_proof":proof,
    }
    _atomic(paths,payload)
    return dict(payload)


def switch(instance_state_root:Path)->dict[str,Any]:
    paths=_paths(instance_state_root);data=_read(paths)
    if data["phase"]!="prepared":
        raise MinecraftServerPackMigrationSwapError("journal phase does not allow runtime switch")
    if paths["rollback"].exists() or paths["failed"].exists():
        raise MinecraftServerPackMigrationSwapError("migration rollback/quarantine path is occupied")
    if _tree_hash(paths["active"])!=data.get("original_tree_sha256") or _tree_hash(paths["stage"])!=data.get("staged_tree_sha256"):
        raise MinecraftServerPackMigrationSwapError("runtime trees changed after migration checkpoint")
    data["phase"]="swapping";_atomic(paths,data)
    os.replace(paths["active"],paths["rollback"]);_sync_dir(paths["root"])
    os.replace(paths["stage"],paths["active"]);_sync_dir(paths["root"])
    if _tree_hash(paths["active"])!=data.get("staged_tree_sha256"):
        raise MinecraftServerPackMigrationSwapError("active runtime differs from staged checkpoint after switch")
    data["phase"]="swapped";_atomic(paths,data)
    return dict(data)


def commit(instance_state_root:Path,*,readiness_passed:bool)->dict[str,Any]:
    paths=_paths(instance_state_root);data=_read(paths)
    if data["phase"]!="swapped" or readiness_passed is not True:
        raise MinecraftServerPackMigrationSwapError("successful readiness after swap is required")
    if _managed_hash(paths["active"])!=data.get("staged_managed_sha256"):
        raise MinecraftServerPackMigrationSwapError("managed runtime changed before commit")
    if _tree_hash(paths["rollback"])!=data.get("original_tree_sha256"):
        raise MinecraftServerPackMigrationSwapError("rollback runtime changed before commit")
    verify_installed_neoforge(paths["active"],str(data.get("target_loader_version") or ""))
    data["phase"]="committed";_atomic(paths,data)
    return {"status":"committed","rollback_retained":True,"journal":dict(data)}


def recover(instance_state_root:Path)->dict[str,Any]:
    paths=_paths(instance_state_root);data=_read(paths)
    if data["phase"]=="committed":
        raise MinecraftServerPackMigrationSwapError("committed migration cannot be silently recovered")
    expected_old=str(data.get("original_tree_sha256") or "")
    expected_new=str(data.get("staged_tree_sha256") or "")
    if len(expected_old)!=64 or len(expected_new)!=64:
        raise MinecraftServerPackMigrationSwapError("migration journal lacks tree checksums")
    if paths["temp"].exists():
        original=paths["rollback"] if paths["rollback"].is_dir() else paths["active"]
        if not original.is_dir() or _tree_hash(original)!=expected_old:
            raise MinecraftServerPackMigrationSwapError("unverified original runtime; retain orphan journal")
        paths["temp"].unlink();_sync_dir(paths["control"])
    if data["phase"]=="recovered":
        if _tree_hash(paths["active"])!=expected_old:
            raise MinecraftServerPackMigrationSwapError("recovered runtime checksum changed")
        return {"status":"already_recovered","failed_runtime_retained":paths["failed"].exists()}
    if paths["rollback"].exists():
        if not paths["rollback"].is_dir() or paths["rollback"].is_symlink() or _tree_hash(paths["rollback"])!=expected_old:
            raise MinecraftServerPackMigrationSwapError("rollback runtime is missing or does not match checkpoint")
        data["phase"]="recovering";_atomic(paths,data)
        if paths["active"].exists():
            if paths["failed"].exists():
                raise MinecraftServerPackMigrationSwapError("failed-runtime quarantine path is occupied")
            if not paths["active"].is_dir() or paths["active"].is_symlink():
                raise MinecraftServerPackMigrationSwapError("active runtime is unsafe during recovery")
            # Keep the candidate for diagnosis. It may be complete or partial.
            os.replace(paths["active"],paths["failed"]);_sync_dir(paths["root"])
        os.replace(paths["rollback"],paths["active"]);_sync_dir(paths["root"])
    else:
        if not paths["active"].is_dir() or _tree_hash(paths["active"])!=expected_old:
            raise MinecraftServerPackMigrationSwapError("original runtime is unavailable; manual recovery required")
    if _tree_hash(paths["active"])!=expected_old:
        raise MinecraftServerPackMigrationSwapError("restored runtime failed checksum verification")
    data["phase"]="recovered";_atomic(paths,data)
    return {"status":"recovered","failed_runtime_retained":paths["failed"].exists(),"journal":dict(data)}



def _archive_checkpoint(paths: dict[str, Path], digest: str) -> None:
    """Durably identify the transaction being archived before either rename."""
    target = paths["control"] / "minecraft-serverpack-archive-checkpoint.json"
    temp = paths["control"] / ".minecraft-serverpack-archive-checkpoint.tmp"
    if target.is_symlink() or temp.exists():
        raise MinecraftServerPackMigrationSwapError("unsafe archival checkpoint")
    if target.exists():
        try:
            old = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MinecraftServerPackMigrationSwapError("corrupted archival checkpoint") from exc
        if old.get("sha256") == digest:
            return
        old_archive = paths["control"] / "migration-history" / old.get("sha256", "")[:24]
        old_journal = old_archive / "minecraft-serverpack-migration.json"
        if (old_archive.is_symlink() or old_journal.is_symlink()
                or not old_journal.is_file()
                or hashlib.sha256(old_journal.read_bytes()).hexdigest() != old.get("sha256")):
            raise MinecraftServerPackMigrationSwapError("prior archival is not complete")
    content = json.dumps({"schema_version": 1, "sha256": digest}, sort_keys=True) + "\n"
    with temp.open("x", encoding="utf-8") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, target)
    _sync_dir(paths["control"])


def archive_committed(instance_state_root: Path) -> dict[str, Any]:
    """Idempotently finalize a committed transaction; preserve prior rollback.

    Caller holds the per-instance lock and proves the instance is stopped.
    Checkpoint is durably written before moving rollback or journal; a crash
    after either rename can be resumed safely without guessing an archive ID.
    """
    paths = _paths(instance_state_root)
    checkpoint = paths["control"] / "minecraft-serverpack-archive-checkpoint.json"
    if checkpoint.is_symlink():
        raise MinecraftServerPackMigrationSwapError("unsafe archival checkpoint")
    saved = None
    if checkpoint.exists():
        try:
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MinecraftServerPackMigrationSwapError("invalid archival checkpoint") from exc
        if (not isinstance(saved, dict) or saved.get("schema_version") != 1
                or not isinstance(saved.get("sha256"), str)
                or len(saved["sha256"]) != 64
                or any(x not in "0123456789abcdef" for x in saved["sha256"])):
            raise MinecraftServerPackMigrationSwapError("invalid archival checkpoint")
    if paths["journal"].is_file() and not paths["journal"].is_symlink():
        if _read(paths).get("phase") != "committed":
            raise MinecraftServerPackMigrationSwapError("only committed migration can be archived")
    if paths["temp"].exists() or paths["failed"].exists() or paths["stage"].exists():
        raise MinecraftServerPackMigrationSwapError("unsafe migration artifacts block archival")
    if not paths["active"].is_dir() or paths["active"].is_symlink():
        raise MinecraftServerPackMigrationSwapError("active runtime is unsafe")
    history = paths["control"] / "migration-history"
    if history.is_symlink() or (history.exists() and not history.is_dir()):
        raise MinecraftServerPackMigrationSwapError("migration history is unsafe")
    journal_present = paths["journal"].is_file() and not paths["journal"].is_symlink()
    if not journal_present and not saved:
        raise MinecraftServerPackMigrationSwapError("no committed journal or archival checkpoint")
    if journal_present:
        data = _read(paths)
        if data.get("phase") != "committed":
            raise MinecraftServerPackMigrationSwapError("only committed migration can be archived")
        digest = hashlib.sha256(paths["journal"].read_bytes()).hexdigest()
        if saved and saved["sha256"] != digest:
            prior = history / saved["sha256"][:24] / "minecraft-serverpack-migration.json"
            if prior.is_symlink() or not prior.is_file() or hashlib.sha256(prior.read_bytes()).hexdigest() != saved["sha256"]:
                raise MinecraftServerPackMigrationSwapError("previous archival is unfinished")
    else:
        digest = saved["sha256"]
        historical = history / digest[:24] / "minecraft-serverpack-migration.json"
        if historical.is_symlink() or not historical.is_file():
            raise MinecraftServerPackMigrationSwapError("archived journal absent after rename")
        if hashlib.sha256(historical.read_bytes()).hexdigest() != digest:
            raise MinecraftServerPackMigrationSwapError("archived journal differs from checkpoint")
        data = json.loads(historical.read_text(encoding="utf-8"))
        if data.get("phase") != "committed":
            raise MinecraftServerPackMigrationSwapError("archived journal is not committed")
    old = data.get("original_tree_sha256")
    if not isinstance(old, str) or len(old) != 64 or any(x not in "0123456789abcdef" for x in old):
        raise MinecraftServerPackMigrationSwapError("committed journal lacks rollback checksum")
    archive = history / digest[:24]
    if archive.is_symlink() or (archive.exists() and not archive.is_dir()):
        raise MinecraftServerPackMigrationSwapError("archive target is unsafe")
    retained = archive / "runtime.migration-rollback"
    historical_journal = archive / "minecraft-serverpack-migration.json"
    if retained.is_symlink() or historical_journal.is_symlink() or paths["rollback"].is_symlink():
        raise MinecraftServerPackMigrationSwapError("archive contains unsafe links")
    if paths["rollback"].exists() and retained.exists():
        raise MinecraftServerPackMigrationSwapError("both rollback locations occupied")
    if paths["rollback"].is_dir():
        if _tree_hash(paths["rollback"]) != old:
            raise MinecraftServerPackMigrationSwapError("rollback evidence differs from checkpoint")
    elif retained.is_dir():
        if _tree_hash(retained) != old:
            raise MinecraftServerPackMigrationSwapError("archived rollback differs from checkpoint")
    else:
        raise MinecraftServerPackMigrationSwapError("rollback evidence is missing")
    if historical_journal.exists() and (not historical_journal.is_file()
            or hashlib.sha256(historical_journal.read_bytes()).hexdigest() != digest):
        raise MinecraftServerPackMigrationSwapError("historical journal differs from checkpoint")
    if journal_present and historical_journal.exists():
        raise MinecraftServerPackMigrationSwapError("both journal locations occupied")

    history.mkdir(exist_ok=True)
    archive.mkdir(exist_ok=True)
    _sync_dir(paths["control"])
    _sync_dir(history)
    _archive_checkpoint(paths, digest)
    if paths["rollback"].is_dir():
        os.replace(paths["rollback"], retained)
        _sync_dir(paths["root"])
        _sync_dir(archive)
    if journal_present:
        os.replace(paths["journal"], historical_journal)
        _sync_dir(paths["control"])
        _sync_dir(archive)
    return {"status": "archived" if journal_present else "already_archived",
            "history": str(archive), "sha256": digest}


__all__=["MinecraftServerPackMigrationSwapError","prepare","switch","commit","recover","archive_committed"]
