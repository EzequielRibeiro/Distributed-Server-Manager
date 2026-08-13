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
from contextlib import closing
from pathlib import Path

import manager as database


SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
PASSWORD_MIN_LENGTH = 8
PASSWORD_REQUIREMENTS = f"Requisitos da senha: no mínimo {PASSWORD_MIN_LENGTH} caracteres."


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"a senha deve ter no mínimo {PASSWORD_MIN_LENGTH} caracteres")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
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


def save_user(database_path: Path, username: str, password: str, role: str, scope_id: str = "", *, replace: bool = False) -> None:
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
    database.initialize(database_path)
    with closing(database.connect(database_path)) as connection:
        if role in {"controller", "customer"}:
            table = "controllers" if role == "controller" else "customers"
            if not connection.execute(f"SELECT 1 FROM {table} WHERE id=?", (scope_id,)).fetchone():
                raise ValueError("scope does not exist")
        if not replace and connection.execute("SELECT 1 FROM dashboard_users WHERE username=?", (username,)).fetchone():
            raise ValueError("user already exists")
        with connection:
            connection.execute(
                "INSERT INTO dashboard_users(username,password_hash,role,scope_id,active) VALUES (?,?,?,?,1) "
                "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash,role=excluded.role,"
                "scope_id=excluded.scope_id,active=1,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
                (username, hash_password(password), role, scope_id or None),
            )


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
    database_path = (args.database or args.root / "data" / "capivara.db").resolve()
    database.initialize(database_path)
    if args.command in {"create", "passwd"}:
        print(PASSWORD_REQUIREMENTS)
        password = getpass.getpass("Senha: ")
        confirmation = getpass.getpass("Confirme a senha: ")
        if password != confirmation:
            print("Erro: a confirmação da senha não corresponde.", file=sys.stderr)
            return 2
        try:
            if args.command == "create":
                save_user(database_path, args.username, password, args.role, args.scope)
            else:
                with closing(database.connect(database_path)) as connection:
                    with connection:
                        cursor = connection.execute(
                            "UPDATE dashboard_users SET password_hash=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE username=?",
                            (hash_password(password), args.username.lower()),
                        )
                    if not cursor.rowcount:
                        raise ValueError("usuário não encontrado")
        except ValueError as error:
            print(f"Erro: {error}.", file=sys.stderr)
            return 2
        print(f"User {args.username.lower()} saved in {database_path}")
    elif args.command == "delete":
        with closing(database.connect(database_path)) as connection:
            row = connection.execute("SELECT role FROM dashboard_users WHERE username=?", (args.username.lower(),)).fetchone()
            if not row:
                raise SystemExit("user not found")
            if row["role"] == "admin" and connection.execute("SELECT COUNT(*) FROM dashboard_users WHERE role='admin' AND active=1").fetchone()[0] <= 1:
                raise SystemExit("cannot delete the last active administrator")
            with connection:
                connection.execute("DELETE FROM dashboard_users WHERE username=?", (args.username.lower(),))
        print(f"User {args.username.lower()} deleted")
    else:
        with closing(database.connect(database_path)) as connection:
            for row in connection.execute("SELECT username,role,COALESCE(scope_id,'') AS scope_id,active FROM dashboard_users ORDER BY username"):
                print(f"{row['username']}\t{row['role']}\t{row['scope_id']}\t{'active' if row['active'] else 'disabled'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
