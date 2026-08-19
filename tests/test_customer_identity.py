#!/usr/bin/env python3
"""Tests for customer self-service identity helpers."""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "database"
if str(DATABASE) not in sys.path:
    sys.path.insert(0, str(DATABASE))

from customer_identity import collision_suffix, normalize_email, sftp_username_seed


def test_normalize_email():
    assert normalize_email("  Client.Example@Example.COM ") == "client.example@example.com"


def test_invalid_email_is_rejected():
    try:
        normalize_email("invalid-address")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid e-mail must be rejected")


def test_sftp_username_uses_email_local_part():
    assert sftp_username_seed("client.example@example.com") == "client.example"


def test_sftp_username_is_linux_safe():
    username = sftp_username_seed("123.Client+Games@example.com")
    assert username == "u-123.client-games"
    assert len(username) <= 32


def test_sftp_username_removes_unicode_accents():
    assert sftp_username_seed("josé.silva@example.com") == "jose.silva"


def test_collision_suffix_is_stable():
    first = collision_suffix("client@example.com")
    second = collision_suffix("CLIENT@example.com")
    assert first == second
    assert len(first) == 8
