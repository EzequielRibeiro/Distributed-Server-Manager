#!/usr/bin/env python3
"""#928 read-only SOURCE coverage inventory for Agent mutator entrypoints.

This audits only the checked-out Python source. It cannot establish which
version a running service imported, whether the opt-in is enabled, whether
an already detached process is in flight, or whether all jobs are known.
NEVER use its result as an authorization for update.sh --no-drain.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import stat
from typing import Any

PRIVILEGED = {
    "materialize_instance.py": "run",
    "native_command.py": "run",
    "create_instance_backup.py": "run",
    "restore_instance_backup.py": "run",
    "reconcile_firewall.py": "run",
    "prepare_customer_files.py": "run",
    "reconcile_runtime_identity.py": "reconcile",
}
NONCOOPERATING = {
    "uninstall_agent.py": "destructive_uninstall_and_detached_finalizer_unfenced",
}
READ_ONLY = {"console_journal_reader.py"}
CHILD_PATH = "agents/linux/runtime/minecraft_serverpack_finalization_worker.py"
_PRIVILEGED = "agents/linux/privileged"
_MAX_BYTES = 2 * 1024 * 1024


def _read_tree(root: Path, relative: str) -> tuple[ast.Module | None, str | None]:
    path = root / relative
    try:
        if any(part.is_symlink() for part in (root, path.parent, path)):
            return None, "symlink_rejected"
        meta = path.lstat()
        if not stat.S_ISREG(meta.st_mode) or not (0 < meta.st_size <= _MAX_BYTES):
            return None, "invalid_source_file"
        data = path.read_bytes()
        if len(data) != meta.st_size:
            return None, "changed_during_read"
        return ast.parse(data, filename=relative), hashlib.sha256(data).hexdigest()
    except (OSError, SyntaxError, UnicodeError, ValueError):
        return None, "source_unreadable_or_invalid"


def _named(tree: ast.Module | None, name: str) -> ast.FunctionDef | None:
    if tree is None:
        return None
    return next((node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name == name),
                None)


def _call_found(node: ast.AST | None, name: str) -> bool:
    if node is None:
        return False
    return any(isinstance(item, ast.Call)
               and isinstance(item.func, ast.Name)
               and item.func.id == name for item in ast.walk(node))


def _decorated(fn: ast.FunctionDef | None, name: str) -> bool:
    return bool(fn and any(isinstance(d, ast.Name) and d.id == name
                           for d in fn.decorator_list))


def assess(source_root: Path) -> dict[str, Any]:
    """Statically inspect the nine known privileged modules and one child.

    Does not read /proc, systemd, environment variables or credentials.
    Unknown privileged executables and broken instrumentation remain blockers.
    This function never returns positive in-flight or deployment attestation.
    """
    root = Path(source_root)
    blockers: list[str] = []
    records: list[dict[str, Any]] = []
    checked = set(PRIVILEGED) | set(NONCOOPERATING) | READ_ONLY

    for filename, entry in PRIVILEGED.items():
        tree, fingerprint = _read_tree(root, f"{_PRIVILEGED}/{filename}")
        fn = _named(tree, entry)
        present = bool(
            _decorated(fn, "fence_privileged_helper_run")
            and _call_found(fn, "require_privileged_mutation_admission")
        )
        records.append({
            "entrypoint": f"{filename}:{entry}",
            "source_guard_markers_found": present,
            "source_sha256": fingerprint if tree is not None else None,
            "runtime_opt_in_verified": False,
            "in_flight_quiescence_verified": False,
        })
        if not present:
            blockers.append(f"missing_source_guard:{filename}:{entry}")

    child, digest = _read_tree(root, CHILD_PATH)
    child_fn = _named(child, "execute_one")
    protected = bool(child_fn and _call_found(child_fn, "require_finalization_admission")
                     and any(
                         isinstance(item, (ast.With, ast.AsyncWith))
                         and any(isinstance(context.context_expr, ast.Call)
                                 and isinstance(context.context_expr.func, ast.Name)
                                 and context.context_expr.func.id == "shared_finalization_lock"
                                 for context in item.items)
                         and _call_found(item, "require_finalization_admission")
                         for item in ast.walk(child_fn)))
    records.append({
        "entrypoint": "minecraft_serverpack_finalization_worker.py:execute_one",
        "source_guard_markers_found": protected,
        "source_sha256": digest if child is not None else None,
        "runtime_opt_in_verified": False,
        "in_flight_quiescence_verified": False,
    })
    if not protected:
        blockers.append("missing_detached_child_source_guard")

    for filename, reason in NONCOOPERATING.items():
        tree, fingerprint = _read_tree(root, f"{_PRIVILEGED}/{filename}")
        records.append({
            "entrypoint": f"{filename}:main",
            "source_guard_markers_found": False,
            "source_sha256": fingerprint if tree is not None else None,
            "runtime_opt_in_verified": False,
            "in_flight_quiescence_verified": False,
            "reason": reason,
        })
        blockers.append(reason)
        if tree is None:
            blockers.append(f"missing_privileged_source:{filename}")

    for filename in sorted(READ_ONLY):
        tree, fingerprint = _read_tree(root, f"{_PRIVILEGED}/{filename}")
        records.append({
            "entrypoint": filename,
            "source_guard_markers_found": None,
            "source_sha256": fingerprint if tree is not None else None,
            "reason": "journal_observer_not_a_mutation_fence",
        })
        if tree is None:
            blockers.append(f"missing_readonly_source:{filename}")

    directory = root / _PRIVILEGED
    try:
        if root.is_symlink() or directory.is_symlink():
            raise OSError("untrusted source directory")
        found = {p.name for p in directory.glob("*.py")}
    except OSError:
        found = set()
        blockers.append("privileged_source_inventory_unavailable")
    unknown = sorted(found - checked)
    if unknown:
        blockers.append("unclassified_privileged_executables")
    if checked - found:
        blockers.append("expected_privileged_entrypoints_missing")

    blockers.extend([
        "runtime_systemd_opt_in_not_attested",
        "all_external_jobs_not_inventoried",
        "remote_agent_quiescence_not_attested",
    ])
    return {
        "status": "source_inventory_only_no_quiescence",
        "scope": "checked_out_linux_agent_privileged_modules_and_one_detached_child",
        "privileged_expected_modules": len(checked),
        "privileged_observed_modules": len(found),
        "privileged_unclassified_modules": unknown,
        "guarded_source_entrypoints": sum(row["source_guard_markers_found"] is True
                                          for row in records),
        "entries": records,
        "blockers": sorted(set(blockers)),
        "installed_process_identity_verified": False,
        "all_runtime_flags_verified": False,
        "all_external_jobs_inventoried": False,
        "external_jobs_acked": False,
        "remote_agents_acked": False,
        "live_no_drain_authorized": False,
    }


if __name__ == "__main__":
    # Strictly read-only diagnostic of this checked-out tree.
    print(json.dumps(assess(Path(__file__).resolve().parents[3]),
                     sort_keys=True, indent=2))
