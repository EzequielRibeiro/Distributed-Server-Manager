#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from migration_parity import validate_customer_migration_parity


def test_customer_account_migrations_have_cross_backend_semantic_parity():
    assert validate_customer_migration_parity(ROOT / "database") == []
