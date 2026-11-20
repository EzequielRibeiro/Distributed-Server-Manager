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
