"""Read-only audit only trusts installed Steam depot manifest paths."""
import os
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents/linux/runtime"))
from content_discovery_audit import audit_dayz_manifest_provenance


def _varint(value):
    result = bytearray()
    while value >= 128:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def _field(number, value):
    return _varint(number * 8 + 2) + _varint(len(value)) + value


@pytest.fixture
def installed(tmp_path):
    root = tmp_path / "game" / "serverfiles"
    addons = root / "future_dlc" / "addons"
    addons.mkdir(parents=True)
    (addons / "future.pbo").write_bytes(b"official")
    (addons / "extra.pbo").write_bytes(b"unlisted")
    custom = root / "custom" / "addons"
    custom.mkdir(parents=True)
    (custom / "custom.pbo").write_bytes(b"unofficial")
    steamapps = root / "steamapps"
    steamapps.mkdir()
    (steamapps / "appmanifest_223350.acf").write_text(
        '"AppState" { "appid" "223350" "InstalledDepots" { '
        '"223351" { "manifest" "123456789" } } }'
    )
    home = tmp_path / "steamhome"
    cache = home / "Steam" / "depotcache"
    cache.mkdir(parents=True)
    payload = _field(1, _field(1, b"future_dlc\\addons\\future.pbo"))
    metadata = (_varint(8) + _varint(223351)
                + _varint(16) + _varint(123456789)
                + _varint(32) + _varint(0))
    binary = (struct.pack("<II", 0x71F617D0, len(payload)) + payload
              + struct.pack("<II", 0x1F4812BE, len(metadata)) + metadata
              + struct.pack("<I", 0x32C415AB))
    (cache / "223351_123456789.manifest").write_bytes(binary)
    state = tmp_path / "agentstate"
    state.mkdir()
    return root, home, state, cache


def test_future_dlc_is_discovered_from_verified_manifest(installed):
    root, home, state, _ = installed
    before = (root / "future_dlc/addons/future.pbo").read_bytes()
    result = audit_dayz_manifest_provenance(
        root, home, state, expected_uid=os.getuid()
    )
    assert result["status"] == "warning"  # extra local PBO never declared official
    assert result["verified_package_count"] == 1
    assert result["unverified_package_count"] == 1
    assert [r["directory"] for r in result["roots"]] == ["future_dlc"]
    assert result["engine_load_verified"] is False
    assert result["read_only"] is True
    assert (root / "future_dlc/addons/future.pbo").read_bytes() == before


def test_fully_verified_dlc_is_reported_ok(installed):
    root, home, state, _ = installed
    (root / "future_dlc/addons/extra.pbo").unlink()
    result = audit_dayz_manifest_provenance(
        root, home, state, expected_uid=os.getuid()
    )
    assert result["status"] == "ok"
    assert result["verified_package_count"] == 1
    assert result["engine_load_verified"] is False


def test_missing_manifest_evidence_never_reports_ok(installed):
    root, home, state, cache = installed
    (cache / "223351_123456789.manifest").unlink()
    result = audit_dayz_manifest_provenance(
        root, home, state, expected_uid=os.getuid()
    )
    assert result["status"] == "unverified"
    assert result["verified_package_count"] == 0


def test_untrusted_depotcache_symlink_fails_closed(installed, tmp_path):
    root, home, state, cache = installed
    cache.rename(home / "real-cache")
    cache.symlink_to(home / "real-cache")
    result = audit_dayz_manifest_provenance(
        root, home, state, expected_uid=os.getuid()
    )
    assert result["status"] == "unsafe"
    assert result["verified_package_count"] == 0


def test_mismatched_runner_uid_requires_review(installed):
    root, home, state, _ = installed
    (root / "future_dlc/addons/extra.pbo").unlink()
    result = audit_dayz_manifest_provenance(
        root, home, state, expected_uid=os.getuid() + 1
    )
    assert result["status"] == "warning"
    assert result["verified_package_count"] == 1
    assert result["roots"][0]["owner_mismatch_count"] == 1
