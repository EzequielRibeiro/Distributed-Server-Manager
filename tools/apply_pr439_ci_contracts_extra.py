#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def update_release_verifier() -> None:
    path = ROOT / "update-manager" / "verify-release.sh"
    replace_once(
        path,
        'REQUIRED_FILES="\nversion\nbin/dsm\ncore/bootstrap.sh\n"',
        'REQUIRED_FILES="\nversion\nbin/cap\ncore/bootstrap.sh\n"',
        "canonical release CLI requirement",
    )


def update_update_manager_test() -> None:
    path = ROOT / "tests" / "update_manager_test.sh"
    text = path.read_text(encoding="utf-8")

    old_package = '    printf \'%s\\n\' \'#!/usr/bin/env bash\' >"${PACKAGE_ROOT}/bin/dsm"\n'
    if text.count(old_package) != 1:
        raise RuntimeError("release verifier test bin/dsm fixture was not found exactly once")
    text = text.replace(
        old_package,
        '    printf \'%s\\n\' \'#!/usr/bin/env bash\' >"${PACKAGE_ROOT}/bin/cap"\n',
        1,
    )

    start_marker = '''(
    source "${UPDATE}"
    INSTALL_DIR="${TMP_DIR}/legacy-install"; DSM_USER=""; DSM_GROUP=""; DSM_HOME=""; mkdir -p "${INSTALL_DIR}"
'''
    next_marker = '''(
    DSM_ROOT="${ROOT}"; source "${UPDATE_MANAGER}"; unset -f notify_dispatch 2>/dev/null || true; log_info(){ :; }
'''
    start = text.find(start_marker)
    end = text.find(next_marker, start)
    if start < 0 or end < 0:
        raise RuntimeError("legacy runtime-account test block not found")
    text = text[:start] + text[end:]

    if "resolve_legacy_runtime_account" in text:
        raise RuntimeError("legacy runtime-account test residue remains")

    path.write_text(text, encoding="utf-8")


def main() -> None:
    update_release_verifier()
    update_update_manager_test()
    print("residual PR439 legacy contracts removed")


if __name__ == "__main__":
    main()
