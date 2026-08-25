#!/usr/bin/env python3
"""Console management for Capivara DSM database-backed dashboard users."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import os
import re
import secrets
import sys
from pathlib import Path

from backend import DatabaseBackend, DatabaseConfig
from backend_factory import create_backend
from runtime_backend import backend_from_environment
from user_repository import UserRepository


SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
PASSWORD_MIN_LENGTH = 8
PASSWORD_REQUIREMENTS = f"Requisitos da senha: no mínimo {PASSWORD_MIN_LENGTH} caracteres."
TEMPORARY_PASSWORD_PREFIX = "temporary$"


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"a senha deve ter no mínimo {PASSWORD_MIN_LENGTH} caracteres")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def hash_temporary_password(password: str) -> str:
    """Hash a first-access password without persisting the secret itself."""
    return TEMPORARY_PASSWORD_PREFIX + hash_password(password)


def is_temporary_password_hash(encoded: str | None) -> bool:
    return isinstance(encoded, str) and encoded.startswith(TEMPORARY_PASSWORD_PREFIX)


def _password_hash_payload(encoded: str | None) -> str:
    if not isinstance(encoded, str):
        return ""
    if is_temporary_password_hash(encoded):
        return encoded[len(TEMPORARY_PASSWORD_PREFIX):]
    return encoded


def verify_password(password: str, encoded: str) -> bool:
    try:
        encoded = _password_hash_payload(encoded)
        algorithm, raw_n, raw_r, raw_p, raw_salt, raw_digest = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(raw_salt),
            n=int(raw_n), r=int(raw_r), p=int(raw_p), dklen=32,
        )
        return hmac.compare_digest(digest, bytes.fromhex(raw_digest))
    except (TypeError, ValueError):
        return False


def generate_temporary_password() -> str:
    """Return a high-entropy password intended to be shown exactly once."""
    return secrets.token_urlsafe(15)


def _repository(target: Path | DatabaseBackend) -> UserRepository:
    if isinstance(target, DatabaseBackend):
        return UserRepository(target)
    return UserRepository(create_backend(DatabaseConfig(
        driver="sqlite",
        database=str(Path(target).expanduser().resolve()),
    )))


def save_user(database_path: Path | DatabaseBackend, username: str, password: str, role: str, scope_id: str = "", *, replace: bool = False) -> None:
    username = username.strip().lower()
    role = role.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,63}", username):
        raise ValueError("invalid username")
    if role not in {"admin", "controller", "customer", "operator"}:
        raise ValueError("invalid role")
    if role in {"controller", "customer"} and not scope_id:
        raise ValueError("controller and customer users require a scope")
    if role in {"admin", "operator"}:
        scope_id = ""
    _repository(database_path).save(
        username=username,
        password_hash=hash_password(password),
        role=role,
        scope_id=scope_id or None,
        replace=replace,
    )


def _runtime_repository(args) -> tuple[UserRepository, str]:
    if args.database is not None or not os.environ.get("DSM_DATABASE_DRIVER"):
        path = (args.database or args.root / "data" / "capivara.db").resolve()
        return _repository(path), str(path)
    backend = backend_from_environment()
    return UserRepository(backend), backend.name


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage Capivara DSM dashboard users")
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("DSM_ROOT", "/opt/dsm")))
    parser.add_argument("--database", type=Path)
    subcommands = parser.add_subparsers(dest="command", required=True)
    create = subcommands.add_parser("create", help="create a database-backed user")
    create.add_argument("username")
    create.add_argument("--role", choices=("admin", "controller", "customer", "operator"), default="admin")
    create.add_argument("--scope", default="")
    password_parser = subcommands.add_parser("passwd", help="reset a user's password")
    password_parser.add_argument("username")
    delete_parser = subcommands.add_parser("delete", help="delete a dashboard user")
    delete_parser.add_argument("username")
    subcommands.add_parser("list", help="list dashboard users")
    args = parser.parse_args()
    repository, database_label = _runtime_repository(args)
    repository.initialize()
    if args.command in {"create", "passwd"}:
        print(PASSWORD_REQUIREMENTS)
        password = getpass.getpass("Senha: ")
        confirmation = getpass.getpass("Confirme a senha: ")
        if password != confirmation:
            print("Erro: a confirmação da senha não corresponde.", file=sys.stderr)
            return 2
        try:
            if args.command == "create":
                save_user(repository.backend, args.username, password, args.role, args.scope)
            else:
                repository.change_password(
                    args.username.lower(),
                    hash_password(password),
                )
        except ValueError as error:
            print(f"Erro: {error}.", file=sys.stderr)
            return 2
        print(f"User {args.username.lower()} saved in {database_label}")
    elif args.command == "delete":
        try:
            repository.delete(args.username.lower())
        except ValueError as error:
            raise SystemExit(str(error)) from error
        print(f"User {args.username.lower()} deleted")
    else:
        for row in repository.list_users():
            print(f"{row['username']}\t{row['role']}\t{row['scope_id'] or ''}\t{'active' if row['active'] else 'disabled'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
