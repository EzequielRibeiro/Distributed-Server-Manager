#!/usr/bin/env python3
"""Cryptographic primitives for Agent enrollment identities.

The Controller never needs to persist plaintext pairing or permanent secrets.
Opaque secrets are random high-entropy values and are compared through stable
SHA-256 digests. The schema also carries public-key material for a future
certificate-backed credential type.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


PAIRING_TOKEN_PREFIX = "cap_pair_"
AGENT_SECRET_PREFIX = "cap_agent_"


def secret_digest(secret: str) -> str:
    value = str(secret).strip()
    if not value:
        raise ValueError("secret is required")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def secrets_match(secret: str, expected_digest: str) -> bool:
    return hmac.compare_digest(secret_digest(secret), str(expected_digest))


def generate_pairing_token() -> str:
    return PAIRING_TOKEN_PREFIX + secrets.token_urlsafe(32)


def generate_agent_secret() -> str:
    return AGENT_SECRET_PREFIX + secrets.token_urlsafe(48)


def generate_identity_id(prefix: str) -> str:
    normalized = str(prefix).strip().replace("_", "-")
    if not normalized:
        raise ValueError("prefix is required")
    return f"{normalized}-{secrets.token_hex(16)}"
