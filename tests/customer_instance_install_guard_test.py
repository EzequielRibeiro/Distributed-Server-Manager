from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_install_failure_guard_disables_management_tabs_only():
    script = (ROOT / "dashboard" / "web" / "customer-instance-events.js").read_text(encoding="utf-8")

    for view in ("logs", "events", "config", "files", "content", "backups", "danger"):
        assert f'"{view}"' in script

    blocked_views = script.split("blockedViews", 1)[1].split("]);", 1)[0]
    assert '"overview"' not in blocked_views
    assert "provision-failed" in script
    assert "button.disabled=blocked" in script
    assert "showOverview" in script
    assert "MutationObserver" in script
