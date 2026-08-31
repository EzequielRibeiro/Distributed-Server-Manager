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
