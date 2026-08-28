#!/usr/bin/env python3
"""Create protected password files for one-time remote Agent bootstrap."""
from __future__ import annotations

import argparse
import getpass
import os
import pwd
import re
import tempfile
from pathlib import Path

_NAME = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
DEFAULT_DIR = Path(
    os.environ.get(
        "DSM_REMOTE_DEPLOY_SECRET_DIR",
        "/etc/capivara/secrets/remote-deploy",
    )
)
DEFAULT_SERVICE_USER = (
    os.environ.get("DSM_SERVICE_USER")
    or os.environ.get("DSM_USER")
    or "capivara"
)


def build_parser():
    parser = argparse.ArgumentParser(description="Manage protected remote-deploy secrets")
    sub = parser.add_subparsers(dest="command", required=True)
    create_cmd = sub.add_parser(
        "create", help="create or replace a protected SSH password file"
    )
    create_cmd.add_argument("name", help="logical host/secret name")
    create_cmd.add_argument("--directory", default=str(DEFAULT_DIR), help=argparse.SUPPRESS)
    remove_cmd = sub.add_parser("delete", help="delete a remote-deploy secret")
    remove_cmd.add_argument("name")
    remove_cmd.add_argument("--directory", default=str(DEFAULT_DIR), help=argparse.SUPPRESS)
    return parser


def _path(directory, name):
    if not _NAME.fullmatch(str(name or "")):
        raise ValueError(
            "secret name may contain only letters, numbers, dot, underscore and hyphen"
        )
    root = Path(directory).expanduser().resolve()
    return root, root / (name + ".secret")


def _service_identity():
    try:
        return pwd.getpwnam(DEFAULT_SERVICE_USER)
    except KeyError:
        return None


def _prepare_service_ssh_home(identity) -> None:
    if identity is None or os.geteuid() != 0:
        return
    home = Path(identity.pw_dir).expanduser()
    if not home.is_dir():
        return
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    os.chown(ssh_dir, identity.pw_uid, identity.pw_gid)
    os.chmod(ssh_dir, 0o700)
    known_hosts = ssh_dir / "known_hosts"
    if known_hosts.exists():
        os.chown(known_hosts, identity.pw_uid, identity.pw_gid)
        os.chmod(known_hosts, 0o600)


def _grant_service_access(root: Path, path: Path) -> None:
    """Keep 0700/0600 and let the Dashboard service consume the secret.

    Root-created secrets used to remain owned by root, which made the Dashboard
    fail with EACCES. When running privileged, reconcile ownership to the
    installed Capivara service account and prepare its persistent ~/.ssh store.
    """
    identity = _service_identity()
    if identity is None or os.geteuid() != 0:
        return
    os.chown(root, identity.pw_uid, identity.pw_gid)
    os.chmod(root, 0o700)
    os.chown(path, identity.pw_uid, identity.pw_gid)
    os.chmod(path, 0o600)
    _prepare_service_ssh_home(identity)


def create(directory, name):
    root, path = _path(directory, name)
    first = getpass.getpass("Senha SSH: ")
    second = getpass.getpass("Confirmar senha: ")
    if not first:
        raise ValueError("password cannot be empty")
    if first != second:
        raise ValueError("password confirmation does not match")

    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    fd, tmp = tempfile.mkstemp(prefix=".capivara-secret-", dir=str(root), text=True)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(first + "\n")
        os.replace(tmp, path)
        os.chmod(path, 0o600)
        _grant_service_access(root, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return path


def delete(directory, name):
    _, path = _path(directory, name)
    try:
        path.unlink()
    except FileNotFoundError:
        raise ValueError(f"secret not found: {path}")
    return path


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            path = create(args.directory, args.name)
            try:
                owner = path.owner()
            except (KeyError, OSError):
                owner = "unknown"
            print("Remote deploy secret created")
            print(f"Path.............. {path}")
            print("Permissions....... 0600")
            print(f"Owner............. {owner}")
            print(
                "Use............... cap agent deploy HOST --ssh-user USER "
                "--password-file " + str(path)
            )
        else:
            path = delete(args.directory, args.name)
            print(f"Remote deploy secret deleted: {path}")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Erro: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
