#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "database"))

from customer_code import format_customer_code, is_customer_code, parse_customer_code


def test_format_customer_code_uses_numeric_primary_key() -> None:
    assert format_customer_code(1) == "CLI-000001"
    assert format_customer_code(17) == "CLI-000017"
    assert format_customer_code(999999) == "CLI-999999"
    assert format_customer_code(1000000) == "CLI-1000000"


def test_parse_customer_code_returns_numeric_primary_key() -> None:
    assert parse_customer_code("CLI-000001") == 1
    assert parse_customer_code("cli-000017") == 17


def test_customer_code_rejects_non_canonical_or_invalid_values() -> None:
    for value in (
        "AURORA",
        "CLIENTE-001",
        "CLI-1",
        "CLI-000000",
        "CLI--000001",
        "",
    ):
        with pytest.raises(ValueError):
            parse_customer_code(value)
        assert not is_customer_code(value)


def test_format_rejects_non_positive_primary_keys() -> None:
    for value in (0, -1, True, None, "abc"):
        with pytest.raises(ValueError):
            format_customer_code(value)
