#!/usr/bin/env python3
"""Regression guard for the retired DSM compatibility CLI layer."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAP = ROOT / "bin" / "cap"


def main() -> None:
    assert not (ROOT / "bin" / "dsm").exists(), "retired public dsm alias returned"
    assert not (ROOT / "bin" / "dsm-compat").exists(), "retired dsm-compat dispatcher returned"

    text = CAP.read_text(encoding="utf-8")
    for marker in (
        "LEGACY_DSM",
        "legacy_exec",
        "dsm-compat",
        "compatibilidade temporária",
        "compatibility dispatcher",
    ):
        assert marker not in text, f"retired compatibility marker remains in bin/cap: {marker}"


if __name__ == "__main__":
    main()
    print("DSM compatibility retirement regression: OK")
