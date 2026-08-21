#!/usr/bin/env python3
"""Administrative CLI for creating a customer and its login."""

from __future__ import annotations

import argparse
import getpass
import json
import sys

from admin_management_repository import AdminManagementRepository
from runtime_backend import backend_from_environment
from users import PASSWORD_REQUIREMENTS, hash_password


def build_parser():
    parser = argparse.ArgumentParser(description="Capivara DSM customer administration")
    parser.add_argument("--json", action="store_true", dest="as_json")
    subparsers = parser.add_subparsers(dest="action", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--id", required=True, dest="customer_id")
    create.add_argument("--name", required=True)
    create.add_argument("--username", required=True)
    create.add_argument("--controller")
    create.add_argument("--email")
    create.add_argument("--phone")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    backend = backend_from_environment()
    backend.initialize()
    repository = AdminManagementRepository(backend)

    print(PASSWORD_REQUIREMENTS, file=sys.stderr if args.as_json else sys.stdout)
    password = getpass.getpass("Senha: ")
    confirmation = getpass.getpass("Confirme a senha: ")
    if password != confirmation:
        raise SystemExit("error: password confirmation does not match")

    try:
        result = repository.create_customer(
            customer_id=args.customer_id,
            name=args.name,
            username=args.username,
            password_hash=hash_password(password),
            controller_id=args.controller,
            email=args.email,
            phone=args.phone,
        )
    except ValueError as exc:
        raise SystemExit(f"error: {exc}") from exc

    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"Customer created: {result['id']}")
        print(f"Login: {result['username']}")
        print(f"Controller: {result['controller_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
