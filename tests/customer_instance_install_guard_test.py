from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_install_failure_guard_targets_only_management_tabs():
    script = (ROOT / "dashboard" / "web" / "customer-instance-install-guard.js").read_text(encoding="utf-8")
    for view in ("logs", "events", "config", "files", "content", "backups", "danger"):
        assert f'"{view}"' in script
    assert '"overview"' not in script.split("blockedViews", 1)[1].split("]);", 1)[0]
    assert "provision-failed" in script
    assert "button.disabled = blocked" in script
