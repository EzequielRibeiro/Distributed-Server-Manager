#!/usr/bin/env python3
"""#928: bounded in-place product-file transaction, separate from draining updater.

The retained-scope owner supplies the reviewed exact changed-file set and a
checkpoint. This engine does not stop services, change systemd, migrate the
database, replace the installation root or move any preserved game tree.
Only existing compatible regular files are supported. Durable before/after
bytes are written before the first mutation; rollback accepts only either
of the recorded states. Installed execution remains unavailable until the
production admission and finalization owner is integrated.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile

_LIMIT = 4 * 1024 * 1024
_TOTAL = 48 * 1024 * 1024
_COUNT = 256
_PREFIXES = ("dashboard/", "api/", "scheduler/", "notification/", "metrics/", "monitor/")
_SUFFIXES = {".py", ".js", ".css", ".html", ".htm", ".json", ".svg", ".png",
             ".ico", ".woff", ".woff2", ".map"}
_METADATA = {"version", "release-manifest.json"}


class FileTransactionBlocked(RuntimeError):
    pass


def _approved_path(relative):
    if type(relative) is not str or not 1 <= len(relative) <= 512:
        return False
    parts = relative.split("/")
    if any(not part or part in (".", "..") or
           not re.fullmatch(r"[A-Za-z0-9_.+-]+", part) for part in parts):
        return False
    if relative in _METADATA:
        return True
    return (relative.startswith(_PREFIXES) and Path(relative).suffix.lower() in _SUFFIXES
            and not any(part in ("state", "runtime", "logs", "data", "uploads",
                                 "backups", "__pycache__") for part in parts[:-1]))


def _directory(path):
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_mode & 0o022):
        raise FileTransactionBlocked("untrusted_product_directory")
    return info


def _file(root, relative):
    if not _approved_path(relative):
        raise FileTransactionBlocked("incompatible_product_path")
    _directory(root)
    parts = relative.split("/")
    for index in range(1, len(parts)):
        _directory(root.joinpath(*parts[:index]))
    return root.joinpath(*parts)


def _read(path):
    named = path.lstat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        def identity(item):
            return (item.st_dev, item.st_ino, item.st_uid, item.st_gid,
                    item.st_mode, item.st_nlink, item.st_size,
                    item.st_mtime_ns, item.st_ctime_ns)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_mode & 0o7133 or info.st_size > _LIMIT
                or identity(named) != identity(info)
                or os.listxattr(fd)):
            raise FileTransactionBlocked("incompatible_product_file")
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(_LIMIT + 1)
        if (len(raw) != info.st_size
                or identity(os.fstat(fd)) != identity(info)
                or identity(path.lstat()) != identity(info)):
            raise FileTransactionBlocked("product_file_changed_while_reading")
        return {"sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": base64.b64encode(raw).decode("ascii"),
                "mode": stat.S_IMODE(info.st_mode), "uid": info.st_uid, "gid": info.st_gid}
    finally:
        os.close(fd)


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_once(path, payload):
    raw = _encode(payload)
    if len(raw) > _TOTAL:
        raise FileTransactionBlocked("file_transaction_snapshot_too_large")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(path.parent)


def _read_journal(path):
    before = path.lstat()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600
                or (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino)
                or not 0 < info.st_size <= _TOTAL):
            raise FileTransactionBlocked("untrusted_file_transaction_journal")
        raw = stream.read(_TOTAL + 1)
    result = json.loads(raw)
    if len(raw) != info.st_size or raw != _encode(result):
        raise FileTransactionBlocked("invalid_file_transaction_journal")
    return result


def _replace(path, desired, expected):
    # Never overwrite an unexpected third state. Write a fresh inode beside
    # the destination, preserve owner/mode, fsync before atomic replacement.
    if _read(path) != expected:
        raise FileTransactionBlocked("product_file_drift_before_replace")
    raw = base64.b64decode(desired["bytes"], validate=True)
    if hashlib.sha256(raw).hexdigest() != desired["sha256"]:
        raise FileTransactionBlocked("snapshot_digest_mismatch")
    # mkstemp converts relative directories into absolute paths. The
    # unprivileged worker deliberately enters a product directory by fd
    # beneath a root-private ancestor, so absolute traversal is forbidden.
    # Keep the sibling name relative to that retained working directory.
    for _ in range(16):
        temp = path.parent / (".dsm928-" + secrets.token_hex(16))
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            break
        except FileExistsError:
            continue
    else:
        raise FileTransactionBlocked("product_temporary_file_collision")
    try:
        with os.fdopen(fd, "wb") as stream:
            current = os.fstat(stream.fileno())
            if (current.st_uid, current.st_gid) != (desired["uid"], desired["gid"]):
                os.fchown(stream.fileno(), desired["uid"], desired["gid"])
            os.fchmod(stream.fileno(), desired["mode"])
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if _read(path) != expected or _read(temp) != desired:
            raise FileTransactionBlocked("product_file_drift_before_activation")
        os.replace(temp, path)
        _fsync_dir(path.parent)
        if _read(path) != desired:
            raise FileTransactionBlocked("product_file_activation_unverified")
    finally:
        if temp.exists():
            temp.unlink()


def _worker_main():
    """Only the unprivileged product account touches its own installation."""
    if os.geteuid() == 0 or os.getegid() == 0 or os.getgroups():
        raise FileTransactionBlocked("privileged_product_worker_forbidden")
    fd = int(sys.argv[1])
    os.fchdir(fd)
    os.close(fd)
    request = json.loads(sys.stdin.buffer.read(2 * _LIMIT * 2 + 65536))
    path = _file(Path("."), request["path"])
    current = _read(path)
    if (current["uid"], current["gid"]) != (os.geteuid(), os.getegid()):
        raise FileTransactionBlocked("product_account_file_owner_mismatch")
    if request["action"] == "replace":
        desired, expected = request["desired"], request["expected"]
        if any((item["uid"], item["gid"]) != (os.geteuid(), os.getegid())
               for item in (desired, expected)):
            raise FileTransactionBlocked("product_worker_ownership_change_forbidden")
        _replace(path, desired, expected)
        current = _read(path)
    elif request["action"] != "read":
        raise FileTransactionBlocked("unknown_product_worker_operation")
    sys.stdout.buffer.write(_encode(current))


class FileTransaction:
    """Fixed file-operation owner for the existing retained transaction driver."""

    def __init__(self, workspace, installed, target, *, transaction_id,
                 release_sha256, checkpoint, product_identity=None,
                 _installed_scope=None):
        self.workspace = Path(workspace)
        self.installed = Path(installed)
        self.target = Path(target)
        if (not isinstance(transaction_id, str) or
                not re.fullmatch(r"[0-9a-f]{32}", transaction_id)
                or not isinstance(release_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", release_sha256)
                or not callable(checkpoint)):
            raise FileTransactionBlocked("unbound_file_transaction")
        root = self.workspace
        self.installed_execution = _installed_scope is not None
        if not self.installed_execution:
            tmp = Path(tempfile.gettempdir()).resolve(strict=True)
            if (tmp not in root.parents or root.resolve(strict=True) != root
                    or _directory(root).st_mode & 0o077
                    or self.installed != root / "installed"
                    or self.target != root / "new-payload"
                    or (root / "fixture-owner").is_symlink()
                    or (root / "fixture-owner").read_bytes() != b"DSM928_DISPOSABLE_FIXTURE_V1\n"):
                raise FileTransactionBlocked("installed_file_transaction_not_authorized")
        else:
            # Internal installed owner only. These are necessary retained
            # guarantees, not an operator override or a standalone CLI.
            state = Path("/var/lib/capivara-dsm-928")
            if (os.geteuid() != 0 or type(_installed_scope) is not dict
                    or _installed_scope.get("kind") != "DSM928InstalledDistributedScope"
                    or _installed_scope.get("transaction_id") != transaction_id
                    or _installed_scope.get("release_sha256") != release_sha256
                    or _installed_scope.get("checkpoint") is not checkpoint
                    or _installed_scope.get("all_mutators_fenced") is not True
                    or _installed_scope.get("external_jobs_acked") is not True
                    or root != state / ("transaction-" + transaction_id)
                    or self.installed != Path("/opt/dsm")
                    or self.target != state / "reviewed-release/payload"
                    or product_identity is None):
                raise FileTransactionBlocked("installed_file_transaction_not_authorized")
            for folder in (Path("/var"), Path("/var/lib"), state, root,
                           self.target.parent, self.target):
                _directory(folder)
            if stat.S_IMODE(root.lstat().st_mode) != 0o700:
                raise FileTransactionBlocked("installed_transaction_workspace_not_private")
            checkpoint()
        if product_identity is not None and (
                os.geteuid() != 0 or type(product_identity) is not tuple
                or len(product_identity) != 2
                or any(type(value) is not int or value <= 0 for value in product_identity)):
            raise FileTransactionBlocked("invalid_unprivileged_product_identity")
        self.product_identity = product_identity
        if product_identity is None:
            _directory(self.installed)
        else:
            info = self.installed.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022
                    or (info.st_uid, info.st_gid) != product_identity):
                raise FileTransactionBlocked("untrusted_product_account_directory")
        _directory(self.target)
        self.transaction_id = transaction_id
        self.release_sha256 = release_sha256
        self.checkpoint = checkpoint
        self.journal = root / "dsm928-product-files.json"

    def _account_operation(self, name, action, **values):
        # The private root-owned journal parent is inaccessible to the
        # product account. Pass only the opened installation directory,
        # never the journal, locks or a privileged filesystem descriptor.
        uid, gid = self.product_identity
        fd = os.open(self.installed, os.O_RDONLY | os.O_DIRECTORY |
                     os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            named = self.installed.lstat()
            if ((info.st_uid, info.st_gid) != (uid, gid)
                    or info.st_mode & 0o022
                    or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
                raise FileTransactionBlocked("product_account_root_changed")
            source = Path(__file__).read_text(encoding="utf-8")
            result = subprocess.run(
                ("/usr/bin/python3", "-I", "-S", "-B", "-c",
                 source + "\n_worker_main()\n", str(fd)),
                input=_encode({"path": name, "action": action, **values}),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                user=uid, group=gid, extra_groups=[], pass_fds=(fd,),
                cwd="/", env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                check=False, timeout=15)
            after = self.installed.lstat()
            if (result.returncode != 0 or len(result.stdout) > 2 * _LIMIT + 4096
                    or (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode)
                    != (after.st_dev, after.st_ino, after.st_uid, after.st_gid, after.st_mode)):
                raise FileTransactionBlocked("unprivileged_product_operation_failed")
            item = json.loads(result.stdout)
            if (type(item) is not dict
                    or set(item) != {"sha256", "bytes", "mode", "uid", "gid"}
                    or (item["uid"], item["gid"]) != (uid, gid)
                    or type(item["mode"]) is not int or item["mode"] & 0o7133
                    or hashlib.sha256(base64.b64decode(item["bytes"], validate=True)).hexdigest()
                       != item["sha256"]
                    or result.stdout != _encode(item)):
                raise FileTransactionBlocked("untrusted_product_worker_receipt")
            return item
        finally:
            os.close(fd)

    def _installed_read(self, name):
        if self.product_identity is None:
            return _read(_file(self.installed, name))
        return self._account_operation(name, "read")

    def _installed_replace(self, name, desired, expected):
        if self.product_identity is None:
            _replace(_file(self.installed, name), desired, expected)
        elif self._account_operation(name, "replace", desired=desired,
                                     expected=expected) != desired:
            raise FileTransactionBlocked("unprivileged_product_activation_unverified")

    @contextmanager
    def _exclusive(self):
        fd = os.open(self.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise FileTransactionBlocked("product_file_transaction_busy") from exc
            self.checkpoint()
            yield
            self.checkpoint()
        finally:
            os.close(fd)

    def run_control_plane_fixture(self, plan, restart_services, verify_services):
        """Exercise file and service recovery with disposable callbacks only.

        A failed rollback propagates; the durable journal remains available.
        No installed service command or production admission is exposed.
        """
        if self.installed_execution:
            raise FileTransactionBlocked("control_plane_restart_fixture_only")
        if not callable(restart_services) or not callable(verify_services):
            raise FileTransactionBlocked("control_plane_fixture_callbacks_required")
        self.prepare_control_plane(plan)
        try:
            self.apply()
            self.checkpoint()
            restart_services()
            self.checkpoint()
            if verify_services() is not True:
                raise FileTransactionBlocked("control_plane_fixture_health_failed")
            self.verify_terminal("verified")
            return {"status": "verified", "live_no_drain_authorized": False}
        except Exception:
            self.rollback()
            self.checkpoint()
            restart_services()
            self.checkpoint()
            if verify_services() is not True:
                raise FileTransactionBlocked("control_plane_fixture_rollback_health_failed")
            self.verify_terminal("rolled_back")
            return {"status": "rolled_back", "live_no_drain_authorized": False}

    def run_verified_restart_fixture(self, plan, *, observe_inventory,
                                     observe_games, restart_services,
                                     verify_services, validate_replacement):
        """Compose replacement and game witnesses with disposable recovery.

        Observers and restart callbacks are fixture inputs, not installed
        authority. The retained checkpoint must remain valid throughout.
        """
        if self.installed_execution:
            raise FileTransactionBlocked("control_plane_restart_fixture_only")
        callbacks = (observe_inventory, observe_games, restart_services,
                     verify_services, validate_replacement)
        if not all(callable(item) for item in callbacks):
            raise FileTransactionBlocked("restart_fixture_callbacks_required")
        import copy
        self.checkpoint()
        games = copy.deepcopy(observe_games())
        previous = copy.deepcopy(observe_inventory())
        if not games or not previous:
            raise FileTransactionBlocked("restart_fixture_witness_missing")

        original = copy.deepcopy(previous)
        attempts = 0

        def restart():
            nonlocal previous, attempts
            self.checkpoint()
            if observe_games() != games:
                raise FileTransactionBlocked("restart_fixture_game_identity_changed")
            attempts += 1
            if attempts == 1:
                if observe_inventory() != original:
                    raise FileTransactionBlocked("restart_fixture_inventory_changed")
            else:
                # A failed startup can leave the service inventory unreadable.
                # Restore the old files and attempt restart anyway, but never
                # certify a rollback without a valid replacement witness.
                try:
                    previous = copy.deepcopy(observe_inventory())
                except (OSError, RuntimeError, ValueError):
                    previous = None
            restart_services()
            self.checkpoint()

        def verify():
            current = copy.deepcopy(observe_inventory())
            if previous is None:
                return False
            # Preserve the original registry, queues and alert identity even
            # when the rollback has its own immediate pre-restart witness.
            for baseline in (original, previous):
                result = validate_replacement(baseline, current)
                if (type(result) is not dict
                        or result.get("status") != "replacement_inventory_verified_only"
                        or result.get("replacement_count") != 11
                        or result.get("live_no_drain_authorized") is not False):
                    return False
            if observe_games() != games or verify_services() is not True:
                return False
            self.checkpoint()
            return observe_games() == games and observe_inventory() == current

        return self.run_control_plane_fixture(plan, restart, verify)

    def prepare_control_plane(self, plan):
        """Prepare a restart candidate in a disposable workspace only.

        The ordinary installed admission is unchanged. This entry point
        validates the exact diagnostic plan and reuses the durable file
        journal; it does not restart services or claim runtime compatibility.
        """
        if self.installed_execution:
            raise FileTransactionBlocked("control_plane_restart_fixture_only")
        if (type(plan) is not dict
                or plan.get("status") != "restart_candidate_review_only"
                or plan.get("live_no_drain_authorized") is not False
                or plan.get("blocking_path_count") != 0
                or plan.get("blocking_paths") != []):
            raise FileTransactionBlocked("invalid_control_plane_restart_plan")
        paths = plan.get("changed_paths")
        if (type(paths) is not list or not 1 <= len(paths) <= _COUNT
                or any(not _approved_path(name) for name in paths)
                or len(set(paths)) != len(paths)):
            raise FileTransactionBlocked("invalid_control_plane_restart_paths")
        python_paths = []
        for name in paths:
            if ("game_uptime" in name or "maintenance_hold" in name):
                raise FileTransactionBlocked("control_plane_fence_change_forbidden")
            if name.startswith("dashboard/") and name.endswith(".py"):
                python_paths.append(name)
            elif not (name in _METADATA or
                      (name.startswith("dashboard/web/") and
                       Path(name).suffix.lower() in _SUFFIXES - {".py"})):
                raise FileTransactionBlocked("outside_control_plane_restart_scope")
        if not python_paths or len(python_paths) != plan.get("candidate_python_file_count"):
            raise FileTransactionBlocked("control_plane_candidate_count_mismatch")
        self.prepare(paths, _validate_python=True)

    def prepare(self, changed_paths, *, _validate_python=False):
        if (type(changed_paths) is not list or not 1 <= len(changed_paths) <= _COUNT
                or any(not _approved_path(x) for x in changed_paths)
                or len(set(changed_paths)) != len(changed_paths)):
            raise FileTransactionBlocked("invalid_compatible_file_plan")
        with self._exclusive():
            if os.path.lexists(self.journal):
                raise FileTransactionBlocked("existing_product_file_transaction")
            entries = []
            total = 0
            for name in sorted(changed_paths, key=lambda x: (x in _METADATA, x)):
                old = self._installed_read(name)
                new = _read(_file(self.target, name))
                if _validate_python and name.endswith(".py"):
                    try:
                        for item in (old, new):
                            compile(base64.b64decode(item["bytes"], validate=True),
                                    name, "exec", dont_inherit=True)
                    except (SyntaxError, ValueError) as exc:
                        raise FileTransactionBlocked("control_plane_python_syntax_invalid") from exc
                if old["mode"] != new["mode"]:
                    raise FileTransactionBlocked("incompatible_product_mode_change")
                new = {**new, "uid": old["uid"], "gid": old["gid"]}
                if old == new:
                    raise FileTransactionBlocked("unchanged_product_file_in_plan")
                total += len(old["bytes"]) + len(new["bytes"])
                if total > _TOTAL - 1048576:
                    raise FileTransactionBlocked("file_transaction_snapshot_too_large")
                entries.append({"path": name, "before": old, "after": new})
            self.checkpoint()
            _write_once(self.journal, {
                "kind": "DSM928ProductFileTransaction", "schema_version": 1,
                "transaction_id": self.transaction_id,
                "release_sha256": self.release_sha256, "entries": entries,
                "product_identity": list(self.product_identity) if self.product_identity else None,
                "installed_execution": self.installed_execution,
                "live_no_drain_authorized": False})

    def _entries(self):
        report = _read_journal(self.journal)
        if (type(report) is not dict or report.get("kind") != "DSM928ProductFileTransaction"
                or report.get("schema_version") != 1
                or report.get("transaction_id") != self.transaction_id
                or report.get("release_sha256") != self.release_sha256
                or report.get("installed_execution", False) is not self.installed_execution
                or report.get("product_identity") != (
                    list(self.product_identity) if self.product_identity else None)
                or report.get("live_no_drain_authorized") is not False
                or type(report.get("entries")) is not list
                or not 1 <= len(report["entries"]) <= _COUNT):
            raise FileTransactionBlocked("file_transaction_binding_mismatch")
        entries = report["entries"]
        names = [entry["path"] for entry in entries]
        if (any(not _approved_path(x) for x in names) or len(set(names)) != len(names)):
            raise FileTransactionBlocked("invalid_durable_product_file_plan")
        return entries

    def _transition(self, direction):
        with self._exclusive():
            entries = self._entries()
            # Validate every recorded destination before touching any of them.
            # On recovery the installed state can legitimately be mixed.
            for entry in entries:
                if self._installed_read(entry["path"]) not in (entry["before"], entry["after"]):
                    raise FileTransactionBlocked("unexpected_product_file_state")
            if direction == "before":
                entries = list(reversed(entries))
            for entry in entries:
                self.checkpoint()
                found = self._installed_read(entry["path"])
                if found != entry[direction]:
                    self._installed_replace(entry["path"], entry[direction], entry[
                        "before" if direction == "after" else "after"])
                self.checkpoint()
            for entry in entries:
                if self._installed_read(entry["path"]) != entry[direction]:
                    raise FileTransactionBlocked("product_file_transaction_not_verified")
            return {"status": "files_applied" if direction == "after" else "files_restored",
                    "file_count": len(entries), "live_no_drain_authorized": False}

    def journal_digest(self):
        with self._exclusive():
            self._entries()
            return hashlib.sha256(_encode(_read_journal(self.journal))).hexdigest()

    def verify_terminal(self, outcome):
        if outcome not in ("verified", "rolled_back", "recovered_rollback"):
            raise FileTransactionBlocked("invalid_product_terminal_outcome")
        direction = "after" if outcome == "verified" else "before"
        with self._exclusive():
            for entry in self._entries():
                if self._installed_read(entry["path"]) != entry[direction]:
                    raise FileTransactionBlocked("terminal_product_file_state_mismatch")

    def apply(self):
        return self._transition("after")

    def rollback(self):
        return self._transition("before")
