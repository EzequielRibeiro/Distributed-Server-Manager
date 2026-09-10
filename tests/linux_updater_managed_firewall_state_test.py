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
