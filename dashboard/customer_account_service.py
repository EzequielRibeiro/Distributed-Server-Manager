#!/usr/bin/env python3
"""Customer account policy for Capivara DSM self-service surfaces.

Keeps customer-facing account rules outside dashboard/server.py.  Transport
(HTTP), password hashing and mail delivery remain separate concerns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


CUSTOMER_ACCOUNT_PERMISSIONS = {
    "owner": frozenset({
        "account.members.manage",
        "account.profile.manage",
        "contract.read",
        "instance.create",
        "instance.read",
    }),
    "manager": frozenset({
        "contract.read",
        "instance.create",
        "instance.read",
    }),
    "member": frozenset({
        "contract.read",
        "instance.read",
    }),
}

NAME_RE = re.compile(r"\S(?:.*\S)?$")


@dataclass(frozen=True)
class RegistrationRequest:
    name: str
    email: str
    phone: str = ""
    document_type: str = ""
    document_number: str = ""


def normalize_registration(payload: dict[str, Any]) -> RegistrationRequest:
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    phone = str(payload.get("phone", "")).strip()
    document_type = str(payload.get("document_type", "")).strip().lower()
    document_number = str(payload.get("document_number", "")).strip()
    if len(name) < 2 or len(name) > 255 or not NAME_RE.fullmatch(name):
        raise ValueError("invalid customer name")
    if document_type not in {"", "cpf", "cnpj", "other"}:
        raise ValueError("invalid document type")
    return RegistrationRequest(
        name=name,
        email=email,
        phone=phone,
        document_type=document_type,
        document_number=document_number,
    )


def permissions_for(account_role: str) -> frozenset[str]:
    try:
        return CUSTOMER_ACCOUNT_PERMISSIONS[account_role]
    except KeyError as exc:
        raise ValueError("invalid customer account role") from exc


def may_manage_members(account_role: str) -> bool:
    return "account.members.manage" in permissions_for(account_role)
