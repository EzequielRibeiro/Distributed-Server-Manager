from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_linux_updater_creates_managed_firewall_state_before_restart():
    updater = (
        ROOT / "agents" / "linux" / "updater" / "updater.py"
    ).read_text(encoding="utf-8")

    marker = '_ensure_state_directory(STATE_DIR / "privileged-firewall")'

    assert marker in updater

    ensure = updater.index(marker)
    reload_systemd = updater.index("_daemon_reload()", ensure)
    restart = updater.index("_restart_agent(expected_agent_id)", ensure)

    assert ensure < reload_systemd < restart


def test_linux_updater_packages_firewall_helper_and_unit():
    updater = (
        ROOT / "agents" / "linux" / "updater" / "updater.py"
    ).read_text(encoding="utf-8")

    assert (
        'package_root / "agent/privileged/reconcile_firewall.py"'
        in updater
    )

    assert (
        'package_root / "services/capivara-agent-firewall@.service"'
        in updater
    )

    assert (
        'package_root / "agent/policy/'
        '49-capivara-agent-instance-units.rules"'
        in updater
    )


def test_updater_result_keeps_agent_root_traversable_but_private_children_closed(tmp_path):
    """Result reporting must not undo runtime identity's traverse-only ACL."""
    import importlib.util
    import stat
    from unittest.mock import patch

    spec = importlib.util.spec_from_file_location(
        "capivara_updater_mode_test",
        ROOT / "agents" / "linux" / "updater" / "updater.py",
    )
    assert spec and spec.loader
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)

    agent_root = tmp_path / "capivara-agent"
    agent_root.mkdir(mode=0o700)
    updater.STATE_DIR = agent_root
    updater.RESULT_PATH = agent_root / "update-result.json"
    updater.HISTORY_DIR = agent_root / "update-history"

    with patch.object(updater.os, "chown"):
        updater._write_result("applied", installed_version="test")

    assert stat.S_IMODE(agent_root.stat().st_mode) == 0o710
    assert stat.S_IMODE(updater.HISTORY_DIR.stat().st_mode) == 0o700
    assert stat.S_IMODE(updater.RESULT_PATH.stat().st_mode) == 0o600


def _load_updater_for_manual_preview():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "capivara_manual_preview_test",
        ROOT / "agents" / "linux" / "updater" / "updater.py",
    )
    assert spec and spec.loader
    updater = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(updater)
    return updater


def test_manual_preview_uses_private_owned_staging_without_remote_paths(tmp_path):
    import os
    import stat

    updater = _load_updater_for_manual_preview()
    stage = tmp_path / "manual"
    stage.mkdir(mode=0o700)
    updater.MANUAL_PACKAGE_DIR = stage

    version = "2.0.133-rc.6.pr1102.2"
    base = "capivara-agent-linux-" + version
    assets = {
        base + ".tar.gz": b"archive",
        base + ".tar.gz.sha256": b"checksum",
        base + ".manifest.json": b"manifest",
    }
    for name, payload in assets.items():
        target = stage / name
        target.write_bytes(payload)
        target.chmod(0o600)

    destination = tmp_path / "extract"
    destination.mkdir()
    targets = [destination / name for name in assets]

    updater._stage_local_manual_package(version, *targets)

    assert [target.read_bytes() for target in targets] == list(assets.values())
    assert all(stat.S_IMODE(target.stat().st_mode) & 0o077 == 0
               for target in (stage, *stage.iterdir()))
    assert os.geteuid() == stage.stat().st_uid

    updater._verify_manifest({
        "kind": "CapivaraAgentPackage", "platform": "linux",
        "version": version, "channel": "beta",
    }, version, "local/manual")


def test_manual_preview_rejects_untrusted_artifacts(tmp_path):
    import pytest

    updater = _load_updater_for_manual_preview()
    stage = tmp_path / "manual"
    stage.mkdir(mode=0o700)
    updater.MANUAL_PACKAGE_DIR = stage

    version = "2.0.133-rc.6.pr1102.2"
    prefix = "capivara-agent-linux-" + version
    names = (prefix + ".tar.gz", prefix + ".tar.gz.sha256",
             prefix + ".manifest.json")
    for name in names:
        target = stage / name
        target.write_bytes(b"trusted")
        target.chmod(0o600)

    dest = tmp_path / "extract"
    dest.mkdir()
    targets = tuple(dest / name for name in names)

    with pytest.raises(RuntimeError, match="prerelease"):
        updater._stage_local_manual_package("2.0.133", *targets)

    stage.chmod(0o777)
    with pytest.raises(PermissionError, match="directory"):
        updater._stage_local_manual_package(version, *targets)
    stage.chmod(0o700)

    package = stage / names[0]
    package.unlink()
    package.symlink_to(stage / names[1])
    with pytest.raises(OSError):
        updater._stage_local_manual_package(version, *targets)
