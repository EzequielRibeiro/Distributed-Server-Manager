from pathlib import Path

from dashboard.game_library_service import library_entry, provision_from_library


def definition(provider="steam"):
    return {
        "id": "dayz-linux",
        "game": "dayz",
        "artifact": {"provider": provider},
        "process": {"executable": "DayZServer"},
        "version": {"resolver": "steam"},
    }


def test_library_inventory_reports_provider_readiness_and_size(tmp_path):
    base = tmp_path / "game-data" / "dayz"
    base.mkdir(parents=True)
    (base / "DayZServer").write_bytes(b"server")
    entry = library_entry(tmp_path, definition(), base)
    assert entry["ready"] is True
    assert entry["provider"] == "steam"
    assert entry["size_bytes"] == 6
    assert entry["role"] == "agent_server_base_library"


def test_provision_copies_base_and_isolates_instance(tmp_path):
    base = tmp_path / "game-data" / "dayz"
    base.mkdir(parents=True)
    (base / "DayZServer").write_bytes(b"base-v1")
    (base / "serverDZ.cfg").write_text("base")
    target = tmp_path / "instances" / "node" / "dayz" / "customer" / "serverfiles"
    result = provision_from_library(base, target, executable="DayZServer")
    assert result["isolated"] is True
    assert (target / "DayZServer").read_bytes() == b"base-v1"

    # A later library update cannot mutate an already provisioned customer instance.
    (base / "DayZServer").write_bytes(b"base-v2")
    (base / "serverDZ.cfg").write_text("changed-base")
    assert (target / "DayZServer").read_bytes() == b"base-v1"
    assert (target / "serverDZ.cfg").read_text() == "base"


def test_incomplete_library_is_rejected(tmp_path):
    base = tmp_path / "game-data" / "dayz"
    base.mkdir(parents=True)
    target = tmp_path / "instances" / "node" / "dayz" / "customer" / "serverfiles"
    try:
        provision_from_library(base, target, executable="DayZServer")
    except ValueError as exc:
        assert "incomplete" in str(exc)
    else:
        raise AssertionError("incomplete library should be rejected")
    assert not target.exists()
