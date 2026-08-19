import io
import json
import sys
from pathlib import Path


DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "dashboard"

if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

import server


def test_unauthorized_returns_json_without_basic_auth_challenge():
    handler = server.DashboardHandler.__new__(
        server.DashboardHandler
    )

    handler.wfile = io.BytesIO()

    status = {}
    headers = {}

    def send_response(code, message=None):
        status["code"] = code
        status["message"] = message

    def send_header(name, value):
        headers[name.lower()] = value

    def end_headers():
        pass

    handler.send_response = send_response
    handler.send_header = send_header
    handler.end_headers = end_headers

    handler.unauthorized()

    assert status["code"] == 401

    assert (
        headers.get("content-type")
        == "application/json; charset=utf-8"
    )

    assert "www-authenticate" not in headers

    body = json.loads(
        handler.wfile.getvalue().decode("utf-8")
    )

    assert body == {
        "error": (
            "Autenticação necessária | "
            "Authentication required"
        )
    }
