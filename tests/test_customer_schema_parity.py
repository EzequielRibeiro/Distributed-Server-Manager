#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from schema_parity import validate_customer_schema_parity


def test_customer_account_schemas_have_cross_backend_semantic_parity():
    assert validate_customer_schema_parity(ROOT / "database") == []
