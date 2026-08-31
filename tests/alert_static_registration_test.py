from pathlib import Path


def test_alert_enhancement_assets_are_registered():
    source = Path("dashboard/server_part14.py").read_text(encoding="utf-8")
    assert '"/alerts-page-enhancements.js"' in source
    assert '"/agent-alert-link.js"' in source


def test_alert_search_has_explicit_submit_control():
    html = Path("dashboard/web/alerts.html").read_text(encoding="utf-8")
    script = Path("dashboard/web/alerts-page-enhancements.js").read_text(encoding="utf-8")
    assert 'id="alert-search-button"' in html
    assert 'alert-search-button' in script
    assert 'keydown' in script


def test_agent_alert_link_preserves_agent_scope():
    html = Path("dashboard/web/agent-details.html").read_text(encoding="utf-8")
    script = Path("dashboard/web/agent-alert-link.js").read_text(encoding="utf-8")
    assert 'id="agent-alerts-link"' in html
    assert 'alerts.html?agent_id=' in script
